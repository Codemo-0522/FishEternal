"""
分片器注册中心
管理所有可用的分片器，支持动态注册和查找
"""

from typing import Dict, List, Type, Optional
from .base_chunker import BaseChunker, ChunkingConfig, DocumentType
import logging

logger = logging.getLogger(__name__)


class ChunkerRegistry:
    """分片器注册中心（单例模式）"""
    
    _instance = None
    _chunkers: Dict[str, Type[BaseChunker]] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def register(cls, name: str, chunker_class: Type[BaseChunker]):
        """
        注册分片器
        
        Args:
            name: 分片器名称（唯一标识）
            chunker_class: 分片器类
        """
        if not issubclass(chunker_class, BaseChunker):
            raise TypeError(f"{chunker_class} must be a subclass of BaseChunker")
        
        cls._chunkers[name] = chunker_class
        logger.info(f"Registered chunker: {name} -> {chunker_class.__name__}")
    
    @classmethod
    def unregister(cls, name: str):
        """
        注销分片器
        
        Args:
            name: 分片器名称
        """
        if name in cls._chunkers:
            del cls._chunkers[name]
            logger.info(f"Unregistered chunker: {name}")
    
    @classmethod
    def get_chunker(cls, name: str, config: ChunkingConfig) -> Optional[BaseChunker]:
        """
        获取分片器实例
        
        Args:
            name: 分片器名称
            config: 分片配置
            
        Returns:
            分片器实例
        """
        chunker_class = cls._chunkers.get(name)
        if chunker_class:
            return chunker_class(config)
        return None
    
    @classmethod
    def get_best_chunker(cls, file_type: str, content: str, config: ChunkingConfig) -> BaseChunker:
        """
        根据文件类型和内容自动选择最佳分片器
        
        Args:
            file_type: 文件类型（扩展名）
            content: 文档内容
            config: 分片配置
            
        Returns:
            最佳分片器实例
        """
        candidates = []
        
        for name, chunker_class in cls._chunkers.items():
            chunker = chunker_class(config)
            if chunker.can_handle(file_type, content):
                candidates.append((chunker, chunker.get_priority()))
        
        if not candidates:
            # 没有找到合适的分片器，使用默认分片器
            logger.warning(f"No suitable chunker found for {file_type}, using default")
            from .simple_chunker import SimpleChunker
            return SimpleChunker(config)
        
        # 按优先级排序，返回优先级最高的
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_chunker = candidates[0][0]
        
        logger.info(f"Selected chunker: {best_chunker.__class__.__name__} for {file_type}")
        return best_chunker
    
    @classmethod
    def list_chunkers(cls) -> List[str]:
        """
        列出所有已注册的分片器
        
        Returns:
            分片器名称列表
        """
        return list(cls._chunkers.keys())
    
    @classmethod
    def clear(cls):
        """清空所有注册的分片器"""
        cls._chunkers.clear()
        logger.info("Cleared all registered chunkers")


# 装饰器：用于自动注册分片器
def register_chunker(name: str):
    """
    分片器注册装饰器
    
    Usage:
        @register_chunker("json")
        class JSONChunker(BaseChunker):
            ...
    """
    def decorator(chunker_class: Type[BaseChunker]):
        ChunkerRegistry.register(name, chunker_class)
        return chunker_class
    return decorator

