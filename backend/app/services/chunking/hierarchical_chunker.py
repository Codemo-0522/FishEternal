"""
层级分片器
支持父子分片关系，提供多层次的上下文
"""

from typing import List, Dict, Any, Optional
import uuid
from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig
from .factory import ChunkerFactory


class HierarchicalChunker(BaseChunker):
    """层级分片器"""
    
    def __init__(self, file_type: str, content: str, config: ChunkingConfig):
        super().__init__(config)
        self.file_type = file_type
        self.content = content
    
    def can_handle(self, file_type: str, content: str) -> bool:
        """可以处理任何类型"""
        return True
    
    def get_priority(self) -> int:
        """低优先级（特殊用途）"""
        return 30
    
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        创建层级分片
        
        Args:
            content: 文档内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表（包含父子关系）
        """
        if not content or not content.strip():
            return []
        
        # 第一层：创建父分片（大块）
        parent_config = ChunkingConfig(
            strategy=self.config.strategy,
            chunk_size=self.config.parent_chunk_size,
            chunk_overlap=self.config.chunk_overlap * 2,  # 父分片使用更大的重叠
            separators=self.config.separators,
            preserve_structure=self.config.preserve_structure,
            ast_parsing=self.config.ast_parsing
        )
        
        # 使用文档感知分片器创建父分片
        parent_chunker = ChunkerFactory.create_chunker(
            self.file_type,
            content,
            parent_config
        )
        
        parent_chunks = parent_chunker.chunk(content, metadata)
        
        # 第二层：为每个父分片创建子分片
        all_chunks = []
        
        for parent_chunk in parent_chunks:
            # 生成父分片ID
            parent_id = str(uuid.uuid4())
            
            # 添加父分片（标记为父级）
            parent_chunk.metadata['is_parent'] = True
            parent_chunk.metadata['parent_id'] = parent_id
            parent_chunk.metadata['hierarchy_level'] = 1
            all_chunks.append(parent_chunk)
            
            # 创建子分片
            child_config = ChunkingConfig(
                strategy=self.config.strategy,
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                separators=self.config.separators,
                preserve_structure=self.config.preserve_structure,
                ast_parsing=self.config.ast_parsing
            )
            
            child_chunker = ChunkerFactory.create_chunker(
                self.file_type,
                parent_chunk.content,
                child_config
            )
            
            child_chunks = child_chunker.chunk(parent_chunk.content, metadata)
            
            # 为子分片添加父级信息
            for child_chunk in child_chunks:
                child_chunk.parent_chunk_id = parent_id
                child_chunk.metadata['is_parent'] = False
                child_chunk.metadata['parent_id'] = parent_id
                child_chunk.metadata['hierarchy_level'] = 2
                all_chunks.append(child_chunk)
        
        return all_chunks

