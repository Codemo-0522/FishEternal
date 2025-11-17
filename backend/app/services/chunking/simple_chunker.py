"""
简单分片器
基于分隔符的传统分片方法
"""

from typing import List, Dict, Any, Optional
from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig
from .registry import register_chunker
import re


@register_chunker("simple")
class SimpleChunker(BaseChunker):
    """简单分片器（基于分隔符）"""
    
    def can_handle(self, file_type: str, content: str) -> bool:
        """可以处理任何类型的文档（作为降级方案）"""
        return True
    
    def get_priority(self) -> int:
        """最低优先级（仅作为降级方案）"""
        return 10
    
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        使用分隔符进行分片
        
        Args:
            content: 文档内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        if not content or not content.strip():
            return []
        
        # 递归分割
        chunks = self._split_text(content, self.config.separators)
        
        # 转换为ChunkResult
        results = []
        for i, chunk_text in enumerate(chunks):
            if not chunk_text.strip():
                continue
            
            chunk = ChunkResult(
                content=chunk_text,
                metadata={
                    'chunker': 'simple',
                    'separator_used': self._detect_separator(chunk_text),
                    **(metadata or {})
                },
                chunk_index=i,
                completeness=True
            )
            
            chunk = self.enrich_metadata(chunk, metadata)
            
            if self.validate_chunk(chunk):
                results.append(chunk)
        
        # 添加重叠
        if self.config.chunk_overlap > 0:
            results = self.add_overlap(results)
        
        return results
    
    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """
        递归分割文本
        
        **核心原则：chunk_size 是硬性上限**
        - 优先使用高优先级分隔符
        - 超过 chunk_size 时，使用下一级分隔符继续分割
        
        Args:
            text: 待分割文本
            separators: 分隔符列表（按优先级排序）
            
        Returns:
            分片列表
        """
        if not separators:
            # 没有分隔符了，强制按大小分割
            return self._split_by_size(text)
        
        separator = separators[0]
        remaining_separators = separators[1:]
        
        # 使用当前分隔符分割
        if separator:
            splits = text.split(separator)
        else:
            # 空分隔符表示按字符分割
            splits = list(text)
        
        # 合并小片段
        chunks = []
        current_chunk = []
        current_size = 0
        
        for split in splits:
            split_size = len(split)
            
            # 情况1: 单个片段就超过 chunk_size
            if split_size > self.config.chunk_size:
                # 先保存当前累积的片段
                if current_chunk:
                    chunk_text = separator.join(current_chunk) if separator else ''.join(current_chunk)
                    chunks.append(chunk_text)
                    current_chunk = []
                    current_size = 0
                
                # 超大片段：使用下一级分隔符继续分割
                if remaining_separators:
                    chunks.extend(self._split_text(split, remaining_separators))
                else:
                    # 没有更多分隔符，强制按大小分割
                    chunks.extend(self._split_by_size(split))
                continue
            
            # 情况2: 添加当前片段后会超过 chunk_size
            if current_size + split_size > self.config.chunk_size and current_chunk:
                # 保存当前块
                chunk_text = separator.join(current_chunk) if separator else ''.join(current_chunk)
                chunks.append(chunk_text)
                
                current_chunk = [split]
                current_size = split_size
            else:
                current_chunk.append(split)
                current_size += split_size + len(separator)
        
        # 处理最后一块
        if current_chunk:
            chunk_text = separator.join(current_chunk) if separator else ''.join(current_chunk)
            
            # 检查最后一块是否超过 chunk_size
            if len(chunk_text) > self.config.chunk_size and remaining_separators:
                chunks.extend(self._split_text(chunk_text, remaining_separators))
            else:
                chunks.append(chunk_text)
        
        return chunks
    
    def _split_by_size(self, text: str) -> List[str]:
        """
        按固定大小强制分割（最后的降级方案）
        
        Args:
            text: 待分割文本
            
        Returns:
            分片列表
        """
        chunks = []
        for i in range(0, len(text), self.config.chunk_size):
            chunks.append(text[i:i + self.config.chunk_size])
        return chunks
    
    def _detect_separator(self, text: str) -> str:
        """
        检测文本中使用的主要分隔符
        
        Args:
            text: 文本内容
            
        Returns:
            主要分隔符
        """
        for sep in self.config.separators:
            if sep and sep in text:
                return sep
        return "none"

