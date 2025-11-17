"""
轻量级消息过滤器

在调用LLM之前快速过滤出可能回复的AI，减少API调用成本
"""
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from ...models.group_chat import (
    GroupMessage, GroupMember, AIBehaviorConfig,
    MemberStatus, MemberType, AIReplyDecision
)

logger = logging.getLogger(__name__)


class BaseFilter:
    """过滤器基类"""
    
    filter_name: str = "base_filter"
    
    def __init__(self):
        pass
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """
        判断AI是否应该通过此过滤器
        
        Returns:
            (是否通过, 原因说明)
        """
        raise NotImplementedError


class OnlineStatusFilter(BaseFilter):
    """在线状态过滤器"""
    
    filter_name = "online_status"
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """只有在线的AI才能回复"""
        if ai_member.status == MemberStatus.ONLINE:
            return True, "AI在线"
        return False, f"AI离线 (status={ai_member.status})"


class SelfMessageFilter(BaseFilter):
    """自我消息过滤器"""
    
    filter_name = "self_message"
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """AI不回复自己的消息"""
        if message.sender_id == ai_member.member_id:
            return False, "不回复自己的消息"
        return True, "不是自己的消息"


class CooldownFilter(BaseFilter):
    """冷却时间过滤器"""
    
    filter_name = "cooldown"
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """检查是否在冷却期内"""
        if not ai_member.last_reply_time or not ai_member.behavior_config:
            return True, "无冷却限制"
        
        cooldown = ai_member.behavior_config.cooldown_after_reply
        time_since_last_reply = (datetime.now() - ai_member.last_reply_time).total_seconds()
        
        if time_since_last_reply < cooldown:
            return False, f"冷却中 ({time_since_last_reply:.1f}s / {cooldown}s)"
        return True, "冷却完成"


class ConsecutiveReplyFilter(BaseFilter):
    """连续回复过滤器"""
    
    filter_name = "consecutive_reply"
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """检查连续回复次数是否超限"""
        if not ai_member.behavior_config:
            return True, "无连续回复限制"
        
        max_consecutive = ai_member.behavior_config.max_consecutive_replies
        
        # 从上下文中获取最近消息，检查是否连续回复
        recent_messages = context.get("recent_messages", []) if context else []
        
        # 统计AI连续回复次数
        consecutive_count = 0
        for msg in reversed(recent_messages):
            if msg.sender_id == ai_member.member_id:
                consecutive_count += 1
            else:
                # 遇到其他成员的消息，重置计数
                break
        
        if consecutive_count >= max_consecutive:
            return False, f"连续回复次数超限 ({consecutive_count}/{max_consecutive})"
        return True, f"连续回复 {consecutive_count}/{max_consecutive}"


class MentionFilter(BaseFilter):
    """@提及过滤器"""
    
    filter_name = "mention"
    priority = 100  # 高优先级
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """被@时大概率通过"""
        if ai_member.member_id in message.mentions or ai_member.session_id in message.mentions:
            return True, "被@提及（高优先级）"
        return True, "未被提及"  # 不阻断，让其他过滤器决定


class KeywordFilter(BaseFilter):
    """关键词过滤器"""
    
    filter_name = "keyword"
    
    def should_pass(
        self,
        message: GroupMessage,
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[bool, str]:
        """检查消息是否包含AI的兴趣关键词"""
        if not ai_member.behavior_config or not ai_member.behavior_config.interest_keywords:
            return True, "无关键词配置"
        
        content = message.content.lower()
        matched_keywords = []
        
        for keyword in ai_member.behavior_config.interest_keywords:
            if keyword.lower() in content:
                matched_keywords.append(keyword)
        
        if matched_keywords:
            return True, f"匹配关键词: {', '.join(matched_keywords)}"
        return True, "无关键词匹配"  # 不阻断


class ProbabilityCalculator:
    """概率计算器"""
    
    @staticmethod
    def _calculate_mention_frequency_boost(
        ai_member: GroupMember,
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[float, int]:
        """
        计算最近消息中被@的频率加成
        
        Returns:
            (额外加成概率, 被@次数)
        """
        if not context or "recent_messages" not in context:
            return 0.0, 0
        
        recent_messages = context["recent_messages"]
        # 统计最近10条消息
        check_count = min(10, len(recent_messages))
        mention_count = 0
        
        for msg in recent_messages[-check_count:]:
            if isinstance(msg, GroupMessage):
                if ai_member.member_id in msg.mentions or ai_member.session_id in msg.mentions:
                    mention_count += 1
        
        # 根据被@次数计算加成
        # 1次: +0.1, 2次: +0.25, 3次: +0.45, 4次及以上: +0.7
        if mention_count == 0:
            return 0.0, 0
        elif mention_count == 1:
            return 0.1, mention_count
        elif mention_count == 2:
            return 0.25, mention_count
        elif mention_count == 3:
            return 0.45, mention_count
        else:  # 4次及以上
            return 0.7, mention_count
    
    @staticmethod
    def calculate_reply_probability(
        message: GroupMessage,
        ai_member: GroupMember,
        filter_results: Dict[str, tuple[bool, str]],
        context: Optional[Dict[str, Any]] = None
    ) -> tuple[float, str]:
        """
        综合计算AI回复概率
        
        Returns:
            (概率值, 计算说明)
        """
        if not ai_member.behavior_config:
            return 0.0, "无行为配置"
        
        config = ai_member.behavior_config
        base_prob = config.base_reply_probability
        
        # 基础概率
        prob = base_prob
        reasons = [f"基础概率: {base_prob:.2f}"]
        
        # 当前消息被@提及 - 大幅提升
        current_mentioned = ai_member.member_id in message.mentions or ai_member.session_id in message.mentions
        if current_mentioned:
            mention_boost = config.mention_reply_probability - base_prob
            prob = min(1.0, prob + mention_boost)
            reasons.append(f"当前被@: +{mention_boost:.2f}")
        
        # 🔥 新增：历史@频率加成（重复@会累积增强）
        freq_boost, mention_count = ProbabilityCalculator._calculate_mention_frequency_boost(
            ai_member, context
        )
        if freq_boost > 0:
            prob = min(1.0, prob + freq_boost)
            reasons.append(f"近期被@{mention_count}次: +{freq_boost:.2f}")
        
        # 关键词匹配 - 提升
        if filter_results.get("keyword", (False, ""))[1].startswith("匹配关键词"):
            interest_boost = config.interest_boost
            prob = min(1.0, prob + interest_boost)
            reasons.append(f"兴趣关键词: +{interest_boost:.2f}")
        
        # 🔥 被@的成员豁免冷却和连续回复限制
        if current_mentioned or mention_count >= 2:
            # 被@的成员不受冷却限制
            if not filter_results.get("cooldown", (True, ""))[0]:
                reasons.append("被@豁免冷却")
            
            # 被多次@的成员不受连续回复限制
            consecutive_result = filter_results.get("consecutive_reply", (True, ""))[1]
            if "超限" in consecutive_result and mention_count >= 2:
                reasons.append("多次被@豁免连续限制")
        else:
            # 未被@的成员正常受冷却和连续限制
            # 冷却中 - 大幅降低
            if not filter_results.get("cooldown", (True, ""))[0]:
                prob *= 0.1
                reasons.append("冷却中: ×0.1")
            
            # 连续回复 - 降低
            consecutive_result = filter_results.get("consecutive_reply", (True, ""))[1]
            if "超限" in consecutive_result:
                prob = 0.0
                reasons.append("连续回复超限: ×0")
        
        explanation = " | ".join(reasons)
        return min(1.0, max(0.0, prob)), explanation


class FilterChain:
    """过滤器链"""
    
    def __init__(self):
        self.filters: List[BaseFilter] = []
        self.probability_calculator = ProbabilityCalculator()
    
    def add_filter(self, filter_instance: BaseFilter):
        """添加过滤器"""
        self.filters.append(filter_instance)
        return self
    
    def evaluate(
        self,
        message: GroupMessage,
        ai_members: List[GroupMember],
        context: Optional[Dict[str, Any]] = None
    ) -> List[AIReplyDecision]:
        """
        评估所有AI成员，返回决策列表
        
        Args:
            message: 当前消息
            ai_members: 所有AI成员列表
            context: 上下文信息（如recent_messages）
        
        Returns:
            AIReplyDecision列表（仅包含可能回复的AI）
        """
        decisions = []
        
        for ai_member in ai_members:
            # 运行所有过滤器
            filter_results = {}
            passed_filters = []
            failed_filters = []
            
            for filter_instance in self.filters:
                passed, reason = filter_instance.should_pass(message, ai_member, context)
                filter_results[filter_instance.filter_name] = (passed, reason)
                
                if passed:
                    passed_filters.append(f"{filter_instance.filter_name}: {reason}")
                else:
                    failed_filters.append(f"{filter_instance.filter_name}: {reason}")
            
            # 计算回复概率（传入context以支持历史@统计）
            probability, prob_explanation = self.probability_calculator.calculate_reply_probability(
                message, ai_member, filter_results, context
            )
            
            # 如果概率>0，加入候选列表
            if probability > 0:
                decision = AIReplyDecision(
                    ai_member_id=ai_member.member_id,
                    session_id=ai_member.session_id,
                    should_reply=False,  # 最终决策由调度器决定
                    decision_reason=prob_explanation,
                    probability_score=probability,
                    passed_filters=passed_filters,
                    failed_filters=failed_filters
                )
                decisions.append(decision)
                
                logger.info(
                    f"🎯 AI候选: {ai_member.display_name or ai_member.member_id} | "
                    f"概率={probability:.2%} | {prob_explanation}"
                )
            else:
                logger.debug(
                    f"❌ AI过滤: {ai_member.display_name or ai_member.member_id} | "
                    f"概率={probability:.2%} | {prob_explanation}"
                )
        
        return decisions


def create_default_filter_chain() -> FilterChain:
    """创建默认过滤器链"""
    chain = FilterChain()
    
    # 按顺序添加过滤器
    chain.add_filter(OnlineStatusFilter())      # 1. 在线状态
    chain.add_filter(SelfMessageFilter())       # 2. 不回复自己
    chain.add_filter(CooldownFilter())          # 3. 冷却检查
    chain.add_filter(ConsecutiveReplyFilter())  # 4. 连续回复检查
    chain.add_filter(MentionFilter())           # 5. @提及检查
    chain.add_filter(KeywordFilter())           # 6. 关键词检查
    
    return chain

