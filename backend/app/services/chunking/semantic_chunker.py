"""
语义分片器
基于句子边界和语义相似度的智能分片
"""

from typing import List, Dict, Any, Optional
import re
from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig
from .registry import register_chunker


@register_chunker("semantic")
class SemanticChunker(BaseChunker):
    """语义分片器"""
    
    def can_handle(self, file_type: str, content: str) -> bool:
        """可以处理任何文本类型"""
        return True
    
    def get_priority(self) -> int:
        """中等优先级"""
        return 60
    
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        基于语义边界分片
        
        Args:
            content: 文档内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        if not content or not content.strip():
            return []
        
        # 分割句子
        sentences = self._split_sentences(content)
        
        if not sentences:
            return self.fallback_chunk(content, metadata)
        
        # 合并句子为分片
        chunks = self._merge_sentences(sentences, metadata)
        
        return chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        智能分割句子
        
        Args:
            text: 文本内容
            
        Returns:
            句子列表
        """
        # 中文句子分割
        chinese_pattern = r'([^。！？\n]+[。！？])'
        # 英文句子分割
        english_pattern = r'([^.!?\n]+[.!?])'
        
        # 先按换行分割段落
        paragraphs = text.split('\n')
        
        sentences = []
        for para in paragraphs:
            if not para.strip():
                continue
            
            # 检测是否为中文为主
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', para))
            total_chars = len(para.strip())
            
            if chinese_chars / max(total_chars, 1) > 0.3:
                # 中文句子分割
                para_sentences = re.findall(chinese_pattern, para)
                if para_sentences:
                    sentences.extend(para_sentences)
                else:
                    sentences.append(para)
            else:
                # 英文句子分割
                para_sentences = re.findall(english_pattern, para)
                if para_sentences:
                    sentences.extend(para_sentences)
                else:
                    # 按句号分割
                    para_sentences = re.split(r'(?<=[.!?])\s+', para)
                    sentences.extend(para_sentences)
        
        return [s.strip() for s in sentences if s.strip()]
    
    def _merge_sentences(
        self,
        sentences: List[str],
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[ChunkResult]:
        """
        合并句子为分片，保持语义连贯性
        
        Args:
            sentences: 句子列表
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for i, sentence in enumerate(sentences):
            sentence_size = len(sentence)
            
            # **核心原则：语义边界优先，chunk_size 只是参考值**
            # 优先在语义边界处分片，即使没有达到 chunk_size
            # 只有在超过 chunk_size 且不是语义边界时，才强制分片
            
            # 检查是否为语义边界
            is_boundary = self._is_semantic_boundary(current_chunk, sentence)
            
            if is_boundary and current_chunk and current_size > self.config.chunk_size * 0.5:
                # 在语义边界处分片（至少达到 chunk_size 的 50%）
                chunk_content = ' '.join(current_chunk)
                
                chunk = ChunkResult(
                    content=chunk_content,
                    metadata={
                        'chunker': 'semantic',
                        'sentence_count': len(current_chunk),
                        'semantic_boundary': True,
                        **(metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=True
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                chunk_index += 1
                
                current_chunk = [sentence]
                current_size = sentence_size
            elif current_size + sentence_size > self.config.chunk_size and current_chunk:
                # 超过 chunk_size，强制分片
                chunk_content = ' '.join(current_chunk)
                
                chunk = ChunkResult(
                    content=chunk_content,
                    metadata={
                        'chunker': 'semantic',
                        'sentence_count': len(current_chunk),
                        'semantic_boundary': False,
                        'forced_split': True,
                        **(metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=False
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                chunk_index += 1
                
                current_chunk = [sentence]
                current_size = sentence_size
            else:
                current_chunk.append(sentence)
                current_size += sentence_size + 1  # +1 for space
        
        # 处理最后一个分片
        if current_chunk:
            chunk_content = ' '.join(current_chunk)
            
            chunk = ChunkResult(
                content=chunk_content,
                metadata={
                    'chunker': 'semantic',
                    'sentence_count': len(current_chunk),
                    **(metadata or {})
                },
                chunk_index=chunk_index,
                completeness=True
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks
    
    def _is_semantic_boundary(self, current_sentences: List[str], next_sentence: str) -> bool:
        """
        判断是否为语义边界
        
        Args:
            current_sentences: 当前分片的句子列表
            next_sentence: 下一个句子
            
        Returns:
            是否为语义边界
        """
        if not current_sentences:
            return True
        
        last_sentence = current_sentences[-1]
        
        # 简单的启发式规则
        # 1. 检查是否有明显的主题转换标记
        topic_markers = [
            '首先', '其次', '然后', '最后', '另外', '此外', '总之', '综上',
            'First', 'Second', 'Third', 'Finally', 'Moreover', 'However', 'In conclusion'
        ]
        
        for marker in topic_markers:
            if next_sentence.startswith(marker):
                return True
        
        # 2. 检查是否有段落标记（换行）
        if '\n' in last_sentence or '\n' in next_sentence:
            return True
        
        # 3. 检查句子长度差异（可能表示主题转换）
        len_ratio = len(next_sentence) / max(len(last_sentence), 1)
        if len_ratio > 2 or len_ratio < 0.5:
            return True
        
        # 默认不是语义边界
        return False

