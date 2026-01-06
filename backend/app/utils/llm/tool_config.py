"""
工具调用全局配置中心

所有工具调用相关的参数都在这里统一管理
任何方法都可以直接引用，无需修改函数签名
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolCallConfig:
    """工具调用全局配置"""
    
    # ==================== 核心参数 ====================
    # 最大工具调用迭代次数
    max_iterations: int = 10

    # 工具调用超时设置（秒）
    tool_execution_timeout: int = 600  # 单个工具执行的超时时间（10分钟，用于图片生成等耗时操作）
    llm_call_timeout: int = 180  # LLM调用（含工具思考）的超时时间
    total_timeout: int = 900  # 整个工具调用流程的总超时时间（15分钟）
    
    # 并发控制
    max_concurrent_tools: int = 5
    
    # 重试设置
    max_retries: int = 2
    retry_delay: float = 1.0  # 重试延迟（秒）
    
    # ==================== 功能开关 ====================
    # 是否启用工具结果缓存
    enable_tool_cache: bool = True
    
    # 是否启用详细日志
    verbose_logging: bool = True
    
    # 是否在达到最大迭代次数时强制返回
    force_reply_on_max_iterations: bool = True
    
    # 是否启用工具调用统计
    enable_tool_stats: bool = True
    
    # ==================== 安全设置 ====================
    # 单次工具调用最大返回大小（字节）
    max_tool_result_size: int = 1024 * 1024  # 1MB
    
    # 是否允许工具调用失败后继续
    allow_continue_on_error: bool = True
    
    # ==================== 扩展配置 ====================
    # 自定义配置（用于未来扩展）
    custom_config: Dict[str, Any] = field(default_factory=dict)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持自定义配置）
        
        Args:
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值
        """
        # 先查找标准配置
        if hasattr(self, key):
            return getattr(self, key)
        # 再查找自定义配置
        return self.custom_config.get(key, default)
    
    def set(self, key: str, value: Any):
        """
        设置配置值
        
        Args:
            key: 配置键名
            value: 配置值
        """
        if hasattr(self, key):
            setattr(self, key, value)
            logger.info(f"✅ 更新全局配置: {key} = {value}")
        else:
            self.custom_config[key] = value
            logger.info(f"✅ 添加自定义配置: {key} = {value}")
    
    def update(self, **kwargs):
        """
        批量更新配置
        
        Args:
            **kwargs: 配置键值对
        """
        for key, value in kwargs.items():
            self.set(key, value)
    
    def to_dict(self) -> Dict[str, Any]:
        """导出配置为字典"""
        result = {
            'max_iterations': self.max_iterations,
            'tool_execution_timeout': self.tool_execution_timeout,
            'llm_call_timeout': self.llm_call_timeout,
            'total_timeout': self.total_timeout,
            'max_concurrent_tools': self.max_concurrent_tools,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'enable_tool_cache': self.enable_tool_cache,
            'verbose_logging': self.verbose_logging,
            'force_reply_on_max_iterations': self.force_reply_on_max_iterations,
            'enable_tool_stats': self.enable_tool_stats,
            'max_tool_result_size': self.max_tool_result_size,
            'allow_continue_on_error': self.allow_continue_on_error,
        }
        result.update(self.custom_config)
        return result
    
    def reset(self):
        """重置为默认配置"""
        self.__init__()
        logger.info("🔄 已重置为默认配置")


# ==================== 全局单例 ====================
tool_config = ToolCallConfig()


# ==================== 便捷函数 ====================
def get_config() -> ToolCallConfig:
    """获取全局配置对象"""
    return tool_config


def get_max_iterations() -> int:
    """获取最大迭代次数"""
    return tool_config.max_iterations


def set_max_iterations(value: int):
    """设置最大迭代次数"""
    tool_config.max_iterations = value
    logger.info(f"✅ 全局最大迭代次数已设置为: {value}")


def update_config(**kwargs):
    """
    更新全局配置
    
    示例:
        update_config(max_iterations=20, tool_timeout=60)
    """
    tool_config.update(**kwargs)


def reset_config():
    """重置为默认配置"""
    tool_config.reset()


# ==================== 配置加载（可选） ====================
def load_config_from_env():
    """从环境变量加载配置"""
    import os
    
    # 从环境变量读取
    if max_iter := os.getenv('TOOL_MAX_ITERATIONS'):
        tool_config.max_iterations = int(max_iter)
    
    if exec_timeout := os.getenv('TOOL_EXECUTION_TIMEOUT'):
        tool_config.tool_execution_timeout = int(exec_timeout)
    
    if llm_timeout := os.getenv('LLM_CALL_TIMEOUT'):
        tool_config.llm_call_timeout = int(llm_timeout)
    
    if total_timeout := os.getenv('TOOL_TOTAL_TIMEOUT'):
        tool_config.total_timeout = int(total_timeout)
    
    logger.info(f"📋 已从环境变量加载配置: {tool_config.to_dict()}")


def load_config_from_dict(config_dict: Dict[str, Any]):
    """从字典加载配置"""
    tool_config.update(**config_dict)
    logger.info(f"📋 已从字典加载配置: {tool_config.to_dict()}")


# 初始化时尝试从环境变量加载
try:
    load_config_from_env()
except Exception as e:
    logger.debug(f"未从环境变量加载配置: {e}")

