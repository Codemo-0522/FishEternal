"""
智能分片系统集成模块
将新的智能分片系统集成到现有的文档处理流程中
"""

import logging
from typing import List, Dict, Any, Optional
import asyncio

from .chunking import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkerFactory
)
from .chunking.async_processor import (
    AsyncChunkingProcessor,
    ChunkingTask,
    ExecutorType
)

logger = logging.getLogger(__name__)


class ChunkingIntegration:
    """智能分片集成服务"""
    
    def __init__(self):
        """初始化集成服务"""
        self.processor = None
    
    def _get_processor(self) -> AsyncChunkingProcessor:
        """获取或创建异步处理器"""
        if self.processor is None:
            self.processor = AsyncChunkingProcessor(
                max_workers=4,
                executor_type=ExecutorType.THREAD
            )
        return self.processor
    
    async def chunk_text_smart(
        self,
        text: str,
        filename: str,
        kb_settings: Dict[str, Any]
    ) -> List[str]:
        """
        智能分片文本（兼容现有接口）
        
        Args:
            text: 文本内容
            filename: 文件名（用于检测文件类型）
            kb_settings: 知识库配置
            
        Returns:
            分片文本列表
        """
        try:
            # 从kb_settings中提取分片配置
            config = self._build_config_from_kb_settings(kb_settings)
            
            # 检测文件类型
            file_type = self._detect_file_type(filename)
            
            # 使用异步处理器进行分片
            loop = asyncio.get_event_loop()
            
            def _chunk():
                # 创建分片器
                chunker = ChunkerFactory.create_chunker(
                    file_type=file_type,
                    content=text,
                    config=config
                )
                
                # 执行分片
                chunks = chunker.chunk(text, metadata={'filename': filename})
                
                # 返回分片文本列表
                return [chunk.content for chunk in chunks]
            
            # 在线程池中执行（避免阻塞）
            chunks = await loop.run_in_executor(None, _chunk)
            
            logger.info(f"✅ 智能分片完成: {filename}, 生成 {len(chunks)} 个分片")
            
            return chunks
            
        except Exception as e:
            logger.error(f"智能分片失败: {e}, 降级到传统分片", exc_info=True)
            # 降级到传统分片方法
            return await self._fallback_chunk(text, kb_settings)
    
    def _build_config_from_kb_settings(self, kb_settings: Dict[str, Any]) -> ChunkingConfig:
        """
        从知识库配置构建分片配置
        
        Args:
            kb_settings: 知识库配置
            
        Returns:
            分片配置对象
        """
        sp = kb_settings.get("split_params", {})
        
        # 提取分片策略（如果有）
        strategy_str = sp.get("chunking_strategy", sp.get("strategy", "document_aware"))
        try:
            strategy = ChunkingStrategy(strategy_str)
        except ValueError:
            logger.warning(f"Unknown chunking strategy: {strategy_str}, using document_aware")
            strategy = ChunkingStrategy.DOCUMENT_AWARE
        
        # 构建配置
        chunk_size = int(sp.get("chunk_size", 1024))
        chunk_overlap = int(sp.get("chunk_overlap", 100))
        
        config = ChunkingConfig(
            strategy=strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=sp.get("separators", ["\n\n", "\n", "。", "！", "？", "，", " ", ""]),
            use_sentence_boundary=sp.get("use_sentence_boundary", True),
            semantic_threshold=float(sp.get("semantic_threshold", 0.5)),
            preserve_structure=sp.get("preserve_structure", True),
            ast_parsing=sp.get("ast_parsing", True),
            enable_hierarchy=sp.get("enable_hierarchy", False),
            parent_chunk_size=int(sp.get("parent_chunk_size", 4096)),
            max_workers=int(sp.get("max_workers", 4)),
            batch_size=int(sp.get("batch_size", 100))
        )
        
        logger.info(f"📋 分片配置: strategy={strategy}, chunk_size={chunk_size}, chunk_overlap={chunk_overlap}")
        
        return config
    
    def _detect_file_type(self, filename: str) -> str:
        """
        从文件名检测文件类型
        
        Args:
            filename: 文件名
            
        Returns:
            文件类型（扩展名）
        """
        if '.' not in filename:
            return 'txt'
        
        return filename.rsplit('.', 1)[-1].lower()
    
    async def _fallback_chunk(self, text: str, kb_settings: Dict[str, Any]) -> List[str]:
        """
        降级分片方法（使用传统的RecursiveCharacterTextSplitter）
        
        Args:
            text: 文本内容
            kb_settings: 知识库配置
            
        Returns:
            分片文本列表
        """
        loop = asyncio.get_event_loop()
        
        def _chunk():
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            
            sp = kb_settings.get("split_params", {})
            chunk_size = int(sp.get("chunk_size", 1024))
            chunk_overlap = int(sp.get("chunk_overlap", 100))
            separators = sp.get("separators", ["\n\n", "\n", "。", "！", "？", "，", " ", ""])
            
            # 确保分隔符列表末尾有空字符串
            if isinstance(separators, list):
                separators = list(separators)
                if "" not in separators:
                    separators.append("")
            else:
                separators = ["\n\n", "\n", "。", "！", "？", "，", " ", ""]
            
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
                length_function=len
            )
            
            return splitter.split_text(text)
        
        return await loop.run_in_executor(None, _chunk)
    
    async def batch_chunk_documents(
        self,
        documents: List[Dict[str, Any]],
        kb_settings: Dict[str, Any],
        progress_callback: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        批量分片多个文档（并发处理）
        
        Args:
            documents: 文档列表 [{"content": str, "filename": str, "doc_id": str}, ...]
            kb_settings: 知识库配置
            progress_callback: 进度回调函数 (completed, total)
            
        Returns:
            分片结果列表 [{"doc_id": str, "chunks": List[str], "success": bool}, ...]
        """
        if not documents:
            return []
        
        # 构建配置
        config = self._build_config_from_kb_settings(kb_settings)
        
        # 创建任务列表
        tasks = []
        for doc in documents:
            file_type = self._detect_file_type(doc['filename'])
            task = ChunkingTask(
                task_id=doc['doc_id'],
                content=doc['content'],
                file_type=file_type,
                config=config,
                metadata={'filename': doc['filename'], 'doc_id': doc['doc_id']}
            )
            tasks.append(task)
        
        # 使用异步处理器批量处理
        processor = self._get_processor()
        
        def _progress_callback(completed, total):
            if progress_callback:
                progress_callback(completed, total)
        
        results = processor.process_batch(tasks, _progress_callback)
        
        # 转换结果格式
        output = []
        for result in results:
            output.append({
                'doc_id': result.task_id,
                'chunks': [chunk.content for chunk in result.chunks] if result.success else [],
                'success': result.success,
                'error': result.error,
                'chunk_count': len(result.chunks) if result.success else 0,
                'duration': result.duration
            })
        
        return output
    
    def shutdown(self):
        """关闭处理器"""
        if self.processor:
            self.processor.shutdown()
            self.processor = None


# 全局单例
_integration_instance: Optional[ChunkingIntegration] = None


def get_chunking_integration() -> ChunkingIntegration:
    """
    获取全局智能分片集成服务实例
    
    Returns:
        ChunkingIntegration实例
    """
    global _integration_instance
    
    if _integration_instance is None:
        _integration_instance = ChunkingIntegration()
    
    return _integration_instance

