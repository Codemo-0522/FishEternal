"""
文档处理服务 - 异步非阻塞版本

特性：
1. 完全异步处理，不阻塞主服务
2. 使用后台任务队列
3. 用户操作完全隔离
4. 支持并发文档处理
5. 自动错误恢复
"""
import logging
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
from bson import ObjectId

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..config import settings
from .async_task_processor import get_task_processor, TaskPriority

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """
    文档处理服务
    
    负责文档的解析、分块、向量化，全程异步非阻塞
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """
        初始化文档处理服务
        
        Args:
            db: MongoDB 数据库实例
        """
        self.db = db
        self.task_processor = get_task_processor()
        
        # 限流器（防止单个用户提交过多任务）
        self.user_rate_limits: Dict[str, asyncio.Semaphore] = {}
        self.max_user_concurrent_tasks = 5  # 每个用户最多同时处理5个文档
    
    async def submit_document_processing(
        self,
        kb_id: str,
        doc_id: str,
        user_id: str,
        file_path: str,
        filename: str,
        kb_settings: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> str:
        """
        提交文档处理任务（异步、非阻塞）
        
        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            user_id: 用户ID
            file_path: 文件路径
            filename: 文件名
            kb_settings: 知识库配置
            priority: 任务优先级
            
        Returns:
            任务ID
            
        Raises:
            RuntimeError: 提交失败
        """
        try:
            # 用户级别的限流（不在这里做限制检查，而是在实际处理时通过 semaphore 排队）
            if user_id not in self.user_rate_limits:
                self.user_rate_limits[user_id] = asyncio.Semaphore(
                    self.max_user_concurrent_tasks
                )
            
            # 提交任务到异步队列
            # 注意：使用包装函数避免 user_id 参数名冲突
            async def _handler_wrapper(**kwargs):
                return await self._process_document_async(
                    kb_id=kwargs['kb_id'],
                    doc_id=kwargs['doc_id'],
                    user_id=kwargs['task_user_id'],  # 使用重命名后的参数
                    file_path=kwargs['file_path'],
                    filename=kwargs['filename'],
                    kb_settings=kwargs['kb_settings']
                )
            
            task_id = await self.task_processor.submit_task(
                task_type="document_processing",
                user_id=user_id,
                handler=_handler_wrapper,
                kb_id=kb_id,
                doc_id=doc_id,
                task_user_id=user_id,  # 重命名以避免与 submit_task 的 user_id 冲突
                file_path=file_path,
                filename=filename,
                kb_settings=kb_settings,
                priority=priority
            )
            
            # 更新文档状态为处理中
            await self.db.kb_documents.update_one(
                {"_id": ObjectId(doc_id)},
                {
                    "$set": {
                        "status": "processing",
                        "task_id": task_id,
                        "updated_at": datetime.utcnow().isoformat()
                    }
                }
            )
            
            logger.info(
                f"文档处理任务已提交: doc_id={doc_id}, task_id={task_id}, "
                f"user_id={user_id}"
            )
            
            return task_id
            
        except Exception as e:
            logger.error(f"提交文档处理任务失败: {str(e)}")
            raise
    
    async def _process_document_async(
        self,
        kb_id: str,
        doc_id: str,
        user_id: str,
        file_path: str,
        filename: str,
        kb_settings: Dict[str, Any]
    ):
        """
        异步处理文档（在后台任务中执行）
        
        这个方法会在独立的协程中执行，不会阻塞主服务
        
        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            user_id: 用户ID
            file_path: 文件路径
            filename: 文件名
            kb_settings: 知识库配置
        """
        # 获取用户的限流器
        semaphore = self.user_rate_limits.get(user_id)
        
        # 🎯 获取当前任务的 task_id（从数据库读取）
        task_id = None
        try:
            doc_record = await self.db.kb_documents.find_one({"_id": ObjectId(doc_id)})
            if doc_record:
                task_id = doc_record.get("task_id")
        except Exception as e:
            logger.warning(f"⚠️ 无法获取 task_id: {e}")
        
        async def update_progress(progress: float, message: str = ""):
            """更新任务进度"""
            if task_id:
                try:
                    await self.task_processor.update_task_progress(task_id, progress, message)
                except Exception as e:
                    logger.warning(f"⚠️ 更新进度失败: {e}")
        
        try:
            # 应用用户级限流
            async with semaphore if semaphore else asyncio.Semaphore(1):
                logger.info(f"开始处理文档: {filename} (doc_id: {doc_id})")
                await update_progress(0.1, "开始处理文档...")
                
                # 步骤1: 读取文件
                file_content = await self._read_file_async(file_path)
                await update_progress(0.2, "读取文件完成")
                
                # 步骤2: 解析文档
                text_content = await self._parse_document_async(
                    file_content, filename
                )
                await update_progress(0.4, "文档解析完成")
                
                # 步骤3: 文本分块（使用智能分片系统）
                chunks = await self._chunk_text_async(
                    text_content, kb_settings, filename
                )
                await update_progress(0.5, f"文本分块完成: {len(chunks)} 个分块")
                logger.info(f"文档分块完成: {len(chunks)} 个分块")
                
                # 步骤4: 向量化并存储（异步批量处理）
                await self._embed_and_store_async(
                    kb_id, doc_id, chunks, kb_settings, filename, update_progress
                )
                await update_progress(0.9, "向量化存储完成")
                
                # 步骤4.5: 🔥 【已废弃】单文档持久化检查
                # 改为：仅在最终完成时全局检查（避免重复等待）
                # await self._final_persistence_check(kb_id, kb_settings)
                
                # 步骤5: 更新文档状态为完成
                await self._update_document_completed(
                    doc_id, len(chunks)
                )
                await update_progress(1.0, "文档处理完成")
                
                logger.info(f"文档处理完成: {filename} (doc_id: {doc_id})")
                
        except asyncio.CancelledError:
            logger.info(f"文档处理被取消: {doc_id}")
            await update_progress(0.0, "任务被取消")
            await self._update_document_failed(
                doc_id, "任务被取消"
            )
            raise
            
        except Exception as e:
            logger.error(f"文档处理失败: {doc_id}, 错误: {str(e)}", exc_info=True)
            await update_progress(0.0, f"处理失败: {str(e)}")
            await self._update_document_failed(
                doc_id, str(e)
            )
            raise
    
    async def _read_file_async(self, file_path: str) -> bytes:
        """
        异步读取文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件内容（字节）
        """
        # 使用 asyncio 的异步文件操作
        loop = asyncio.get_event_loop()
        
        def _read():
            with open(file_path, 'rb') as f:
                return f.read()
        
        return await loop.run_in_executor(None, _read)
    
    async def _parse_document_async(
        self, content: bytes, filename: str
    ) -> str:
        """
        异步解析文档（提取文本）
        
        Args:
            content: 文件内容
            filename: 文件名
            
        Returns:
            提取的文本
        """
        # 延迟导入，避免启动时加载
        loop = asyncio.get_event_loop()
        
        def _parse():
            from ..services.document_upload_service import DocumentUploadService
            service = DocumentUploadService()
            
            # 临时写入文件供解析器使用
            import tempfile
            with tempfile.NamedTemporaryFile(
                delete=False, 
                suffix=Path(filename).suffix
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            
            try:
                # 同步解析
                success, text, error = asyncio.run(
                    service.parse_document(content, filename)
                )
                if not success:
                    raise RuntimeError(error or "文档解析失败")
                return text
            finally:
                # 清理临时文件
                import os
                try:
                    os.unlink(tmp_path)
                except:
                    pass
        
        return await loop.run_in_executor(None, _parse)
    
    async def _chunk_text_async(
        self, text: str, kb_settings: Dict[str, Any], filename: str = "unknown"
    ) -> list:
        """
        异步文本分块（使用智能分片系统）
        
        Args:
            text: 文本内容
            kb_settings: 知识库配置
            filename: 文件名（用于检测文件类型）
            
        Returns:
            分块列表
        """
        try:
            # 使用新的智能分片系统
            from .chunking_integration import ChunkingIntegration
            
            chunking_service = ChunkingIntegration()
            chunks = await chunking_service.chunk_text_smart(
                text=text,
                filename=filename,
                kb_settings=kb_settings
            )
            
            logger.info(f"✅ 使用智能分片系统完成分块: {len(chunks)} 个分片")
            return chunks
            
        except Exception as e:
            logger.error(f"智能分片失败，降级到传统分片: {e}", exc_info=True)
            
            # 降级：使用传统分片方法
            loop = asyncio.get_event_loop()
            
            def _chunk():
                from langchain.text_splitter import RecursiveCharacterTextSplitter
                
                sp = kb_settings.get("split_params", {})
                chunk_size = int(sp.get("chunk_size", 500))
                chunk_overlap = int(sp.get("chunk_overlap", 50))
                separators = sp.get("separators", ["\n\n", "\n", "。", "！", "？", "，", " ", ""])
                
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
    
    async def _embed_and_store_async(
        self,
        kb_id: str,
        doc_id: str,
        chunks: list,
        kb_settings: Dict[str, Any],
        filename: str = None,
        progress_callback = None
    ):
        """
        异步向量化并存储
        
        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            chunks: 分块列表
            kb_settings: 知识库配置
            filename: 文档文件名（用于在metadata中存储）
            progress_callback: 进度回调函数
        """
        # 这里应该调用向量存储服务
        # 为了避免阻塞，使用批处理
        
        # 🔥 批处理策略：每批100个分块
        # ChromaDB 的 HNSW 索引构建和持久化在 VectorStoreWithLock 中已处理
        # 文件锁内部会根据批次大小自动等待（3-5秒），确保索引完整写入磁盘
        batch_size = 100  # 每批处理100个分块
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        
        for batch_idx, i in enumerate(range(0, len(chunks), batch_size)):
            batch = chunks[i:i + batch_size]
            
            # 异步处理一批（内部使用文件锁保护，自动等待索引持久化）
            await self._process_chunk_batch(
                kb_id, doc_id, batch, i, kb_settings, filename
            )
            
            # 更新进度（0.5-0.9之间）
            if progress_callback:
                batch_progress = 0.5 + (batch_idx + 1) / total_batches * 0.4
                await progress_callback(batch_progress, f"向量化进度: {batch_idx + 1}/{total_batches} 批次")
    
    async def _process_chunk_batch(
        self,
        kb_id: str,
        doc_id: str,
        chunks: list,
        start_idx: int,
        kb_settings: Dict[str, Any],
        filename: str = None
    ):
        """
        处理一批分块
        
        Args:
            kb_id: 知识库ID
            doc_id: 文档ID
            chunks: 分块列表
            start_idx: 起始索引
            kb_settings: 知识库配置
        """
        from langchain_core.documents import Document
        from ..services.embedding_manager import get_embedding_manager
        from ..services.vectorstore_manager import get_vectorstore_manager
        from ..config import settings
        from ..utils.embedding.path_utils import (
            build_chroma_persist_dir, get_chroma_collection_name,
            build_faiss_persist_dir, get_faiss_collection_name
        )
        
        # 获取向量数据库类型
        vector_db_type = kb_settings.get("vector_db", "chroma")
        
        # 获取知识库配置（使用工具函数处理collection名称和持久化目录）
        collection_name_raw = kb_settings.get('collection_name', 'default')
        
        if vector_db_type == "chroma":
            collection_name = get_chroma_collection_name(collection_name_raw)
            persist_dir = build_chroma_persist_dir(collection_name_raw)
        elif vector_db_type == "faiss":
            collection_name = get_faiss_collection_name(collection_name_raw)
            persist_dir = build_faiss_persist_dir(collection_name_raw)
        else:
            raise ValueError(f"不支持的向量数据库类型: {vector_db_type}")
        
        # 获取 Embedding 管理器和 VectorStore 管理器
        embedding_mgr = get_embedding_manager()
        vectorstore_mgr = get_vectorstore_manager()
        
        # 获取 embedding 配置（从知识库创建时保存的配置中读取）
        embeddings_config = kb_settings.get("embeddings") or {}
        provider = embeddings_config.get("provider", "ollama")
        model = embeddings_config.get("model")
        base_url = embeddings_config.get("base_url")
        api_key = embeddings_config.get("api_key")
        local_model_path = embeddings_config.get("local_model_path")
        
        # 使用 EmbeddingManager 的 get_or_create 方法（与 kb.py 的 _get_kb_components 完全一致）
        embedding_func = embedding_mgr.get_or_create(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            local_model_path=local_model_path,
            max_length=512,
            batch_size=8,
            normalize=True
        )
        
        # 获取搜索参数（包含距离度量）
        search_params = kb_settings.get("search_params") or {}
        distance_metric = search_params.get("distance_metric", "cosine")
        
        # 获取 VectorStore 实例
        vectorstore = vectorstore_mgr.get_or_create(
            collection_name=collection_name,
            persist_dir=persist_dir,
            embedding_function=embedding_func,
            vector_db_type=vector_db_type,
            distance_metric=distance_metric  # 🎯 传递距离度量参数
        )
        
        # 准备文档（使用 langchain Document 对象）
        docs = []
        chunk_ids = []
        
        for idx, chunk_text in enumerate(chunks):
            # 生成稳定的 chunk_id（使用 UUID 而不是 MD5）
            import uuid
            chunk_id = str(uuid.uuid4())
            chunk_ids.append(chunk_id)
            
            # 创建 Document 对象
            doc = Document(
                page_content=chunk_text,
                metadata={
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "chunk_index": start_idx + idx,
                    "source": f"{doc_id}_{start_idx + idx}",
                    "filename": filename  # 添加文件名到元数据
                }
            )
            docs.append(doc)
        
        # 🔒 使用带锁的异步方法，防止并发写入导致索引损坏
        await vectorstore.add_documents_async(docs, ids=chunk_ids)
        
        # 🔥 关键修复：每个文档写入后，触发全局持久化检查
        # 使用智能去重，避免短时间内重复等待
        collection_name = kb_settings.get("collection_name")
        if collection_name:
            try:
                from .vectorstore_manager import get_vectorstore_manager
                vectorstore_mgr = get_vectorstore_manager()
                
                # 在线程池中执行（避免阻塞事件循环）
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self._trigger_global_persistence_if_needed,
                    vectorstore_mgr,
                    collection_name,
                    kb_id
                )
            except Exception as e:
                logger.warning(f"⚠️ 全局持久化检查失败（可忽略）: {e}")
    
    def _trigger_global_persistence_if_needed(self, vectorstore_mgr, collection_name: str, kb_id: str):
        """
        同步方法：智能触发全局持久化（避免重复）
        
        在线程池中执行，不阻塞事件循环
        """
        import time
        
        # 使用类级别的字典记录最后持久化时间
        if not hasattr(self.__class__, '_last_global_persistence'):
            self.__class__._last_global_persistence = {}
        
        current_time = time.time()
        last_time = self.__class__._last_global_persistence.get(kb_id, 0)
        
        # 如果距离上次持久化不足60秒，跳过
        if current_time - last_time < 60:
            logger.debug(f"⏭️ 距离上次全局持久化不足60秒，跳过 (kb_id: {kb_id})")
            return
        
        # 更新时间戳
        self.__class__._last_global_persistence[kb_id] = current_time
        
        # 执行全局持久化
        vectorstore_mgr.force_global_compaction_wait(collection_name)
    
    async def _global_persistence_check_if_needed(self, kb_id: str, kb_settings: Dict[str, Any]):
        """
        🔥 全局持久化检查（智能版）
        
        **问题分析**：
        批量处理100个文档时，如果每个文档完成后都等待持久化，会浪费大量时间。
        
        **优化策略**：
        - 使用进程级标记，确保同一知识库在短时间内只执行一次全局持久化
        - 避免100个文档都重复等待30秒
        
        Args:
            kb_id: 知识库ID
            kb_settings: 知识库配置
        """
        import time
        import asyncio
        
        # 使用类级别的字典记录最后持久化时间
        if not hasattr(self.__class__, '_last_persistence_time'):
            self.__class__._last_persistence_time = {}
        
        current_time = time.time()
        last_time = self.__class__._last_persistence_time.get(kb_id, 0)
        
        # 如果距离上次持久化不足60秒，跳过
        if current_time - last_time < 60:
            logger.debug(f"⏭️ 距离上次全局持久化不足60秒，跳过 (kb_id: {kb_id})")
            return
        
        # 更新时间戳
        self.__class__._last_persistence_time[kb_id] = current_time
        
        # 执行全局持久化
        collection_name = kb_settings.get("collection_name")
        if not collection_name:
            logger.warning("⚠️ 缺少 collection_name，跳过全局持久化检查")
            return
        
        try:
            from .vectorstore_manager import get_vectorstore_manager
            
            vectorstore_mgr = get_vectorstore_manager()
            
            # 在线程池中执行（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                vectorstore_mgr.force_global_compaction_wait,
                collection_name
            )
            
        except Exception as e:
            logger.error(f"❌ 全局持久化检查失败: {e}", exc_info=True)
    
    async def _final_persistence_check(self, kb_id: str, kb_settings: Dict[str, Any]):
        """
        🔥 最终持久化确认：确保ChromaDB后台compaction完全完成
        
        问题场景：
        当多个文档并发处理时（3个worker同时写入）：
        - worker-1 完成写入 → 等待10秒 → 释放锁
        - worker-2 完成写入 → 等待10秒 → 释放锁
        - worker-3 完成写入 → 等待10秒 → 释放锁
        
        但是！ChromaDB的后台compaction是全局的，可能还在合并前面worker的索引段。
        此时如果重启服务器，索引就会损坏。
        
        解决方案：
        在文档处理的最后，再次强制触发compaction并等待，确保：
        1. 所有批次的索引段都已合并
        2. SQLite WAL已经checkpoint
        3. HNSW索引完全持久化到磁盘
        
        Args:
            kb_id: 知识库ID
            kb_settings: 知识库配置
        """
        import asyncio
        
        try:
            # 获取vectorstore实例（不需要embedding，只用来访问collection）
            from .embedding_manager import get_embedding_manager
            from .vectorstore_manager import get_vectorstore_manager
            
            collection_name = kb_settings.get("collection_name")
            persist_dir = kb_settings.get("persist_dir")
            
            if not collection_name or not persist_dir:
                logger.warning("⚠️ 缺少 collection_name 或 persist_dir，跳过最终持久化检查")
                return
            
            # 获取embedding配置（仅用于获取vectorstore实例）
            embeddings_config = kb_settings.get("embeddings") or {}
            provider = embeddings_config.get("provider", "local")
            model = embeddings_config.get("model", "checkpoints/embeddings/all-MiniLM-L6-v2")
            base_url = embeddings_config.get("base_url")
            api_key = embeddings_config.get("api_key")
            local_model_path = embeddings_config.get("local_model_path")
            
            embedding_mgr = get_embedding_manager()
            vectorstore_mgr = get_vectorstore_manager()
            
            embedding_func = embedding_mgr.get_or_create(
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                local_model_path=local_model_path,
                max_length=512,
                batch_size=8,
                normalize=True
            )
            
            search_params = kb_settings.get("search_params") or {}
            distance_metric = search_params.get("distance_metric")
            
            vectorstore = vectorstore_mgr.get_or_create(
                collection_name=collection_name,
                persist_dir=persist_dir,
                embedding_function=embedding_func,
                distance_metric=distance_metric
            )
            
            # 在线程池中执行最终持久化检查（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._force_final_compaction,
                vectorstore
            )
            
        except Exception as e:
            logger.warning(f"⚠️ 最终持久化检查失败（可忽略）: {e}")
    
    def _force_final_compaction(self, vectorstore):
        """
        同步方法：强制触发最终的compaction
        
        在线程池中执行，不阻塞事件循环
        """
        import time
        
        try:
            if hasattr(vectorstore, '_vectorstore'):
                # 如果是VectorStoreWithLock包装类，获取内部实例
                vectorstore = vectorstore._vectorstore
            
            if hasattr(vectorstore, '_store') and hasattr(vectorstore._store, '_collection'):
                collection = vectorstore._store._collection
                
                logger.info(f"💾 [最终持久化] 开始强制触发最终compaction...")
                
                # 触发compaction
                doc_count = collection.count()
                logger.info(f"💾 [最终持久化] 已触发compaction，当前文档数: {doc_count}")
                
                # 🔥 关键：等待足够长的时间让所有积压的compaction任务完成
                # 这是在文档处理的最后阶段，不再有新的写入，可以放心等待
                wait_time = 10.0
                time.sleep(wait_time)
                logger.warning(f"💾 [最终持久化] 已等待 {wait_time}秒 确保后台compaction完成")
                
                # 再次确认
                final_count = collection.count()
                logger.info(f"✅ [最终持久化] 最终确认完成，文档数: {final_count}")
                
        except Exception as e:
            logger.warning(f"⚠️ 最终compaction触发失败: {e}")
    
    async def _update_document_completed(self, doc_id: str, chunk_count: int):
        """
        更新文档状态为完成，同时更新知识库的分片计数
        
        Args:
            doc_id: 文档ID
            chunk_count: 分块数量
        """
        # 1. 更新文档状态
        result = await self.db.kb_documents.update_one(
            {"_id": ObjectId(doc_id)},
            {
                "$set": {
                    "status": "completed",
                    "chunk_count": chunk_count,
                    "error_message": None,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        # 2. 更新知识库的分片计数（原子操作）
        if result.modified_count > 0:
            doc = await self.db.kb_documents.find_one({"_id": ObjectId(doc_id)})
            if doc and doc.get("kb_id"):
                await self.db.knowledge_bases.update_one(
                    {"_id": ObjectId(doc["kb_id"])},
                    {
                        "$inc": {"chunk_count": chunk_count},
                        "$set": {"updated_at": datetime.utcnow().isoformat()}
                    }
                )
                logger.info(f"已更新知识库 {doc['kb_id']} 的 chunk_count，增加 {chunk_count}")
    
    async def _update_document_failed(self, doc_id: str, error: str):
        """
        更新文档状态为失败
        
        Args:
            doc_id: 文档ID
            error: 错误信息
        """
        await self.db.kb_documents.update_one(
            {"_id": ObjectId(doc_id)},
            {
                "$set": {
                    "status": "failed",
                    "error_message": error,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )


# 依赖注入函数
async def get_document_processor(
    db: AsyncIOMotorDatabase = None
) -> DocumentProcessor:
    """
    获取文档处理服务实例
    
    Args:
        db: 数据库连接
        
    Returns:
        文档处理服务实例
    """
    if db is None:
        from ..database import get_database
        db_client = await anext(get_database())
        db = db_client[settings.mongodb_db_name]
    
    return DocumentProcessor(db)

