"""
企业级异步文档处理管道
支持流式处理、批量优化、进度跟踪等企业级特性
"""
import asyncio
import hashlib
import logging
import re
import uuid
from typing import List, Optional, Callable, Dict, Any, Tuple
from dataclasses import dataclass
from langchain_core.documents import Document

from .async_embedding_wrapper import get_embedding_manager, EmbeddingConfig
from .task_queue import TaskQueue, EmbeddingTask, TaskPriority

logger = logging.getLogger(__name__)


@dataclass
class ProcessingConfig:
    """处理配置"""
    # 批处理配置
    chunk_batch_size: int = 50  # 文档块批处理大小
    embedding_batch_size: int = 32  # 嵌入批处理大小
    
    # 并发配置
    max_concurrent_batches: int = 3  # 最大并发批次
    
    # 性能配置
    enable_streaming: bool = True  # 启用流式处理
    progress_update_interval: float = 1.0  # 进度更新间隔(秒)
    
    # 超时配置
    batch_timeout: float = 60.0  # 批处理超时
    total_timeout: float = 600.0  # 总处理超时


class AsyncTextIngestionPipeline:
    """异步文本摄取管道"""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.embedding_manager = None
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.embedding_manager = await get_embedding_manager()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.embedding_manager:
            await self.embedding_manager.cleanup()
    
    async def process_document_async(
        self,
        text: str,
        filename: str,
        kb_settings: Dict[str, Any],
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> int:
        """异步处理文档"""
        
        # 1. 文本切分
        await self._update_progress(progress_callback, 0.1, "开始文本切分...")
        documents = await self._split_text_async(text, filename, kb_settings)
        
        if not documents:
            return 0
        
        # 2. 获取嵌入模型和向量存储
        await self._update_progress(progress_callback, 0.2, "初始化嵌入模型...")
        embedding_model = await self._get_embedding_model(kb_settings)
        vector_store = await self._get_vector_store(kb_settings)
        
        # 3. 流式处理文档
        if self.config.enable_streaming:
            total_processed = await self._process_documents_streaming(
                documents, embedding_model, vector_store, progress_callback
            )
        else:
            total_processed = await self._process_documents_batch(
                documents, embedding_model, vector_store, progress_callback
            )
        
        await self._update_progress(progress_callback, 1.0, f"处理完成，共 {total_processed} 个文档块")
        
        # 4. 更新文档记录状态
        await self._update_document_record(filename, kb_settings, total_processed)
        
        return total_processed
    
    async def _split_text_async(
        self, 
        text: str, 
        filename: str, 
        kb_settings: Dict[str, Any]
    ) -> List[Document]:
        """异步文本切分"""
        # 在线程池中执行文本切分
        loop = asyncio.get_event_loop()
        
        def split_text_sync():
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            
            # 构建文本切分器
            sp = kb_settings.get("split_params", {})
            chunk_size = int(sp.get("chunk_size", 500))
            chunk_overlap = int(sp.get("chunk_overlap", 100))
            separators = sp.get("separators", ["\n\n", "\n", "。", "！", "？", "，", " ", ""])
            
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=list(separators),
            )
            
            # 切分文本
            chunks = splitter.split_text(text)
            
            # 构建文档对象
            documents = []
            for idx, chunk in enumerate(chunks):
                doc = Document(
                    page_content=chunk,
                    metadata={
                        "source": filename,
                        "chunk_index": idx,
                        # 优先使用传入的 document_id，用于后续状态更新与追踪
                        "document_id": kb_settings.get("document_id", filename),
                        "chunk_id": str(uuid.uuid4())
                    }
                )
                documents.append(doc)
            
            logger.info(f"文本切分完成: {len(documents)} 个文档块")
            logger.debug(f"第一个文档类型: {type(documents[0]) if documents else 'N/A'}")
            
            return documents
        
        result = await loop.run_in_executor(None, split_text_sync)
        logger.info(f"_split_text_async 返回: {len(result)} 个文档，类型检查: {type(result[0]) if result else 'N/A'}")
        return result
    
    async def _get_embedding_model(self, kb_settings: Dict[str, Any]):
        """获取嵌入模型"""
        embeddings_config = kb_settings.get("embeddings", {})
        provider = embeddings_config.get("provider", "local")
        
        if provider == "local":
            model_path = embeddings_config.get("local_model_path", "checkpoints/embeddings/all-MiniLM-L6-v2")
            return await self.embedding_manager.get_embedding(
                provider="local",
                model_name_or_path=model_path,
                max_length=512,
                batch_size=8,
                normalize=True
            )
        elif provider == "ark":
            api_key = embeddings_config.get("api_key")
            model = embeddings_config.get("model", "doubao-embedding-large-text-250515")
            return await self.embedding_manager.get_embedding(
                provider="ark",
                api_key=api_key,
                model=model
            )
        else:
            raise ValueError(f"不支持的嵌入提供商: {provider}")
    
    async def _get_vector_store(self, kb_settings: Dict[str, Any]):
        """获取向量存储（使用全局单例管理器）"""
        from .path_utils import (
            build_chroma_persist_dir, get_chroma_collection_name,
            build_faiss_persist_dir, get_faiss_collection_name
        )
        from app.services.embedding_manager import get_embedding_manager
        from app.services.vectorstore_manager import get_vectorstore_manager
        
        # 获取向量数据库类型
        vector_db_type = kb_settings.get("vector_db", "chroma")
        
        # 获取集合名称和持久化目录
        collection_name_raw = kb_settings.get("collection_name", "default")
        
        if vector_db_type == "chroma":
            collection_name = get_chroma_collection_name(collection_name_raw)
            persist_dir = build_chroma_persist_dir(collection_name_raw)
        elif vector_db_type == "faiss":
            collection_name = get_faiss_collection_name(collection_name_raw)
            persist_dir = build_faiss_persist_dir(collection_name_raw)
        else:
            raise ValueError(f"不支持的向量数据库类型: {vector_db_type}")
        
        # 获取嵌入配置
        embeddings_config = kb_settings.get("embeddings", {})
        provider = embeddings_config.get("provider", "local")
        model = embeddings_config.get("model")
        base_url = embeddings_config.get("base_url")
        api_key = embeddings_config.get("api_key")
        local_model_path = embeddings_config.get("local_model_path")
        
        # 获取 Embedding 实例（全局共享）
        embedding_mgr = get_embedding_manager()
        embedding_function = embedding_mgr.get_or_create(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            local_model_path=local_model_path,
            max_length=512,
            batch_size=8,
            normalize=True
        )
        
        # 获取距离度量参数
        search_params = kb_settings.get("search_params", {})
        distance_metric = search_params.get("distance_metric", "cosine")
        
        # 获取 VectorStore 实例（全局共享，已包含文件锁保护）
        vectorstore_mgr = get_vectorstore_manager()
        vector_store = vectorstore_mgr.get_or_create(
            collection_name=collection_name,
            persist_dir=persist_dir,
            embedding_function=embedding_function,
            vector_db_type=vector_db_type,
            distance_metric=distance_metric
        )
        
        # ✅ 直接返回带文件锁的 VectorStore，不需要额外包装
        # vectorstore_mgr 返回的已经是 VectorStoreWithLock，支持 add_documents_async
        return vector_store
    
    async def _process_documents_streaming(
        self,
        documents: List[Document],
        embedding_model,
        vector_store,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> int:
        """流式处理文档"""
        total_docs = len(documents)
        processed_docs = 0
        batch_size = self.config.chunk_batch_size
        
        # 创建信号量控制并发
        semaphore = asyncio.Semaphore(self.config.max_concurrent_batches)
        
        async def process_batch(batch_docs: List[Document], batch_idx: int):
            """处理单个批次"""
            nonlocal processed_docs
            
            async with semaphore:
                try:
                    # 添加类型检查
                    logger.debug(f"批次 {batch_idx}: 接收到 {len(batch_docs)} 个文档")
                    for idx, doc in enumerate(batch_docs):
                        if not isinstance(doc, Document):
                            logger.error(f"批次 {batch_idx}, 文档 {idx} 不是 Document 对象: {type(doc)}, 值: {doc!r}")
                            raise TypeError(f"批次中的文档必须是 Document 对象，但收到 {type(doc).__name__}")
                    
                    # 提取文本进行嵌入
                    texts = [doc.page_content for doc in batch_docs]
                    
                    # 异步嵌入
                    embeddings = await embedding_model.embed_documents_async(texts)
                    
                    # 注意：不要将 embedding 向量添加到 metadata 中，ChromaDB 不支持复杂数据类型
                    # ChromaDB 会自动处理向量存储，我们只需要传递文档即可
                    
                    # 提取 chunk_id 作为文档ID
                    chunk_ids = [doc.metadata.get("chunk_id") for doc in batch_docs]
                    
                    # 异步添加到向量存储
                    logger.debug(f"批次 {batch_idx}: 准备添加 {len(batch_docs)} 个文档到向量存储")
                    await vector_store.add_documents_async(
                        batch_docs,
                        ids=chunk_ids,  # 传递 chunk_id 作为文档ID
                        progress_callback=lambda p: None  # 批次内部进度暂不处理
                    )
                    
                    processed_docs += len(batch_docs)
                    
                    # 更新总体进度
                    progress = 0.2 + (processed_docs / total_docs) * 0.8
                    await self._update_progress(
                        progress_callback, 
                        progress, 
                        f"已处理 {processed_docs}/{total_docs} 个文档块"
                    )
                    
                    logger.info(f"批次 {batch_idx} 处理完成，包含 {len(batch_docs)} 个文档")
                    
                except Exception as e:
                    logger.error(f"批次 {batch_idx} 处理失败: {str(e)}")
                    raise
        
        # 创建批处理任务
        tasks = []
        for i in range(0, total_docs, batch_size):
            batch_docs = documents[i:i + batch_size]
            batch_idx = i // batch_size
            task = asyncio.create_task(process_batch(batch_docs, batch_idx))
            tasks.append(task)
        
        # 等待所有批次完成
        await asyncio.gather(*tasks)
        
        return processed_docs
    
    async def _process_documents_batch(
        self,
        documents: List[Document],
        embedding_model,
        vector_store,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> int:
        """批量处理文档（非流式）"""
        total_docs = len(documents)
        
        # 提取所有文本
        texts = [doc.page_content for doc in documents]
        
        # 批量嵌入
        await self._update_progress(progress_callback, 0.5, "正在生成嵌入向量...")
        embeddings = await embedding_model.embed_documents_async(texts)
        
        # 注意：不要将 embedding 向量添加到 metadata 中，ChromaDB 不支持复杂数据类型
        # ChromaDB 会自动处理向量存储，我们只需要传递文档即可
        
        # 提取 chunk_id 作为文档ID
        chunk_ids = [doc.metadata.get("chunk_id") for doc in documents]
        
        # 批量添加到向量存储
        await self._update_progress(progress_callback, 0.8, "正在保存到向量数据库...")
        await vector_store.add_documents_async(
            documents,
            ids=chunk_ids,  # 传递 chunk_id 作为文档ID
            progress_callback=lambda p: asyncio.create_task(
                self._update_progress(progress_callback, 0.8 + p * 0.2, "保存中...")
            )
        )
        
        return total_docs
    
    async def _update_progress(
        self, 
        callback: Optional[Callable[[float], None]], 
        progress: float, 
        message: str = ""
    ):
        """更新进度"""
        if callback:
            # 检查回调是否是协程函数
            if asyncio.iscoroutinefunction(callback):
                await callback(progress)
            else:
                callback(progress)
        if message:
            logger.info(f"进度 {progress*100:.1f}%: {message}")

    async def _update_document_record(
        self,
        filename: str,
        kb_settings: Dict[str, Any],
        chunk_count: int
    ):
        """更新文档记录状态"""
        try:
            from app.database import get_database
            from app.config import settings
            from app.services.knowledge_base_service import KnowledgeBaseService
            
            # 获取数据库连接
            db = await get_database()
            kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            
            # 从kb_settings中获取文档ID
            document_id = kb_settings.get('document_id')
            
            if not document_id:
                logger.warning(f"缺少文档ID，无法更新文档记录: {filename}")
                return
            
            # 更新文档状态为已完成
            await kb_service.update_document_status(
                doc_id=document_id,
                status="completed",
                chunk_count=chunk_count
            )
            
            logger.info(f"已更新文档记录: {filename}, 分片数: {chunk_count}")
            
        except Exception as e:
            logger.error(f"更新文档记录失败: {str(e)}")
            # 不影响主要处理流程


# 任务处理器
async def process_embedding_task(
    task_data: EmbeddingTask,
    progress_callback: Optional[Callable[[float], None]] = None
) -> Dict[str, Any]:
    """处理嵌入任务"""
    config = ProcessingConfig()
    
    async with AsyncTextIngestionPipeline(config) as pipeline:
        num_docs = await pipeline.process_document_async(
            task_data.text,
            task_data.filename,
            task_data.kb_settings,
            progress_callback
        )
        
        return {
            "chunks": num_docs,
            "filename": task_data.filename,
            "session_id": task_data.session_id
        }
    
    async def _update_document_record(
        self,
        filename: str,
        kb_settings: Dict[str, Any],
        chunk_count: int
    ):
        """更新文档记录状态"""
        try:
            from app.database import get_database
            from app.config import settings
            from app.services.knowledge_base_service import KnowledgeBaseService
            
            # 获取数据库连接
            db = await get_database()
            kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            
            # 从kb_settings中获取文档ID
            document_id = kb_settings.get('document_id')
            
            if not document_id:
                logger.warning(f"缺少文档ID，无法更新文档记录: {filename}")
                return
            
            # 更新文档状态为已完成
            await kb_service.update_document_status(
                doc_id=document_id,
                status="completed",
                chunk_count=chunk_count
            )
            
            logger.info(f"已更新文档记录: {filename}, 分片数: {chunk_count}")
            
        except Exception as e:
            logger.error(f"更新文档记录失败: {str(e)}")
            # 不影响主要处理流程


__all__ = [
    "ProcessingConfig",
    "AsyncTextIngestionPipeline",
    "process_embedding_task"
]
