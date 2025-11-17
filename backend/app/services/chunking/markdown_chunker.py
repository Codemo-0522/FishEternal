"""
Markdown分片器
基于标题层级的智能分片
"""

from typing import List, Dict, Any, Optional
import re
from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig
from .registry import register_chunker


@register_chunker("markdown")
class MarkdownChunker(BaseChunker):
    """Markdown专用分片器"""
    
    def can_handle(self, file_type: str, content: str) -> bool:
        """判断是否为Markdown文件"""
        if file_type.lower() in ['md', 'markdown']:
            return True
        # 检测内容是否包含Markdown特征
        if re.search(r'^#{1,6}\s+', content, re.MULTILINE):
            return True
        return False
    
    def get_priority(self) -> int:
        """高优先级（专用分片器）"""
        return 85
    
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        基于标题层级分片Markdown文档
        
        Args:
            content: Markdown内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        if not content or not content.strip():
            return []
        
        # 按标题分割
        sections = self._split_by_headers(content)
        
        if not sections:
            # 没有标题，降级到段落分割
            return self._split_by_paragraphs(content, metadata)
        
        chunks = []
        chunk_index = 0
        
        for section in sections:
            section_content = section['content']
            section_size = len(section_content)
            
            # **核心原则：每个章节是一个完整的分片单位，chunk_size 只是保底值**
            # 只有当单个章节本身超过 chunk_size 时，才对其进行二次切分
            if section_size > self.config.chunk_size:
                # 章节超过 chunk_size，进一步分割
                sub_chunks = self._split_large_section(section, metadata, chunk_index)
                chunks.extend(sub_chunks)
                chunk_index += len(sub_chunks)
            else:
                # 章节大小合适，作为一个完整分片
                chunk = ChunkResult(
                    content=section_content,
                    metadata={
                        'chunker': 'markdown',
                        'header_level': section['level'],
                        'header_text': section['header'],
                        'has_code_blocks': section.get('has_code', False),
                        **(metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=True
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                chunk_index += 1
        
        return chunks
    
    def _split_by_headers(self, content: str) -> List[Dict[str, Any]]:
        """
        按Markdown标题分割
        
        Args:
            content: Markdown内容
            
        Returns:
            章节列表
        """
        # 匹配Markdown标题 (# 到 ######)
        header_pattern = r'^(#{1,6})\s+(.+)$'
        
        lines = content.split('\n')
        sections = []
        current_section = None
        
        for line in lines:
            match = re.match(header_pattern, line)
            
            if match:
                # 保存上一个章节
                if current_section:
                    sections.append(current_section)
                
                # 开始新章节
                level = len(match.group(1))
                header_text = match.group(2).strip()
                
                current_section = {
                    'level': level,
                    'header': header_text,
                    'content': line + '\n',
                    'has_code': False
                }
            else:
                if current_section:
                    current_section['content'] += line + '\n'
                    
                    # 检测代码块
                    if line.strip().startswith('```'):
                        current_section['has_code'] = True
                else:
                    # 文档开头没有标题的内容
                    if not sections or sections[0]['level'] != 0:
                        sections.insert(0, {
                            'level': 0,
                            'header': 'Introduction',
                            'content': line + '\n',
                            'has_code': False
                        })
                        current_section = sections[0]
                    else:
                        sections[0]['content'] += line + '\n'
        
        # 保存最后一个章节
        if current_section:
            sections.append(current_section)
        
        return sections
    
    def _split_large_section(
        self,
        section: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        start_index: int = 0
    ) -> List[ChunkResult]:
        """
        分割大章节，在段落边界截断
        
        **核心原则：chunk_size 是硬性上限**
        - 段落 < chunk_size：保持段落完整性
        - 段落 > chunk_size：在句子边界截断
        
        Args:
            section: 章节信息
            metadata: 文档元数据
            start_index: 起始索引
            
        Returns:
            分片结果列表
        """
        content = section['content']
        
        # 尝试按段落分割
        paragraphs = re.split(r'\n\s*\n', content)
        
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = start_index
        
        for para in paragraphs:
            para_size = len(para) + 2  # +2 for \n\n
            
            # 情况1: 单个段落就超过 chunk_size
            if para_size > self.config.chunk_size:
                # 先保存当前累积的段落
                if current_chunk:
                    chunk_content = '\n\n'.join(current_chunk)
                    chunk = ChunkResult(
                        content=chunk_content,
                        metadata={
                            'chunker': 'markdown',
                            'header_level': section['level'],
                            'header_text': section['header'],
                            'partial': True,
                            **(metadata or {})
                        },
                        chunk_index=chunk_index,
                        completeness=False
                    )
                    chunks.append(self.enrich_metadata(chunk, metadata))
                    chunk_index += 1
                    current_chunk = []
                    current_size = 0
                
                # 超大段落：在句子边界截断
                sub_chunks = self._split_large_paragraph(para, section, metadata, chunk_index)
                chunks.extend(sub_chunks)
                chunk_index += len(sub_chunks)
                continue
            
            # 情况2: 添加当前段落后会超过 chunk_size
            if current_size + para_size > self.config.chunk_size and current_chunk:
                chunk_content = '\n\n'.join(current_chunk)
                
                chunk = ChunkResult(
                    content=chunk_content,
                    metadata={
                        'chunker': 'markdown',
                        'header_level': section['level'],
                        'header_text': section['header'],
                        'partial': True,
                        **(metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=False
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                chunk_index += 1
                
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size
        
        # 保存最后一个分片
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            
            chunk = ChunkResult(
                content=chunk_content,
                metadata={
                    'chunker': 'markdown',
                    'header_level': section['level'],
                    'header_text': section['header'],
                    'partial': True,
                    **(metadata or {})
                },
                chunk_index=chunk_index,
                completeness=False
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks
    
    def _split_large_paragraph(
        self,
        paragraph: str,
        section: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        start_index: int = 0
    ) -> List[ChunkResult]:
        """
        分割超大段落，在句子边界截断
        
        Args:
            paragraph: 超大段落
            section: 章节信息
            metadata: 文档元数据
            start_index: 起始索引
            
        Returns:
            分片结果列表
        """
        # 尝试按句子分割
        # 中文句子分割
        chinese_pattern = r'([^。！？\n]+[。！？])'
        # 英文句子分割
        english_pattern = r'([^.!?\n]+[.!?])'
        
        # 检测是否为中文为主
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', paragraph))
        total_chars = len(paragraph.strip())
        
        if chinese_chars / max(total_chars, 1) > 0.3:
            sentences = re.findall(chinese_pattern, paragraph)
        else:
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
        
        if not sentences:
            # 无法按句子分割，强制按 chunk_size 截断
            sentences = [paragraph[i:i+self.config.chunk_size] 
                        for i in range(0, len(paragraph), self.config.chunk_size)]
        
        # 合并句子为分片
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = start_index
        
        for sentence in sentences:
            sentence_size = len(sentence) + 1  # +1 for space
            
            if current_size + sentence_size > self.config.chunk_size and current_chunk:
                chunk_content = ' '.join(current_chunk)
                
                chunk = ChunkResult(
                    content=chunk_content,
                    metadata={
                        'chunker': 'markdown',
                        'header_level': section['level'],
                        'header_text': section['header'],
                        'partial': True,
                        'split_from': 'large_paragraph',
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
                current_size += sentence_size
        
        # 保存最后一个分片
        if current_chunk:
            chunk_content = ' '.join(current_chunk)
            
            chunk = ChunkResult(
                content=chunk_content,
                metadata={
                    'chunker': 'markdown',
                    'header_level': section['level'],
                    'header_text': section['header'],
                    'partial': True,
                    'split_from': 'large_paragraph',
                    **(metadata or {})
                },
                chunk_index=chunk_index,
                completeness=False
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks
    
    def _split_by_paragraphs(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[ChunkResult]:
        """
        按段落分割（降级方案）
        
        Args:
            content: Markdown内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        paragraphs = re.split(r'\n\s*\n', content)
        
        chunks = []
        current_chunk = []
        current_size = 0
        chunk_index = 0
        
        for para in paragraphs:
            para_size = len(para) + 2
            
            if current_size + para_size > self.config.chunk_size and current_chunk:
                chunk_content = '\n\n'.join(current_chunk)
                
                chunk = ChunkResult(
                    content=chunk_content,
                    metadata={
                        'chunker': 'markdown',
                        'method': 'paragraphs',
                        **(metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=True
                )
                chunks.append(self.enrich_metadata(chunk, metadata))
                chunk_index += 1
                
                current_chunk = [para]
                current_size = para_size
            else:
                current_chunk.append(para)
                current_size += para_size
        
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            
            chunk = ChunkResult(
                content=chunk_content,
                metadata={
                    'chunker': 'markdown',
                    'method': 'paragraphs',
                    **(metadata or {})
                },
                chunk_index=chunk_index,
                completeness=True
            )
            chunks.append(self.enrich_metadata(chunk, metadata))
        
        return chunks

