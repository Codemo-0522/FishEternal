"""
群聊策略配置适配器

负责将数据库中的GroupStrategyConfig转换为各个限流模块需要的配置格式

核心功能：
1. 统一处理 unrestricted_mode（无限制模式）
2. 当开启无限制模式时，所有限流参数自动设置为最大值
3. 避免在每个判断处都添加条件检查
"""
import logging
from typing import Dict, Any
from ...models.group_chat import GroupStrategyConfig

logger = logging.getLogger(__name__)


class StrategyConfigAdapter:
    """策略配置适配器"""
    
    # 无限制模式的最大值常量（合理的上限，防止系统崩溃）
    UNRESTRICTED_LIMITS = {
        "max_ai_consecutive_replies": 9999,    # AI连续回复次数
        "max_messages_per_round": 9999,        # 每轮最大消息数
        "max_tokens_per_round": 999999,        # 每轮最大token数
        "cooldown_seconds": 0,                  # 冷却时间
        "max_cooldown_recoveries": 9999,       # 冷却恢复次数
        "ai_reply_probability": 1.0,           # AI回复概率100%
        "max_concurrent": 999,                  # 最大并发数
        "min_delay_gap": 0.1,                  # 最小延迟（保留微小延迟避免瞬间爆发）
        "delay_min": 0.1,                      # 最小延迟
        "delay_max": 0.5,                      # 最大延迟
        "ai_to_ai_delay_seconds": 0.5,         # AI-to-AI触发延迟（保留短延迟避免瞬间爆发）
        "keep_rate": 1.0,                      # 保留率100%
        "min_sample_count": 999,               # 最小采样数
        "multiplier": 1.0,                     # 概率倍数100%
        "similarity_threshold": 0.0,           # 相似度阈值0（不检测）
    }
    
    @staticmethod
    def to_conversation_controller_config(config: GroupStrategyConfig) -> Dict[str, Any]:
        """
        转换为ConversationController需要的配置格式
        
        Args:
            config: 群聊策略配置
            
        Returns:
            ConversationController配置字典
        """
        # 如果开启无限制模式，直接返回最大值配置
        if config.unrestricted_mode:
            logger.info(f"🔓 无限制模式已开启 - ConversationController使用最大值配置")
            return {
                "max_ai_consecutive_replies": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_ai_consecutive_replies"],
                "max_messages_per_round": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_messages_per_round"],
                "max_tokens_per_round": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_tokens_per_round"],
                "cooldown_seconds": StrategyConfigAdapter.UNRESTRICTED_LIMITS["cooldown_seconds"],
                "enable_ai_to_ai": True,  # 强制开启AI互相对话
                "ai_reply_probability": StrategyConfigAdapter.UNRESTRICTED_LIMITS["ai_reply_probability"],
                "max_cooldown_recoveries": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_cooldown_recoveries"],
            }
        
        # 正常模式：使用数据库配置
        return {
            "max_ai_consecutive_replies": config.max_ai_consecutive_replies,
            "max_messages_per_round": config.max_messages_per_round,
            "max_tokens_per_round": config.max_tokens_per_round,
            "cooldown_seconds": config.cooldown_seconds,
            "enable_ai_to_ai": config.enable_ai_to_ai,
            "ai_reply_probability": config.ai_reply_probability,
            "max_cooldown_recoveries": config.max_cooldown_recoveries,
        }
    
    @staticmethod
    def to_ai_scheduler_config(config: GroupStrategyConfig) -> Dict[str, Any]:
        """
        转换为AIScheduler需要的配置格式
        
        Args:
            config: 群聊策略配置
            
        Returns:
            AIScheduler配置字典
        """
        # 如果开启无限制模式，直接返回最大值配置
        if config.unrestricted_mode:
            logger.info(f"🔓 无限制模式已开启 - AIScheduler使用最大值配置")
            return {
                "high_probability_threshold": 0.0,  # 阈值降到0，所有AI都算高概率
                "high_probability_keep_rate": StrategyConfigAdapter.UNRESTRICTED_LIMITS["keep_rate"],
                "mid_probability_threshold": 0.0,
                "low_probability_keep_rate": StrategyConfigAdapter.UNRESTRICTED_LIMITS["keep_rate"],
                "min_ai_sample_count": StrategyConfigAdapter.UNRESTRICTED_LIMITS["min_sample_count"],
                "mention_delay_min": StrategyConfigAdapter.UNRESTRICTED_LIMITS["delay_min"],
                "mention_delay_max": StrategyConfigAdapter.UNRESTRICTED_LIMITS["delay_max"],
                "high_interest_delay_min": StrategyConfigAdapter.UNRESTRICTED_LIMITS["delay_min"],
                "high_interest_delay_max": StrategyConfigAdapter.UNRESTRICTED_LIMITS["delay_max"],
                "normal_delay_min": StrategyConfigAdapter.UNRESTRICTED_LIMITS["delay_min"],
                "normal_delay_max": StrategyConfigAdapter.UNRESTRICTED_LIMITS["delay_max"],
            }
        
        # 正常模式：使用数据库配置
        return {
            "high_probability_threshold": config.high_probability_threshold,
            "high_probability_keep_rate": config.high_probability_keep_rate,
            "mid_probability_threshold": config.mid_probability_threshold,
            "low_probability_keep_rate": config.low_probability_keep_rate,
            "min_ai_sample_count": config.min_ai_sample_count,
            "mention_delay_min": config.mention_delay_min,
            "mention_delay_max": config.mention_delay_max,
            "high_interest_delay_min": config.high_interest_delay_min,
            "high_interest_delay_max": config.high_interest_delay_max,
            "normal_delay_min": config.normal_delay_min,
            "normal_delay_max": config.normal_delay_max,
        }
    
    @staticmethod
    def to_intelligent_scheduler_config(config: GroupStrategyConfig) -> Dict[str, Any]:
        """
        转换为IntelligentScheduler需要的配置格式
        
        Args:
            config: 群聊策略配置
            
        Returns:
            IntelligentScheduler配置字典
        """
        # 如果开启无限制模式，直接返回最大值配置
        if config.unrestricted_mode:
            logger.info(f"🔓 无限制模式已开启 - IntelligentScheduler使用最大值配置")
            return {
                # 活跃度配置 - 所有情况下都允许最大并发
                "activity": {
                    "cold": {
                        "max_concurrent": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
                        "min_delay_gap": StrategyConfigAdapter.UNRESTRICTED_LIMITS["min_delay_gap"],
                        "description": "冷清群（无限制）"
                    },
                    "warm": {
                        "max_concurrent": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
                        "min_delay_gap": StrategyConfigAdapter.UNRESTRICTED_LIMITS["min_delay_gap"],
                        "description": "温和群（无限制）"
                    },
                    "hot": {
                        "max_concurrent": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
                        "min_delay_gap": StrategyConfigAdapter.UNRESTRICTED_LIMITS["min_delay_gap"],
                        "description": "热闹群（无限制）"
                    }
                },
                # 触发类型配置 - 所有类型都允许最大并发
                "trigger_type": {
                    "human_message": {
                        "max_concurrent": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
                        "prefer_multiple": True,
                        "description": "人类消息（无限制）"
                    },
                    "ai_message": {
                        "max_concurrent": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
                        "prefer_multiple": True,  # 无限制模式下也鼓励多AI回复
                        "description": "AI消息（无限制）"
                    },
                    "at_mention": {
                        "max_concurrent": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
                        "prefer_multiple": True,
                        "description": "@消息（无限制）"
                    }
                },
                # AI连续回复概率衰减 - 全部设为1.0，不衰减
                "ai_consecutive": {
                    0: {"multiplier": StrategyConfigAdapter.UNRESTRICTED_LIMITS["multiplier"], "description": "无AI连续（无限制）"},
                    1: {"multiplier": StrategyConfigAdapter.UNRESTRICTED_LIMITS["multiplier"], "description": "1次AI连续（无限制）"},
                    2: {"multiplier": StrategyConfigAdapter.UNRESTRICTED_LIMITS["multiplier"], "description": "2次AI连续（无限制）"},
                    3: {"multiplier": StrategyConfigAdapter.UNRESTRICTED_LIMITS["multiplier"], "description": "3次及以上AI连续（无限制）"}
                },
                # AI密度 - 不限制密度
                "recent_ai_density": {
                    "sparse": {"encourage": True, "description": "AI回复稀疏（无限制）"},
                    "balanced": {"encourage": True, "description": "AI回复适中（无限制）"},
                    "dense": {
                        "encourage": True,  # 无限制模式下也鼓励
                        "multiplier": StrategyConfigAdapter.UNRESTRICTED_LIMITS["multiplier"],
                        "description": "AI回复过密（无限制）"
                    }
                },
                # 相似度检测 - 禁用
                "enable_similarity_detection": False,
                "similarity_threshold": StrategyConfigAdapter.UNRESTRICTED_LIMITS["similarity_threshold"],
                "similarity_lookback": 0,
            }
        
        # 正常模式：使用数据库配置
        return {
            # 活跃度配置
            "activity": {
                "cold": {
                    "max_concurrent": config.cold_group_max_concurrent,
                    "min_delay_gap": config.cold_group_min_delay_gap,
                    "description": "冷清群"
                },
                "warm": {
                    "max_concurrent": config.warm_group_max_concurrent,
                    "min_delay_gap": config.warm_group_min_delay_gap,
                    "description": "温和群"
                },
                "hot": {
                    "max_concurrent": config.hot_group_max_concurrent,
                    "min_delay_gap": config.hot_group_min_delay_gap,
                    "description": "热闹群"
                }
            },
            # 触发类型配置
            "trigger_type": {
                "human_message": {
                    "max_concurrent": config.human_message_max_concurrent,
                    "prefer_multiple": True,
                    "description": "人类消息"
                },
                "ai_message": {
                    "max_concurrent": config.ai_message_max_concurrent,
                    "prefer_multiple": False,
                    "description": "AI消息"
                },
                "at_mention": {
                    "max_concurrent": config.at_mention_max_concurrent,
                    "prefer_multiple": False,
                    "description": "@消息"
                }
            },
            # AI连续回复概率衰减
            "ai_consecutive": {
                0: {"multiplier": config.ai_consecutive_0_multiplier, "description": "无AI连续"},
                1: {"multiplier": config.ai_consecutive_1_multiplier, "description": "1次AI连续"},
                2: {"multiplier": config.ai_consecutive_2_multiplier, "description": "2次AI连续"},
                3: {"multiplier": config.ai_consecutive_3_multiplier, "description": "3次及以上AI连续"}
            },
            # AI密度
            "recent_ai_density": {
                "sparse": {"encourage": True, "description": "AI回复稀疏"},
                "balanced": {"encourage": False, "description": "AI回复适中"},
                "dense": {
                    "encourage": False,
                    "multiplier": config.dense_ai_multiplier,
                    "description": "AI回复过密"
                }
            },
            # 相似度检测
            "enable_similarity_detection": config.enable_similarity_detection,
            "similarity_threshold": config.similarity_threshold,
            "similarity_lookback": config.similarity_lookback,
        }
    
    @staticmethod
    def to_reply_controller_config(config: GroupStrategyConfig) -> Dict[str, Any]:
        """
        转换为ReplyController需要的配置格式
        
        Args:
            config: 群聊策略配置
            
        Returns:
            ReplyController配置字典
        """
        # 如果开启无限制模式，直接返回最大值配置
        if config.unrestricted_mode:
            logger.info(f"🔓 无限制模式已开启 - ReplyController使用最大值配置")
            return {
                "max_concurrent_replies": StrategyConfigAdapter.UNRESTRICTED_LIMITS["max_concurrent"],
            }
        
        # 正常模式：使用数据库配置
        return {
            "max_concurrent_replies": config.max_concurrent_replies_per_message,
        }
    
    @staticmethod
    def get_ai_to_ai_delay(config: GroupStrategyConfig) -> float:
        """
        获取AI-to-AI触发延迟时间
        
        Args:
            config: 群聊策略配置
            
        Returns:
            延迟秒数
        """
        if config.unrestricted_mode:
            return StrategyConfigAdapter.UNRESTRICTED_LIMITS["ai_to_ai_delay_seconds"]
        return config.ai_to_ai_delay_seconds
    
    @staticmethod
    def get_default_config() -> GroupStrategyConfig:
        """获取默认配置"""
        return GroupStrategyConfig()

