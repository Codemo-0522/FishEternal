"""
基础分片器接口
定义所有分片器的统一接口和数据结构
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ChunkingStrategy(str, Enum):
    """分片策略枚举"""
    SIMPLE = "simple"  # 简单分片（基于分隔符）
    SEMANTIC = "semantic"  # 语义分片（智能边界）
    DOCUMENT_AWARE = "document_aware"  # 文档感知分片（推荐）
    HIERARCHICAL = "hierarchical"  # 层级分片


class DocumentType(str, Enum):
    """文档类型枚举"""
    JSON = "json"
    CODE = "code"
    MARKDOWN = "markdown"
    PDF = "pdf"
    TEXT = "text"
    HTML = "html"
    CSV = "csv"
    EXCEL = "excel"
    UNKNOWN = "unknown"


@dataclass
class ChunkingConfig:
    """分片配置"""
    strategy: ChunkingStrategy = ChunkingStrategy.DOCUMENT_AWARE
    chunk_size: int = 1024
    chunk_overlap: int = 100
    separators: List[str] = field(default_factory=lambda: ["\n\n", "\n", "。", "！", "？", "，", " ", ""])
    
    # 语义分片配置
    use_sentence_boundary: bool = True
    semantic_threshold: float = 0.5
    
    # 文档感知配置
    preserve_structure: bool = True
    ast_parsing: bool = True
    
    # 层级分片配置
    enable_hierarchy: bool = False
    parent_chunk_size: int = 4096
    
    # 性能配置
    max_workers: int = 4
    batch_size: int = 100


@dataclass
class ChunkResult:
    """分片结果"""
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    parent_chunk_id: Optional[str] = None
    
    # 质量指标
    quality_score: float = 1.0  # 分片质量分数 (0-1)
    completeness: bool = True  # 是否完整（未被强制截断）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'content': self.content,
            'metadata': self.metadata,
            'chunk_index': self.chunk_index,
            'parent_chunk_id': self.parent_chunk_id,
            'quality_score': self.quality_score,
            'completeness': self.completeness,
        }


class BaseChunker(ABC):
    """
    基础分片器抽象类
    所有分片器必须继承此类并实现chunk方法
    """
    
    def __init__(self, config: ChunkingConfig):
        self.config = config
    
    @abstractmethod
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        分片方法（必须实现）
        
        Args:
            content: 文档内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        pass
    
    @abstractmethod
    def can_handle(self, file_type: str, content: str) -> bool:
        """
        判断是否可以处理该类型的文档
        
        Args:
            file_type: 文件类型（扩展名）
            content: 文档内容
            
        Returns:
            是否可以处理
        """
        pass
    
    def get_priority(self) -> int:
        """
        获取分片器优先级（数字越大优先级越高）
        用于在多个分片器都能处理时选择最合适的
        
        Returns:
            优先级（0-100）
        """
        return 50
    
    def validate_chunk(self, chunk: ChunkResult) -> bool:
        """
        验证分片是否有效
        
        Args:
            chunk: 分片结果
            
        Returns:
            是否有效
        """
        if not chunk.content or not chunk.content.strip():
            return False
        
        if len(chunk.content) > self.config.chunk_size * 2:
            # 分片过大，可能存在问题
            return False
        
        return True
    
    def calculate_quality_score(self, chunk: ChunkResult) -> float:
        """
        计算分片质量分数
        
        Args:
            chunk: 分片结果
            
        Returns:
            质量分数 (0-1)
        """
        score = 1.0
        
        # 长度惩罚（过短或过长）
        ideal_size = self.config.chunk_size
        actual_size = len(chunk.content)
        size_ratio = actual_size / ideal_size
        
        if size_ratio < 0.3:
            score -= 0.3  # 过短
        elif size_ratio > 1.5:
            score -= 0.2  # 过长
        
        # 完整性奖励
        if chunk.completeness:
            score += 0.1
        
        return max(0.0, min(1.0, score))
    
    def fallback_chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        降级分片方法（当专用分片器失败时使用）
        使用简单的分隔符分片
        
        Args:
            content: 文档内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        from .simple_chunker import SimpleChunker
        
        simple_chunker = SimpleChunker(self.config)
        return simple_chunker.chunk(content, metadata)
    
    def add_overlap(self, chunks: List[ChunkResult]) -> List[ChunkResult]:
        """
        为分片添加重叠部分
        
        Args:
            chunks: 原始分片列表
            
        Returns:
            添加重叠后的分片列表
        """
        if self.config.chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        
        overlapped_chunks = []
        
        for i, chunk in enumerate(chunks):
            if i == 0:
                overlapped_chunks.append(chunk)
                continue
            
            # 从前一个分片中取overlap部分
            prev_chunk = chunks[i - 1]
            overlap_text = prev_chunk.content[-self.config.chunk_overlap:]
            
            # 添加到当前分片前面
            new_content = overlap_text + chunk.content
            chunk.content = new_content
            overlapped_chunks.append(chunk)
        
        return overlapped_chunks
    
    def enrich_metadata(self, chunk: ChunkResult, doc_metadata: Optional[Dict[str, Any]] = None) -> ChunkResult:
        """
        增强分片元数据
        
        Args:
            chunk: 分片结果
            doc_metadata: 文档级元数据
            
        Returns:
            增强后的分片结果
        """
        if doc_metadata:
            chunk.metadata.update(doc_metadata)
        
        # 添加统计信息
        chunk.metadata['char_count'] = len(chunk.content)
        chunk.metadata['word_count'] = len(chunk.content.split())
        chunk.metadata['chunker_type'] = self.__class__.__name__
        
        # 计算质量分数
        chunk.quality_score = self.calculate_quality_score(chunk)
        
        return chunk

