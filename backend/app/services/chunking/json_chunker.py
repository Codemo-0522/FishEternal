"""
JSON分片器
保持JSON结构完整性的智能分片
"""

from typing import List, Dict, Any, Optional
import json
import logging
from .base_chunker import BaseChunker, ChunkResult, ChunkingConfig
from .registry import register_chunker

logger = logging.getLogger(__name__)


@register_chunker("json")
class JSONChunker(BaseChunker):
    """JSON专用分片器"""
    
    def can_handle(self, file_type: str, content: str) -> bool:
        """判断是否为JSON文件"""
        if file_type.lower() == 'json':
            try:
                json.loads(content)
                return True
            except json.JSONDecodeError:
                return False
        return False
    
    def get_priority(self) -> int:
        """高优先级（专用分片器）"""
        return 90
    
    def chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        智能分片JSON文档
        
        Args:
            content: JSON内容
            metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            return self.fallback_chunk(content, metadata)
        
        logger.info(f"🔪 JSONChunker 开始分片: chunk_size={self.config.chunk_size}, 数据类型={type(data).__name__}")
        if isinstance(data, list):
            logger.info(f"  - JSON数组，元素数量: {len(data)}")
        elif isinstance(data, dict):
            logger.info(f"  - JSON对象，字段数量: {len(data)}")
        
        chunks = []
        
        if isinstance(data, list):
            chunks = self._chunk_array(data, metadata)
        elif isinstance(data, dict):
            chunks = self._chunk_object(data, metadata)
        else:
            # 基本类型，直接返回
            chunk = ChunkResult(
                content=json.dumps(data, ensure_ascii=False, indent=2),
                metadata={
                    'chunker': 'json',
                    'json_type': type(data).__name__,
                    **(metadata or {})
                },
                chunk_index=0,
                completeness=True
            )
            chunks = [self.enrich_metadata(chunk, metadata)]
        
        logger.info(f"✅ JSONChunker 分片完成: 生成 {len(chunks)} 个分片")
        
        return chunks
    
    def _chunk_array(self, array: list, doc_metadata: Optional[Dict[str, Any]] = None) -> List[ChunkResult]:
        """
        分片JSON数组，保持元素完整性
        
        **核心原则：chunk_size 是硬性上限**
        - 对象 < chunk_size：保持对象完整性（优先级第一）
        - 对象 > chunk_size：在合适的边界截断（字段边界）
        
        Args:
            array: JSON数组
            doc_metadata: 文档元数据
            
        Returns:
            分片结果列表
        """
        chunks = []
        chunk_index = 0
        
        for array_index, item in enumerate(array):
            item_str = json.dumps(item, ensure_ascii=False, indent=2)
            item_size = len(item_str)
            
            # 情况1: 元素在 chunk_size 范围内，保持完整性
            if item_size <= self.config.chunk_size:
                chunk = ChunkResult(
                    content=item_str,
                    metadata={
                        'chunker': 'json',
                        'json_type': 'array_item',
                        'array_index': array_index,
                        'oversized': False,
                        **(doc_metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=True
                )
                chunks.append(self.enrich_metadata(chunk, doc_metadata))
                chunk_index += 1
            
            # 情况2: 元素超过 chunk_size，需要在字段边界截断
            else:
                logger.info(f"📦 数组元素超过 chunk_size ({item_size} > {self.config.chunk_size})，在字段边界截断")
                
                if isinstance(item, dict):
                    # 对象类型：按字段分片
                    sub_chunks = self._chunk_large_object(item, doc_metadata, chunk_index, array_index)
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                elif isinstance(item, list):
                    # 嵌套数组：递归处理
                    sub_chunks = self._chunk_array(item, doc_metadata)
                    for sub_chunk in sub_chunks:
                        sub_chunk.metadata['parent_array_index'] = array_index
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                elif isinstance(item, str):
                    # 字符串类型：按句子边界分片
                    sub_chunks = self._chunk_large_string(item, doc_metadata, chunk_index, array_index)
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                else:
                    # 其他基本类型（数字、布尔等）：直接保存（通常不会很大）
                    chunk = ChunkResult(
                        content=item_str,
                        metadata={
                            'chunker': 'json',
                            'json_type': 'array_item',
                            'array_index': array_index,
                            'oversized': True,
                            **(doc_metadata or {})
                        },
                        chunk_index=chunk_index,
                        completeness=True
                    )
                    chunks.append(self.enrich_metadata(chunk, doc_metadata))
                    chunk_index += 1
        
        logger.info(f"✅ 数组分片完成: {len(array)} 个元素 → {len(chunks)} 个分片")
        return chunks
    
    def _chunk_object(
        self,
        obj: dict,
        doc_metadata: Optional[Dict[str, Any]] = None,
        start_index: int = 0
    ) -> List[ChunkResult]:
        """
        分片JSON对象，保持键值对完整性
        
        Args:
            obj: JSON对象
            doc_metadata: 文档元数据
            start_index: 起始索引
            
        Returns:
            分片结果列表
        """
        chunks = []
        current_obj = {}
        current_size = 0
        chunk_index = start_index
        
        for key, value in obj.items():
            kv_str = json.dumps({key: value}, ensure_ascii=False, indent=2)
            kv_size = len(kv_str)
            
            # 单个键值对就超过chunk_size
            if kv_size > self.config.chunk_size:
                # 先保存当前对象
                if current_obj:
                    chunk = self._create_object_chunk(current_obj, chunk_index, doc_metadata)
                    chunks.append(chunk)
                    chunk_index += 1
                    current_obj = {}
                    current_size = 0
                
                # 大键值对特殊处理
                if isinstance(value, dict):
                    # 嵌套对象，递归处理
                    sub_chunks = self._chunk_object(value, doc_metadata, chunk_index)
                    # 为子分片添加父键信息
                    for sub_chunk in sub_chunks:
                        sub_chunk.metadata['parent_key'] = key
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                elif isinstance(value, list):
                    # 嵌套数组，递归处理
                    sub_chunks = self._chunk_array(value, doc_metadata)
                    for sub_chunk in sub_chunks:
                        sub_chunk.metadata['parent_key'] = key
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                else:
                    # 基本类型但很大，单独保存
                    chunk = ChunkResult(
                        content=kv_str,
                        metadata={
                            'chunker': 'json',
                            'json_type': 'object_field',
                            'field_key': key,
                            'oversized': True,
                            **(doc_metadata or {})
                        },
                        chunk_index=chunk_index,
                        completeness=False
                    )
                    chunks.append(self.enrich_metadata(chunk, doc_metadata))
                    chunk_index += 1
                
                continue
            
            # 检查是否超过chunk_size
            if current_size + kv_size > self.config.chunk_size and current_obj:
                # 保存当前对象
                chunk = self._create_object_chunk(current_obj, chunk_index, doc_metadata)
                chunks.append(chunk)
                chunk_index += 1
                
                current_obj = {key: value}
                current_size = kv_size
            else:
                current_obj[key] = value
                current_size += kv_size
        
        # 处理最后一个对象
        if current_obj:
            chunk = self._create_object_chunk(current_obj, chunk_index, doc_metadata)
            chunks.append(chunk)
        
        return chunks
    
    def _create_array_chunk(
        self,
        items: list,
        chunk_index: int,
        doc_metadata: Optional[Dict[str, Any]] = None
    ) -> ChunkResult:
        """创建数组分片"""
        content = json.dumps(items, ensure_ascii=False, indent=2)
        
        chunk = ChunkResult(
            content=content,
            metadata={
                'chunker': 'json',
                'json_type': 'array',
                'item_count': len(items),
                **(doc_metadata or {})
            },
            chunk_index=chunk_index,
            completeness=True
        )
        
        return self.enrich_metadata(chunk, doc_metadata)
    
    def _create_object_chunk(
        self,
        obj: dict,
        chunk_index: int,
        doc_metadata: Optional[Dict[str, Any]] = None
    ) -> ChunkResult:
        """创建对象分片"""
        content = json.dumps(obj, ensure_ascii=False, indent=2)
        
        chunk = ChunkResult(
            content=content,
            metadata={
                'chunker': 'json',
                'json_type': 'object',
                'keys': list(obj.keys()),
                'key_count': len(obj),
                **(doc_metadata or {})
            },
            chunk_index=chunk_index,
            completeness=True
        )
        
        return self.enrich_metadata(chunk, doc_metadata)
    
    def _chunk_large_object(
        self,
        obj: dict,
        doc_metadata: Optional[Dict[str, Any]] = None,
        start_index: int = 0,
        array_index: Optional[int] = None
    ) -> List[ChunkResult]:
        """
        分片超大JSON对象，在字段边界截断
        
        策略：
        1. 按字段逐个添加到当前分片
        2. 当累积大小接近 chunk_size 时，创建新分片
        3. 保持字段完整性（不拆分单个字段）
        
        Args:
            obj: 超大JSON对象
            doc_metadata: 文档元数据
            start_index: 起始分片索引
            array_index: 如果是数组元素，记录其在数组中的索引
            
        Returns:
            分片结果列表
        """
        chunks = []
        current_obj = {}
        current_size = 2  # 起始大小："{}"
        chunk_index = start_index
        total_fields = len(obj)
        
        logger.info(f"  🔪 开始分片超大对象: {total_fields} 个字段")
        
        for field_index, (key, value) in enumerate(obj.items()):
            # 计算单个字段的大小
            field_str = json.dumps({key: value}, ensure_ascii=False, indent=2)
            field_size = len(field_str)
            
            # 检查单个字段是否超过 chunk_size
            if field_size > self.config.chunk_size:
                # 先保存当前累积的对象
                if current_obj:
                    chunk = ChunkResult(
                        content=json.dumps(current_obj, ensure_ascii=False, indent=2),
                        metadata={
                            'chunker': 'json',
                            'json_type': 'object_partial',
                            'keys': list(current_obj.keys()),
                            'array_index': array_index,
                            'part_of_large_object': True,
                            'total_fields': total_fields,
                            **(doc_metadata or {})
                        },
                        chunk_index=chunk_index,
                        completeness=False
                    )
                    chunks.append(self.enrich_metadata(chunk, doc_metadata))
                    chunk_index += 1
                    current_obj = {}
                    current_size = 2
                
                # 处理超大字段
                logger.info(f"    ⚠️ 字段 '{key}' 超过 chunk_size ({field_size} > {self.config.chunk_size})")
                
                if isinstance(value, dict):
                    # 嵌套对象：递归分片
                    sub_chunks = self._chunk_large_object(value, doc_metadata, chunk_index, array_index)
                    for sub_chunk in sub_chunks:
                        sub_chunk.metadata['parent_field'] = key
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                elif isinstance(value, list):
                    # 嵌套数组：递归分片
                    sub_chunks = self._chunk_array(value, doc_metadata)
                    for sub_chunk in sub_chunks:
                        sub_chunk.metadata['parent_field'] = key
                        sub_chunk.metadata['array_index'] = array_index
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                elif isinstance(value, str):
                    # 超大字符串：按句子边界分片
                    sub_chunks = self._chunk_large_string(value, doc_metadata, chunk_index, array_index, key)
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                else:
                    # 其他类型（通常不会很大）：单独保存
                    chunk = ChunkResult(
                        content=field_str,
                        metadata={
                            'chunker': 'json',
                            'json_type': 'large_field',
                            'field_key': key,
                            'array_index': array_index,
                            **(doc_metadata or {})
                        },
                        chunk_index=chunk_index,
                        completeness=False
                    )
                    chunks.append(self.enrich_metadata(chunk, doc_metadata))
                    chunk_index += 1
                
                continue
            
            # 检查添加当前字段后是否会超过 chunk_size
            estimated_size = current_size + field_size + 2  # +2 for comma and newline
            
            if estimated_size > self.config.chunk_size and current_obj:
                # 保存当前对象，开始新分片
                chunk = ChunkResult(
                    content=json.dumps(current_obj, ensure_ascii=False, indent=2),
                    metadata={
                        'chunker': 'json',
                        'json_type': 'object_partial',
                        'keys': list(current_obj.keys()),
                        'array_index': array_index,
                        'part_of_large_object': True,
                        'total_fields': total_fields,
                        **(doc_metadata or {})
                    },
                    chunk_index=chunk_index,
                    completeness=False
                )
                chunks.append(self.enrich_metadata(chunk, doc_metadata))
                chunk_index += 1
                
                # 开始新分片
                current_obj = {key: value}
                current_size = field_size + 2
            else:
                # 添加到当前对象
                current_obj[key] = value
                current_size = estimated_size
        
        # 保存最后一个分片
        if current_obj:
            chunk = ChunkResult(
                content=json.dumps(current_obj, ensure_ascii=False, indent=2),
                metadata={
                    'chunker': 'json',
                    'json_type': 'object_partial',
                    'keys': list(current_obj.keys()),
                    'array_index': array_index,
                    'part_of_large_object': True,
                    'total_fields': total_fields,
                    **(doc_metadata or {})
                },
                chunk_index=chunk_index,
                completeness=False
            )
            chunks.append(self.enrich_metadata(chunk, doc_metadata))
        
        logger.info(f"  ✅ 超大对象分片完成: {total_fields} 个字段 → {len(chunks)} 个分片")
        return chunks
    
    def _chunk_large_string(
        self,
        text: str,
        doc_metadata: Optional[Dict[str, Any]] = None,
        start_index: int = 0,
        array_index: Optional[int] = None,
        field_key: Optional[str] = None
    ) -> List[ChunkResult]:
        """
        分片超大字符串，在句子边界截断
        
        Args:
            text: 超大字符串
            doc_metadata: 文档元数据
            start_index: 起始分片索引
            array_index: 数组索引（如果适用）
            field_key: 字段名（如果适用）
            
        Returns:
            分片结果列表
        """
        chunks = []
        chunk_index = start_index
        
        # 使用配置的分隔符进行分片
        separators = self.config.separators
        
        # 简单实现：按 chunk_size 切分，尽量在句子边界
        current_pos = 0
        text_len = len(text)
        
        logger.info(f"  🔪 开始分片超大字符串: 长度={text_len}")
        
        while current_pos < text_len:
            # 计算本次分片的结束位置
            end_pos = min(current_pos + self.config.chunk_size, text_len)
            
            # 如果不是最后一段，尝试在句子边界截断
            if end_pos < text_len:
                # 在 chunk_size 范围内查找最后一个句子分隔符
                best_split = end_pos
                for sep in separators:
                    # 在当前位置往前查找分隔符
                    last_sep = text.rfind(sep, current_pos, end_pos)
                    if last_sep > current_pos:
                        best_split = last_sep + len(sep)
                        break
                end_pos = best_split
            
            # 提取分片内容
            chunk_text = text[current_pos:end_pos]
            
            # 创建分片
            chunk = ChunkResult(
                content=json.dumps(chunk_text, ensure_ascii=False),
                metadata={
                    'chunker': 'json',
                    'json_type': 'string_partial',
                    'field_key': field_key,
                    'array_index': array_index,
                    'string_part': f"{chunk_index - start_index + 1}",
                    'char_range': f"{current_pos}-{end_pos}",
                    **(doc_metadata or {})
                },
                chunk_index=chunk_index,
                completeness=False
            )
            chunks.append(self.enrich_metadata(chunk, doc_metadata))
            
            current_pos = end_pos
            chunk_index += 1
        
        logger.info(f"  ✅ 超大字符串分片完成: {text_len} 字符 → {len(chunks)} 个分片")
        return chunks

