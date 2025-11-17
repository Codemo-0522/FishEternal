"""
AI调度器

负责AI回复决策、延迟队列管理、抢答控制
"""
import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict
from ...models.group_chat import (
    GroupMessage, GroupMember, AIReplyDecision,
    GroupChatContext, MemberType
)
from .filters import FilterChain, create_default_filter_chain

logger = logging.getLogger(__name__)


class DelayedReply:
    """延迟回复任务"""
    
    def __init__(
        self,
        ai_member_id: str,
        session_id: str,
        message: GroupMessage,
        delay_seconds: float,
        context: GroupChatContext
    ):
        self.ai_member_id = ai_member_id
        self.session_id = session_id
        self.message = message
        self.delay_seconds = delay_seconds
        self.context = context
        self.scheduled_time = datetime.now() + timedelta(seconds=delay_seconds)
        self.cancelled = False
    
    async def execute(self, callback):
        """
        执行延迟回复（支持中途取消）
        
        策略：将延迟分成小块（每0.5秒检查一次是否被取消）
        """
        remaining_time = self.delay_seconds
        check_interval = 0.5  # 每0.5秒检查一次取消状态
        
        while remaining_time > 0 and not self.cancelled:
            sleep_time = min(check_interval, remaining_time)
            await asyncio.sleep(sleep_time)
            remaining_time -= sleep_time
        
        # 最终再次检查是否被取消
        if not self.cancelled:
            await callback(self)


class AIScheduler:
    """AI调度器"""
    
    def __init__(self):
        self.filter_chain = create_default_filter_chain()
        
        # 延迟队列：group_id -> List[DelayedReply]
        self.delay_queues: Dict[str, List[DelayedReply]] = defaultdict(list)
        
        # 群组回复锁：防止同一时间多个AI抢答
        self.group_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        
        # 统计信息
        self.stats = {
            "total_messages": 0,
            "filtered_candidates": 0,
            "llm_calls": 0,
            "actual_replies": 0
        }
    
    async def process_message(
        self,
        message: GroupMessage,
        ai_members: List[GroupMember],
        context: GroupChatContext,
        base_reply_probability: float = 1.0,
        unrestricted_mode: bool = False
    ) -> List[AIReplyDecision]:
        """
        处理新消息，返回需要回复的AI决策列表
        
        Args:
            message: 当前消息
            ai_members: 所有在线的AI成员
            context: 群聊上下文
            base_reply_probability: 基础回复概率（由对话控制器提供，0.0-1.0）
            unrestricted_mode: 是否开启无限制模式（跳过采样）
        
        Returns:
            最终决策列表（需要调用LLM的AI）
        """
        self.stats["total_messages"] += 1
        group_id = message.group_id
        
        logger.info(
            f"\n{'='*60}\n"
            f"📨 新消息处理 | 群组: {group_id}\n"
            f"发送者: {message.sender_name} ({message.sender_type})\n"
            f"内容: {message.content[:100]}\n"
            f"在线AI数量: {len(ai_members)}\n"
            f"基础回复概率: {base_reply_probability:.2f}\n"
            f"{'='*60}"
        )
        
        # 第一阶段：轻量级过滤
        candidate_decisions = await self._lightweight_filter(message, ai_members, context)
        
        if not candidate_decisions:
            logger.info("❌ 无AI通过轻量级过滤器，跳过LLM调用")
            return []
        
        # 应用基础回复概率调整
        if base_reply_probability < 1.0:
            for decision in candidate_decisions:
                decision.probability_score *= base_reply_probability
                logger.debug(
                    f"  - {decision.ai_member_id}: 概率调整 "
                    f"{decision.probability_score / base_reply_probability:.2f} -> {decision.probability_score:.2f}"
                )
        
        self.stats["filtered_candidates"] += len(candidate_decisions)
        
        # 第二阶段：随机采样决策（避免所有AI都调用LLM）
        # 🔥 unrestricted_mode：跳过采样，所有候选AI都回复
        if unrestricted_mode:
            sampled_decisions = candidate_decisions
            logger.info(f"🔓 无限制模式：跳过采样，所有{len(candidate_decisions)}个候选AI将回复")
        else:
            sampled_decisions = await self._sample_candidates(candidate_decisions)
        
        logger.info(
            f"✅ 轻量级过滤完成: {len(ai_members)} AI -> {len(candidate_decisions)} 候选 -> {len(sampled_decisions)} 采样"
        )
        
        # 第三阶段：为每个候选添加延迟
        for decision in sampled_decisions:
            decision.delay_seconds = self._calculate_delay(decision, message)
            decision.scheduled_time = datetime.now() + timedelta(seconds=decision.delay_seconds)
        
        # 按延迟排序
        sampled_decisions.sort(key=lambda d: d.delay_seconds)
        
        return sampled_decisions
    
    async def _lightweight_filter(
        self,
        message: GroupMessage,
        ai_members: List[GroupMember],
        context: GroupChatContext
    ) -> List[AIReplyDecision]:
        """轻量级过滤阶段"""
        
        # 构建过滤器上下文
        filter_context = {
            "recent_messages": context.recent_messages,
            "online_members": context.online_members,
            "current_message": message
        }
        
        # 运行过滤器链
        decisions = self.filter_chain.evaluate(message, ai_members, filter_context)
        
        return decisions
    
    async def _sample_candidates(
        self,
        candidate_decisions: List[AIReplyDecision]
    ) -> List[AIReplyDecision]:
        """
        随机采样候选AI（基于概率）
        
        策略：
        0. **兜底策略：AI数量 ≤ 3 时，直接全部放行**
        1. 被@的AI：100%保留（包括当前被@和近期被@）
        2. 高概率AI（>0.7）：80%保留
        3. 中概率AI（0.3-0.7）：根据概率采样
        4. 低概率AI（<0.3）：30%采样
        5. 兜底策略2：如果没有AI被采样，至少选择概率最高的一个
        """
        # 🔥 兜底策略：AI数量 ≤ 3 时，直接全部放行，不过滤
        if len(candidate_decisions) <= 3:
            logger.info(
                f"🎯 AI数量 ≤ 3（当前{len(candidate_decisions)}个），直接全部放行，不进行采样过滤"
            )
            return candidate_decisions
        
        sampled = []
        mentioned_ais = []  # 记录被@的AI
        
        for decision in candidate_decisions:
            # 被@的AI（从decision_reason判断：包括"当前被@"和"近期被@"）
            if "被@" in decision.decision_reason or "近期被@" in decision.decision_reason:
                sampled.append(decision)
                mentioned_ais.append(decision.ai_member_id)
                logger.debug(f"✅ 采样保留（被@）: {decision.ai_member_id} | {decision.decision_reason}")
                continue
            
            # 根据概率采样
            prob = decision.probability_score
            
            if prob >= 0.7:
                # 高概率：80%保留
                if random.random() < 0.8:
                    sampled.append(decision)
                    logger.debug(f"✅ 采样保留（高概率）: {decision.ai_member_id} | {prob:.2%}")
            elif prob >= 0.3:
                # 中概率：按概率采样
                if random.random() < prob:
                    sampled.append(decision)
                    logger.debug(f"✅ 采样保留（中概率）: {decision.ai_member_id} | {prob:.2%}")
            else:
                # 低概率：30%采样
                if random.random() < 0.3:
                    sampled.append(decision)
                    logger.debug(f"✅ 采样保留（低概率）: {decision.ai_member_id} | {prob:.2%}")
        
        # 兜底策略2：如果没有AI被采样，至少选择概率最高的一个
        if not sampled and candidate_decisions:
            best_candidate = max(candidate_decisions, key=lambda d: d.probability_score)
            sampled.append(best_candidate)
            logger.info(
                f"🎲 兜底策略2：选择概率最高的AI - {best_candidate.ai_member_id} "
                f"(概率={best_candidate.probability_score:.2%})"
            )
        
        # 记录被@的AI数量
        if mentioned_ais:
            logger.info(f"🎯 采样阶段保留被@的AI: {len(mentioned_ais)}个 - {mentioned_ais}")
        
        return sampled
    
    def _calculate_delay(
        self,
        decision: AIReplyDecision,
        message: GroupMessage
    ) -> float:
        """
        计算延迟时间（模拟人类思考延迟）
        
        规则：
        1. 被@的AI：短延迟（0.5-2秒）
        2. 高兴趣AI：中等延迟（1-3秒）
        3. 普通AI：长延迟（2-5秒）
        """
        
        # 被@：快速响应
        if "被@提及" in decision.decision_reason:
            return random.uniform(0.5, 2.0)
        
        # 高概率：中等延迟
        if decision.probability_score >= 0.7:
            return random.uniform(1.0, 3.0)
        
        # 普通：长延迟
        return random.uniform(2.0, 5.0)
    
    async def schedule_reply(
        self,
        decision: AIReplyDecision,
        message: GroupMessage,
        context: GroupChatContext,
        reply_callback
    ) -> DelayedReply:
        """
        调度一个延迟回复任务
        
        Args:
            decision: AI决策
            message: 原始消息
            context: 群聊上下文
            reply_callback: 回复回调函数 async def(DelayedReply)
        
        Returns:
            延迟回复任务
        """
        delayed_reply = DelayedReply(
            ai_member_id=decision.ai_member_id,
            session_id=decision.session_id,
            message=message,
            delay_seconds=decision.delay_seconds,
            context=context
        )
        
        group_id = message.group_id
        self.delay_queues[group_id].append(delayed_reply)
        
        logger.info(
            f"⏰ 调度延迟回复: AI={decision.ai_member_id} | "
            f"延迟={decision.delay_seconds:.2f}s | "
            f"预计时间={delayed_reply.scheduled_time.strftime('%H:%M:%S')}"
        )
        
        # 创建异步任务
        asyncio.create_task(delayed_reply.execute(reply_callback))
        
        return delayed_reply
    
    async def cancel_pending_replies(
        self,
        group_id: str,
        ai_member_id: Optional[str] = None
    ):
        """
        取消待处理的回复任务
        
        Args:
            group_id: 群组ID
            ai_member_id: AI成员ID（可选，不指定则取消该群所有任务）
        """
        if group_id not in self.delay_queues:
            logger.debug(f"🔍 无待取消任务: 群组={group_id} (队列为空)")
            return
        
        cancelled_count = 0
        cancelled_ais = []
        
        for delayed_reply in self.delay_queues[group_id]:
            if ai_member_id is None or delayed_reply.ai_member_id == ai_member_id:
                delayed_reply.cancelled = True
                cancelled_count += 1
                cancelled_ais.append(delayed_reply.ai_member_id)
        
        # 清理已取消的任务
        self.delay_queues[group_id] = [
            dr for dr in self.delay_queues[group_id]
            if not dr.cancelled
        ]
        
        if cancelled_count > 0:
            logger.info(
                f"❌ 取消延迟回复: 群组={group_id} | "
                f"AI={ai_member_id or 'ALL'} | "
                f"数量={cancelled_count} | "
                f"AI列表={cancelled_ais}"
            )
        else:
            logger.debug(f"🔍 无匹配任务需取消: 群组={group_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "active_delay_queues": {
                group_id: len(queue)
                for group_id, queue in self.delay_queues.items()
                if queue
            }
        }
    
    def reset_stats(self):
        """重置统计"""
        self.stats = {
            "total_messages": 0,
            "filtered_candidates": 0,
            "llm_calls": 0,
            "actual_replies": 0
        }


class ReplyController:
    """回复控制器（抢答控制）"""
    
    def __init__(self, max_concurrent_replies: int = 2):
        """
        Args:
            max_concurrent_replies: 单条消息的最大并发回复数
        """
        self.max_concurrent_replies = max_concurrent_replies
        
        # 消息ID -> 已回复AI数量
        self.message_reply_counts: Dict[str, int] = defaultdict(int)
        
        # 消息ID -> 锁
        self.message_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    async def should_allow_reply(self, message_id: str, max_concurrent_replies: int = None) -> bool:
        """
        判断是否允许回复（抢答控制）
        
        Args:
            message_id: 消息ID
            max_concurrent_replies: 最大并发回复数（如果为None则使用实例默认值）
        
        Returns:
            True: 允许回复
            False: 已达到并发限制
        """
        # 使用传入的值或实例默认值
        limit = max_concurrent_replies if max_concurrent_replies is not None else self.max_concurrent_replies
        
        async with self.message_locks[message_id]:
            current_count = self.message_reply_counts[message_id]
            
            if current_count >= limit:
                logger.warning(
                    f"🚫 抢答限制: 消息 {message_id} 已有 {current_count} 个AI回复，拒绝新回复 (限制={limit})"
                )
                return False
            
            # 允许回复，计数+1
            self.message_reply_counts[message_id] += 1
            logger.info(
                f"✅ 允许回复: 消息 {message_id} | 当前回复数 {self.message_reply_counts[message_id]}/{limit}"
            )
            return True
    
    def cleanup_old_messages(self, max_age_seconds: int = 3600):
        """清理旧消息的计数（避免内存泄漏）"""
        # 简单实现：定期清空（生产环境应基于时间戳）
        if len(self.message_reply_counts) > 1000:
            logger.info("🧹 清理旧消息回复计数")
            self.message_reply_counts.clear()
            self.message_locks.clear()


# 全局单例
_ai_scheduler = None
_reply_controller = None


def get_ai_scheduler() -> AIScheduler:
    """获取全局AI调度器单例"""
    global _ai_scheduler
    if _ai_scheduler is None:
        _ai_scheduler = AIScheduler()
    return _ai_scheduler


def get_reply_controller() -> ReplyController:
    """获取全局回复控制器单例"""
    global _reply_controller
    if _reply_controller is None:
        _reply_controller = ReplyController(max_concurrent_replies=3)
    return _reply_controller

