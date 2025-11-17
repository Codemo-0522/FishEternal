"""
消息分发器

负责消息存储、广播、上下文构建
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from ...models.group_chat import (
    GroupMessage, GroupMember, GroupChatContext,
    MessageType, MemberType, MemberRole, SendMessageRequest
)
from ...config import settings
from .group_manager import GroupManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 启用 DEBUG 日志


class MessageDispatcher:
    """
    消息分发器
    
    ⚠️ WebSocket池使用类变量，所有实例共享同一个连接池
    这样可以确保不同的服务实例能够访问到所有已连接的WebSocket
    """
    
    # 🔥 类变量：所有实例共享同一个WebSocket池
    _websocket_pool: Dict[str, Any] = {}
    _member_ws_mapping: Dict[str, str] = {}
    
    def __init__(self, db: AsyncIOMotorClient):
        self.db = db
        self.collection_messages = db[settings.mongodb_db_name].group_messages
        self.collection_groups = db[settings.mongodb_db_name].group_chats
        self.group_manager = GroupManager(db)
    
    def register_websocket(self, member_id: str, websocket_id: str, websocket):
        """注册WebSocket连接"""
        self._websocket_pool[websocket_id] = websocket
        self._member_ws_mapping[member_id] = websocket_id
        logger.info(
            f"📡 注册WebSocket成功:\n"
            f"  - 成员ID: {member_id}\n"
            f"  - WS_ID: {websocket_id}\n"
            f"  - 当前池大小: {len(self._websocket_pool)}\n"
            f"  - 当前映射: {self._member_ws_mapping}"
        )
    
    def unregister_websocket(self, member_id: str):
        """注销WebSocket连接"""
        websocket_id = self._member_ws_mapping.pop(member_id, None)
        if websocket_id:
            self._websocket_pool.pop(websocket_id, None)
            logger.info(
                f"📡 注销WebSocket成功:\n"
                f"  - 成员ID: {member_id}\n"
                f"  - WS_ID: {websocket_id}\n"
                f"  - 剩余池大小: {len(self._websocket_pool)}"
            )
        else:
            logger.warning(f"⚠️ 尝试注销不存在的WebSocket: 成员={member_id}")
    
    async def save_message(
        self,
        group_id: str,
        sender_id: str,
        sender_type: MemberType,
        sender_name: str,
        content: str,
        images: List[str] = None,
        mentions: List[str] = None,
        reply_to: Optional[str] = None,
        message_type: MessageType = MessageType.TEXT,
        ai_session_id: Optional[str] = None,
        reference: List[Dict[str, Any]] = None  # 🔥 改为单数，与普通会话一致
    ) -> GroupMessage:
        """
        保存消息到数据库
        
        Returns:
            保存的消息对象
        """
        message_id = str(uuid.uuid4())
        
        message = GroupMessage(
            message_id=message_id,
            group_id=group_id,
            sender_id=sender_id,
            sender_type=sender_type,
            sender_name=sender_name,
            message_type=message_type,
            content=content,
            images=images or [],
            mentions=mentions or [],
            reply_to=reply_to,
            ai_session_id=ai_session_id,
            reference=reference or []  # 🔥 改为单数
        )
        
        # 保存到数据库
        await self.collection_messages.insert_one(message.dict())
        
        # 更新群组统计
        await self.collection_groups.update_one(
            {"group_id": group_id},
            {
                "$inc": {"message_count": 1},
                "$set": {"last_message_time": message.timestamp}
            }
        )
        
        logger.info(
            f"💾 保存消息: 群组={group_id} | 发送者={sender_name} ({sender_type}) | "
            f"内容={content[:50]}..."
        )
        
        return message
    
    async def broadcast_message(
        self,
        message: GroupMessage,
        exclude_sender: bool = False
    ):
        """
        广播消息到所有在线真人成员
        
        Args:
            message: 消息对象
            exclude_sender: 是否排除发送者
        """
        logger.info(f"\n{'='*80}\n📤 开始广播消息 | 群组={message.group_id} | 发送者={message.sender_id}\n{'='*80}")
        
        # 获取所有在线真人成员
        members = await self.group_manager.get_all_members(message.group_id)
        
        # 🔥 详细调试日志
        logger.info(f"📋 群组所有成员（共{len(members)}个）:")
        for m in members:
            logger.info(f"  - 成员ID={m.member_id} | 类型={m.member_type} | 状态={m.status} | WS_ID={getattr(m, 'websocket_id', None)}")
        
        online_humans = [
            m for m in members
            if m.member_type == MemberType.HUMAN and m.websocket_id
        ]
        
        logger.info(f"🌐 筛选后的在线真人（共{len(online_humans)}个）:")
        for m in online_humans:
            logger.info(f"  - 成员ID={m.member_id} | WS_ID={m.websocket_id}")
        
        logger.info(f"🔌 内存中的WebSocket池（共{len(self._websocket_pool)}个）:")
        for ws_id in self._websocket_pool.keys():
            logger.info(f"  - WS_ID={ws_id}")
        
        logger.info(f"🗺️ 成员ID→WebSocket映射（共{len(self._member_ws_mapping)}个）:")
        for member_id, ws_id in self._member_ws_mapping.items():
            logger.info(f"  - 成员={member_id} → WS_ID={ws_id}")
        
        if exclude_sender:
            before_exclude = len(online_humans)
            online_humans = [m for m in online_humans if m.member_id != message.sender_id]
            logger.info(f"🚫 排除发送者: 排除前={before_exclude} | 排除后={len(online_humans)} | 发送者ID={message.sender_id}")
        
        # 构建WebSocket消息
        message_data = message.model_dump(mode='json')
        ws_message = {
            "type": "message",
            "data": message_data
        }
        
        # 广播到所有在线真人
        success_count = 0
        fail_count = 0
        for member in online_humans:
            websocket = self._websocket_pool.get(member.websocket_id)
            if websocket:
                try:
                    await websocket.send_json(ws_message)
                    success_count += 1
                    logger.info(f"✅ 广播成功: 成员={member.member_id} | WS_ID={member.websocket_id}")
                except Exception as e:
                    fail_count += 1
                    logger.error(f"❌ 广播失败: 成员={member.member_id} | 错误={e}", exc_info=True)
            else:
                fail_count += 1
                logger.warning(f"⚠️ WebSocket未找到: 成员={member.member_id} | WS_ID={member.websocket_id} | 可能原因：连接已断开或未注册")
        
        logger.info(
            f"\n📊 广播结果统计:\n"
            f"  - 群组: {message.group_id}\n"
            f"  - 目标真人数: {len(online_humans)}\n"
            f"  - 成功发送: {success_count}\n"
            f"  - 失败: {fail_count}\n"
            f"{'='*80}\n"
        )
    
    async def broadcast_member_status(
        self,
        group_id: str,
        member_id: str,
        status: str
    ):
        """
        广播成员状态变更到所有在线真人成员
        
        Args:
            group_id: 群组ID
            member_id: 成员ID
            status: 新状态 (online/offline/busy)
        """
        # 获取所有在线真人成员
        members = await self.group_manager.get_all_members(group_id)
        online_humans = [
            m for m in members
            if m.member_type == MemberType.HUMAN and m.websocket_id
        ]
        
        # 构建状态更新消息
        ws_message = {
            "type": "member_status",
            "data": {
                "member_id": member_id,
                "status": status
            }
        }
        
        # 广播到所有在线真人
        success_count = 0
        for member in online_humans:
            websocket = self._websocket_pool.get(member.websocket_id)
            if websocket:
                try:
                    await websocket.send_json(ws_message)
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ 广播状态失败: 成员={member.member_id} | 错误={e}")
        
        logger.info(
            f"📢 广播状态更新: 群组={group_id} | 成员={member_id} | "
            f"状态={status} | 发送成功={success_count}/{len(online_humans)}"
        )
    
    async def send_to_member(
        self,
        member_id: str,
        message_type: str,
        data: Dict[str, Any]
    ):
        """
        发送消息到指定成员
        
        Args:
            member_id: 成员ID
            message_type: 消息类型
            data: 消息数据
        """
        websocket_id = self._member_ws_mapping.get(member_id)
        if not websocket_id:
            logger.warning(f"⚠️ 成员未连接: {member_id}")
            return
        
        websocket = self._websocket_pool.get(websocket_id)
        if not websocket:
            logger.warning(f"⚠️ WebSocket不存在: {websocket_id}")
            return
        
        try:
            await websocket.send_json({
                "type": message_type,
                "data": data
            })
        except Exception as e:
            logger.error(f"❌ 发送消息失败: 成员={member_id} | 错误={e}")
    
    async def get_recent_messages(
        self,
        group_id: str,
        limit: int = 50
    ) -> List[GroupMessage]:
        """
        获取最近的消息（动态获取AI头像）
        
        Args:
            group_id: 群组ID
            limit: 数量限制
        
        Returns:
            消息列表（按时间倒序）
        """
        cursor = self.collection_messages.find(
            {"group_id": group_id}
        ).sort("timestamp", -1).limit(limit)
        
        messages = []
        async for doc in cursor:
            doc.pop("_id", None)
            message = GroupMessage(**doc)
            
            
            messages.append(message)
        
        # 反转列表（变为按时间正序）
        messages.reverse()
        
        return messages
    
    async def build_context_for_ai(
        self,
        group_id: str,
        ai_member: GroupMember,
        current_message: GroupMessage
    ) -> GroupChatContext:
        """
        为AI构建上下文
        
        Args:
            group_id: 群组ID
            ai_member: AI成员
            current_message: 当前触发的消息
        
        Returns:
            群聊上下文
        """
        # 获取AI的上下文窗口大小
        context_size = 20  # 默认
        if ai_member.behavior_config:
            context_size = ai_member.behavior_config.context_window_size
        
        # 获取最近消息
        recent_messages = await self.get_recent_messages(group_id, limit=context_size)
        
        # 🔥 动态更新历史消息中的用户名称和AI名称
        from bson import ObjectId
        for msg in recent_messages:
            if msg.sender_type == MemberType.HUMAN:
                # 动态获取用户最新名称
                try:
                    user_doc = await self.db[settings.mongodb_db_name].users.find_one(
                        {"_id": ObjectId(msg.sender_id)}
                    )
                    if user_doc:
                        msg.sender_name = user_doc.get("full_name") or user_doc.get("account") or msg.sender_id
                except Exception as e:
                    logger.warning(f"获取用户显示名称失败: sender_id={msg.sender_id}, 错误={e}")
            elif msg.sender_type == MemberType.AI and msg.ai_session_id:
                # 🔥 动态获取AI会话的最新名称
                try:
                    # 从chat_sessions或ragflow_sessions获取最新名称
                    session_doc = await self.db[settings.mongodb_db_name].chat_sessions.find_one(
                        {"_id": msg.ai_session_id}
                    )
                    if not session_doc:
                        session_doc = await self.db[settings.mongodb_db_name].ragflow_sessions.find_one(
                            {"_id": msg.ai_session_id}
                        )
                    if session_doc:
                        msg.sender_name = session_doc.get("name") or msg.sender_id
                except Exception as e:
                    logger.warning(f"获取AI会话显示名称失败: ai_session_id={msg.ai_session_id}, 错误={e}")
        
        # 获取成员信息
        all_members = await self.group_manager.get_all_members(group_id)
        # 注意：由于 GroupMember 配置了 use_enum_values=True，status 已经是字符串
        online_members = [m for m in all_members if m.status == "online"]
        ai_members = [m for m in all_members if m.member_type == MemberType.AI]
        
        # 🔥 批量更新在线成员的显示名称和头像，避免逐个查询造成阻塞
        await self._batch_update_online_members(online_members)
        
        # 获取群组信息
        group = await self.group_manager.get_group(group_id)
        
        context = GroupChatContext(
            group_id=group_id,
            group_name=group.name if group else "未知群组",
            recent_messages=recent_messages,
            current_message=current_message,
            online_members=online_members,
            ai_members=ai_members,
            total_members=len(all_members)
        )
        
        logger.debug(
            f"📋 构建AI上下文: 群组={group_id} | AI={ai_member.display_name} | "
            f"历史消息={len(recent_messages)} | 在线成员={len(online_members)}"
        )
        
        return context
    
    async def _batch_update_online_members(self, online_members: List[GroupMember]) -> None:
        """批量更新在线成员信息，避免逐个查询造成阻塞"""
        if not online_members:
            return
        
        # 分离人类用户和AI用户
        human_members = [m for m in online_members if m.member_type == MemberType.HUMAN]
        ai_members = [m for m in online_members if m.member_type == MemberType.AI]
        
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
            
            for member in ai_members:
                actual_session_id = member.member_id.replace("ai_", "") if member.member_id.startswith("ai_") else member.member_id
                session_ids.append(actual_session_id)
            
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
    
    async def mark_message_read(
        self,
        message_id: str,
        member_id: str
    ):
        """标记消息已读"""
        await self.collection_messages.update_one(
            {"message_id": message_id},
            {"$addToSet": {"read_by": member_id}}
        )
    
    async def get_message(self, message_id: str) -> Optional[GroupMessage]:
        """获取单条消息"""
        doc = await self.collection_messages.find_one({"message_id": message_id})
        
        if not doc:
            return None
        
        doc.pop("_id", None)
        return GroupMessage(**doc)
    
    async def update_message_content(
        self,
        message_id: str,
        content: str
    ):
        """更新消息内容（用于流式回复追加）"""
        await self.collection_messages.update_one(
            {"message_id": message_id},
            {"$set": {"content": content}}
        )
    
    async def _format_members_with_identity(self, members: List[GroupMember]) -> str:
        """
        为成员列表添加身份标识（仅显示群内角色：群主/管理员）
        
        格式：名称1(群主), 名称2(管理员), 名称3, ...
        例如：玖凝(群主), 苏冉(管理员), 周子扬, 林溪(管理员)
        
        Args:
            members: 成员列表
            
        Returns:
            格式化后的成员字符串
        """
        if not members:
            return ""
        
        formatted_members = []
        
        # 只显示群内角色身份（群主/管理员），不显示AI的角色设定
        for member in members:
            display_name = member.display_name or member.member_id
            
            # 添加群内角色身份
            if member.role == MemberRole.OWNER:
                formatted_members.append(f"{display_name}(群主)")
            elif member.role == MemberRole.ADMIN:
                formatted_members.append(f"{display_name}(管理员)")
            else:
                formatted_members.append(display_name)
        
        return ", ".join(formatted_members)
    
    async def format_context_for_llm(
        self,
        context: GroupChatContext,
        ai_member: GroupMember,
        user_system_prompt: str = None,
        group_system_prompt: str = None
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        格式化上下文为LLM输入格式
        
        系统提示词由3部分组成：
        1. AI原本的系统提示词（user_system_prompt）
        2. 用户自定义的群聊系统提示词（group_system_prompt）
        3. 动态生成的群聊信息（成员列表等）
        
        Args:
            context: 群聊上下文
            ai_member: AI成员信息
            user_system_prompt: AI会话的系统提示词（可选）
            group_system_prompt: 用户为群聊自定义的系统提示词（可选）
        
        Returns:
            (system_prompt, history_messages)
        """
        # 🎯 为在线成员添加身份标识
        online_members_with_identity = await self._format_members_with_identity(context.online_members)
        
        # 🎯 第3部分：动态生成的群聊信息
        group_info = [
            "",
            "---",
            "【当前群聊信息】",
            f"群聊名称：{context.group_name}",
            f"成员总数：{context.total_members} 人",
            f"在线成员：{online_members_with_identity} ({len(context.online_members)} 人在线)",
            "---",
        ]
        
        # 🔥 拼接3部分系统提示词
        prompt_parts = []
        
        # 第1部分：AI原本的系统提示词
        if user_system_prompt and user_system_prompt.strip():
            prompt_parts.append(user_system_prompt.strip())
        else:
            # 如果用户没有配置system_prompt，使用默认身份
            prompt_parts.append(f"你是 {ai_member.display_name}。")
        
        # 第2部分：群聊自定义系统提示词
        if group_system_prompt and group_system_prompt.strip():
            prompt_parts.append("\n" + group_system_prompt.strip())
        
        # 第3部分：群聊信息
        prompt_parts.append("\n".join(group_info))
        
        system_prompt = "\n".join(prompt_parts)
        
        # 🔥 构建历史消息（包含所有recent_messages，不再跳过任何消息）
        # 这样可以保证AI看到完整的、按时间顺序的对话历史
        # 
        # 🎯 关键：每个AI都有独立的上下文
        # - 只有本AI自己的回复是 role=assistant
        # - 所有其他人（包括真人和其他AI）的消息都是 role=user
        # - 这样每个AI都有独立的对话历史，不会混淆其他AI的身份
        history_messages = []
        
        # 🔍 调试：打印AI成员ID
        logger.debug(f"🔍 当前AI成员ID: {ai_member.member_id}")
        
        for msg in context.recent_messages:
            # 判断是否是本AI发送的消息
            role = "assistant" if msg.sender_id == ai_member.member_id else "user"
            
            # 🔍 调试：打印每条消息的发送者ID和角色判断
            logger.debug(
                f"🔍 消息: sender_id={msg.sender_id} | sender_name={msg.sender_name} | "
                f"sender_type={msg.sender_type} | role={role} | "
                f"匹配={msg.sender_id == ai_member.member_id}"
            )
            
            # 格式化消息内容（包含发送者名称，让AI知道是谁说的）
            content = f"[{msg.sender_name}]: {msg.content}"
            
            history_messages.append({
                "role": role,
                "content": content
            })
        
        return system_prompt, history_messages
    

