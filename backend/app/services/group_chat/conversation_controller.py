"""
群聊对话控制器

负责管理AI-to-AI对话的流程控制，防止无限对话和成本失控。

核心功能：
1. 对话轮次追踪和限制
2. 冷却期管理
3. 手动中断控制
4. 成本估算和预警
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from collections import defaultdict, deque
from ...models.group_chat import GroupMessage, MemberType

logger = logging.getLogger(__name__)


class ConversationState:
    """单个群组的对话状态"""
    
    def __init__(self, group_id: str, controller_config: Dict = None):
        self.group_id = group_id
        self.controller_config = controller_config or {}  # 保存控制器配置引用
        
        # 调试日志
        logger.debug(
            f"🔧 创建ConversationState | 群组={group_id} | "
            f"has_recovery_callback={bool(self.controller_config.get('recovery_callback'))}"
        )
        
        # 对话轮次追踪（最近N条消息的发送者类型）
        self.recent_senders = deque(maxlen=10)  # 最近10条消息
        
        # AI连续回复计数
        self.ai_consecutive_count = 0
        
        # 最后一次用户消息时间
        self.last_human_message_time: Optional[datetime] = None
        
        # 最后一次AI消息时间
        self.last_ai_message_time: Optional[datetime] = None
        
        # 冷却期状态
        self.in_cooldown = False
        self.cooldown_until: Optional[datetime] = None
        self.cooldown_recovery_count = 0  # 冷却期恢复次数
        self.max_cooldown_recoveries = 3  # 最大允许恢复次数（防止无限循环）
        
        # 手动中断标志
        self.manually_stopped = False
        
        # 本轮对话的消息计数
        self.current_round_message_count = 0
        self.current_round_start_time: Optional[datetime] = None
        
        # 成本估算（按token数）
        self.estimated_tokens_used = 0
        
    def add_message(self, sender_type: MemberType, estimated_tokens: int = 0):
        """添加消息记录"""
        now = datetime.now()
        
        self.recent_senders.append(sender_type)
        self.estimated_tokens_used += estimated_tokens
        
        if sender_type == MemberType.AI:
            self.ai_consecutive_count += 1
            self.last_ai_message_time = now
        else:
            # 人类消息：重置AI连续计数和冷却期恢复计数
            self.ai_consecutive_count = 0
            self.cooldown_recovery_count = 0  # 重置恢复计数，允许新一轮对话
            self.last_human_message_time = now
            
            # 新的一轮对话开始
            if self.in_cooldown or self.current_round_message_count > 0:
                logger.info(f"👤 人类消息，重置对话轮次和恢复计数 | 群组={self.group_id}")
                self.current_round_message_count = 0
                self.current_round_start_time = now
                self.in_cooldown = False
                self.manually_stopped = False
        
        self.current_round_message_count += 1
        if not self.current_round_start_time:
            self.current_round_start_time = now
    
    def should_allow_ai_response(self, config: Dict) -> tuple[bool, str]:
        """
        判断是否允许AI回复
        
        Returns:
            (是否允许, 原因说明)
        """
        now = datetime.now()
        
        # 1. 检查手动中断
        if self.manually_stopped:
            return False, "对话已被手动中断"
        
        # 2. 检查冷却期恢复次数（防止无限循环）
        if self.cooldown_recovery_count >= self.max_cooldown_recoveries:
            logger.warning(
                f"⛔ 冷却期恢复次数达到上限 | 群组={self.group_id} | "
                f"恢复次数={self.cooldown_recovery_count} | 停止自动恢复"
            )
            return False, f"冷却期恢复次数达到上限（{self.max_cooldown_recoveries}次），停止自动对话"
        
        # 3. 检查冷却期
        if self.in_cooldown and self.cooldown_until:
            if now < self.cooldown_until:
                remaining = (self.cooldown_until - now).total_seconds()
                return False, f"冷却期中（剩余{remaining:.0f}秒）"
            else:
                # 冷却期结束，重置状态
                self.in_cooldown = False
                self.cooldown_until = None
                self.ai_consecutive_count = 0  # 重置AI连续计数
                logger.info(f"✅ 冷却期结束，对话状态已重置 | 群组={self.group_id}")
                # 返回一个特殊标记，表示冷却期刚结束
                return True, "冷却期刚结束，允许恢复对话"
        
        # 4. 检查AI连续回复限制
        max_ai_consecutive = config.get("max_ai_consecutive_replies", 3)
        if self.ai_consecutive_count >= max_ai_consecutive:
            # 触发冷却期
            cooldown_seconds = config.get("cooldown_seconds", 30)
            self.in_cooldown = True
            self.cooldown_until = now + timedelta(seconds=cooldown_seconds)
            self.cooldown_recovery_count += 1  # 增加恢复计数
            
            logger.warning(
                f"🚫 AI连续回复达到上限 | 群组={self.group_id} | "
                f"连续次数={self.ai_consecutive_count} | 恢复次数={self.cooldown_recovery_count}/{self.max_cooldown_recoveries} | "
                f"进入冷却期{cooldown_seconds}秒"
            )
            
            # 只在未达到最大恢复次数时才调度恢复任务
            if self.cooldown_recovery_count < self.max_cooldown_recoveries:
                recovery_callback = self.controller_config.get("recovery_callback")
                if recovery_callback:
                    self.schedule_cooldown_recovery(recovery_callback, cooldown_seconds)
                else:
                    logger.warning(f"⚠️ 未找到recovery_callback，无法调度恢复任务 | 群组={self.group_id}")
            else:
                logger.warning(
                    f"⛔ 已达到最大冷却期恢复次数，不再调度恢复任务 | 群组={self.group_id}"
                )
            
            return False, f"AI连续回复达到上限（{max_ai_consecutive}次），进入冷却期"
        
        # 4. 检查本轮总消息数限制
        max_round_messages = config.get("max_messages_per_round", 20)
        if self.current_round_message_count >= max_round_messages:
            # 触发冷却期
            cooldown_seconds = config.get("cooldown_seconds", 60)
            self.in_cooldown = True
            self.cooldown_until = now + timedelta(seconds=cooldown_seconds)
            
            logger.warning(
                f"🚫 本轮对话消息数达到上限 | 群组={self.group_id} | "
                f"消息数={self.current_round_message_count} | 进入冷却期{cooldown_seconds}秒"
            )
            return False, f"本轮对话消息数达到上限（{max_round_messages}），进入冷却期"
        
        # 5. 检查成本限制
        max_tokens_per_round = config.get("max_tokens_per_round", 50000)
        if self.estimated_tokens_used >= max_tokens_per_round:
            self.in_cooldown = True
            self.cooldown_until = now + timedelta(seconds=300)  # 5分钟冷却
            
            logger.warning(
                f"🚫 本轮对话token使用达到上限 | 群组={self.group_id} | "
                f"已用tokens={self.estimated_tokens_used}"
            )
            return False, f"本轮对话token使用达到上限（{max_tokens_per_round}），进入冷却期"
        
        return True, "允许回复"
    
    def schedule_cooldown_recovery(self, callback, cooldown_seconds: int):
        """
        调度冷却期结束后的恢复任务
        
        Args:
            callback: 冷却期结束后要调用的异步函数
            cooldown_seconds: 冷却期时长（秒）
        """
        async def recovery_task():
            await asyncio.sleep(cooldown_seconds + 1)  # 多等1秒确保冷却期结束
            
            now = datetime.now()
            logger.debug(
                f"⏰ 冷却期恢复任务执行 | 群组={self.group_id} | "
                f"in_cooldown={self.in_cooldown} | cooldown_until={self.cooldown_until}"
            )
            
            # 先检查并更新冷却期状态
            if self.in_cooldown and self.cooldown_until:
                if now >= self.cooldown_until:
                    # 冷却期确实结束了，重置状态
                    self.in_cooldown = False
                    self.cooldown_until = None
                    self.ai_consecutive_count = 0  # 重置AI连续计数
                    logger.info(f"✅ 冷却期已结束，状态已重置 | 群组={self.group_id}")
                else:
                    # 时间还没到（理论上不应该发生）
                    remaining = (self.cooldown_until - now).total_seconds()
                    logger.warning(f"⚠️ 冷却期尚未结束 | 群组={self.group_id} | 剩余{remaining:.0f}秒")
                    return
            
            # 检查是否应该恢复对话
            if not self.in_cooldown:
                logger.info(f"🔄 冷却期已结束，尝试恢复AI对话 | 群组={self.group_id}")
                try:
                    await callback(self.group_id)
                except Exception as e:
                    logger.error(f"❌ 冷却期恢复回调执行失败 | 群组={self.group_id} | 错误: {e}", exc_info=True)
            else:
                logger.debug(f"⏸️ 冷却期进入新状态，跳过恢复 | 群组={self.group_id}")
        
        # 创建异步任务
        asyncio.create_task(recovery_task())
        logger.info(f"⏰ 已调度冷却期恢复任务 | 群组={self.group_id} | {cooldown_seconds}秒后执行")
    
    def get_status_summary(self) -> Dict:
        """获取状态摘要"""
        return {
            "group_id": self.group_id,
            "ai_consecutive_count": self.ai_consecutive_count,
            "cooldown_recovery_count": self.cooldown_recovery_count,
            "max_cooldown_recoveries": self.max_cooldown_recoveries,
            "current_round_messages": self.current_round_message_count,
            "estimated_tokens": self.estimated_tokens_used,
            "in_cooldown": self.in_cooldown,
            "manually_stopped": self.manually_stopped,
            "last_human_message_time": self.last_human_message_time.isoformat() if self.last_human_message_time else None,
            "last_ai_message_time": self.last_ai_message_time.isoformat() if self.last_ai_message_time else None,
        }


class ConversationController:
    """对话控制器"""
    
    # 默认配置
    DEFAULT_CONFIG = {
        "max_ai_consecutive_replies": 3,      # AI最多连续回复3次
        "max_messages_per_round": 20,         # 每轮对话最多20条消息
        "max_tokens_per_round": 50000,        # 每轮对话最多5万tokens
        "cooldown_seconds": 30,               # 默认冷却期30秒
        "enable_ai_to_ai": True,              # 是否启用AI互相对话
        "ai_reply_probability": 0.6,          # AI对AI消息的回复概率（降低）
    }
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        
        # 群组状态：group_id -> ConversationState
        self.group_states: Dict[str, ConversationState] = {}
        
        # 统计信息
        self.stats = {
            "total_messages": 0,
            "ai_messages": 0,
            "human_messages": 0,
            "blocked_by_consecutive_limit": 0,
            "blocked_by_round_limit": 0,
            "blocked_by_cooldown": 0,
            "blocked_by_manual_stop": 0,
        }
        
        # 冷却期恢复回调
        self.on_cooldown_end_callback = None
        
        logger.info(f"✅ 对话控制器已初始化 | 配置: {self.config}")
    
    def get_group_state(self, group_id: str) -> ConversationState:
        """获取群组状态（不存在则创建）"""
        if group_id not in self.group_states:
            self.group_states[group_id] = ConversationState(group_id, self.config)
        return self.group_states[group_id]
    
    def track_message(self, message: GroupMessage, estimated_tokens: int = 0):
        """
        追踪消息
        
        Args:
            message: 群消息
            estimated_tokens: 估算的token数（可选）
        """
        state = self.get_group_state(message.group_id)
        state.add_message(message.sender_type, estimated_tokens)
        
        self.stats["total_messages"] += 1
        if message.sender_type == MemberType.AI:
            self.stats["ai_messages"] += 1
        else:
            self.stats["human_messages"] += 1
        
        logger.debug(
            f"📊 消息追踪 | 群组={message.group_id} | 发送者={message.sender_name}({message.sender_type}) | "
            f"AI连续={state.ai_consecutive_count} | 本轮消息数={state.current_round_message_count}"
        )
    
    def should_trigger_ai_decision(self, message: GroupMessage, config: Optional[Dict] = None) -> tuple[bool, str]:
        """
        判断是否应该触发AI决策流程
        
        Args:
            message: 触发的消息
            config: 可选的配置字典，如果未提供则使用默认配置
        
        Returns:
            (是否触发, 原因说明)
        """
        # 使用传入的配置或默认配置
        config = config or self.config
        
        # 人类消息：总是触发
        if message.sender_type != MemberType.AI:
            return True, "人类消息，触发AI决策"
        
        # AI消息：检查是否启用AI-to-AI
        if not config.get("enable_ai_to_ai", self.config["enable_ai_to_ai"]):
            return False, "AI-to-AI对话未启用"
        
        # AI消息：检查对话控制限制
        state = self.get_group_state(message.group_id)
        allowed, reason = state.should_allow_ai_response(config)
        
        if not allowed:
            # 更新统计
            if "连续回复" in reason:
                self.stats["blocked_by_consecutive_limit"] += 1
            elif "消息数达到上限" in reason:
                self.stats["blocked_by_round_limit"] += 1
            elif "冷却期" in reason:
                self.stats["blocked_by_cooldown"] += 1
            elif "手动中断" in reason:
                self.stats["blocked_by_manual_stop"] += 1
        
        return allowed, reason
    
    def get_ai_reply_probability(self, message: GroupMessage, config: Optional[Dict] = None) -> float:
        """
        获取AI回复概率（根据消息类型动态调整）
        
        Args:
            message: 触发的消息
            config: 可选的配置字典，如果未提供则使用默认配置
        
        Returns:
            回复概率 (0.0 ~ 1.0)
        """
        # 使用传入的配置或默认配置
        config = config or self.config
        
        base_probability = 1.0 if message.sender_type != MemberType.AI else config.get("ai_reply_probability", self.config["ai_reply_probability"])
        
        state = self.get_group_state(message.group_id)
        
        # 根据AI连续回复次数降低概率
        if state.ai_consecutive_count > 0:
            # 每次AI连续回复，概率降低20%
            reduction = 0.2 * state.ai_consecutive_count
            base_probability = max(0.1, base_probability - reduction)
        
        return base_probability
    
    def manual_stop(self, group_id: str) -> bool:
        """
        手动中断群组对话
        
        Args:
            group_id: 群组ID
        
        Returns:
            是否成功中断
        """
        state = self.get_group_state(group_id)
        state.manually_stopped = True
        
        logger.warning(f"🛑 群组对话被手动中断 | 群组={group_id}")
        return True
    
    def resume(self, group_id: str) -> bool:
        """
        恢复群组对话
        
        Args:
            group_id: 群组ID
        
        Returns:
            是否成功恢复
        """
        state = self.get_group_state(group_id)
        state.manually_stopped = False
        state.in_cooldown = False
        
        logger.info(f"▶️ 群组对话已恢复 | 群组={group_id}")
        return True
    
    def get_group_status(self, group_id: str) -> Dict:
        """获取群组状态"""
        state = self.get_group_state(group_id)
        return state.get_status_summary()
    
    def get_all_stats(self) -> Dict:
        """获取全局统计"""
        return {
            "global_stats": self.stats,
            "group_count": len(self.group_states),
            "groups": {
                group_id: state.get_status_summary()
                for group_id, state in self.group_states.items()
            }
        }

