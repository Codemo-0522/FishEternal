"""
全局 VectorStore 实例管理器
确保同一个知识库只创建一次连接，所有用户共享

🔒 多进程安全：
使用文件锁（filelock）代替 asyncio.Lock，确保多个 worker 进程不会并发写入 ChromaDB
"""
import logging
import threading
import asyncio
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
from filelock import FileLock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorStoreKey:
    """VectorStore 的唯一标识符"""
    collection_name: str
    persist_dir: str
    distance_metric: str  # 🎯 新增：距离度量也是唯一性的一部分
    
    def __hash__(self):
        return hash((self.collection_name, self.persist_dir, self.distance_metric))


class VectorStoreWithLock:
    """
    VectorStore 包装类，为写入操作添加文件锁
    
    🔒 多进程安全：
    使用文件锁（FileLock）替代 asyncio.Lock，确保多个 worker 进程
    不会并发写入同一个 ChromaDB collection，防止 HNSW 索引损坏。
    
    提供异步的 add_documents_async 方法，确保同一时间只有一个写入操作。
    """
    
    def __init__(self, vectorstore: Any, lock_file_path: str, persist_directory: str = None):
        """
        Args:
            vectorstore: 向量数据库实例
            lock_file_path: 锁文件路径（多进程共享）
            persist_directory: 持久化目录（用于SQLite checkpoint）
        """
        self._vectorstore = vectorstore
        self._lock_file_path = lock_file_path
        self._persist_directory = persist_directory
        self._file_lock = FileLock(lock_file_path, timeout=300)  # 5分钟超时
        logger.info(f"🔒 [多进程锁] 初始化文件锁: {lock_file_path}")
    
    async def add_documents_async(self, documents, ids=None):
        """
        异步的 add_documents，使用文件锁保护（多进程安全）
        
        Args:
            documents: 要添加的文档列表
            ids: 文档ID列表
        """
        logger.debug(f"🔒 [多进程锁] 等待写入锁: {len(documents)} 个文档")
        
        # 在线程池中执行加锁+写入操作（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._add_documents_with_file_lock,
            documents,
            ids
        )
        
        logger.debug(f"✅ [多进程锁] 写入完成，已释放锁")
    
    def _add_documents_with_file_lock(self, documents, ids):
        """
        同步方法：在文件锁保护下写入文档
        
        这个方法在线程池中执行，不会阻塞事件循环
        """
        import time
        
        with self._file_lock:
            logger.debug(f"🔒 [多进程锁] 已获取写入锁，开始写入 {len(documents)} 个文档")
            self._vectorstore.add_documents(documents, ids=ids)
            
            # 🔥 修复：批量并发写入时的索引损坏问题
            # 
            # 问题根源：
            # ChromaDB 1.1.0+ Rust 后端的后台 compaction 是**全局的、跨批次的**
            # 当多个 worker 快速连续写入时：
            #   - worker-1: 写入417个chunk → 等待5秒（但后台compaction可能需要8秒）
            #   - worker-2: 获得锁，写入306个chunk → 后台又积压新的compaction任务
            #   - worker-3: 写入244个chunk → 此时后台compaction已经严重积压
            #   - 重启服务器 → SQLite WAL没来得及checkpoint → 索引损坏！
            # 
            # 解决方案：
            # 1. 写入后立即触发 compaction（强制索引构建）
            # 2. 等待足够长的时间让后台compaction完成
            # 3. 在锁内部进行，确保下一个writer等待当前批次完全持久化
            
            try:
                # 访问底层 Chroma 实例
                if hasattr(self._vectorstore, '_store') and hasattr(self._vectorstore._store, '_collection'):
                    collection = self._vectorstore._store._collection
                    batch_size = len(documents)
                    
                    # 方法1: 尝试调用 persist (旧版 ChromaDB)
                    if hasattr(collection, '_client') and hasattr(collection._client, 'persist'):
                        collection._client.persist()
                        logger.debug(f"💾 [ChromaDB 旧版] 已调用 persist() 持久化索引")
                    
                    # 方法2: 对于 Rust 后端 (1.0+)，强制持久化
                    try:
                        # Step 1: 触发 count() 开始 compaction
                        doc_count = collection.count()
                        logger.info(f"💾 [ChromaDB Rust] 写入完成，文档数: {doc_count}, 批量大小: {batch_size}")
                        
                        # Step 2: 🔥 强制SQLite checkpoint（同步操作，无需等待）
                        try:
                            import sqlite3
                            from pathlib import Path
                            
                            # 从VectorStore初始化参数中获取persist_directory
                            if self._persist_directory:
                                persist_dir = Path(self._persist_directory)
                                db_file = persist_dir / "chroma.sqlite3"
                                
                                if db_file.exists():
                                    # 强制WAL checkpoint（这是同步阻塞操作）
                                    conn = sqlite3.connect(str(db_file))
                                    try:
                                        # TRUNCATE: 将WAL文件内容写入主数据库并清空WAL
                                        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                        # 返回值: (busy, log, checkpointed)
                                        # - busy: 0=成功, 非0=失败（数据库被锁定）
                                        # - log: WAL文件的总页数
                                        # - checkpointed: 成功checkpoint的页数
                                        busy, log_pages, checkpointed_pages = result.fetchone()
                                        
                                        if busy == 0:
                                            logger.info(f"✅ [WAL Checkpoint] 成功! WAL页数={log_pages}, 已写入={checkpointed_pages}")
                                        else:
                                            logger.warning(f"⚠️ [WAL Checkpoint] 部分失败! busy={busy}, WAL页数={log_pages}, 已写入={checkpointed_pages}")
                                    finally:
                                        conn.close()
                                else:
                                    logger.warning(f"⚠️ [SQLite WAL] 数据库文件不存在: {db_file}")
                            else:
                                logger.warning(f"⚠️ [SQLite WAL] persist_directory 未设置")
                        except Exception as checkpoint_e:
                            logger.error(f"❌ [SQLite WAL] checkpoint失败: {checkpoint_e}", exc_info=True)
                        
                        # Step 3: 验证持久化结果（count是同步的，无需等待）
                        final_count = collection.count()
                        logger.info(f"✅ [持久化完成] 批量={batch_size}, 最终文档数={final_count}")
                            
                    except Exception as inner_e:
                        logger.warning(f"⚠️ ChromaDB 持久化流程失败: {inner_e}")
                        
            except Exception as e:
                logger.warning(f"⚠️ ChromaDB 索引持久化检查失败: {e}")
    
    def add_documents(self, documents, ids=None):
        """
        ❌ 已废弃：禁止使用同步的 add_documents
        
        为了防止索引损坏，所有写入操作必须使用 add_documents_async
        这样可以确保：
        1. 文件锁在异步环境中正确工作
        2. 不会因为同步阻塞导致死锁
        3. 多进程环境下的安全性
        
        请使用: await vectorstore.add_documents_async(documents, ids)
        """
        raise RuntimeError(
            "❌ 禁止使用同步的 add_documents 方法！\n"
            "为了防止索引损坏，请使用异步方法: await vectorstore.add_documents_async(documents, ids)\n"
            "这是强制性的安全措施，不存在例外。"
        )
    
    def __getattr__(self, name):
        """代理其他方法到原始 vectorstore"""
        return getattr(self._vectorstore, name)


class VectorStoreManager:
    """
    全局 VectorStore 实例管理器（单例模式）
    
    职责：
    1. 管理所有 VectorStore 连接的生命周期
    2. 确保同一个知识库只创建一次连接
    3. 线程安全的实例获取
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._instances: Dict[VectorStoreKey, Any] = {}
            self._instance_lock = threading.Lock()
            # 🔒 锁文件目录（多进程共享）
            self._lock_dir = Path("data/locks")
            self._lock_dir.mkdir(parents=True, exist_ok=True)
            self._initialized = True
            logger.info(f"✅ VectorStoreManager 初始化完成 (锁文件目录: {self._lock_dir})")
    
    def get_or_create(
        self,
        collection_name: str,
        persist_dir: str,
        embedding_function: Any,
        vector_db_type: str = "chroma",
        distance_metric: str = "cosine"  # 新增：距离度量参数
    ) -> Any:
        """
        获取或创建 VectorStore 实例
        
        Args:
            collection_name: 集合名称
            persist_dir: 持久化目录
            embedding_function: Embedding 函数（来自 EmbeddingManager）
            vector_db_type: 向量数据库类型 ("chroma" 或 "faiss")
            distance_metric: 距离度量方式 ("cosine", "l2", "ip")
            
        Returns:
            VectorStore 实例（所有用户共享）
            
        Raises:
            ValueError: 参数错误
        """
        if vector_db_type not in ["chroma", "faiss"]:
            raise ValueError(f"不支持的向量数据库类型: {vector_db_type}，仅支持: chroma, faiss")
        
        cache_key = VectorStoreKey(
            collection_name=collection_name,
            persist_dir=persist_dir,
            distance_metric=distance_metric
        )
        
        # 双重检查锁定
        if cache_key in self._instances:
            logger.info(f"♻️ 复用已加载的 VectorStore ({vector_db_type}): {cache_key.collection_name}")
            return self._instances[cache_key]
        
        # 🔒 获取文件锁路径（用于跨进程保护collection创建）
        lock_file_path = self._get_lock_file_path(f"{vector_db_type}_{collection_name}")
        
        # 🔥 使用文件锁保护整个创建过程（防止并发创建导致索引冲突）
        from filelock import FileLock
        file_lock = FileLock(lock_file_path, timeout=30)
        
        with file_lock:
            # 再次检查（可能其他进程已经创建完成）
            if cache_key in self._instances:
                logger.info(f"♻️ 复用已加载的 VectorStore ({vector_db_type}): {cache_key.collection_name}")
                return self._instances[cache_key]
            
            with self._instance_lock:
                # 线程锁内再次检查
                if cache_key in self._instances:
                    logger.info(f"♻️ 复用已加载的 VectorStore ({vector_db_type}): {cache_key.collection_name}")
                    return self._instances[cache_key]
                
                logger.info(f"⏳ 创建新的 {vector_db_type.upper()} VectorStore: {cache_key.collection_name} (距离度量: {distance_metric})")
                
                try:
                    # 根据类型选择实现
                    if vector_db_type == "chroma":
                        from ..utils.embedding.vector_store import ChromaVectorStore
                        instance = ChromaVectorStore(
                            embedding_function=embedding_function,
                            persist_directory=persist_dir,
                            collection_name=collection_name,
                            distance_metric=distance_metric
                        )
                    elif vector_db_type == "faiss":
                        from ..utils.embedding.vector_store import FAISSVectorStore
                        instance = FAISSVectorStore(
                            embedding_function=embedding_function,
                            persist_directory=persist_dir,
                            collection_name=collection_name,
                            distance_metric=distance_metric
                        )
                    else:
                        raise ValueError(f"不支持的向量数据库类型: {vector_db_type}")
                    
                    # 包装 instance，添加文件锁（用于后续写入保护）
                    wrapped_instance = VectorStoreWithLock(instance, lock_file_path, persist_dir)
                    
                    self._instances[cache_key] = wrapped_instance
                    logger.info(f"✅ {vector_db_type.upper()} VectorStore 创建成功: {cache_key.collection_name}")
                    logger.info(f"📊 当前 VectorStore 连接数: {len(self._instances)}")
                    return wrapped_instance
                    
                except Exception as e:
                    logger.error(f"❌ {vector_db_type.upper()} VectorStore 创建失败: {cache_key.collection_name} - {e}")
                    raise RuntimeError(f"VectorStore 创建失败: {e}") from e
    
    def _get_lock_file_path(self, collection_name: str) -> str:
        """
        获取指定 collection 的锁文件路径（多进程共享）
        
        Args:
            collection_name: collection 名称
            
        Returns:
            锁文件的绝对路径
        """
        # 使用 collection 名称创建锁文件
        # 文件名使用安全字符
        safe_name = collection_name.replace("/", "_").replace("\\", "_")
        lock_file = self._lock_dir / f"{safe_name}.lock"
        return str(lock_file.absolute())
    
    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        return {
            "active_connections": len(self._instances),
            "collections": [
                {
                    "collection_name": key.collection_name,
                    "persist_dir": key.persist_dir
                }
                for key in self._instances.keys()
            ]
        }
    
    def remove(self, collection_name: str, persist_dir: str, distance_metric: str = "cosine") -> bool:
        """
        移除并关闭特定的 VectorStore 实例
        
        Args:
            collection_name: 集合名称
            persist_dir: 持久化目录
            distance_metric: 距离度量方式
            
        Returns:
            是否成功移除
        """
        cache_key = VectorStoreKey(
            collection_name=collection_name,
            persist_dir=persist_dir,
            distance_metric=distance_metric
        )
        
        with self._instance_lock:
            if cache_key in self._instances:
                instance = self._instances[cache_key]
                
                # 🔥 在关闭连接前，强制执行SQLite checkpoint
                try:
                    import sqlite3
                    from pathlib import Path
                    
                    persist_dir = Path(persist_dir)
                    db_file = persist_dir / "chroma.sqlite3"
                    
                    if db_file.exists():
                        conn = sqlite3.connect(str(db_file))
                        try:
                            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            checkpoint_result = result.fetchone()
                            logger.info(f"💾 [关闭前checkpoint] {collection_name}: {checkpoint_result}")
                        finally:
                            conn.close()
                except Exception as checkpoint_e:
                    logger.warning(f"⚠️ [关闭前checkpoint] 失败: {checkpoint_e}")
                
                # 尝试关闭 ChromaDB 连接
                try:
                    # ChromaVectorStore 包装了 Chroma 实例在 _store 属性中
                    if hasattr(instance, '_store') and hasattr(instance._store, '_client'):
                        # 关闭 ChromaDB 客户端连接
                        chroma_client = instance._store._client
                        if hasattr(chroma_client, '_system') and hasattr(chroma_client._system, 'stop'):
                            chroma_client._system.stop()
                            logger.info(f"🔌 已关闭 ChromaDB 客户端连接: {collection_name}")
                except Exception as e:
                    logger.warning(f"⚠️ 关闭 ChromaDB 连接时出错: {e}")
                
                # 从缓存中移除
                del self._instances[cache_key]
                logger.info(f"🗑️ 已移除 VectorStore 实例: {collection_name}")
                logger.info(f"📊 剩余 VectorStore 连接数: {len(self._instances)}")
                return True
            else:
                logger.warning(f"⚠️ VectorStore 实例不存在: {collection_name}")
                return False
    
    def force_global_compaction_wait(self, collection_name: str):
        """
        🔥 强制等待全局compaction完成
        
        **问题根源**：
        批量并发写入时，每个批次虽然等待了10秒，但ChromaDB的后台compaction是全局的：
        - 批次1: 写入300 chunks + 等待10秒 ✅
        - 批次2: 写入300 chunks + 等待10秒 ✅  
        - 批次3: 写入300 chunks + 等待10秒 ✅
        
        此时每个批次的索引在内存中是好的（所以当场查看正常），
        但全局的后台compaction线程可能还在：
        - 合并3个批次的索引段
        - 执行SQLite WAL checkpoint
        - 将HNSW索引写入磁盘
        
        如果此时重启 → 索引文件不完整 → 加载失败！
        
        **解决方案**：
        在所有批次完成后，强制等待全局compaction队列清空
        
        Args:
            collection_name: collection名称
        """
        import time
        
        try:
            key = self._find_key_by_collection(collection_name)
            if not key:
                logger.warning(f"⚠️ 未找到collection: {collection_name}")
                return
            
            instance = self._instances.get(key)
            if not instance or not hasattr(instance, '_vectorstore'):
                return
            
            vectorstore = instance._vectorstore
            if not hasattr(vectorstore, '_store') or not hasattr(vectorstore._store, '_collection'):
                return
            
            collection = vectorstore._store._collection
            
            # 获取当前文档总数
            doc_count = collection.count()
            logger.warning(f"💾 [全局持久化] 开始强制WAL checkpoint (文档总数: {doc_count})")
            
            # 🔥 直接执行WAL checkpoint，无需等待
            try:
                import sqlite3
                from pathlib import Path
                
                if hasattr(vectorstore, '_store') and hasattr(vectorstore._store, '_client'):
                    client = vectorstore._store._client
                    if hasattr(client, '_settings') and hasattr(client._settings, 'persist_directory'):
                        persist_dir = Path(client._settings.persist_directory)
                        db_file = persist_dir / "chroma.sqlite3"
                        
                        if db_file.exists():
                            conn = sqlite3.connect(str(db_file))
                            try:
                                result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                busy, log_pages, checkpointed_pages = result.fetchone()
                                
                                if busy == 0:
                                    logger.warning(f"✅ [全局持久化] WAL checkpoint成功! WAL页数={log_pages}, 已写入={checkpointed_pages}")
                                else:
                                    logger.warning(f"⚠️ [全局持久化] WAL checkpoint部分失败! busy={busy}")
                            finally:
                                conn.close()
                        else:
                            logger.warning(f"⚠️ [全局持久化] 数据库文件不存在: {db_file}")
            except Exception as checkpoint_e:
                logger.error(f"❌ [全局持久化] WAL checkpoint失败: {checkpoint_e}")
            
            # 验证最终结果
            final_count = collection.count()
            logger.warning(f"✅ [全局持久化] 完成！最终文档数: {final_count}")
            logger.warning(f"✅ [全局持久化] 现在重启服务器是安全的")
            
        except Exception as e:
            logger.error(f"❌ [全局持久化] 强制等待失败: {e}")
    
    def _find_key_by_collection(self, collection_name: str) -> Optional[VectorStoreKey]:
        """根据collection_name查找key"""
        with self._instance_lock:
            for key in self._instances.keys():
                if key.collection_name == collection_name:
                    return key
        return None
    
    def clear(self):
        """清空所有缓存的实例（仅用于测试或重启）"""
        with self._instance_lock:
            # 尝试关闭所有连接
            for key, instance in list(self._instances.items()):
                try:
                    if hasattr(instance, '_store') and hasattr(instance._store, '_client'):
                        chroma_client = instance._store._client
                        if hasattr(chroma_client, '_system') and hasattr(chroma_client._system, 'stop'):
                            chroma_client._system.stop()
                except Exception as e:
                    logger.warning(f"⚠️ 关闭连接时出错 ({key.collection_name}): {e}")
            
            count = len(self._instances)
            self._instances.clear()
            logger.warning(f"⚠️ 已清空所有 VectorStore 连接 (共 {count} 个)")


# 全局单例实例
_vectorstore_manager: Optional[VectorStoreManager] = None


def get_vectorstore_manager() -> VectorStoreManager:
    """获取全局 VectorStoreManager 单例"""
    global _vectorstore_manager
    if _vectorstore_manager is None:
        _vectorstore_manager = VectorStoreManager()
    return _vectorstore_manager

