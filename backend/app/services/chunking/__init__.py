"""
智能分片系统
支持多种文档类型的智能分片，异步处理，模块化设计
"""

from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig, ChunkingStrategy
from .factory import ChunkerFactory
from .registry import ChunkerRegistry

# 导入所有分片器模块，触发 @register_chunker 装饰器
from . import simple_chunker
from . import json_chunker
from . import code_chunker
from . import markdown_chunker
from . import semantic_chunker
from . import hierarchical_chunker

__all__ = [
    'BaseChunker',
    'ChunkResult',
    'ChunkingConfig',
    'ChunkingStrategy',
    'ChunkerFactory',
    'ChunkerRegistry',
]

