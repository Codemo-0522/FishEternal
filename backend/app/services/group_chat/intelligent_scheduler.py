"""
AI智能调度优化器 v2.0

核心目标：
1. 多维度阈值控制并发数量
2. 智能延迟分级（让后发AI能看到先发AI）
3. 内容去重检测（避免雷同回复）
4. 行为真实感增强（让AI无法区分彼此）
5. 促进AI-to-AI深度互动

设计理念：
- 像导演指挥群戏，而不是机械调度
- 让对话"活"起来，有起伏、有节奏
- 让真人和AI都觉得这是真实群聊
"""
import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, deque
from ...models.group_chat import (
    GroupMessage, GroupMember, AIReplyDecision,
    GroupChatContext, MemberType
)

logger = logging.getLogger(__name__)


class ConcurrencyStrategy:
    """并发控制策略"""
    
    # 默认多维度阈值配置
    DEFAULT_THRESHOLDS = {
        # 维度1：根据群组活跃度
        "activity": {
            "cold": {  # 冷清群（最近5分钟 < 3条消息）
                "max_concurrent": 1,
                "min_delay_gap": 5.0,  # 最小延迟间隔
                "description": "冷清群，1个AI慢慢回复"
            },
            "warm": {  # 温和群（3-10条消息）
                "max_concurrent": 2,
                "min_delay_gap": 3.0,
                "description": "温和群，最多2个AI，间隔3秒"
            },
            "hot": {  # 热闹群（> 10条消息）
                "max_concurrent": 3,
                "min_delay_gap": 2.0,
                "description": "热闹群，最多3个AI，间隔2秒"
            }
        },
        
        # 维度2：根据触发消息类型
        "trigger_type": {
            "human_message": {
                "max_concurrent": 3,
                "prefer_multiple": True,  # 人类消息鼓励多AI回复
                "description": "人类消息，可以多个AI回复"
            },
            "ai_message": {
                "max_concurrent": 2,
                "prefer_multiple": False,  # AI消息控制回复数
                "description": "AI消息，最多2个AI回复"
            },
            "at_mention": {
                "max_concurrent": 1,
                "prefer_multiple": False,  # @消息通常只需要被@的AI回复
                "description": "@消息，优先被@的AI"
            }
        },
        
        # 维度3：根据AI连续回复情况
        "ai_consecutive": {
            0: {"multiplier": 1.0, "description": "无AI连续，正常"},
            1: {"multiplier": 0.8, "description": "1次AI连续，概率-20%"},
            2: {"multiplier": 0.5, "description": "2次AI连续，概率-50%"},
            3: {"multiplier": 0.2, "description": "3次AI连续，概率-80%"}
        },
        
        # 维度4：根据最近回复的AI数量
        "recent_ai_density": {
            "sparse": {  # 最近5条消息中 < 2条AI
                "encourage": True,
                "description": "AI回复稀疏，鼓励参与"
            },
            "balanced": {  # 2-3条AI
                "encourage": False,
                "description": "AI回复适中，正常"
            },
            "dense": {  # > 3条AI
                "encourage": False,
                "multiplier": 0.5,
                "description": "AI回复过密，降低概率50%"
            }
        }
    }
    
    def __init__(self, custom_thresholds: Optional[Dict[str, Any]] = None):
        """
        初始化策略
        
        Args:
            custom_thresholds: 自定义阈值配置（用于无限制模式等特殊场景）
        """
        self.thresholds = custom_thresholds if custom_thresholds else self.DEFAULT_THRESHOLDS
    
    def analyze_situation(
        self,
        message: GroupMessage,
        context: GroupChatContext,
        ai_consecutive_count: int
    ) -> Dict[str, Any]:
        """
        分析当前群聊情况，返回综合策略
        
        Returns:
            {
                "max_concurrent": int,
                "min_delay_gap": float,
                "probability_multiplier": float,
                "reasoning": str
            }
        """
        recent_messages = context.recent_messages[-10:]  # 最近10条
        
        # 1. 活跃度分析
        recent_5min_count = len([
            m for m in recent_messages
            if (datetime.now() - m.timestamp).total_seconds() < 300
        ])
        
        if recent_5min_count < 3:
            activity_level = "cold"
        elif recent_5min_count < 10:
            activity_level = "warm"
        else:
            activity_level = "hot"
        
        activity_config = self.thresholds["activity"][activity_level]
        
        # 2. 触发类型分析
        if message.sender_type != MemberType.AI:
            trigger_type = "human_message"
        elif "@" in message.content:
            trigger_type = "at_mention"
        else:
            trigger_type = "ai_message"
        
        trigger_config = self.thresholds["trigger_type"][trigger_type]
        
        # 3. AI连续回复分析
        consecutive_config = self.thresholds["ai_consecutive"].get(
            ai_consecutive_count,
            self.thresholds["ai_consecutive"][3]  # 超过3次，按3次处理
        )
        
        # 4. AI密度分析
        recent_ai_count = len([m for m in recent_messages[-5:] if m.sender_type == MemberType.AI])
        if recent_ai_count < 2:
            density_level = "sparse"
        elif recent_ai_count <= 3:
            density_level = "balanced"
        else:
            density_level = "dense"
        
        density_config = self.thresholds["recent_ai_density"][density_level]
        
        # 5. 综合决策
        max_concurrent = min(
            activity_config["max_concurrent"],
            trigger_config["max_concurrent"]
        )
        
        min_delay_gap = activity_config["min_delay_gap"]
        
        probability_multiplier = consecutive_config["multiplier"]
        if "multiplier" in density_config:
            probability_multiplier *= density_config["multiplier"]
        
        reasoning = (
            f"活跃度={activity_level}({activity_config['description']}) | "
            f"触发类型={trigger_type}({trigger_config['description']}) | "
            f"AI连续={ai_consecutive_count}次({consecutive_config['description']}) | "
            f"AI密度={density_level}({density_config['description']})"
        )
        
        return {
            "max_concurrent": max_concurrent,
            "min_delay_gap": min_delay_gap,
            "probability_multiplier": probability_multiplier,
            "reasoning": reasoning,
            "activity_level": activity_level,
            "trigger_type": trigger_type
        }


class DelayTierCalculator:
    """延迟分级计算器（让后发AI能看到先发AI）"""
    
    @staticmethod
    def calculate_tiered_delays(
        decisions: List[AIReplyDecision],
        min_gap: float = 3.0,
        delay_config: Optional[Dict[str, float]] = None
    ) -> List[AIReplyDecision]:
        """
        计算分级延迟
        
        策略：
        1. 第一个AI：短延迟（让TA先回复）
        2. 第二个AI：第一个 + min_gap（确保能看到第一个的回复）
        3. 第三个AI：第二个 + min_gap
        
        Args:
            decisions: AI决策列表（已按优先级排序）
            min_gap: 最小延迟间隔（秒）
            delay_config: 延迟配置字典，包含各种延迟范围
        
        Returns:
            带有分级延迟的决策列表
        """
        if not decisions:
            return []
        
        logger.info(
            f"\n{'='*60}\n"
            f"📊 延迟分级计算 | AI数量={len(decisions)} | 最小间隔={min_gap}s\n"
            f"{'='*60}"
        )
        
        for i, decision in enumerate(decisions):
            if i == 0:
                # 第一个AI：根据原始规则计算基础延迟
                base_delay = DelayTierCalculator._calculate_base_delay(decision, delay_config)
                decision.delay_seconds = base_delay
                decision.tier = 1
                
                logger.info(
                    f"🥇 第{i+1}梯队: {decision.ai_member_id} | "
                    f"延迟={base_delay:.2f}s（基础延迟）"
                )
            else:
                # 后续AI：在前一个AI的基础上增加min_gap
                prev_delay = decisions[i-1].delay_seconds
                decision.delay_seconds = prev_delay + min_gap
                decision.tier = i + 1
                
                logger.info(
                    f"🥈 第{i+1}梯队: {decision.ai_member_id} | "
                    f"延迟={decision.delay_seconds:.2f}s "
                    f"（前一个{prev_delay:.2f}s + 间隔{min_gap}s）"
                )
            
            decision.scheduled_time = datetime.now() + timedelta(seconds=decision.delay_seconds)
        
        return decisions
    
    @staticmethod
    def _calculate_base_delay(decision: AIReplyDecision, delay_config: Optional[Dict[str, float]] = None) -> float:
        """
        计算基础延迟（第一个AI）
        
        Args:
            decision: AI决策
            delay_config: 延迟配置字典
        
        Returns:
            延迟秒数
        """
        # 默认延迟配置（保持原有的默认值）
        default_config = {
            "mention_delay_min": 0.5,
            "mention_delay_max": 1.5,
            "high_interest_delay_min": 1.0,
            "high_interest_delay_max": 2.0,
            "normal_delay_min": 1.5,
            "normal_delay_max": 3.0,
        }
        
        # 🔥 使用传入的配置，如果没有则使用默认配置
        if delay_config:
            config = delay_config
            logger.info(f"📊 使用用户配置的延迟参数: {config}")
        else:
            config = default_config
            logger.info(f"📊 使用默认延迟参数: {config}")
        
        # 被@：快速响应（使用mention_delay配置）
        if "被@提及" in decision.decision_reason:
            delay = random.uniform(
                config.get("mention_delay_min", 0.5),
                config.get("mention_delay_max", 1.5)
            )
            logger.info(f"⚡ 被@消息延迟: {delay:.2f}s (范围: {config.get('mention_delay_min')}-{config.get('mention_delay_max')}s)")
            return delay
        
        # 高概率：中等延迟（使用high_interest_delay配置）
        if decision.probability_score >= 0.7:
            delay = random.uniform(
                config.get("high_interest_delay_min", 1.0),
                config.get("high_interest_delay_max", 2.0)
            )
            logger.info(f"🔥 高兴趣消息延迟: {delay:.2f}s (范围: {config.get('high_interest_delay_min')}-{config.get('high_interest_delay_max')}s)")
            return delay
        
        # 普通：稍长延迟（使用normal_delay配置）
        delay = random.uniform(
            config.get("normal_delay_min", 1.5),
            config.get("normal_delay_max", 3.0)
        )
        logger.info(f"💬 普通消息延迟: {delay:.2f}s (范围: {config.get('normal_delay_min')}-{config.get('normal_delay_max')}s)")
        return delay


class ContentSimilarityDetector:
    """内容相似度检测器（避免雷同回复）"""
    
    @staticmethod
    def is_similar_response(
        response1: str,
        response2: str,
        threshold: float = 0.6
    ) -> bool:
        """
        检测两个回复是否过于相似
        
        Args:
            response1: 回复1
            response2: 回复2
            threshold: 相似度阈值（0-1）
        
        Returns:
            True: 相似度过高
            False: 相似度可接受
        """
        # 简单实现：基于关键词重叠度
        # 生产环境可用更复杂的算法（如TF-IDF、BERT相似度）
        
        # 提取关键词（去除标点和常见词）
        stopwords = {"我", "你", "的", "了", "是", "在", "也", "都", "和", "哈哈", "啊", "呢", "吗"}
        
        def extract_keywords(text: str) -> set:
            import re
            # 移除@提及
            text = re.sub(r'@\S+', '', text)
            # 分词（简单按字符）
            words = [w for w in text if w.strip() and w not in stopwords and not re.match(r'[^\w\s]', w)]
            return set(words)
        
        keywords1 = extract_keywords(response1)
        keywords2 = extract_keywords(response2)
        
        if not keywords1 or not keywords2:
            return False
        
        # 计算Jaccard相似度
        intersection = len(keywords1 & keywords2)
        union = len(keywords1 | keywords2)
        
        similarity = intersection / union if union > 0 else 0
        
        logger.debug(
            f"📊 相似度检测: {similarity:.2%} | "
            f"关键词1={keywords1} | 关键词2={keywords2}"
        )
        
        return similarity >= threshold


class BehaviorRealism:
    """行为真实感增强"""
    
    # AI行为模式配置
    BEHAVIOR_PATTERNS = {
        "active": {  # 活跃型AI
            "reply_boost": 1.2,
            "min_interval": 1.0,
            "description": "性格活跃，回复积极"
        },
        "cautious": {  # 谨慎型AI
            "reply_boost": 0.8,
            "min_interval": 3.0,
            "description": "性格谨慎，回复较慢"
        },
        "balanced": {  # 平衡型AI
            "reply_boost": 1.0,
            "min_interval": 2.0,
            "description": "性格平衡，回复适中"
        }
    }
    
    @staticmethod
    def adjust_for_realism(
        decision: AIReplyDecision,
        ai_member: GroupMember,
        recent_ai_replies: List[Dict]
    ) -> AIReplyDecision:
        """
        根据AI性格和历史行为调整决策
        
        Args:
            decision: 原始决策
            ai_member: AI成员信息
            recent_ai_replies: 该AI最近的回复记录
        
        Returns:
            调整后的决策
        """
        # 1. 根据AI性格调整（从metadata或角色设定获取）
        # 这里简化处理：根据AI ID hash值分配性格
        personality = BehaviorRealism._get_personality(ai_member.member_id)
        pattern = BehaviorRealism.BEHAVIOR_PATTERNS[personality]
        
        decision.probability_score *= pattern["reply_boost"]
        
        # 2. 避免AI回复过于频繁（模拟人类需要时间思考）
        if recent_ai_replies:
            last_reply_time = recent_ai_replies[-1].get("timestamp")
            if last_reply_time:
                time_since_last = (datetime.now() - last_reply_time).total_seconds()
                
                # 如果距离上次回复太近，降低概率
                if time_since_last < pattern["min_interval"]:
                    cooldown_penalty = 0.5
                    decision.probability_score *= cooldown_penalty
                    logger.debug(
                        f"⏳ {ai_member.display_name or ai_member.member_id} 回复过于频繁，"
                        f"降低概率（{cooldown_penalty:.0%}）"
                    )
        
        return decision
    
    @staticmethod
    def _get_personality(ai_id: str) -> str:
        """根据AI ID分配性格（伪随机，保持一致性）"""
        hash_val = hash(ai_id) % 100
        if hash_val < 30:
            return "active"
        elif hash_val < 60:
            return "balanced"
        else:
            return "cautious"


class IntelligentScheduler:
    """智能调度器 v2.0"""
    
    def __init__(self, custom_thresholds: Optional[Dict[str, Any]] = None):
        """
        初始化智能调度器
        
        Args:
            custom_thresholds: 自定义阈值配置（用于无限制模式等特殊场景）
        """
        self.concurrency_strategy = ConcurrencyStrategy(custom_thresholds)
        self.delay_calculator = DelayTierCalculator()
        self.similarity_detector = ContentSimilarityDetector()
        self.realism_enhancer = BehaviorRealism()
        
        # AI回复历史（用于相似度检测和行为分析）
        # group_id -> List[{ai_id, content, timestamp}]
        self.reply_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        
        # AI个人回复历史（用于频率控制）
        # ai_member_id -> List[{group_id, timestamp}]
        self.ai_reply_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
    
    def optimize_decisions(
        self,
        decisions: List[AIReplyDecision],
        message: GroupMessage,
        context: GroupChatContext,
        ai_consecutive_count: int,
        ai_members: List[GroupMember],
        delay_config: Optional[Dict[str, float]] = None
    ) -> List[AIReplyDecision]:
        """
        智能优化AI决策列表
        
        流程：
        1. 分析当前情况（多维度阈值）
        2. 限制并发数量
        3. 调整概率（根据情况）
        4. 计算分级延迟
        5. 增强行为真实感
        
        Args:
            decisions: 原始决策列表
            message: 触发消息
            context: 群聊上下文
            ai_consecutive_count: AI连续回复次数
            ai_members: 所有AI成员
            delay_config: 延迟配置字典（包含各种延迟范围）
        
        Returns:
            优化后的决策列表
        """
        if not decisions:
            return []
        
        logger.info(
            f"\n{'='*80}\n"
            f"🧠 智能调度优化开始 | 原始候选数={len(decisions)}\n"
            f"{'='*80}"
        )
        
        # 1. 分析当前情况
        situation = self.concurrency_strategy.analyze_situation(
            message, context, ai_consecutive_count
        )
        
        logger.info(
            f"📊 情况分析:\n"
            f"  - 最大并发数: {situation['max_concurrent']}\n"
            f"  - 最小延迟间隔: {situation['min_delay_gap']}s\n"
            f"  - 概率倍数: {situation['probability_multiplier']:.2%}\n"
            f"  - 决策理由: {situation['reasoning']}"
        )
        
        # 2. 应用概率调整
        for decision in decisions:
            original_prob = decision.probability_score
            decision.probability_score *= situation['probability_multiplier']
            
            if original_prob != decision.probability_score:
                logger.debug(
                    f"  📉 {decision.ai_member_id}: "
                    f"{original_prob:.2%} -> {decision.probability_score:.2%}"
                )
        
        # 3. 增强行为真实感
        ai_member_map = {ai.member_id: ai for ai in ai_members}
        for decision in decisions:
            ai_member = ai_member_map.get(decision.ai_member_id)
            if ai_member:
                recent_replies = list(self.ai_reply_history[decision.ai_member_id])
                decision = self.realism_enhancer.adjust_for_realism(
                    decision, ai_member, recent_replies
                )
        
        # 4. 分离被@的AI（优先保留）
        mentioned_decisions = []
        normal_decisions = []
        
        for decision in decisions:
            if "被@" in decision.decision_reason or "近期被@" in decision.decision_reason:
                mentioned_decisions.append(decision)
            else:
                normal_decisions.append(decision)
        
        # 5. 按概率排序
        mentioned_decisions.sort(key=lambda d: d.probability_score, reverse=True)
        normal_decisions.sort(key=lambda d: d.probability_score, reverse=True)
        
        # 6. 限制并发数量（被@的AI优先保留，剩余名额给普通AI）
        max_concurrent = situation['max_concurrent']
        
        # 🔥 被@的AI全部保留（不受并发限制）
        selected_decisions = mentioned_decisions.copy()
        
        # 剩余名额分配给普通AI
        remaining_slots = max(0, max_concurrent - len(mentioned_decisions))
        selected_decisions.extend(normal_decisions[:remaining_slots])
        
        if mentioned_decisions:
            logger.info(
                f"🎯 被@的AI优先保留: {len(mentioned_decisions)}个（不受并发限制）"
            )
        
        if len(decisions) > len(selected_decisions):
            logger.info(
                f"✂️ 并发限制: {len(decisions)} -> {len(selected_decisions)} "
                f"(被@AI: {len(mentioned_decisions)}, 普通AI: {len(selected_decisions) - len(mentioned_decisions)}, "
                f"丢弃: {len(decisions) - len(selected_decisions)}个)"
            )
        
        # 6. 计算分级延迟
        selected_decisions = self.delay_calculator.calculate_tiered_delays(
            selected_decisions,
            min_gap=situation['min_delay_gap'],
            delay_config=delay_config
        )
        
        logger.info(
            f"\n{'='*80}\n"
            f"✅ 智能调度优化完成 | 最终选择={len(selected_decisions)}个AI\n"
            f"{'='*80}"
        )
        
        return selected_decisions
    
    def record_reply(self, group_id: str, ai_member_id: str, content: str):
        """记录AI回复（用于相似度检测和行为分析）"""
        timestamp = datetime.now()
        
        # 记录到群组历史
        self.reply_history[group_id].append({
            "ai_id": ai_member_id,
            "content": content,
            "timestamp": timestamp
        })
        
        # 记录到AI个人历史
        self.ai_reply_history[ai_member_id].append({
            "group_id": group_id,
            "timestamp": timestamp
        })
    
    def check_similarity_with_recent(
        self,
        group_id: str,
        content: str,
        lookback: int = 3,
        threshold: float = 0.6
    ) -> Tuple[bool, Optional[str]]:
        """
        检查内容是否与最近的回复相似
        
        Args:
            group_id: 群组ID
            content: 待检查内容
            lookback: 回溯条数
            threshold: 相似度阈值（0-1）
        
        Returns:
            (是否相似, 相似的回复内容)
        """
        recent_replies = list(self.reply_history[group_id])[-lookback:]
        
        for reply in recent_replies:
            if self.similarity_detector.is_similar_response(content, reply["content"], threshold):
                logger.warning(
                    f"⚠️ 内容相似度过高！\n"
                    f"  新回复: {content[:50]}...\n"
                    f"  相似回复: {reply['content'][:50]}... (来自 {reply['ai_id']})\n"
                    f"  阈值: {threshold}"
                )
                return True, reply["content"]
        
        return False, None


# 全局单例（保留默认实例用于向后兼容）
_intelligent_scheduler = None


def get_intelligent_scheduler(custom_thresholds: Optional[Dict[str, Any]] = None) -> IntelligentScheduler:
    """
    获取智能调度器实例
    
    Args:
        custom_thresholds: 自定义阈值配置（用于无限制模式等特殊场景）
                         如果提供，则创建新实例；否则返回全局单例
    
    Returns:
        IntelligentScheduler实例
    """
    # 如果提供自定义配置，创建新实例
    if custom_thresholds is not None:
        return IntelligentScheduler(custom_thresholds)
    
    # 否则返回全局单例
    global _intelligent_scheduler
    if _intelligent_scheduler is None:
        _intelligent_scheduler = IntelligentScheduler()
    return _intelligent_scheduler

