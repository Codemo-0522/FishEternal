"""
群聊服务（核心编排层）

整合所有模块，提供统一的群聊业务逻辑
"""
import asyncio
import json
import logging
import time
import traceback
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from ...config import settings
from ...models.group_chat import (
    GroupChat, GroupMessage, GroupMember, GroupChatContext,
    CreateGroupRequest, SendMessageRequest, UpdateBehaviorRequest,
    MemberType, MemberStatus, MessageType, AIReplyDecision,
    GroupStrategyConfig
)
from ...utils.llm.llm_service import LLMService
from .group_manager import GroupManager
from .message_dispatcher import MessageDispatcher
from .ai_scheduler import get_ai_scheduler, get_reply_controller
from .conversation_controller import ConversationController
from .intelligent_scheduler import get_intelligent_scheduler
from .strategy_config_adapter import StrategyConfigAdapter

logger = logging.getLogger(__name__)


class GroupChatService:
    """群聊服务"""
    
    def __init__(self, db: AsyncIOMotorClient):
        self.db = db
        
        # 核心模块
        self.group_manager = GroupManager(db)
        self.message_dispatcher = MessageDispatcher(db)
        self.ai_scheduler = get_ai_scheduler()
        self.reply_controller = get_reply_controller()
        
        # 🔥 简单缓存机制，避免重复查询
        self._user_cache = {}  # 用户信息缓存
        self._session_cache = {}  # 会话信息缓存
        self._cache_ttl = 30  # 缓存30秒
        
        # 🔥 群聊策略配置缓存（避免每次消息都查库）
        self._strategy_config_cache: Dict[str, tuple[float, GroupStrategyConfig]] = {}
        self._strategy_cache_ttl = 60  # 策略配置缓存60秒
        
        # 🎯 LLM调用信号量控制（防止多个AI同时刷屏）
        # 每个群组最多允许2个AI并发调用LLM，其他排队等待
        self._llm_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._max_concurrent_llm_per_group = 2  # 每个群最多2个AI同时生成
        
        # 🔥 AI-to-AI延迟任务管理器（真人发言时取消）
        # group_id -> asyncio.Task
        self._ai_to_ai_tasks: Dict[str, asyncio.Task] = {}
        
        # 对话控制器（新增）- 配置冷却期恢复回调
        controller_config = {
            "recovery_callback": self._on_cooldown_recovery
        }
        self.conversation_controller = ConversationController(config=controller_config)
        
        # 注意：智能调度器不再作为实例变量，而是在需要时动态创建（支持无限制模式）
        
        # LLM服务
        self.llm_service = LLMService()
    
    def _is_cache_valid(self, cache_key: str, cache_dict: dict) -> bool:
        """检查缓存是否有效"""
        if cache_key not in cache_dict:
            return False
        
        cache_time, _ = cache_dict[cache_key]
        return time.time() - cache_time < self._cache_ttl
    
    def _get_cached_data(self, cache_key: str, cache_dict: dict):
        """获取缓存数据"""
        if self._is_cache_valid(cache_key, cache_dict):
            _, data = cache_dict[cache_key]
            return data
        return None
    
    def _set_cache_data(self, cache_key: str, cache_dict: dict, data):
        """设置缓存数据"""
        cache_dict[cache_key] = (time.time(), data)
    
    async def _get_group_strategy_config(self, group_id: str) -> GroupStrategyConfig:
        """
        获取群聊的策略配置（带缓存）
        
        Args:
            group_id: 群聊ID
            
        Returns:
            群聊策略配置（如果群聊不存在或未配置，返回默认配置）
        """
        # 检查缓存
        if self._is_cache_valid(group_id, self._strategy_config_cache):
            cached_config = self._get_cached_data(group_id, self._strategy_config_cache)
            if cached_config:
                logger.debug(f"✅ 使用缓存的策略配置: group_id={group_id}")
                return cached_config
        
        # 从数据库读取
        try:
            group_doc = await self.db[settings.mongodb_db_name].group_chats.find_one(
                {"group_id": group_id},
                {"strategy_config": 1}
            )
            
            if group_doc and "strategy_config" in group_doc:
                # 将字典转换为Pydantic模型
                config = GroupStrategyConfig(**group_doc["strategy_config"])
                logger.info(f"✅ 从数据库加载策略配置: group_id={group_id}")
            else:
                # 使用默认配置
                config = GroupStrategyConfig()
                logger.info(f"⚠️ 群聊未配置策略，使用默认配置: group_id={group_id}")
            
            # 缓存
            self._set_cache_data(group_id, self._strategy_config_cache, config)
            return config
            
        except Exception as e:
            logger.error(f"❌ 获取群聊策略配置失败: group_id={group_id}, 错误={e}", exc_info=True)
            # 出错时返回默认配置
            return GroupStrategyConfig()
    
    # ============ 群组管理 ============
    
    async def create_group(
        self,
        owner_id: str,
        request: CreateGroupRequest
    ) -> GroupChat:
        """创建群聊"""
        return await self.group_manager.create_group(owner_id, request)
    
    async def add_ai_to_group(
        self,
        group_id: str,
        session_id: str,
        user_id: str
    ) -> GroupMember:
        """添加AI到群聊"""
        return await self.group_manager.add_ai_member(group_id, session_id, user_id)
    
    async def add_human_to_group(
        self,
        group_id: str,
        user_id: str,
        inviter_id: str
    ) -> GroupMember:
        """添加真人用户到群聊"""
        return await self.group_manager.add_human_member(group_id, user_id, inviter_id)
    
    async def remove_member(
        self,
        group_id: str,
        member_id: str
    ):
        """从群聊中移除成员"""
        return await self.group_manager.remove_member(group_id, member_id)
    
    async def set_admin(
        self,
        group_id: str,
        member_id: str
    ) -> bool:
        """设置成员为管理员"""
        return await self.group_manager.set_admin(group_id, member_id)
    
    async def remove_admin(
        self,
        group_id: str,
        member_id: str
    ) -> bool:
        """取消成员的管理员身份"""
        return await self.group_manager.remove_admin(group_id, member_id)
    
    async def update_ai_behavior(
        self,
        group_id: str,
        request: UpdateBehaviorRequest
    ):
        """更新AI行为配置"""
        await self.group_manager.update_behavior_config(
            group_id,
            request.ai_member_id,
            request.behavior_config
        )
    
    async def ai_go_online(self, group_id: str, ai_member_id: str):
        """AI上线（由MCP工具调用）"""
        await self.group_manager.update_member_status(
            group_id,
            ai_member_id,
            MemberStatus.ONLINE
        )
        
        # 广播状态更新到所有在线成员
        await self.message_dispatcher.broadcast_member_status(
            group_id,
            ai_member_id,
            "online"
        )
        
        logger.info(f"✅ AI上线: 群组={group_id} | AI={ai_member_id}")
    
    async def ai_go_offline(self, group_id: str, ai_member_id: str):
        """AI下线（由MCP工具调用）"""
        await self.group_manager.update_member_status(
            group_id,
            ai_member_id,
            MemberStatus.OFFLINE
        )
        
        # 广播状态更新到所有在线成员
        await self.message_dispatcher.broadcast_member_status(
            group_id,
            ai_member_id,
            "offline"
        )
        
        # 取消该AI的待处理回复
        await self.ai_scheduler.cancel_pending_replies(group_id, ai_member_id)
        
        logger.info(f"❌ AI下线: 群组={group_id} | AI={ai_member_id}")
    
    async def set_ai_status(self, group_id: str, ai_member_id: str, status: str):
        """设置AI状态（HTTP API 使用）"""
        if status == "online":
            await self.ai_go_online(group_id, ai_member_id)
        elif status == "offline":
            await self.ai_go_offline(group_id, ai_member_id)
        else:
            raise ValueError(f"无效的状态: {status}")
    
    async def human_connect(
        self,
        group_id: str,
        user_id: str,
        websocket_id: str,
        websocket
    ):
        """真人用户连接到群聊"""
        member_id = user_id
        
        # 注册WebSocket
        self.message_dispatcher.register_websocket(member_id, websocket_id, websocket)
        
        # 更新状态为在线
        await self.group_manager.update_member_status(
            group_id,
            member_id,
            MemberStatus.ONLINE,
            websocket_id=websocket_id
        )
        
        # 广播状态更新到所有在线成员
        await self.message_dispatcher.broadcast_member_status(
            group_id,
            member_id,
            "online"
        )
        
        logger.info(f"🔗 真人连接群聊: 群组={group_id} | 用户={user_id}")
    
    async def human_disconnect(
        self,
        group_id: str,
        user_id: str
    ):
        """真人用户断开连接"""
        member_id = user_id
        
        # 注销WebSocket
        self.message_dispatcher.unregister_websocket(member_id)
        
        # 更新状态为离线
        await self.group_manager.update_member_status(
            group_id,
            member_id,
            MemberStatus.OFFLINE
        )
        
        # 广播状态更新到所有在线成员
        await self.message_dispatcher.broadcast_member_status(
            group_id,
            member_id,
            "offline"
        )
        
        logger.info(f"🔌 真人断开群聊: 群组={group_id} | 用户={user_id}")
    
    # ============ 消息处理 ============
    
    async def send_message(
        self,
        group_id: str,
        user_id: str,
        request: SendMessageRequest
    ) -> GroupMessage:
        """发送消息（通用接口）"""
        return await self.send_human_message(group_id, user_id, request)
    
    async def send_human_message(
        self,
        group_id: str,
        user_id: str,
        request: SendMessageRequest
    ) -> GroupMessage:
        """
        真人发送消息
        
        触发AI决策流程
        """
        # 检查用户是否在群组中
        member = await self.group_manager.get_member(group_id, user_id)
        if not member:
            raise ValueError(f"用户不在群组中: {user_id}")
        
        # 🔥 动态获取用户名称（因为用户可能在前端随时修改）
        sender_name = await self._get_user_display_name(user_id)
        
        # 保存消息
        message = await self.message_dispatcher.save_message(
            group_id=group_id,
            sender_id=user_id,
            sender_type=MemberType.HUMAN,
            sender_name=sender_name,
            content=request.content,
            images=request.images,
            mentions=request.mentions,
            reply_to=request.reply_to
        )
        
        # 追踪消息到对话控制器
        self.conversation_controller.track_message(message, estimated_tokens=len(request.content) // 4)
        
        # 广播消息到所有真人（排除发送者）
        await self.message_dispatcher.broadcast_message(message, exclude_sender=True)
        
        # 重置其他成员的连续回复计数
        await self.group_manager.reset_consecutive_replies(group_id, user_id)
        
        # 🔥 真人发送消息时，取消所有待处理的AI延迟任务，重新开始决策
        await self.ai_scheduler.cancel_pending_replies(group_id)
        logger.info(f"🔄 真人发送消息，已取消群组 {group_id} 的所有待处理AI回复任务")
        
        # 🔥 真人发言时，立即取消待处理的AI-to-AI延迟任务
        await self._cancel_ai_to_ai_task(group_id)
        logger.info(f"🔄 真人发送消息，已取消群组 {group_id} 的AI-to-AI延迟任务")
        
        # 触发AI决策流程（异步）
        asyncio.create_task(self._trigger_ai_decision(message))
        
        return message
    
    async def _on_cooldown_recovery(self, group_id: str):
        """
        冷却期结束后的恢复回调
        
        在冷却期结束后，主动触发一次AI决策，让AI有机会继续对话
        """
        logger.info(f"🔄 冷却期恢复回调触发 | 群组={group_id}")
        
        try:
            # 获取群组最后一条消息
            messages = await self.message_dispatcher.get_recent_messages(group_id, limit=1)
            if not messages:
                logger.info(f"📭 群组无消息历史，跳过恢复 | 群组={group_id}")
                return
            
            last_message = messages[0]
            
            # 创建一个虚拟的触发消息（用最后一条消息模拟）
            logger.info(f"🎯 触发冷却期恢复决策 | 最后消息: {last_message.content[:50]}...")
            await self._trigger_ai_decision(last_message)
            
        except Exception as e:
            logger.error(f"❌ 冷却期恢复失败 | 群组={group_id} | 错误: {e}", exc_info=True)
    
    async def _trigger_ai_decision(self, message: GroupMessage):
        """
        触发AI决策流程（内部方法）
        
        流程：
        1. 对话控制检查
        2. 获取所有在线AI
        3. 轻量级过滤 + 概率计算
        4. 调度延迟回复
        5. 执行LLM调用
        """
        group_id = message.group_id
        
        logger.info(f"\n{'='*80}\n🚀 触发AI决策流程\n{'='*80}")
        
        # 0. 获取群组策略配置并转换为控制器配置
        strategy_config = await self._get_group_strategy_config(group_id)
        controller_config = StrategyConfigAdapter.to_conversation_controller_config(strategy_config)
        
        # 1. 对话控制检查（传入动态配置）
        should_trigger, reason = self.conversation_controller.should_trigger_ai_decision(message, controller_config)
        if not should_trigger:
            logger.info(f"🚫 对话控制阻止: {reason}")
            return
        
        logger.info(f"✅ 对话控制检查通过: {reason}")
        
        # 2. 获取所有在线AI
        ai_members = await self.group_manager.get_online_ai_members(group_id)
        
        if not ai_members:
            logger.info("❌ 无在线AI成员，跳过决策流程")
            return
        
        logger.info(f"📊 在线AI成员: {len(ai_members)}")
        for ai in ai_members:
            logger.info(f"  - {ai.display_name or ai.member_id} (session={ai.session_id})")
        
        # 3. 构建通用上下文（用于过滤器）
        # 注意：这里只构建一次，所有AI共享recent_messages
        sample_ai = ai_members[0]
        base_context = await self.message_dispatcher.build_context_for_ai(
            group_id, sample_ai, message
        )
        
        # 4. 轻量级过滤 + 决策（考虑动态回复概率，传入动态配置）
        reply_probability = self.conversation_controller.get_ai_reply_probability(message, controller_config)
        decisions = await self.ai_scheduler.process_message(
            message, ai_members, base_context, 
            base_reply_probability=reply_probability,
            unrestricted_mode=strategy_config.unrestricted_mode
        )
        
        if not decisions:
            logger.info("❌ 无AI通过决策，跳过LLM调用")
            return
        
        logger.info(f"✅ 初步决策完成: {len(decisions)} 个AI候选")
        
        # 5. 🧠 智能调度优化（新增）
        state = self.conversation_controller.get_group_state(group_id)
        
        # 根据策略配置创建调度器实例
        scheduler_config = StrategyConfigAdapter.to_intelligent_scheduler_config(strategy_config)
        scheduler = get_intelligent_scheduler(scheduler_config if strategy_config.unrestricted_mode else None)
        
        # 构建延迟配置
        delay_config = {
            "mention_delay_min": strategy_config.mention_delay_min,
            "mention_delay_max": strategy_config.mention_delay_max,
            "high_interest_delay_min": strategy_config.high_interest_delay_min,
            "high_interest_delay_max": strategy_config.high_interest_delay_max,
            "normal_delay_min": strategy_config.normal_delay_min,
            "normal_delay_max": strategy_config.normal_delay_max,
        }
        
        optimized_decisions = scheduler.optimize_decisions(
            decisions=decisions,
            message=message,
            context=base_context,
            ai_consecutive_count=state.ai_consecutive_count,
            ai_members=ai_members,
            delay_config=delay_config
        )
        
        if not optimized_decisions:
            logger.info("❌ 智能调度优化后无AI被选中，跳过LLM调用")
            return
        
        logger.info(f"✅ 智能调度优化完成: {len(optimized_decisions)} 个AI将回复")
        
        # 6. 为每个AI调度延迟回复（使用优化后的决策）
        for decision in optimized_decisions:
            ai_member = next((ai for ai in ai_members if ai.member_id == decision.ai_member_id), None)
            if not ai_member:
                continue
            
            # 构建该AI的专属上下文
            ai_context = await self.message_dispatcher.build_context_for_ai(
                group_id, ai_member, message
            )
            
            # 调度延迟回复
            await self.ai_scheduler.schedule_reply(
                decision,
                message,
                ai_context,
                reply_callback=self._execute_ai_reply
            )
        
        logger.info(f"⏰ 已调度 {len(optimized_decisions)} 个延迟回复任务")
    
    async def _execute_ai_reply(self, delayed_reply):
        """
        执行AI回复（延迟回调）
        
        Args:
            delayed_reply: DelayedReply对象
        """
        ai_member_id = delayed_reply.ai_member_id
        session_id = delayed_reply.session_id
        message = delayed_reply.message
        old_context = delayed_reply.context
        group_id = message.group_id
        
        logger.info(
            f"\n{'='*80}\n"
            f"🤖 开始执行AI回复\n"
            f"AI: {ai_member_id}\n"
            f"会话: {session_id}\n"
            f"触发消息: {message.content[:50]}...\n"
            f"{'='*80}"
        )
        
        # 🔥 获取群聊策略配置并转换为ReplyController配置
        strategy_config = await self._get_group_strategy_config(group_id)
        reply_config = StrategyConfigAdapter.to_reply_controller_config(strategy_config)
        max_concurrent_replies = reply_config["max_concurrent_replies"]
        
        # 🔥 抢答控制（使用动态配置）
        allowed = await self.reply_controller.should_allow_reply(
            message.message_id, 
            max_concurrent_replies=max_concurrent_replies
        )
        if not allowed:
            logger.warning(f"🚫 抢答限制: AI {ai_member_id} 被阻止回复 (最大并发数={max_concurrent_replies})")
            return
        
        try:
            # 获取AI成员信息
            ai_member = await self.group_manager.get_member(old_context.group_id, ai_member_id)
            if not ai_member:
                logger.error(f"❌ AI成员不存在: {ai_member_id}")
                return
            
            # 检查AI是否仍在线
            if ai_member.status != MemberStatus.ONLINE:
                logger.warning(f"⚠️ AI已离线，跳过回复: {ai_member_id}")
                return
            
            # 🎯 信号量控制：避免多个AI同时生成导致刷屏
            # 获取或创建该群组的信号量
            if group_id not in self._llm_semaphores:
                self._llm_semaphores[group_id] = asyncio.Semaphore(self._max_concurrent_llm_per_group)
            
            semaphore = self._llm_semaphores[group_id]
            
            # 等待获取信号量（排队）
            logger.info(f"⏳ {ai_member.display_name or ai_member_id} 正在等待LLM调用许可...")
            async with semaphore:
                # 🔥 在获得信号量后，重新获取最新上下文（包含排队期间其他AI的回复）
                # 这样确保每个AI都能看到最新的对话历史
                logger.info(f"🔄 重新获取最新上下文...")
                context = await self.message_dispatcher.build_context_for_ai(
                    old_context.group_id, ai_member, message
                )
                logger.info(f"📊 最新上下文: {len(context.recent_messages)} 条历史消息")
                
                # 从会话加载模型配置和系统提示词
                from ...config import settings
                session_data = await self.db[settings.mongodb_db_name].chat_sessions.find_one({
                    "_id": session_id
                })
                
                if not session_data:
                    logger.error(f"❌ 会话不存在: {session_id}")
                    return
                
                model_settings = session_data.get("model_settings")
                if not model_settings:
                    logger.error(f"❌ 会话无模型配置: {session_id}")
                    return
                
                # 获取AI会话的系统提示词
                user_system_prompt = session_data.get("system_prompt", "")
                
                # 获取群聊的自定义系统提示词
                group_doc = await self.db[settings.mongodb_db_name].group_chats.find_one(
                    {"group_id": old_context.group_id},
                    {"group_system_prompt": 1}
                )
                group_system_prompt = group_doc.get("group_system_prompt", "") if group_doc else ""
                
                # 格式化上下文为LLM输入（传入AI系统提示词 + 群聊系统提示词）
                system_prompt, history_messages = await self.message_dispatcher.format_context_for_llm(
                    context, ai_member, user_system_prompt, group_system_prompt
                )
                
                # 调用LLM生成回复
                logger.info(f"✅ {ai_member.display_name or ai_member_id} 获得LLM调用许可，开始生成回复")
                logger.info(f"📝 系统提示词:\n{system_prompt}")
                logger.info(f"📚 历史消息数量: {len(history_messages)}")
                
                # 🔥 修复：群聊改用流式处理（与1对1会话100%一致，确保引用数据正确）
                complete_response = ""
                skip_reply = False
                tools_called = []
                references = []
                
                try:
                    # 使用流式生成器（与chat.py完全一致）
                    stream_generator = self.llm_service.generate_stream_universal(
                    user_message="",  # 当前消息已在system_prompt中
                    history=history_messages,
                    model_settings=model_settings,
                    system_prompt=system_prompt,
                    session_id=session_id,
                    user_id=session_data.get("user_id"),
                        images_base64=[],  # 群聊暂不支持图片
                        enable_tools=True,  # 启用工具调用
                        message_id=None,  # 群聊不需要message_id
                        # max_tool_iterations 参数已移除，使用 tool_config.max_iterations 全局配置
                    )
                    
                    # 🔥 用于累积 MCP 工具返回的引用（与chat.py完全一致）
                    mcp_rich_refs = []
                    mcp_lean_refs = []
                    
                    # 🔥 遍历流式输出（与chat.py完全一致的处理方式）
                    async for chunk in stream_generator:
                        if chunk:
                            # 🎯 检查是否是工具状态消息（特殊格式）
                            if chunk.startswith("__TOOL_STATUS__") and chunk.endswith("__END__"):
                                # 提取工具状态JSON，但不发送到前端（避免显示多余气泡）
                                try:
                                    status_json = chunk[15:-7]  # 去掉 __TOOL_STATUS__ 和 __END__
                                    status_data = json.loads(status_json)
                                    # 只记录日志，不发送到前端
                                    logger.debug(f"🔧 工具状态（不发送到前端）: {status_data}")
                                except Exception as e:
                                    logger.error(f"解析工具状态失败: {e}")
                            # 🎯 检查是否是引用数据消息（新增）
                            elif chunk.startswith("__REFERENCES__") and chunk.endswith("__END__"):
                                # 提取引用数据JSON
                                try:
                                    refs_json = chunk[14:-7]  # 去掉 __REFERENCES__ 和 __END__
                                    refs_data = json.loads(refs_json)
                                    mcp_rich_refs.extend(refs_data.get("rich", []))
                                    mcp_lean_refs.extend(refs_data.get("lean", []))
                                    
                                    logger.info(f"📚 已接收 MCP 工具引用，条数: {len(refs_data.get('rich', []))}")
                                except Exception as e:
                                    logger.error(f"解析引用数据失败: {e}")
                            else:
                                # 正常的消息内容
                                complete_response += chunk  # 累积响应
                                logger.debug(f"发送回复片段(len={len(chunk)}): {chunk[:120]}{'...' if len(chunk) > 120 else ''}")
                    
                    # 🔥 使用MCP工具返回的引用（与chat.py完全一致）
                    references = mcp_lean_refs
                    
                    logger.info(f"🏁 {ai_member.display_name or ai_member_id} LLM流式生成完毕")
                    logger.info(f"📊 生成结果: 内容长度={len(complete_response)}, 引用数={len(references)}")
                
                except Exception as stream_error:
                    logger.error(f"❌ 流式生成失败: {stream_error}")
                    logger.error(traceback.format_exc())
                    # 生成失败时，返回空响应
                    complete_response = ""
                    skip_reply = True
            
            # 🧠 相似度检测（避免雷同回复）
            # 注意：无限制模式下或配置禁用时跳过相似度检测
            is_similar = False
            similar_content = None
            
            enable_similarity = strategy_config.enable_similarity_detection
            unlimited_mode = strategy_config.unrestricted_mode
            
            if enable_similarity and not unlimited_mode:
                # 获取相似度配置参数
                similarity_threshold = strategy_config.similarity_threshold
                similarity_lookback = strategy_config.similarity_lookback
                
                # 进行相似度检测
                default_scheduler = get_intelligent_scheduler()
                is_similar, similar_content = default_scheduler.check_similarity_with_recent(
                    old_context.group_id,
                    complete_response,
                    lookback=similarity_lookback,
                    threshold=similarity_threshold
                )
                
                if is_similar:
                    # 内容相似度过高，AI自动跳过回复
                    logger.warning(
                        f"🚫 相似度检测：AI回复与最近内容重复，自动跳过\n"
                        f"AI: {ai_member.display_name or ai_member_id}\n"
                        f"原回复: {complete_response[:100]}...\n"
                        f"相似内容: {similar_content[:100] if similar_content else ''}...\n"
                        f"阈值: {similarity_threshold} | 回溯: {similarity_lookback}\n"
                        f"{'='*80}"
                    )
                    skip_reply = True
            else:
                reason = "无限制模式" if unlimited_mode else "配置禁用"
                logger.debug(
                    f"🔓 跳过相似度检测 ({reason}) | "
                    f"AI={ai_member.display_name or ai_member_id}"
                )
            
            # 检查AI是否调用了skip_reply工具（或被相似度检测拦截）
            if skip_reply:
                # AI选择不回复
                logger.info(
                    f"🤐 AI通过skip_reply工具选择不回复: {ai_member.display_name or ai_member_id}\n"
                    f"工具调用: {tools_called}\n"
                    f"{'='*80}"
                )
            else:
                # 🧹 清洗AI回复内容（去除模型可能添加的多余标识）
                # 🔥 动态获取AI会话的最新名称（确保使用chat_sessions中的最新名称）
                ai_name = await self._get_ai_display_name(session_id)
                
                # 🔥 获取群组所有成员名称（用于精确清洗）
                all_members = await self.group_manager.get_all_members(context.group_id)
                member_names = [m.display_name for m in all_members if m.display_name]
                
                cleaned_response = self._clean_ai_response(complete_response, ai_name, member_names)
                
                # 保存并广播消息
                ai_message = await self.message_dispatcher.save_message(
                    group_id=context.group_id,
                    sender_id=ai_member_id,
                    sender_type=MemberType.AI,
                    sender_name=ai_name,
                    content=cleaned_response,
                    message_type=MessageType.AI_REPLY,
                    ai_session_id=session_id,
                    reference=references  # 🔥 改为单数，与普通会话一致
                )
                
                # 追踪AI回复到对话控制器
                self.conversation_controller.track_message(
                    ai_message, 
                    estimated_tokens=len(complete_response) // 4
                )
                
                # 🧠 记录AI回复到智能调度器（用于相似度检测）
                # 注意：这里使用默认调度器记录回复（与策略配置无关）
                default_scheduler = get_intelligent_scheduler()
                default_scheduler.record_reply(
                    group_id=context.group_id,
                    ai_member_id=ai_member_id,
                    content=cleaned_response
                )
                
                await self.message_dispatcher.broadcast_message(ai_message)
                
                # 🎯 消息发送后短暂延迟，避免多个AI同时完成信号量后立即刷屏
                # 这让前端有时间渲染每条消息，用户体验更平滑
                await asyncio.sleep(0.3)
                
                # 更新AI回复统计
                await self.group_manager.update_member_reply_stats(
                    context.group_id,
                    ai_member_id,
                    increment_consecutive=True
                )
                
                logger.info(
                    f"✅ AI回复完成: {ai_member.display_name or ai_member_id}\n"
                    f"工具调用: {tools_called}\n"
                    f"原始回复: {complete_response[:150]}{'...' if len(complete_response) > 150 else ''}\n"
                    f"清洗后: {cleaned_response[:150]}{'...' if len(cleaned_response) > 150 else ''}\n"
                    f"{'='*80}"
                )
                
                # 🔥 触发新的AI决策流程（AI-to-AI对话）
                # 从群组配置读取延迟时间，如果期间有真人发言则会被取消
                # 通过适配器统一获取延迟时间（自动处理无限制模式）
                delay_seconds = StrategyConfigAdapter.get_ai_to_ai_delay(strategy_config)
                task = asyncio.create_task(self._trigger_ai_decision_with_delay(ai_message, delay_seconds=delay_seconds))
                self._ai_to_ai_tasks[context.group_id] = task
            
        except Exception as e:
            logger.error(f"❌ AI回复失败: {ai_member_id} | 错误: {e}", exc_info=True)
    
    def _clean_ai_response(self, content: str, ai_name: str, member_names: List[str]) -> str:
        """
        清洗AI回复内容，去除模型可能添加的多余标识
        
        处理策略：
        1. 循环清洗所有群组成员的名称前缀（支持精确匹配和模糊匹配）
        2. 优先清洗当前AI自己的名称
        3. 支持名称简写形式（如 "白淑" → "白淑-大模型数据处理工程师"）
        4. 支持模糊匹配（如 "舟镜-大模型训练工程师" 匹配 "舟镜-大模型训练师工程师"）
        5. 保护正文内容中的[]符号和冒号
        
        Args:
            content: 原始回复内容
            ai_name: AI的显示名称
            member_names: 群组所有成员的显示名称列表（用于精确匹配）
        
        Returns:
            清洗后的内容
            
        Examples:
            "[张三]: [张三]: 你好" → "你好" (重复清洗)
            "[张三]: 时间：下午3点" → "时间：下午3点" (保留正文冒号)
            "[白淑]: 你好" → "你好" (简写形式，ai_name="白淑-大模型数据处理工程师")
            "[舟镜-大模型训练工程师]: 你好" → "你好" (模糊匹配，ai_name="舟镜-大模型训练师工程师")
            "[紧急通知]: 请注意" → "[紧急通知]: 请注意" (不在成员名单，不清洗)
        """
        if not content:
            return content
        
        import re
        cleaned = content.strip()
        
        # 🔄 循环清洗，直到没有匹配为止（处理重复前缀问题）
        max_iterations = 10  # 防止无限循环
        iteration = 0
        
        # 🎯 构建所有需要清洗的名称列表（AI名称优先）
        names_to_clean = [ai_name] + [name for name in member_names if name != ai_name]
        
        # 🔥 为每个名称生成多种变体（用于匹配不同格式的前缀）
        # 变体包括：
        # 1. 完整名称（精确匹配）
        # 2. 简写形式（连字符前的部分，如 "白淑"）
        # 3. 模糊匹配（使用正则表达式匹配任何以相同前缀开始的变体）
        name_variants = {}
        for name in names_to_clean:
            if not name:
                continue
            name_variants[name] = [name]  # 完整名称
            
            # 添加简写形式（连字符前的部分）
            if '-' in name:
                short_name = name.split('-')[0].strip()
                if short_name:
                    name_variants[name].append(short_name)
                
                # 🔥 添加模糊匹配模式（匹配以相同前缀开始的任何变体）
                # 例如："舟镜-大模型训练师工程师" 会生成模式匹配 "舟镜-大模型训练[.*]工程师"
                # 这样可以匹配 "舟镜-大模型训练工程师"（缺少"师"）
                # 
                # 策略：如果名称包含连字符，则将连字符后的部分作为模糊匹配区域
                # 模式：短名称-[任意内容]（但要确保不会匹配到其他成员）
                # 
                # 注意：为了安全，我们只对特定模式启用模糊匹配（包含"工程师"等关键词）
                if '工程师' in name or '专家' in name or '经理' in name:
                    # 生成模糊匹配模式：短名称-.*?[关键词]
                    # 例如："舟镜-.*?工程师"
                    fuzzy_pattern = rf"{re.escape(short_name)}-[^:\]】]*?工程师"
                    name_variants[name].append(fuzzy_pattern)
        
        while iteration < max_iterations:
            iteration += 1
            previous = cleaned
            
            # 清洗所有成员名称前缀（支持完整名称、简写和模糊匹配）
            for name, variants in name_variants.items():
                for variant in variants:
                    # 判断是否为模糊匹配模式（包含正则表达式特殊字符）
                    is_fuzzy_pattern = any(c in variant for c in ['[', ']', '*', '?', '.'])
                    
                    if is_fuzzy_pattern:
                        # 🔥 模糊匹配：使用正则表达式匹配
                        # 格式：[模糊模式]: 或 【模糊模式】: 等
                        patterns = [
                            rf"^\[{variant}\]\s*[：:]\s*",   # [模糊名称]: 或 [模糊名称]：
                            rf"^【{variant}】\s*[：:]\s*",  # 【模糊名称】: 或 【模糊名称】：
                            rf"^{variant}\s*[：:]\s*",       # 模糊名称: 或 模糊名称：
                        ]
                    else:
                        # 精确匹配：直接匹配完整名称或简写
                        # 格式：[名称]: 【名称】: 名称: 等
                        patterns = [
                            rf"^\[{re.escape(variant)}\]\s*[：:]\s*",   # [名称]: 或 [名称]：
                            rf"^【{re.escape(variant)}】\s*[：:]\s*",  # 【名称】: 或 【名称】：
                            rf"^{re.escape(variant)}\s*[：:]\s*",       # 名称: 或 名称：
                        ]
                    
                    for pattern in patterns:
                        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
            
            # 如果本次清洗后内容没有变化，说明已清洗完毕
            if cleaned == previous:
                break
        
        return cleaned
    
    def _should_skip_ai_reply(self, content: str) -> bool:
        """
        判断AI是否选择不回复
        
        Args:
            content: AI生成的内容
            
        Returns:
            True: 应该跳过此回复
            False: 正常回复
        """
        if not content:
            return True
        
        # 去除空白字符后检查
        cleaned = content.strip()
        
        # 定义"不回复"的各种表达方式
        skip_patterns = [
            "不回复",
            "不回答",
            "不响应",
            "沉默",
            "pass",
            "skip",
            "no reply",
            "no response",
            "...",  # 只有省略号
        ]
        
        # 检查是否匹配任何跳过模式
        for pattern in skip_patterns:
            if cleaned.lower() == pattern.lower():
                return True
        
        # 如果内容太短（少于2个字符），也认为是无效回复
        if len(cleaned) < 2:
            return True
        
        return False
    
    # ============ 查询接口 ============
    
    async def get_group_info(self, group_id: str) -> Optional[GroupChat]:
        """获取群组信息"""
        return await self.group_manager.get_group(group_id)
    
    async def get_group_members(self, group_id: str) -> List[GroupMember]:
        """获取群组所有成员（动态更新显示名称和头像）"""
        members = await self.group_manager.get_all_members(group_id)
        
        # 🔥 批量获取所有成员信息，避免逐个查询造成阻塞
        await self._batch_update_member_info(members)
        
        return members
    
    async def _batch_update_member_info(self, members: List[GroupMember]) -> None:
        """批量更新成员信息，避免逐个查询造成阻塞"""
        if not members:
            return
        
        # 分离人类用户和AI用户
        human_members = [m for m in members if m.member_type == MemberType.HUMAN]
        ai_members = [m for m in members if m.member_type == MemberType.AI]
        
        # 并行处理人类用户和AI用户信息
        tasks = []
        
        if human_members:
            tasks.append(self._batch_update_human_members(human_members))
        
        if ai_members:
            tasks.append(self._batch_update_ai_members(ai_members))
        
        # 并行执行所有任务
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _batch_update_human_members(self, human_members: List[GroupMember]) -> None:
        """批量更新人类用户信息"""
        if not human_members:
            return
        
        try:
            # 批量查询所有用户信息
            user_ids = [ObjectId(m.member_id) for m in human_members]
            user_docs = await self.db[settings.mongodb_db_name].users.find(
                {"_id": {"$in": user_ids}}
            ).to_list(length=None)
            
            # 创建用户信息映射
            user_info_map = {
                str(doc["_id"]): {
                    "display_name": doc.get("full_name") or doc.get("account") or str(doc["_id"]),
                    "avatar": doc.get("avatar_url") or ""
                }
                for doc in user_docs
            }
            
            # 更新成员信息
            for member in human_members:
                user_info = user_info_map.get(member.member_id)
                if user_info:
                    member.display_name = user_info["display_name"]
                    member.avatar = user_info["avatar"]
                else:
                    # 如果找不到用户信息，使用默认值
                    member.display_name = member.member_id
                    member.avatar = ""
                    
        except Exception as e:
            logger.warning(f"批量更新人类用户信息失败: {e}")
            # 发生错误时使用默认值
            for member in human_members:
                member.display_name = member.member_id
                member.avatar = ""
    
    async def _batch_update_ai_members(self, ai_members: List[GroupMember]) -> None:
        """批量更新AI用户信息"""
        if not ai_members:
            return
        
        try:
            # 提取实际的session_id（去掉ai_前缀）
            session_ids = []
            member_session_map = {}
            
            for member in ai_members:
                actual_session_id = member.member_id.replace("ai_", "") if member.member_id.startswith("ai_") else member.member_id
                session_ids.append(actual_session_id)
                member_session_map[actual_session_id] = member
            
            # 并行查询chat_sessions和ragflow_sessions
            tasks = [
                self.db[settings.mongodb_db_name].chat_sessions.find(
                    {"_id": {"$in": session_ids}}
                ).to_list(length=None),
                self.db[settings.mongodb_db_name].ragflow_sessions.find(
                    {"_id": {"$in": session_ids}}
                ).to_list(length=None)
            ]
            
            chat_sessions, ragflow_sessions = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理查询结果
            if isinstance(chat_sessions, Exception):
                chat_sessions = []
            if isinstance(ragflow_sessions, Exception):
                ragflow_sessions = []
            
            # 创建会话信息映射
            session_info_map = {}
            
            # 处理chat_sessions结果
            for doc in chat_sessions:
                session_id = str(doc["_id"])
                session_info_map[session_id] = {
                    "display_name": doc.get("name") or session_id,
                    "avatar": doc.get("role_avatar_url") or ""
                }
            
            # 处理ragflow_sessions结果（如果chat_sessions中没有找到）
            for doc in ragflow_sessions:
                session_id = str(doc["_id"])
                if session_id not in session_info_map:
                    session_info_map[session_id] = {
                        "display_name": doc.get("name") or session_id,
                        "avatar": doc.get("role_avatar_url") or ""
                    }
            
            # 更新成员信息
            for member in ai_members:
                actual_session_id = member.member_id.replace("ai_", "") if member.member_id.startswith("ai_") else member.member_id
                session_info = session_info_map.get(actual_session_id)
                
                if session_info:
                    member.display_name = session_info["display_name"]
                    member.avatar = session_info["avatar"]
                else:
                    # 如果找不到会话信息，使用默认值
                    member.display_name = member.member_id
                    member.avatar = ""
                    
        except Exception as e:
            logger.warning(f"批量更新AI用户信息失败: {e}")
            # 发生错误时使用默认值
            for member in ai_members:
                member.display_name = member.member_id
                member.avatar = ""
    
    async def _get_user_display_name(self, user_id: str) -> str:
        """从数据库获取用户的显示名称（带缓存）"""
        # 🔥 先检查缓存
        cache_key = f"user_name_{user_id}"
        cached_data = self._get_cached_data(cache_key, self._user_cache)
        if cached_data:
            return cached_data
        
        try:
            user_doc = await self.db[settings.mongodb_db_name].users.find_one(
                {"_id": ObjectId(user_id)}
            )
            if user_doc:
                result = user_doc.get("full_name") or user_doc.get("account") or user_id
            else:
                result = user_id
            
            # 🔥 缓存结果
            self._set_cache_data(cache_key, self._user_cache, result)
            return result
            
        except Exception as e:
            logger.warning(f"获取用户显示名称失败: {e}")
            result = user_id
            # 即使出错也缓存，避免重复查询
            self._set_cache_data(cache_key, self._user_cache, result)
            return result
    
    
    async def _get_ai_display_name(self, session_id: str) -> str:
        """从数据库获取AI会话的显示名称（带缓存）"""
        # 🔥 先检查缓存
        cache_key = f"ai_name_{session_id}"
        cached_data = self._get_cached_data(cache_key, self._session_cache)
        if cached_data:
            return cached_data
        
        try:
            logger.info(f"🔍 正在获取AI会话显示名称: session_id={session_id}")
            
            # 去掉 ai_ 前缀（如果有）
            actual_session_id = session_id.replace("ai_", "") if session_id.startswith("ai_") else session_id
            logger.info(f"📝 实际查询的session_id: {actual_session_id}")
            
            # 先尝试从chat_sessions查找
            session_doc = await self.db[settings.mongodb_db_name].chat_sessions.find_one(
                {"_id": actual_session_id}
            )
            if session_doc:
                result = session_doc.get("name") or session_id
                logger.info(f"✅ 从chat_sessions找到: {result}")
                # 🔥 缓存结果
                self._set_cache_data(cache_key, self._session_cache, result)
                return result
            
            # 再尝试从ragflow_sessions查找
            session_doc = await self.db[settings.mongodb_db_name].ragflow_sessions.find_one(
                {"_id": actual_session_id}
            )
            if session_doc:
                result = session_doc.get("name") or session_id
                logger.info(f"✅ 从ragflow_sessions找到: {result}")
                # 🔥 缓存结果
                self._set_cache_data(cache_key, self._session_cache, result)
                return result
            
            logger.warning(f"⚠️ 未找到session_id={actual_session_id}的会话，使用ID作为显示名称")
            result = session_id
            # 🔥 缓存结果
            self._set_cache_data(cache_key, self._session_cache, result)
            return result
            
        except Exception as e:
            logger.warning(f"❌ 获取AI会话显示名称失败: {e}")
            result = session_id
            # 即使出错也缓存，避免重复查询
            self._set_cache_data(cache_key, self._session_cache, result)
            return result
    
    
    async def _cancel_ai_to_ai_task(self, group_id: str):
        """
        取消群组的AI-to-AI延迟任务
        
        Args:
            group_id: 群聊ID
        """
        if group_id in self._ai_to_ai_tasks:
            task = self._ai_to_ai_tasks[group_id]
            if not task.done():
                task.cancel()
                logger.info(f"✅ 已取消群组 {group_id} 的AI-to-AI延迟任务")
            del self._ai_to_ai_tasks[group_id]
    
    async def _trigger_ai_decision_with_delay(self, message: GroupMessage, delay_seconds: float):
        """
        延迟触发AI决策流程（用于AI-to-AI对话）
        
        如果延迟期间有真人发言，该任务会被取消
        
        Args:
            message: 触发消息（AI消息）
            delay_seconds: 延迟秒数（从群组配置读取）
        """
        group_id = message.group_id
        
        try:
            logger.info(
                f"⏰ AI-to-AI延迟任务已调度 | 群组={group_id} | "
                f"触发者={message.sender_name} | 延迟={delay_seconds}秒"
            )
            
            # 等待延迟
            await asyncio.sleep(delay_seconds)
            
            logger.info(f"🎯 AI-to-AI延迟期结束，触发AI决策 | 群组={group_id}")
            
            # 触发AI决策
            await self._trigger_ai_decision(message)
            
        except asyncio.CancelledError:
            logger.info(f"🚫 AI-to-AI延迟任务被取消 | 群组={group_id} | 原因：真人发言")
        except Exception as e:
            logger.error(f"❌ AI-to-AI延迟任务失败 | 群组={group_id} | 错误: {e}", exc_info=True)
        finally:
            # 清理任务引用
            if group_id in self._ai_to_ai_tasks:
                del self._ai_to_ai_tasks[group_id]
    
    async def get_recent_messages(
        self,
        group_id: str,
        limit: int = 50
    ) -> List[GroupMessage]:
        """获取最近消息"""
        return await self.message_dispatcher.get_recent_messages(group_id, limit)
    
    async def get_scheduler_stats(self) -> Dict[str, Any]:
        """获取调度器统计信息"""
        return self.ai_scheduler.get_stats()

