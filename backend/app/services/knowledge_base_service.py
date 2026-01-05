"""
知识库服务层 - 高并发优化版本
特性：
1. 完全异步操作，避免阻塞
2. 连接池管理，支持高并发
3. 事务一致性保证
4. 模块化解耦设计
"""
import logging
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from ..config import settings
from ..models.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    DocumentResponse,
    KBStatistics
)

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """
    知识库服务 - 线程安全、高并发版本
    
    设计原则：
    1. 所有数据库操作都是异步的
    2. 使用连接池避免连接耗尽
    3. 操作原子化，避免数据不一致
    4. 服务无状态，可水平扩展
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """
        初始化知识库服务
        
        Args:
            db: MongoDB 数据库实例（已配置连接池）
        """
        self.db = db
        self.kb_collection = db.knowledge_bases
        self.doc_collection = db.kb_documents
        
        # 并发控制配置
        self._semaphore = asyncio.Semaphore(100)  # 限制并发操作数
    
    async def create_knowledge_base(
        self,
        user_id: str,
        kb_data: KnowledgeBaseCreate
    ) -> KnowledgeBaseResponse:
        """
        创建知识库（异步、线程安全）
        
        Args:
            user_id: 用户ID
            kb_data: 知识库创建数据
            
        Returns:
            创建的知识库信息
            
        Raises:
            ValueError: 参数无效
            RuntimeError: 数据库操作失败
        """
        async with self._semaphore:
            try:
                now = datetime.utcnow().isoformat()
                
                # 验证嵌入配置是否存在
                if kb_data.embedding_config_id:
                    config_exists = await self.db.embedding_configs.find_one({
                        "_id": ObjectId(kb_data.embedding_config_id),
                        "user_id": user_id
                    })
                    if not config_exists:
                        raise ValueError("嵌入配置不存在或无权限")
                
                kb_dict = {
                    "name": kb_data.name,
                    "description": kb_data.description,
                    "user_id": user_id,
                    "embedding_config_id": kb_data.embedding_config_id,
                    "kb_settings": kb_data.kb_settings or {},
                    "collection_name": (kb_data.kb_settings or {}).get("collection_name"),  # 提取为顶层字段
                    "document_count": 0,
                    "chunk_count": 0,
                    "total_size": 0,
                    "created_at": now,
                    "updated_at": now
                }
                
                result = await self.kb_collection.insert_one(kb_dict)
                kb_dict["_id"] = result.inserted_id
                
                logger.info(f"用户 {user_id} 创建知识库: {kb_dict['name']} (ID: {result.inserted_id})")
                return self._kb_dict_to_response(kb_dict)
                
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"创建知识库失败: {str(e)}", exc_info=True)
                raise RuntimeError(f"创建知识库失败: {str(e)}")
    
    async def get_knowledge_bases(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[KnowledgeBaseResponse]:
        """
        获取用户的知识库列表（支持分页）
        
        Args:
            user_id: 用户ID
            skip: 跳过的记录数
            limit: 返回的最大记录数
            
        Returns:
            知识库列表
        """
        async with self._semaphore:
            try:
                # 限制 limit 最大值，防止查询过大
                limit = min(limit, 1000)
                
                cursor = self.kb_collection.find({"user_id": user_id}) \
                    .sort("created_at", -1) \
                    .skip(skip) \
                    .limit(limit)
                
                kbs = await cursor.to_list(length=limit)
                return [self._kb_dict_to_response(kb) for kb in kbs]
                
            except Exception as e:
                logger.error(f"获取知识库列表失败: {str(e)}")
                raise RuntimeError(f"获取知识库列表失败: {str(e)}")
    
    async def get_knowledge_base(
        self,
        kb_id: str,
        user_id: str
    ) -> Optional[KnowledgeBaseResponse]:
        """
        获取单个知识库（带权限验证）
        支持获取用户自己的知识库和拉取的共享知识库
        
        Args:
            kb_id: 知识库ID（可以是knowledge_bases或pulled_knowledge_bases的ID）
            user_id: 用户ID
            
        Returns:
            知识库信息，如果不存在或无权限则返回 None
        """
        async with self._semaphore:
            try:
                # 首先尝试从用户自己的知识库中查找
                kb = await self.kb_collection.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                
                if kb:
                    return self._kb_dict_to_response(kb)
                
                # 如果找不到，尝试从拉取的知识库中查找
                pulled_kb = await self.db.pulled_knowledge_bases.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id,
                    "enabled": True
                })
                
                if pulled_kb:
                    # 获取原始知识库的信息（用于获取 name, description, collection_name 等）
                    original_kb = await self.kb_collection.find_one({
                        "_id": ObjectId(pulled_kb["original_kb_id"])
                    })
                    
                    if not original_kb:
                        logger.error(f"拉取的知识库 {kb_id} 对应的原始知识库不存在")
                        return None
                    
                    # 合并原始知识库信息和拉取配置
                    # 从原始知识库的 kb_settings 中获取 vector_db（兼容老数据）
                    original_kb_settings = original_kb.get("kb_settings", {})
                    vector_db = original_kb_settings.get("vector_db")
                    split_params = original_kb_settings.get("split_params", {})
                    
                    merged_kb = {
                        **pulled_kb,
                        "name": original_kb.get("name"),
                        "description": original_kb.get("description"),
                        "collection_name": original_kb.get("collection_name"),
                        "vector_db": vector_db,  # ✅ 从 kb_settings 获取，默认 "chroma"
                        "split_params": split_params,  # ✅ 从 kb_settings 获取
                    }
                    
                    # 将拉取的知识库转换为KnowledgeBaseResponse格式
                    return self._pulled_kb_to_response(merged_kb)
                
                return None
                
            except Exception as e:
                logger.error(f"获取知识库失败: {str(e)}")
                raise RuntimeError(f"获取知识库失败: {str(e)}")
    
    async def update_knowledge_base(
        self,
        kb_id: str,
        user_id: str,
        kb_data: KnowledgeBaseUpdate
    ) -> Optional[KnowledgeBaseResponse]:
        """
        更新知识库（原子操作）
        
        Args:
            kb_id: 知识库ID
            user_id: 用户ID
            kb_data: 更新数据
            
        Returns:
            更新后的知识库信息，如果不存在或无权限则返回 None
        """
        async with self._semaphore:
            try:
                update_dict = {}
                if kb_data.name is not None:
                    update_dict["name"] = kb_data.name
                if kb_data.description is not None:
                    update_dict["description"] = kb_data.description
                if kb_data.kb_settings is not None:
                    # 防止修改 distance_metric（向量索引结构依赖此配置）
                    kb_settings = kb_data.kb_settings.copy()
                    
                    # 获取原始知识库配置
                    original_kb = await self.kb_collection.find_one({
                        "_id": ObjectId(kb_id),
                        "user_id": user_id
                    })
                    
                    if original_kb:
                        original_settings = original_kb.get("kb_settings", {})
                        original_search_params = original_settings.get("search_params", {})
                        
                        # 保护 distance_metric 不被修改
                        if "search_params" in kb_settings:
                            if "distance_metric" in original_search_params:
                                kb_settings["search_params"]["distance_metric"] = original_search_params["distance_metric"]
                    
                    update_dict["kb_settings"] = kb_settings
                
                if not update_dict:
                    # 没有要更新的字段，直接返回当前数据
                    return await self.get_knowledge_base(kb_id, user_id)
                
                update_dict["updated_at"] = datetime.utcnow().isoformat()
                
                # 使用 find_one_and_update 保证原子性
                result = await self.kb_collection.find_one_and_update(
                    {"_id": ObjectId(kb_id), "user_id": user_id},
                    {"$set": update_dict},
                    return_document=True
                )
                
                if not result:
                    return None
                
                logger.info(f"用户 {user_id} 更新知识库: {kb_id}")
                return self._kb_dict_to_response(result)
                
            except Exception as e:
                logger.error(f"更新知识库失败: {str(e)}")
                raise RuntimeError(f"更新知识库失败: {str(e)}")
    
    async def delete_knowledge_base(
        self,
        kb_id: str,
        user_id: str
    ) -> bool:
        """
        删除知识库及其所有文档（原子操作）
        
        完整删除流程：
        1. 删除数据库中的文档记录
        2. 删除数据库中的知识库记录
        3. 删除ChromaDB持久化数据（物理文件）
        
        Args:
            kb_id: 知识库ID
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        async with self._semaphore:
            try:
                # 先验证权限并获取知识库配置
                kb = await self.kb_collection.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                
                if not kb:
                    return False
                
                # 获取知识库配置以便删除向量数据
                kb_settings = kb.get("kb_settings", {})
                collection_name = kb_settings.get("collection_name")
                
                # 删除所有文档记录（批量操作）
                await self.doc_collection.delete_many({"kb_id": kb_id})
                
                # 删除知识库记录
                result = await self.kb_collection.delete_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                
                if result.deleted_count > 0:
                    logger.info(f"✅ 用户 {user_id} 删除知识库: {kb_id}, collection: {collection_name}")
                    
                    # 🆕 删除MinIO中的所有文档
                    if collection_name:
                        try:
                            from ..utils.minio_client import minio_client
                            deleted_count = minio_client.delete_kb_all_documents(user_id, collection_name)
                            logger.info(f"✅ 删除MinIO文件: {deleted_count} 个")
                        except Exception as e:
                            logger.error(f"❌ 删除MinIO文件失败: {e}")
                    
                    # 🆕 先释放 VectorStore 连接，再删除 ChromaDB 物理文件
                    if collection_name:
                        # 获取向量数据库类型和持久化目录（使用与创建时相同的路径构建方式）
                        vector_db = kb_settings.get("vector_db", "chroma")
                        
                        # ✅ 使用与创建时相同的转换逻辑
                        from ..utils.embedding.path_utils import build_chroma_persist_dir, get_chroma_collection_name
                        
                        # 🔑 关键：collection_name 需要经过相同的转换
                        collection_name_sanitized = get_chroma_collection_name(collection_name)
                        persist_dir = build_chroma_persist_dir(collection_name)
                        
                        logger.info(f"🔍 准备释放 VectorStore: collection_raw={collection_name}, collection_sanitized={collection_name_sanitized}, persist_dir={persist_dir}")
                        
                        # 从 VectorStoreManager 中移除并关闭连接
                        try:
                            from ..services.vectorstore_manager import get_vectorstore_manager
                            manager = get_vectorstore_manager()
                            # 使用转换后的 collection_name
                            removed = manager.remove(collection_name_sanitized, persist_dir)
                            if removed:
                                logger.info(f"✅ 已释放 VectorStore 连接: {collection_name_sanitized}")
                            else:
                                logger.warning(f"⚠️ VectorStore 实例不存在（可能未加载过）: {collection_name_sanitized}")
                        except Exception as e:
                            logger.warning(f"⚠️ 释放 VectorStore 连接失败: {e}")
                        
                        # 等待一小段时间确保连接完全关闭
                        await asyncio.sleep(0.5)
                        
                        # 删除 ChromaDB 物理文件
                        await self._delete_chroma_data(collection_name, kb_id)
                    
                    return True
                
                return False
                
            except Exception as e:
                logger.error(f"❌ 删除知识库失败: {str(e)}")
                raise RuntimeError(f"删除知识库失败: {str(e)}")
    
    async def _delete_chroma_data(self, collection_name: str, kb_id: str):
        """
        删除ChromaDB持久化数据（支持 Windows 文件锁定重试）
        
        Args:
            collection_name: ChromaDB collection名称
            kb_id: 知识库ID（用于日志）
        """
        import shutil
        import gc
        import time
        from pathlib import Path
        
        try:
            # ✅ 使用 build_chroma_persist_dir 确保路径一致性
            from ..utils.embedding.path_utils import build_chroma_persist_dir
            kb_dir = Path(build_chroma_persist_dir(collection_name))
            
            if not kb_dir.exists():
                logger.warning(f"⚠️ ChromaDB目录不存在，可能已被删除: {kb_dir}")
                return
            
            if not kb_dir.is_dir():
                logger.warning(f"⚠️ ChromaDB路径不是目录: {kb_dir}")
                return
            
            # 强制垃圾回收，释放可能的文件句柄
            gc.collect()
            
            # 尝试删除，最多重试3次（处理 Windows 文件锁定问题）
            max_retries = 3
            retry_delay = 1.0  # 秒
            
            for attempt in range(max_retries):
                try:
                    # 删除整个知识库文件夹
                    shutil.rmtree(kb_dir)
                    logger.info(f"🗑️ 已删除ChromaDB物理文件: {kb_dir}")
                    return
                    
                except PermissionError as pe:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"⚠️ 删除ChromaDB文件失败 (尝试 {attempt + 1}/{max_retries})，"
                            f"文件可能被占用，{retry_delay}秒后重试: {pe}"
                        )
                        # 再次强制垃圾回收
                        gc.collect()
                        # 等待后重试
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5  # 指数退避
                    else:
                        # 最后一次尝试失败，记录详细错误
                        logger.error(
                            f"❌ 删除ChromaDB物理文件失败 (已重试{max_retries}次)，"
                            f"文件被占用无法删除: {kb_dir}\n"
                            f"错误: {pe}\n"
                            f"建议: 请在后端服务停止后手动删除该目录"
                        )
                        raise
                        
                except Exception as e:
                    # 其他错误直接抛出
                    logger.error(f"❌ 删除ChromaDB物理文件时发生错误: {e}")
                    raise
                
        except Exception as e:
            # 删除物理文件失败不影响数据库删除，只记录错误
            logger.error(
                f"❌ 删除ChromaDB物理文件失败 (kb_id={kb_id}, collection={collection_name}): {str(e)}\n"
                f"数据库记录已删除，但物理文件可能需要手动清理"
            )
            # 不抛出异常，因为数据库记录已删除
    
    async def _delete_document_vectors(self, collection_name: str, doc_id: str, kb_settings: dict):
        """
        从ChromaDB中删除指定文档的所有向量数据（后台异步任务）
        
        Args:
            collection_name: ChromaDB collection名称
            doc_id: 文档ID
            kb_settings: 知识库配置
        """
        try:
            # 延迟导入，避免启动时加载
            from ..routers.kb import _get_kb_components
            
            # 构建vectorstore
            _, vectorstore, _ = _get_kb_components(kb_settings)
            
            # 获取ChromaDB collection
            # ChromaVectorStore 将 Chroma 实例存储在 _store 属性中
            chroma_collection = vectorstore._store._collection
            
            # 查询该文档的所有chunks
            # ChromaDB的metadata中存储了doc_id
            results = chroma_collection.get(
                where={"doc_id": doc_id}
            )
            
            if results and results['ids']:
                # 删除所有匹配的chunks
                chunk_ids = results['ids']
                chroma_collection.delete(ids=chunk_ids)
                logger.info(f"🗑️ 已从ChromaDB删除文档向量: doc_id={doc_id}, 删除{len(chunk_ids)}个chunks")
            else:
                logger.warning(f"⚠️ ChromaDB中未找到文档向量: doc_id={doc_id}")
                
        except Exception as e:
            # 删除向量失败不影响数据库删除，只记录错误
            logger.error(f"❌ 从ChromaDB删除文档向量失败 (doc_id={doc_id}, collection={collection_name}): {str(e)}", exc_info=True)
            # 不抛出异常，因为数据库记录已删除
    
    async def create_document(
        self,
        kb_id: str,
        user_id: str,
        filename: str,
        file_size: int,
        file_type: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> DocumentResponse:
        """
        创建文档记录（原子操作，带权限验证）
        
        Args:
            kb_id: 知识库ID
            user_id: 用户ID
            filename: 文件名
            file_size: 文件大小（字节）
            file_type: 文件类型
            task_id: 关联的处理任务ID
            metadata: 元数据
            
        Returns:
            创建的文档信息
            
        Raises:
            ValueError: 知识库不存在或无权限
            RuntimeError: 数据库操作失败
        """
        async with self._semaphore:
            try:
                # 验证知识库存在且属于用户
                kb = await self.kb_collection.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                if not kb:
                    raise ValueError("知识库不存在或无权限")
                
                now = datetime.utcnow().isoformat()
                
                doc_dict = {
                    "kb_id": kb_id,
                    "filename": filename,
                    "file_size": file_size,
                    "file_type": file_type,
                    "chunk_count": 0,
                    "status": "pending",
                    "error_message": None,
                    "metadata": metadata or {},
                    "task_id": task_id,
                    "created_at": now,
                    "updated_at": now
                }
                
                result = await self.doc_collection.insert_one(doc_dict)
                doc_dict["_id"] = result.inserted_id
                
                # 原子更新知识库统计（使用 $inc 避免并发问题）
                await self.kb_collection.update_one(
                    {"_id": ObjectId(kb_id)},
                    {
                        "$inc": {"document_count": 1, "total_size": file_size},
                        "$set": {"updated_at": now}
                    }
                )
                
                logger.info(f"知识库 {kb_id} 添加文档: {filename}")
                return self._doc_dict_to_response(doc_dict)
                
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"创建文档记录失败: {str(e)}")
                raise RuntimeError(f"创建文档记录失败: {str(e)}")
    
    async def get_documents(
        self,
        kb_id: str,
        user_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[DocumentResponse]:
        """
        获取知识库的文档列表（支持分页）
        支持用户自己的知识库和拉取的共享知识库
        
        Args:
            kb_id: 知识库ID（可以是用户自己的知识库ID或原始知识库ID）
            user_id: 用户ID
            skip: 跳过的记录数
            limit: 返回的最大记录数
            
        Returns:
            文档列表
        """
        async with self._semaphore:
            try:
                # 验证知识库存在且属于用户（先检查用户自己的知识库）
                kb = await self.kb_collection.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                
                # 如果找不到，检查是否是拉取的知识库
                if not kb:
                    pulled_kb = await self.db.pulled_knowledge_bases.find_one({
                        "user_id": user_id,
                        "original_kb_id": kb_id,
                        "enabled": True
                    })
                    if not pulled_kb:
                        return []
                
                # 限制 limit 最大值
                limit = min(limit, 1000)
                
                cursor = self.doc_collection.find({"kb_id": kb_id}) \
                    .sort("created_at", -1) \
                    .skip(skip) \
                    .limit(limit)
                
                docs = await cursor.to_list(length=limit)
                
                # 🎯 获取任务处理器以查询进度
                from ..services.async_task_processor import get_task_processor
                task_processor = get_task_processor()
                
                # 批量获取任务状态（提高性能）
                task_ids = [doc.get("task_id") for doc in docs if doc.get("task_id")]
                task_statuses = {}
                for task_id in task_ids:
                    try:
                        status = await task_processor.get_task_status(task_id)
                        if status:
                            task_statuses[task_id] = status
                    except Exception as e:
                        logger.debug(f"获取任务状态失败 {task_id}: {e}")
                
                # 转换为响应格式，并附加进度信息
                return [self._doc_dict_to_response(doc, task_statuses.get(doc.get("task_id"))) for doc in docs]
                
            except Exception as e:
                logger.error(f"获取文档列表失败: {str(e)}")
                raise RuntimeError(f"获取文档列表失败: {str(e)}")
    
    async def count_documents(
        self,
        kb_id: str,
        user_id: str
    ) -> int:
        """
        获取知识库的文档总数（用于分页）
        
        Args:
            kb_id: 知识库ID
            user_id: 用户ID
            
        Returns:
            文档总数
        """
        async with self._semaphore:
            try:
                # 验证知识库存在且属于用户（先检查用户自己的知识库）
                kb = await self.kb_collection.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                
                # 如果找不到，检查是否是拉取的知识库
                if not kb:
                    pulled_kb = await self.db.pulled_knowledge_bases.find_one({
                        "user_id": user_id,
                        "original_kb_id": kb_id,
                        "enabled": True
                    })
                    if not pulled_kb:
                        return 0
                
                # 统计文档总数
                total = await self.doc_collection.count_documents({"kb_id": kb_id})
                return total
                
            except Exception as e:
                logger.error(f"获取文档总数失败: {str(e)}")
                raise RuntimeError(f"获取文档总数失败: {str(e)}")
    
    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        chunk_count: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """
        更新文档状态（原子操作）
        
        Args:
            doc_id: 文档ID
            status: 状态 (pending, uploaded, processing, completed, failed)
            chunk_count: 分片数量
            error_message: 错误信息
            
        Returns:
            是否更新成功
        """
        async with self._semaphore:
            try:
                update_dict = {
                    "status": status,
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                if chunk_count is not None:
                    update_dict["chunk_count"] = chunk_count
                if error_message is not None:
                    update_dict["error_message"] = error_message
                
                result = await self.doc_collection.update_one(
                    {"_id": ObjectId(doc_id)},
                    {"$set": update_dict}
                )
                
                # 如果成功完成，原子更新知识库的分片计数
                if status == "completed" and chunk_count is not None and result.modified_count > 0:
                    doc = await self.doc_collection.find_one({"_id": ObjectId(doc_id)})
                    if doc:
                        await self.kb_collection.update_one(
                            {"_id": ObjectId(doc["kb_id"])},
                            {"$inc": {"chunk_count": chunk_count}}
                        )
                
                return result.modified_count > 0
                
            except Exception as e:
                logger.error(f"更新文档状态失败: {str(e)}")
                raise RuntimeError(f"更新文档状态失败: {str(e)}")
    
    async def update_document_file_url(
        self,
        doc_id: str,
        file_url: str,
        status: str = "uploaded"
    ) -> bool:
        """
        更新文档的 file_url 和状态
        
        Args:
            doc_id: 文档ID
            file_url: MinIO 文件路径
            status: 文档状态
            
        Returns:
            是否更新成功
        """
        async with self._semaphore:
            try:
                result = await self.doc_collection.update_one(
                    {"_id": ObjectId(doc_id)},
                    {"$set": {
                        "file_url": file_url,
                        "status": status,
                        "updated_at": datetime.utcnow().isoformat()
                    }}
                )
                return result.modified_count > 0
            except Exception as e:
                logger.error(f"更新文档file_url失败: {str(e)}")
                raise RuntimeError(f"更新文档file_url失败: {str(e)}")
    
    async def update_document_task_id(
        self,
        doc_id: str,
        task_id: str
    ) -> bool:
        """
        更新文档的任务ID
        
        Args:
            doc_id: 文档ID
            task_id: 任务ID
            
        Returns:
            是否更新成功
        """
        async with self._semaphore:
            try:
                result = await self.doc_collection.update_one(
                    {"_id": ObjectId(doc_id)},
                    {"$set": {
                        "task_id": task_id,
                        "updated_at": datetime.utcnow().isoformat()
                    }}
                )
                return result.modified_count > 0
            except Exception as e:
                logger.error(f"更新文档task_id失败: {str(e)}")
                raise RuntimeError(f"更新文档task_id失败: {str(e)}")
    
    async def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        获取文档原始数据（不含权限检查）
        
        Args:
            doc_id: 文档ID
            
        Returns:
            文档字典，不存在则返回 None
        """
        async with self._semaphore:
            try:
                doc = await self.doc_collection.find_one({"_id": ObjectId(doc_id)})
                if doc:
                    doc["id"] = str(doc["_id"])
                return doc
            except Exception as e:
                logger.error(f"获取文档失败: {str(e)}")
                raise RuntimeError(f"获取文档失败: {str(e)}")
    
    async def delete_document(
        self,
        doc_id: str,
        kb_id: str,
        user_id: str
    ) -> bool:
        """
        删除文档（原子操作，带权限验证）
        
        完整删除流程：
        1. 删除数据库中的文档记录
        2. 更新知识库统计信息
        3. 删除ChromaDB中的向量数据
        
        Args:
            doc_id: 文档ID
            kb_id: 知识库ID
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        async with self._semaphore:
            try:
                # 验证知识库存在且属于用户
                kb = await self.kb_collection.find_one({
                    "_id": ObjectId(kb_id),
                    "user_id": user_id
                })
                if not kb:
                    return False
                
                # 获取知识库配置
                kb_settings = kb.get("kb_settings", {})
                collection_name = kb_settings.get("collection_name")
                
                # 获取文档信息
                doc = await self.doc_collection.find_one({"_id": ObjectId(doc_id)})
                if not doc or doc["kb_id"] != kb_id:
                    return False
                
                doc_filename = doc.get("filename", "")
                file_url = doc.get("file_url", "")
                
                # 删除文档记录
                result = await self.doc_collection.delete_one({"_id": ObjectId(doc_id)})
                
                if result.deleted_count > 0:
                    # 原子更新知识库统计
                    await self.kb_collection.update_one(
                        {"_id": ObjectId(kb_id)},
                        {
                            "$inc": {
                                "document_count": -1,
                                "chunk_count": -doc.get("chunk_count", 0),
                                "total_size": -doc.get("file_size", 0)
                            },
                            "$set": {"updated_at": datetime.utcnow().isoformat()}
                        }
                    )
                    
                    logger.info(f"✅ 删除文档: {doc_id} (知识库: {kb_id}, 文件: {doc_filename})")
                    
                    # 🆕 删除MinIO中的文件
                    if file_url:
                        try:
                            from ..utils.minio_client import minio_client
                            minio_client.delete_kb_document(file_url)
                            logger.info(f"✅ 删除MinIO文件: {file_url}")
                        except Exception as e:
                            logger.error(f"❌ 删除MinIO文件失败: {e}")
                    
                    # 🆕 删除ChromaDB中的向量数据（异步但不阻塞）
                    if collection_name and doc_id:
                        asyncio.create_task(
                            self._delete_document_vectors(collection_name, doc_id, kb_settings)
                        )
                    
                    # TODO: 发送异步任务到队列，删除向量数据
                    # await self._queue_vector_deletion_task(kb_id, doc_id)
                    
                    return True
                
                return False
                
            except Exception as e:
                logger.error(f"删除文档失败: {str(e)}")
                raise RuntimeError(f"删除文档失败: {str(e)}")
    
    async def get_statistics(self, user_id: str) -> KBStatistics:
        """
        获取用户的知识库统计信息（聚合查询）
        
        Args:
            user_id: 用户ID
            
        Returns:
            统计信息
        """
        async with self._semaphore:
            try:
                # 使用聚合管道高效统计
                pipeline = [
                    {"$match": {"user_id": user_id}},
                    {
                        "$group": {
                            "_id": None,
                            "total_kbs": {"$sum": 1},
                            "total_documents": {"$sum": "$document_count"},
                            "total_chunks": {"$sum": "$chunk_count"},
                            "total_size": {"$sum": "$total_size"}
                        }
                    }
                ]
                
                result = await self.kb_collection.aggregate(pipeline).to_list(length=1)
                
                if result:
                    stats = result[0]
                    return KBStatistics(
                        total_kbs=stats.get("total_kbs", 0),
                        total_documents=stats.get("total_documents", 0),
                        total_chunks=stats.get("total_chunks", 0),
                        total_size=stats.get("total_size", 0)
                    )
                else:
                    return KBStatistics()
                    
            except Exception as e:
                logger.error(f"获取统计信息失败: {str(e)}")
                raise RuntimeError(f"获取统计信息失败: {str(e)}")
    
    async def get_document_by_id(
        self,
        doc_id: str,
        user_id: Optional[str] = None
    ) -> Optional[DocumentResponse]:
        """
        根据ID获取文档（可选权限验证）
        
        Args:
            doc_id: 文档ID
            user_id: 用户ID（如果提供，则验证权限）
            
        Returns:
            文档信息，如果不存在或无权限则返回 None
        """
        async with self._semaphore:
            try:
                doc = await self.doc_collection.find_one({"_id": ObjectId(doc_id)})
                if not doc:
                    return None
                
                # 如果提供了用户ID，验证权限
                if user_id:
                    kb = await self.kb_collection.find_one({
                        "_id": ObjectId(doc["kb_id"]),
                        "user_id": user_id
                    })
                    if not kb:
                        return None
                
                return self._doc_dict_to_response(doc)
                
            except Exception as e:
                logger.error(f"获取文档失败: {str(e)}")
                raise RuntimeError(f"获取文档失败: {str(e)}")
    
    def _kb_dict_to_response(self, kb_dict: Dict[str, Any]) -> KnowledgeBaseResponse:
        """将数据库字典转换为响应模型"""
        kb_settings = kb_dict.get("kb_settings", {})
        
        # 从 kb_settings 中提取 embedding_config
        embedding_config = kb_settings.get("embeddings", {})
        
        # 从 kb_settings 中提取 search_params
        search_params = kb_settings.get("search_params", {})
        
        # 构建响应数据，添加前端需要的字段
        response_data = {
            "id": str(kb_dict["_id"]),
            "name": kb_dict["name"],
            "description": kb_dict.get("description"),
            "user_id": kb_dict["user_id"],
            "embedding_config_id": kb_dict.get("embedding_config_id"),
            "kb_settings": kb_settings,
            "document_count": kb_dict.get("document_count", 0),
            "chunk_count": kb_dict.get("chunk_count", 0),
            "total_size": kb_dict.get("total_size", 0),
            "created_at": kb_dict["created_at"],
            "updated_at": kb_dict["updated_at"],
            # 添加前端需要的字段
            "collection_name": kb_settings.get("collection_name"),
            "vector_db": kb_settings.get("vector_db"),
            "embedding_config": embedding_config,
            "split_params": kb_settings.get("split_params", {}),
            "search_params": search_params,  # 添加检索参数
            "similarity_threshold": kb_settings.get("similarity_threshold"),
            "top_k": kb_settings.get("top_k"),
            # 添加共享信息字段
            "sharing_info": kb_dict.get("sharing_info")
        }
        
        return KnowledgeBaseResponse(**response_data)
    
    def _pulled_kb_to_response(self, pulled_kb_dict: Dict[str, Any]) -> KnowledgeBaseResponse:
        """将拉取的知识库字典转换为响应模型"""
        # 构建 kb_settings 格式（与原知识库保持一致）
        kb_settings = {
            "enabled": pulled_kb_dict.get("enabled", True),  # 添加 enabled 字段
            "collection_name": pulled_kb_dict.get("collection_name"),
            "vector_db": pulled_kb_dict.get("vector_db", "chroma"),
            "embeddings": pulled_kb_dict.get("embedding_config", {}),
            "split_params": pulled_kb_dict.get("split_params", {}),
            "similarity_threshold": pulled_kb_dict.get("similarity_threshold", 10.0),
            "top_k": pulled_kb_dict.get("top_k", 5)
        }
        
        # 处理时间字段：确保转换为 ISO 格式字符串
        created_at = pulled_kb_dict.get("pulled_at", pulled_kb_dict.get("created_at", datetime.utcnow()))
        updated_at = pulled_kb_dict.get("updated_at", datetime.utcnow())
        
        # 如果是 datetime 对象，转换为 ISO 格式字符串
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        if isinstance(updated_at, datetime):
            updated_at = updated_at.isoformat()
        
        # 构建响应数据
        response_data = {
            "id": str(pulled_kb_dict["_id"]),
            "name": pulled_kb_dict["name"],
            "description": pulled_kb_dict.get("description", ""),
            "user_id": pulled_kb_dict["user_id"],
            "embedding_config_id": None,  # 拉取的知识库没有embedding_config_id
            "kb_settings": kb_settings,
            "document_count": 0,  # 拉取的知识库使用原知识库的文档
            "chunk_count": 0,
            "total_size": 0,
            "created_at": created_at,
            "updated_at": updated_at,
            # 添加前端需要的字段
            "collection_name": pulled_kb_dict.get("collection_name"),
            "vector_db": pulled_kb_dict.get("vector_db", "chroma"),
            "embedding_config": pulled_kb_dict.get("embedding_config", {}),
            "split_params": pulled_kb_dict.get("split_params", {}),
            "similarity_threshold": pulled_kb_dict.get("similarity_threshold", 10.0),
            "top_k": pulled_kb_dict.get("top_k", 5)
        }
        
        return KnowledgeBaseResponse(**response_data)
    
    def _doc_dict_to_response(self, doc_dict: Dict[str, Any], task_status: Optional[Dict[str, Any]] = None) -> DocumentResponse:
        """
        将数据库字典转换为响应模型
        
        Args:
            doc_dict: 文档数据库记录
            task_status: 任务状态信息（可选）
        """
        # 从任务状态获取进度信息
        progress = 0.0
        progress_msg = ""
        
        if task_status:
            progress = task_status.get("progress", 0.0)
            progress_msg = task_status.get("progress_message", "")
        
        return DocumentResponse(
            id=str(doc_dict["_id"]),
            kb_id=doc_dict["kb_id"],
            filename=doc_dict["filename"],
            file_size=doc_dict["file_size"],
            file_type=doc_dict["file_type"],
            chunk_count=doc_dict.get("chunk_count", 0),
            status=doc_dict.get("status", "pending"),
            error_message=doc_dict.get("error_message"),
            metadata=doc_dict.get("metadata"),
            task_id=doc_dict.get("task_id"),
            upload_time=doc_dict["created_at"],
            update_time=doc_dict["updated_at"],
            progress=progress,
            progress_msg=progress_msg
        )
    


# 依赖注入函数
async def get_kb_service(db: AsyncIOMotorClient = None) -> KnowledgeBaseService:
    """
    获取知识库服务实例（依赖注入）
    
    Args:
        db: 数据库连接（通常由 FastAPI 依赖注入提供）
        
    Returns:
        知识库服务实例
    """
    if db is None:
        from ..database import get_database
        db = await anext(get_database())
    
    return KnowledgeBaseService(db[settings.mongodb_db_name])
