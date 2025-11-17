"""
流式输出配置管理
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import os


@dataclass
class StreamingConfig:
    """流式输出配置"""
    
    # 基础配置
    enable_universal_streaming: bool = True  # 是否启用通用流式管理器
    enable_smart_chunking: bool = True  # 是否启用智能分块输出
    chunk_size: int = 3  # 智能分块大小（字符数）
    chunk_delay: float = 0.01  # 分块输出延迟（秒）
    
    # 工具调用配置
    enable_parallel_tools: bool = True  # 是否启用并行工具调用
    # 注意：max_tool_iterations 已迁移到 tool_config.py 统一管理
    tool_timeout: float = 180.0  # 单个工具调用超时时间（秒）- 增加到3分钟，适应复杂工具调用和LLM思考时间
    use_streaming_tool_calls: bool = True  # 🎯 是否使用流式工具调用（已全面支持流式工具调用，默认启用）
    
    # 并发控制
    max_concurrent_sessions: int = 100  # 最大并发会话数
    session_timeout: float = 300.0  # 会话超时时间（秒）
    cleanup_interval: float = 60.0  # 清理间隔（秒）
    
    # 性能优化
    use_thread_pool_for_sync_calls: bool = True  # 对同步调用使用线程池
    thread_pool_max_workers: int = 10  # 线程池最大工作线程数
    
    # 错误处理
    enable_fallback: bool = True  # 是否启用回退机制
    max_retry_attempts: int = 3  # 最大重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）
    
    # 调试配置
    enable_debug_logging: bool = False  # 是否启用调试日志
    log_chunk_content: bool = False  # 是否记录分块内容
    
    @classmethod
    def from_env(cls) -> 'StreamingConfig':
        """从环境变量创建配置"""
        return cls(
            enable_universal_streaming=os.getenv('STREAMING_ENABLE_UNIVERSAL', 'true').lower() == 'true',
            enable_smart_chunking=os.getenv('STREAMING_ENABLE_SMART_CHUNKING', 'true').lower() == 'true',
            chunk_size=int(os.getenv('STREAMING_CHUNK_SIZE', '3')),
            chunk_delay=float(os.getenv('STREAMING_CHUNK_DELAY', '0.01')),
            
            enable_parallel_tools=os.getenv('STREAMING_ENABLE_PARALLEL_TOOLS', 'true').lower() == 'true',
            # max_tool_iterations 已迁移到 tool_config.py
            tool_timeout=float(os.getenv('STREAMING_TOOL_TIMEOUT', '180.0')),
            use_streaming_tool_calls=os.getenv('STREAMING_USE_STREAMING_TOOL_CALLS', 'true').lower() == 'true',
            
            max_concurrent_sessions=int(os.getenv('STREAMING_MAX_CONCURRENT_SESSIONS', '100')),
            session_timeout=float(os.getenv('STREAMING_SESSION_TIMEOUT', '300.0')),
            cleanup_interval=float(os.getenv('STREAMING_CLEANUP_INTERVAL', '60.0')),
            
            use_thread_pool_for_sync_calls=os.getenv('STREAMING_USE_THREAD_POOL', 'true').lower() == 'true',
            thread_pool_max_workers=int(os.getenv('STREAMING_THREAD_POOL_MAX_WORKERS', '10')),
            
            enable_fallback=os.getenv('STREAMING_ENABLE_FALLBACK', 'true').lower() == 'true',
            max_retry_attempts=int(os.getenv('STREAMING_MAX_RETRY_ATTEMPTS', '3')),
            retry_delay=float(os.getenv('STREAMING_RETRY_DELAY', '1.0')),
            
            enable_debug_logging=os.getenv('STREAMING_ENABLE_DEBUG_LOGGING', 'false').lower() == 'true',
            log_chunk_content=os.getenv('STREAMING_LOG_CHUNK_CONTENT', 'false').lower() == 'true',
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'enable_universal_streaming': self.enable_universal_streaming,
            'enable_smart_chunking': self.enable_smart_chunking,
            'chunk_size': self.chunk_size,
            'chunk_delay': self.chunk_delay,
            'enable_parallel_tools': self.enable_parallel_tools,
            # 'max_tool_iterations' 已迁移到 tool_config.py
            'tool_timeout': self.tool_timeout,
            'use_streaming_tool_calls': self.use_streaming_tool_calls,
            'max_concurrent_sessions': self.max_concurrent_sessions,
            'session_timeout': self.session_timeout,
            'cleanup_interval': self.cleanup_interval,
            'use_thread_pool_for_sync_calls': self.use_thread_pool_for_sync_calls,
            'thread_pool_max_workers': self.thread_pool_max_workers,
            'enable_fallback': self.enable_fallback,
            'max_retry_attempts': self.max_retry_attempts,
            'retry_delay': self.retry_delay,
            'enable_debug_logging': self.enable_debug_logging,
            'log_chunk_content': self.log_chunk_content,
        }


# 全局配置实例
streaming_config = StreamingConfig.from_env()
