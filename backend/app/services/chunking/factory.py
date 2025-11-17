"""
分片器工厂
提供统一的分片器创建接口
"""

from typing import Optional
from .base_chunker import BaseChunker, ChunkingConfig, ChunkingStrategy
from .registry import ChunkerRegistry
import logging

logger = logging.getLogger(__name__)


class ChunkerFactory:
    """分片器工厂类"""
    
    @staticmethod
    def create_chunker(
        file_type: str,
        content: str,
        config: Optional[ChunkingConfig] = None,
        strategy: Optional[ChunkingStrategy] = None
    ) -> BaseChunker:
        """
        创建分片器实例
        
        Args:
            file_type: 文件类型（扩展名，如 'json', 'py', 'md'）
            content: 文档内容
            config: 分片配置（可选，使用默认配置）
            strategy: 分片策略（可选，覆盖config中的策略）
            
        Returns:
            分片器实例
        """
        if config is None:
            config = ChunkingConfig()
        
        if strategy is not None:
            config.strategy = strategy
        
        # 根据策略选择分片器
        if config.strategy == ChunkingStrategy.SIMPLE:
            return ChunkerFactory._create_simple_chunker(config)
        
        elif config.strategy == ChunkingStrategy.SEMANTIC:
            return ChunkerFactory._create_semantic_chunker(config)
        
        elif config.strategy == ChunkingStrategy.DOCUMENT_AWARE:
            return ChunkerFactory._create_document_aware_chunker(file_type, content, config)
        
        elif config.strategy == ChunkingStrategy.HIERARCHICAL:
            return ChunkerFactory._create_hierarchical_chunker(file_type, content, config)
        
        else:
            logger.warning(f"Unknown strategy: {config.strategy}, using document_aware")
            return ChunkerFactory._create_document_aware_chunker(file_type, content, config)
    
    @staticmethod
    def _create_simple_chunker(config: ChunkingConfig) -> BaseChunker:
        """创建简单分片器"""
        from .simple_chunker import SimpleChunker
        return SimpleChunker(config)
    
    @staticmethod
    def _create_semantic_chunker(config: ChunkingConfig) -> BaseChunker:
        """创建语义分片器"""
        from .semantic_chunker import SemanticChunker
        return SemanticChunker(config)
    
    @staticmethod
    def _create_document_aware_chunker(file_type: str, content: str, config: ChunkingConfig) -> BaseChunker:
        """创建文档感知分片器（自动选择最佳分片器）"""
        return ChunkerRegistry.get_best_chunker(file_type, content, config)
    
    @staticmethod
    def _create_hierarchical_chunker(file_type: str, content: str, config: ChunkingConfig) -> BaseChunker:
        """创建层级分片器"""
        from .hierarchical_chunker import HierarchicalChunker
        return HierarchicalChunker(file_type, content, config)
    
    @staticmethod
    def detect_file_type(filename: str) -> str:
        """
        从文件名检测文件类型
        
        Args:
            filename: 文件名
            
        Returns:
            文件类型（扩展名，小写）
        """
        if '.' not in filename:
            return 'unknown'
        
        return filename.rsplit('.', 1)[-1].lower()

