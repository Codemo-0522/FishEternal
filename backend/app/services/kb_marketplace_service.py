"""
知识库广场服务
处理知识库共享、拉取、管理等功能
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..models.kb_marketplace import (
    SharedKnowledgeBase,
    PulledKnowledgeBase,
    ShareKBRequest,
    PullKBRequest,
    UpdatePulledKBRequest,
    SharedKBResponse,
    PulledKBResponse
)
from ..database import (
    knowledge_bases_collection,
    shared_knowledge_bases_collection,
    pulled_knowledge_bases_collection,
    kb_documents_collection,
    users_collection
)

logger = logging.getLogger(__name__)


class KBMarketplaceService:
    """知识库广场服务"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.kb_collection = knowledge_bases_collection
        self.shared_kb_collection = shared_knowledge_bases_collection
        self.pulled_kb_collection = pulled_knowledge_bases_collection
        self.doc_collection = kb_documents_collection
        self.users_collection = users_collection
    
    async def share_knowledge_base(
        self,
        kb_id: str,
        user_id: str,
        description: Optional[str] = None
    ) -> SharedKBResponse:
        """
        共享知识库到广场
        只存储关联关系，所有数据动态从原知识库读取
        """
        # 1. 检查知识库是否存在且属于当前用户
        kb = await self.kb_collection.find_one({
            "_id": ObjectId(kb_id),
            "user_id": user_id
        })
        
        if not kb:
            raise ValueError("知识库不存在或无权限")
        
        # 2. 检查是否已经共享
        existing_share = await self.shared_kb_collection.find_one({
            "original_kb_id": kb_id,
            "owner_id": user_id
        })
        
        if existing_share:
            raise ValueError("该知识库已经共享到广场")
        
        # 3. 创建共享记录（极简设计：只存储关联关系）
        now = datetime.utcnow()
        shared_kb = {
            "original_kb_id": kb_id,  # 指向原知识库
            "owner_id": user_id,      # 指向原作者
            "description_override": description,  # 可选：覆盖原描述
            "pull_count": 0,          # 拉取计数
            "shared_at": now,
        }
        
        result = await self.shared_kb_collection.insert_one(shared_kb)
        shared_kb["_id"] = result.inserted_id
        
        # 4. 在原知识库上添加共享标记（便于前端快速判断）
        await self.kb_collection.update_one(
            {"_id": ObjectId(kb_id)},
            {"$set": {
                "sharing_info": {
                    "is_shared": True,
                    "shared_at": now,
                    "shared_kb_id": str(shared_kb["_id"])
                }
            }}
        )
        
        # 5. 返回响应（动态组装数据）
        return await self._build_shared_kb_response(shared_kb, user_id)
    
    async def _build_shared_kb_response(
        self, 
        shared_record: Dict[str, Any],
        current_user_id: str
    ) -> SharedKBResponse:
        """
        动态构建共享知识库响应（实时从原知识库读取数据）
        """
        # 1. 获取原知识库（实时数据）
        original_kb = await self.kb_collection.find_one({
            "_id": ObjectId(shared_record["original_kb_id"])
        })
        
        if not original_kb:
            raise ValueError("原知识库已被删除")
        
        # 2. 获取用户信息（实时用户名）
        owner = await self.users_collection.find_one({
            "_id": ObjectId(shared_record["owner_id"])
        })
        
        if not owner:
            raise ValueError("原作者不存在")
        
        # 3. 提取配置（不暴露密钥）
        kb_settings = original_kb.get("kb_settings", {})
        embeddings = kb_settings.get("embeddings", {})
        split_params = kb_settings.get("split_params", {})
        
        # 4. 处理时间字段（兼容 datetime 和 str）
        def to_iso_string(value):
            """将 datetime 或 str 转换为 ISO 格式字符串"""
            if isinstance(value, str):
                return value
            return value.isoformat() if value else datetime.utcnow().isoformat()
        
        # 5. 获取搜索参数
        search_params = kb_settings.get("search_params", {})
        distance_metric = search_params.get("distance_metric")
        
        # 6. 组装响应
        return SharedKBResponse(
            id=str(shared_record["_id"]),
            original_kb_id=shared_record["original_kb_id"],
            owner_id=shared_record["owner_id"],
            owner_account=owner.get("full_name") or owner.get("account", "未知用户"),  # ✅ 优先使用昵称，否则使用账号
            name=original_kb.get("name", ""),  # ✅ 实时名称
            description=original_kb.get("description", ""),  # ✅ 始终使用原知识库的实时描述
            collection_name=kb_settings.get("collection_name", ""),  # ✅ 实时
            vector_db=kb_settings.get("vector_db", "chroma"),
            embedding_provider=embeddings.get("provider", "未知"),  # 不暴露密钥
            embedding_model=embeddings.get("model", "未知"),
            chunk_size=split_params.get("chunk_size", 1024),  # ✅ 实时配置
            chunk_overlap=split_params.get("chunk_overlap", 100),
            separators=split_params.get("separators", []),
            distance_metric=distance_metric,  # ✅ 距离度量方式
            similarity_threshold=kb_settings.get("similarity_threshold", 10.0),
            top_k=kb_settings.get("top_k", 5),
            document_count=original_kb.get("document_count", 0),  # ✅ 实时统计
            chunk_count=original_kb.get("chunk_count", 0),  # ✅ 实时统计
            pull_count=shared_record.get("pull_count", 0),
            shared_at=to_iso_string(shared_record["shared_at"]),
            updated_at=to_iso_string(original_kb.get("updated_at", shared_record["shared_at"])),
            is_owner=(shared_record["owner_id"] == current_user_id)
        )
    
    async def unshare_knowledge_base(
        self,
        kb_id: str,
        user_id: str
    ) -> bool:
        """
        取消共享知识库
        """
        result = await self.shared_kb_collection.delete_one({
            "original_kb_id": kb_id,
            "owner_id": user_id
        })
        
        if result.deleted_count == 0:
            raise ValueError("共享记录不存在或无权限")
        
        # 清除原知识库上的共享标记
        await self.kb_collection.update_one(
            {"_id": ObjectId(kb_id)},
            {"$unset": {"sharing_info": ""}}
        )
        
        return True
    
    async def list_shared_knowledge_bases(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取广场知识库列表（动态查询原知识库数据）
        """
        # 1. 获取共享记录
        query = {}
        
        # 注意：搜索功能需要在动态查询后进行过滤
        # 因为name、description等字段不在shared_kb中存储
        
        # 获取总数
        total = await self.shared_kb_collection.count_documents(query)
        
        # 获取列表
        cursor = self.shared_kb_collection.find(query).sort(
            "shared_at", -1
        ).skip(skip).limit(limit)
        
        shared_records = await cursor.to_list(length=limit)
        
        # 2. 动态构建响应（实时从原知识库读取）
        results = []
        for record in shared_records:
            try:
                response = await self._build_shared_kb_response(record, user_id)
                
                # 搜索过滤（在内存中进行）
                if search:
                    search_lower = search.lower()
                    if (search_lower in response.name.lower() or
                        search_lower in response.description.lower() or
                        search_lower in response.owner_account.lower()):
                        results.append(response)
                else:
                    results.append(response)
            except Exception as e:
                # 如果原知识库被删除，跳过该记录
                logger.warning(f"跳过无效的共享记录 {record['_id']}: {str(e)}")
                continue
        
        return {
            "total": len(results),  # 过滤后的总数
            "skip": skip,
            "limit": limit,
            "items": results
        }
    
    async def pull_knowledge_base(
        self,
        shared_kb_id: str,
        user_id: str,
        embedding_config: Dict[str, Any],
        distance_metric: str = 'cosine',  # ⚠️ 此参数已废弃，将被忽略
        similarity_threshold: float = 0.5,
        top_k: int = 5
    ) -> PulledKBResponse:
        """
        拉取共享知识库到用户账号
        
        注意：拉取的知识库会强制使用原知识库的 distance_metric，
        因为向量索引已经用该度量方式构建，使用不同的度量方式会导致检索结果错误。
        """
        # 1. 检查共享知识库是否存在
        shared_record = await self.shared_kb_collection.find_one({
            "_id": ObjectId(shared_kb_id)
        })
        
        if not shared_record:
            raise ValueError("共享知识库不存在")
        
        # 2. 获取原知识库信息
        original_kb = await self.kb_collection.find_one({
            "_id": ObjectId(shared_record["original_kb_id"])
        })
        
        if not original_kb:
            raise ValueError("原知识库已被删除")
        
        # 3. 检查用户是否已经拉取过
        existing_pull = await self.pulled_kb_collection.find_one({
            "user_id": user_id,
            "shared_kb_id": shared_kb_id
        })
        
        if existing_pull:
            raise ValueError("您已经拉取过该知识库")
        
        # 4. 创建拉取记录（只存储用户自定义的配置）
        # ⚠️ 关键修复：不保存用户传入的 distance_metric，而是使用原知识库的
        now = datetime.utcnow()
        pulled_kb = {
            "user_id": user_id,
            "shared_kb_id": shared_kb_id,
            "original_kb_id": shared_record["original_kb_id"],
            "embedding_config": embedding_config,  # 用户自定义嵌入配置
            # ❌ 移除：不再允许用户自定义 distance_metric
            # "distance_metric": distance_metric,  
            "similarity_threshold": similarity_threshold,  # 用户自定义检索参数
            "top_k": top_k,  # 用户自定义检索参数
            "pulled_at": now,
            "updated_at": now,
            "enabled": True
        }
        
        result = await self.pulled_kb_collection.insert_one(pulled_kb)
        pulled_kb["_id"] = result.inserted_id
        
        # 5. 更新共享知识库的拉取计数
        await self.shared_kb_collection.update_one(
            {"_id": ObjectId(shared_kb_id)},
            {"$inc": {"pull_count": 1}}
        )
        
        # 6. 返回响应（动态组装数据）
        return await self._build_pulled_kb_response(pulled_kb)
    
    async def _build_pulled_kb_response(
        self,
        pulled_record: Dict[str, Any]
    ) -> PulledKBResponse:
        """
        动态构建拉取知识库响应（实时从原知识库读取数据）
        """
        # 1. 获取原知识库（实时数据）
        original_kb = await self.kb_collection.find_one({
            "_id": ObjectId(pulled_record["original_kb_id"])
        })
        
        if not original_kb:
            raise ValueError("原知识库已被删除")
        
        # 2. 获取共享记录
        shared_record = await self.shared_kb_collection.find_one({
            "_id": ObjectId(pulled_record["shared_kb_id"])
        })
        
        # 3. 获取用户信息
        owner = await self.users_collection.find_one({
            "_id": ObjectId(shared_record["owner_id"])
        })
        
        # 4. 提取配置
        kb_settings = original_kb.get("kb_settings", {})
        split_params = kb_settings.get("split_params", {})
        
        # 5. 处理时间字段（兼容 datetime 和 str）
        def to_iso_string(value):
            """将 datetime 或 str 转换为 ISO 格式字符串"""
            if isinstance(value, str):
                return value
            return value.isoformat() if value else datetime.utcnow().isoformat()
        
        # 6. 获取搜索参数（强制使用原知识库的 distance_metric）
        search_params = kb_settings.get("search_params", {})
        # ⚠️ 关键修复：拉取的知识库必须使用原知识库的 distance_metric
        distance_metric = search_params.get("distance_metric", "cosine")
        
        # 7. 组装响应
        return PulledKBResponse(
            id=str(pulled_record["_id"]),
            user_id=pulled_record["user_id"],
            shared_kb_id=pulled_record["shared_kb_id"],
            original_kb_id=pulled_record["original_kb_id"],
            owner_id=shared_record["owner_id"],
            owner_account=owner.get("full_name") or owner.get("account", "未知用户"),  # ✅ 优先使用昵称，否则使用账号
            name=original_kb.get("name", ""),  # ✅ 实时名称
            description=original_kb.get("description", ""),  # ✅ 实时描述
            collection_name=kb_settings.get("collection_name", ""),  # ✅ 实时
            vector_db=kb_settings.get("vector_db", "chroma"),
            embedding_config=pulled_record["embedding_config"],  # 用户自定义
            split_params={
                "chunk_size": split_params.get("chunk_size", 1024),  # ✅ 实时
                "chunk_overlap": split_params.get("chunk_overlap", 100),
                "separators": split_params.get("separators", [])
            },
            distance_metric=distance_metric,  # ✅ 用户自定义或原知识库的距离度量
            similarity_threshold=pulled_record["similarity_threshold"],  # 用户自定义
            top_k=pulled_record["top_k"],  # 用户自定义
            pulled_at=to_iso_string(pulled_record["pulled_at"]),
            updated_at=to_iso_string(pulled_record["updated_at"]),
            enabled=pulled_record["enabled"],
            document_count=original_kb.get("document_count", 0),  # ✅ 实时统计
            chunk_count=original_kb.get("chunk_count", 0)  # ✅ 实时统计
        )
    
    async def list_pulled_knowledge_bases(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        获取用户已拉取的知识库列表（动态查询原知识库数据）
        """
        query = {"user_id": user_id}
        
        # 获取总数
        total = await self.pulled_kb_collection.count_documents(query)
        
        # 获取列表
        cursor = self.pulled_kb_collection.find(query).sort(
            "pulled_at", -1
        ).skip(skip).limit(limit)
        
        pulled_records = await cursor.to_list(length=limit)
        
        # 动态构建响应（实时从原知识库读取）
        results = []
        for record in pulled_records:
            try:
                response = await self._build_pulled_kb_response(record)
                results.append(response)
            except Exception as e:
                # 如果原知识库被删除，跳过该记录
                logger.warning(f"跳过无效的拉取记录 {record['_id']}: {str(e)}")
                continue
        
        return {
            "total": len(results),
            "skip": skip,
            "limit": limit,
            "items": results
        }
    
    async def update_pulled_knowledge_base(
        self,
        pulled_kb_id: str,
        user_id: str,
        update_data: UpdatePulledKBRequest
    ) -> PulledKBResponse:
        """
        更新已拉取知识库的配置（只允许修改embedding配置、相似度和top_k）
        """
        # 1. 检查拉取记录是否存在
        pulled_kb = await self.pulled_kb_collection.find_one({
            "_id": ObjectId(pulled_kb_id),
            "user_id": user_id
        })
        
        if not pulled_kb:
            raise ValueError("拉取的知识库不存在或无权限")
        
        # 2. 构建更新数据
        update_fields = {"updated_at": datetime.utcnow()}
        
        if update_data.embedding_config is not None:
            update_fields["embedding_config"] = update_data.embedding_config
        
        if update_data.distance_metric is not None:
            update_fields["distance_metric"] = update_data.distance_metric
        
        if update_data.similarity_threshold is not None:
            update_fields["similarity_threshold"] = update_data.similarity_threshold
        
        if update_data.top_k is not None:
            update_fields["top_k"] = update_data.top_k
        
        if update_data.enabled is not None:
            update_fields["enabled"] = update_data.enabled
        
        # 3. 更新数据库
        await self.pulled_kb_collection.update_one(
            {"_id": ObjectId(pulled_kb_id)},
            {"$set": update_fields}
        )
        
        # 4. 获取更新后的数据并返回响应
        updated_kb = await self.pulled_kb_collection.find_one({
            "_id": ObjectId(pulled_kb_id)
        })
        
        return await self._build_pulled_kb_response(updated_kb)
    
    async def delete_pulled_knowledge_base(
        self,
        pulled_kb_id: str,
        user_id: str
    ) -> bool:
        """
        删除已拉取的知识库
        """
        result = await self.pulled_kb_collection.delete_one({
            "_id": ObjectId(pulled_kb_id),
            "user_id": user_id
        })
        
        if result.deleted_count == 0:
            raise ValueError("拉取的知识库不存在或无权限")
        
        return True
    
    async def get_shared_kb_by_original_id(
        self,
        original_kb_id: str,
        user_id: str
    ) -> Optional[SharedKBResponse]:
        """
        根据原始知识库ID获取共享记录（动态查询原知识库数据）
        """
        shared_record = await self.shared_kb_collection.find_one({
            "original_kb_id": original_kb_id,
            "owner_id": user_id
        })
        
        if not shared_record:
            return None
        
        return await self._build_shared_kb_response(shared_record, user_id)

