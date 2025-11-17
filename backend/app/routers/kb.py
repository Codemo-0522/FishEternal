from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from fastapi import Depends
from typing import Optional
import os
import re
import uuid
import hashlib
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

logger = logging.getLogger(__name__)

# ⚡ 延迟导入重量级模块，避免启动时加载：
# - ChromaVectorStore（ChromaDB 导入耗时约10秒）
# - ArkEmbeddings（volcengine SDK 导入耗时约20秒）
# - MiniLMEmbeddings（torch + sentence-transformers 导入耗时约45秒）
# - RecursiveCharacterTextSplitter（langchain_text_splitters 导入耗时约7秒）
# - OllamaEmbeddings（导入较快）
# 这些模块将在实际使用时才导入
from ..utils.embedding.pipeline import TextIngestionPipeline
from ..utils.auth import get_current_user
from ..models.user import User
from ..database import get_database
from ..config import settings

from ..utils.embedding.pipeline import Retriever
from ..utils.distance_utils import calculate_score_from_distance
from pydantic import BaseModel
from typing import List, Dict, Any

# 导入新的文档上传服务
from ..services.document_upload_service import get_document_upload_service

# 导入知识库服务和模型
from ..services.knowledge_base_service import KnowledgeBaseService
from ..models.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    DocumentResponse,
    KBStatistics,
    KBSearchRequest,
    KBSearchResponse,
    KBSearchResult,
    MultiKBSearchRequest,
    MultiKBSearchResult,
    MultiKBSearchResponse
)

class KnowledgeRetrievalRequest(BaseModel):
	query: str
	kb_settings: dict
	top_k: Optional[int] = 3

class KnowledgeRetrievalResponse(BaseModel):
	success: bool
	results: List[Dict[str, Any]]
	error: Optional[str] = None

router = APIRouter()


@router.get("/debug/vectorstore-stats")
async def get_vectorstore_stats(
    current_user: User = Depends(get_current_user)
):
    """
    调试端点：查看当前 VectorStore 连接状态
    """
    try:
        from ..services.vectorstore_manager import get_vectorstore_manager
        manager = get_vectorstore_manager()
        stats = manager.get_stats()
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"获取 VectorStore 统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _sanitize_collection_name(name: str) -> str:
	"""
	Chroma constraints:
	- 3-63 chars
	- start/end alphanumeric
	- allowed: alnum, '_', '-'
	- no consecutive periods; we avoid '.' entirely
	- not an IPv4 address (we avoid by using letters)
	"""
	original_name = name  # 保存原始名称用于生成确定性哈希
	if not name:
		name = "kb"
	# Replace unsupported chars with '-'
	name = re.sub(r"[^A-Za-z0-9_-]", "-", name)
	# Collapse multiple '-' or '_' to single '-'
	name = re.sub(r"[-_]{2,}", "-", name)
	# Trim non-alnum from ends
	name = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", name)
	# Ensure minimum length by padding with deterministic suffix
	if len(name) < 3:
		# 使用原始名称的哈希值生成确定性的后缀
		original_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:6]
		name = f"kb-{original_hash}"
	# Enforce max length 63
	if len(name) > 63:
		name = name[:63]
	# Final guard: if ends with non-alnum after slice, fix
	name = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", name)
	# If empty again, fallback with deterministic hash
	if not name:
		# 使用原始输入名称生成确定性的名称
		original_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:6]
		name = f"kb-{original_hash}"
	return name




# 允许 Unicode 的文件夹名清洗（仅去除文件系统不允许或危险字符）
_def_fs_forbidden = r"[<>:\\/\|?*]"

def _sanitize_folder_name(name: str) -> str:
	name = name or "kb"
	# 去除非法字符
	name = re.sub(_def_fs_forbidden, "-", name)
	# 去掉首尾空白及点/空格（Windows 末尾点与空格不合法）
	name = name.strip().strip(". ")
	# 避免空字符串
	if not name:
		name = f"kb-{uuid.uuid4().hex[:6]}"
	# 限长，避免过长路径
	if len(name) > 100:
		name = name[:100].rstrip(". ")
	return name


def _get_kb_components(kb_settings: dict):
	"""
	根据知识库配置获取组件（使用全局单例管理器）
	
	Returns:
		(splitter, vectorstore, embeddings)
	"""
	# ⚡ 延迟导入重量级模块
	from langchain_text_splitters import RecursiveCharacterTextSplitter
	from ..utils.embedding.path_utils import (
		build_chroma_persist_dir, get_chroma_collection_name,
		build_faiss_persist_dir, get_faiss_collection_name
	)
	from ..services.embedding_manager import get_embedding_manager
	from ..services.vectorstore_manager import get_vectorstore_manager
	
	if not kb_settings or not kb_settings.get("enabled"):
		raise HTTPException(status_code=400, detail="知识库未启用或配置为空")

	# 1. 解析配置
	embeddings_config = kb_settings.get("embeddings") or {}
	provider = embeddings_config.get("provider", "ollama")
	embed_model = embeddings_config.get("model")
	base_url = embeddings_config.get("base_url")
	api_key = embeddings_config.get("api_key")
	local_model_path = embeddings_config.get("local_model_path")

	# 2. 获取 Embedding 实例（全局共享，不会重复加载）
	embedding_manager = get_embedding_manager()
	try:
		embeddings = embedding_manager.get_or_create(
			provider=provider,
			model=embed_model,
			base_url=base_url,
			api_key=api_key,
			local_model_path=local_model_path,
			max_length=512,
			batch_size=8,
			normalize=True
		)
	except (ValueError, FileNotFoundError, RuntimeError) as e:
		raise HTTPException(status_code=400, detail=str(e))

	# 3. 创建 Splitter（轻量级，每次创建）
	sp = kb_settings.get("split_params") or {}
	chunk_size = int(sp.get("chunk_size", 500))
	chunk_overlap = int(sp.get("chunk_overlap", 100))
	separators = sp.get("separators") or ["\n\n", "\n", "。", "！", "？", "，", " ", ""]
	splitter = RecursiveCharacterTextSplitter(
		chunk_size=chunk_size,
		chunk_overlap=chunk_overlap,
		separators=list(separators),
	)

	# 4. 解析搜索参数（包含距离度量）
	search_params = kb_settings.get("search_params") or {}
	distance_metric = search_params.get("distance_metric", "cosine")  # 默认使用余弦距离
	
	# 5. 获取 VectorStore 实例（全局共享）
	vector_db = kb_settings.get("vector_db", "chroma")  # 默认使用chroma，支持faiss
	if vector_db not in ["chroma", "faiss"]:
		raise HTTPException(status_code=400, detail=f"不支持的向量数据库类型: {vector_db}，仅支持: chroma, faiss")
	
	collection_name_raw = kb_settings.get("collection_name") or "default"
	
	# 根据向量数据库类型选择路径构建函数
	if vector_db == "chroma":
		collection_name = get_chroma_collection_name(collection_name_raw)
		persist_dir = build_chroma_persist_dir(collection_name_raw)
	elif vector_db == "faiss":
		collection_name = get_faiss_collection_name(collection_name_raw)
		persist_dir = build_faiss_persist_dir(collection_name_raw)
	else:
		raise HTTPException(status_code=400, detail=f"不支持的向量数据库类型: {vector_db}")
	
	vectorstore_manager = get_vectorstore_manager()
	try:
		vectorstore = vectorstore_manager.get_or_create(
			collection_name=collection_name,
			persist_dir=persist_dir,
			embedding_function=embeddings,
			vector_db_type=vector_db,
			distance_metric=distance_metric  # 🎯 传递距离度量参数
		)
	except (ValueError, RuntimeError) as e:
		raise HTTPException(status_code=400, detail=str(e))

	return splitter, vectorstore, embeddings


@router.post("/kb/upload_and_ingest")
async def upload_and_ingest(
	file: UploadFile = File(...),
	kb_settings_json: str = Form(...),
	session_id: Optional[str] = Form(default=None),
	priority: Optional[str] = Form(default="NORMAL"),
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database),
):
	"""
	上传单个文件并异步处理（推荐）
	
	使用企业级异步处理，立即返回任务ID，避免阻塞主线程。
	
	Args:
		file: 上传的文件
		kb_settings_json: 知识库配置（JSON字符串）
		session_id: 会话ID（可选）
		priority: 任务优先级 LOW/NORMAL/HIGH（默认NORMAL）
		
	Returns:
		{
			"ok": true,
			"task_id": "uuid",
			"status": "processing",
			"message": "文档正在后台处理中...",
			"metadata": {...}
		}
	"""
	import json
	
	# 1. 解析知识库配置
	try:
		kb_settings = json.loads(kb_settings_json)
	except Exception:
		raise HTTPException(status_code=400, detail="kb_settings_json 不是合法的 JSON")

	if not file.filename:
		raise HTTPException(status_code=422, detail="缺少文件名")
	
	# 2. 立即更新会话的 kb_settings（不等待文档处理完成）
	if session_id:
		doc_service = get_document_upload_service()
		success, error = await doc_service.update_session_kb_config(
			db=db,
			session_id=session_id,
			user_id=str(current_user.id),
			kb_settings=kb_settings,
			kb_parsed=False
		)
		if not success:
			raise HTTPException(status_code=404, detail=error)
	
	# 3. 读取文件内容
	content_bytes = await file.read()
	
	# 4. 使用文档上传服务异步处理
	doc_service = get_document_upload_service()
	result = await doc_service.upload_and_process_async(
		content=content_bytes,
		filename=file.filename,
		kb_settings=kb_settings,
		session_id=session_id,
		user_id=str(current_user.id),
		priority=priority,
		timeout=600.0,
		max_retries=3
	)
	
	if not result.success:
		raise HTTPException(status_code=500, detail=result.error)
	
	return result.to_dict()


@router.get("/kb/supported_formats")
async def get_supported_formats():
	"""获取支持的文档格式信息"""
	try:
		from ..utils.document_parsers import get_supported_formats_info
		return get_supported_formats_info()
	except Exception as e:
		logger.error(f"获取支持格式信息失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"获取支持格式信息失败: {str(e)}")


@router.get("/kb/task_status/{task_id}")
async def get_task_status(
	task_id: str,
	current_user: User = Depends(get_current_user)
):
	"""获取任务状态和进度"""
	try:
		from ..utils.embedding.task_queue import get_task_queue
		
		task_queue = await get_task_queue()
		task_info = await task_queue.get_task_status(task_id)
		
		if not task_info:
			raise HTTPException(status_code=404, detail="任务不存在")
		
		# 检查权限（只能查看自己的任务）
		if task_info.metadata.get("user_id") != str(current_user.id):
			raise HTTPException(status_code=403, detail="无权限访问此任务")
		
		return {
			"task_id": task_info.task_id,
			"status": task_info.status.value,
			"progress": task_info.progress,
			"created_at": task_info.created_at.isoformat(),
			"started_at": task_info.started_at.isoformat() if task_info.started_at else None,
			"completed_at": task_info.completed_at.isoformat() if task_info.completed_at else None,
			"result": task_info.result,
			"error": task_info.error,
			"retry_count": task_info.retry_count,
			"metadata": task_info.metadata
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"获取任务状态失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")


@router.post("/kb/cancel_task/{task_id}")
async def cancel_task(
	task_id: str,
	current_user: User = Depends(get_current_user)
):
	"""取消任务"""
	try:
		from ..utils.embedding.task_queue import get_task_queue
		
		task_queue = await get_task_queue()
		task_info = await task_queue.get_task_status(task_id)
		
		if not task_info:
			raise HTTPException(status_code=404, detail="任务不存在")
		
		# 检查权限
		if task_info.metadata.get("user_id") != str(current_user.id):
			raise HTTPException(status_code=403, detail="无权限操作此任务")
		
		success = await task_queue.cancel_task(task_id)
		
		return {
			"ok": success,
			"message": "任务已取消" if success else "任务无法取消（可能已完成或不存在）"
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"取消任务失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")


@router.get("/kb/queue_stats")
async def get_queue_stats(
	current_user: User = Depends(get_current_user)
):
	"""获取队列统计信息（管理员功能）"""
	try:
		from ..utils.embedding.task_queue import get_task_queue
		
		task_queue = await get_task_queue()
		stats = task_queue.get_stats()
		
		return {
			"ok": True,
			"stats": stats
		}
		
	except Exception as e:
		logger.error(f"获取队列统计失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"获取队列统计失败: {str(e)}")


@router.post("/kb/retrieve", response_model=KnowledgeRetrievalResponse)
async def retrieve_knowledge(
	request: KnowledgeRetrievalRequest,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database),
):
	"""
	根据查询文本和会话的知识库配置进行向量检索，返回相关文档片段
	"""
	try:
		# 检查知识库是否启用
		if not request.kb_settings or not request.kb_settings.get("enabled"):
			return KnowledgeRetrievalResponse(
				success=True,
				results=[],
				error="知识库未启用"
			)
		
		# 构建知识库组件（使用全局单例）
		_, vectorstore, _ = _get_kb_components(request.kb_settings)
		
		# 从配置中获取相似度阈值和距离度量类型
		similarity_threshold = request.kb_settings.get("similarity_threshold", 0.5) if isinstance(request.kb_settings, dict) else 0.5
		search_params = request.kb_settings.get("search_params") or {}
		distance_metric = search_params.get("distance_metric", "cosine")
		
		# 创建检索器，应用相似度阈值和距离度量
		retriever = Retriever(
			vector_store=vectorstore, 
			top_k=request.top_k, 
			similarity_threshold=similarity_threshold,
			distance_metric=distance_metric
		)
		
		# 执行检索 - ✅ 使用异步方法，避免阻塞事件循环
		search_results = await retriever.search(request.query, top_k=request.top_k)
		
		# 格式化结果
		formatted_results = []
		for doc, score in search_results:
			formatted_results.append({
				"content": doc.page_content,
				"score": float(score),
				"metadata": doc.metadata
			})
		
		return KnowledgeRetrievalResponse(
			success=True,
			results=formatted_results
		)
		
	except Exception as e:
		return KnowledgeRetrievalResponse(
			success=False,
			results=[],
			error=f"检索失败: {str(e)}"
		) 

@router.post("/kb/resolve_references")
async def resolve_references(
	payload: dict,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database),
):
	"""
	将精简引用 [{document_id, chunk_id}] 展开为富引用。
	输入示例：{"kb_settings": {...}, "items": [{"document_id":"path/file.txt","chunk_id":"uuid"}, ...]}
	"""
	try:
		items = payload.get("items") or []
		kb_settings = payload.get("kb_settings") or {}
		if not items:
			return {"success": True, "results": []}

		# 构建向量库（必须与入库时一致，使用全局单例）
		_, vectorstore, _ = _get_kb_components(kb_settings)
		if not hasattr(vectorstore, "get_by_ids"):
			raise HTTPException(status_code=400, detail="向量库未实现 get_by_ids，无法解析引用")

		ids = [it.get("chunk_id") for it in items if it.get("chunk_id")]
		if not ids:
			return {"success": True, "results": []}

		# ✅ 使用异步方法，避免阻塞事件循环
		docs = await vectorstore.get_by_ids(ids)
		results = []
		# 将返回的文档与输入的 items 按 chunk_id 对齐
		id_to_doc = {doc.metadata.get("chunk_id"): doc for doc in docs}
		for it in items:
			chunk_id = it.get("chunk_id")
			doc = id_to_doc.get(chunk_id)
			if not doc:
				continue
			meta = doc.metadata or {}
			results.append({
				"document_id": meta.get("document_id") or it.get("document_id"),
				"chunk_id": chunk_id,
				"content": doc.page_content,
				"metadata": meta,
			})

		return {"success": True, "results": results}
	except HTTPException:
		raise
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"解析引用失败: {str(e)}")


# ================================
# 知识库管理 API（新增）
# ================================

@router.post("/kb/create", response_model=KnowledgeBaseResponse)
async def create_knowledge_base(
	request_data: KnowledgeBaseCreateRequest,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	创建知识库
	
	特性：
	- 完全异步操作
	- 自动验证权限
	- 支持高并发
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		# 将前端格式转换为后端格式
		kb_settings = {
			"enabled": True,
			"vector_db": request_data.vector_db,
			"collection_name": request_data.collection_name or _sanitize_collection_name(request_data.name),
			"embeddings": request_data.embedding_config.model_dump(exclude_none=True),
			"split_params": request_data.split_params.model_dump(exclude_none=True),
			"search_params": request_data.search_params.model_dump(exclude_none=True) if request_data.search_params else {},
			# 兼容旧版字段
			"similarity_threshold": request_data.similarity_threshold,
			"top_k": request_data.top_k
		}
		
		kb_data = KnowledgeBaseCreate(
			name=request_data.name,
			description=request_data.description,
			kb_settings=kb_settings
		)
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		result = await kb_service.create_knowledge_base(
			user_id=current_user.id,
			kb_data=kb_data
		)
		
		return result
		
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))
	except Exception as e:
		logger.error(f"创建知识库失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"创建知识库失败: {str(e)}")


@router.get("/kb/list")
async def list_knowledge_bases(
	skip: int = 0,
	limit: int = 100,
	include_pulled: bool = False,  # 新增参数：是否包含拉取的知识库
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	获取用户的知识库列表
	
	特性：
	- 支持分页
	- 异步查询
	- 按创建时间倒序
	- 默认只返回用户自己创建的知识库，可通过 include_pulled=true 包含拉取的知识库
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..services.kb_marketplace_service import KBMarketplaceService
		
		# 获取用户自己的知识库
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		own_kbs = await kb_service.get_knowledge_bases(
			user_id=current_user.id,
			skip=skip,
			limit=limit
		)
		
		pulled_kbs = []
		
		# 如果需要包含拉取的知识库
		if include_pulled:
			# 获取用户拉取的知识库
			marketplace_service = KBMarketplaceService(db[settings.mongodb_db_name])
			pulled_result = await marketplace_service.list_pulled_knowledge_bases(
				user_id=current_user.id,
				skip=0,
				limit=1000  # 获取所有拉取的知识库
			)
			
			# 将拉取的知识库转换为标准格式，添加标记
			for pulled_kb in pulled_result["items"]:
				if pulled_kb.enabled:  # 只返回启用的
					# 处理时间字段：确保是字符串格式
					created_at = pulled_kb.pulled_at
					if isinstance(created_at, datetime):
						created_at = created_at.isoformat()
					
					pulled_kbs.append({
						"id": pulled_kb.id,
						"name": f"[共享] {pulled_kb.name}",  # 添加标记
						"description": pulled_kb.description,
						"document_count": pulled_kb.document_count,
						"chunk_count": pulled_kb.chunk_count,
						"created_at": created_at,
						"is_pulled": True,  # 标记为拉取的知识库
						"owner_account": pulled_kb.owner_account,
						"kb_settings": {
							"collection_name": pulled_kb.collection_name,
							"vector_db": pulled_kb.vector_db,
							"embeddings": pulled_kb.embedding_config,
							"split_params": pulled_kb.split_params,
							"similarity_threshold": pulled_kb.similarity_threshold,
							"top_k": pulled_kb.top_k
						}
					})
		
		# 合并两个列表（如果需要）
		all_kbs = own_kbs + pulled_kbs
		
		return {
			"success": True,
			"knowledge_bases": all_kbs,
			"own_count": len(own_kbs),
			"pulled_count": len(pulled_kbs)
		}
		
	except Exception as e:
		logger.error(f"获取知识库列表失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"获取知识库列表失败: {str(e)}")


@router.get("/kb/statistics", response_model=KBStatistics)
async def get_statistics(
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	获取用户的知识库统计信息
	
	特性：
	- 聚合查询
	- 异步计算
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		result = await kb_service.get_statistics(current_user.id)
		
		return result
		
	except Exception as e:
		logger.error(f"获取统计信息失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/kb/system/stats")
async def get_system_stats(
	current_user: User = Depends(get_current_user)
):
	"""
	获取系统统计信息（管理员功能）
	
	返回：
	- 任务队列状态
	- 性能指标
	- 资源使用情况
	"""
	try:
		from ..services.async_task_processor import get_task_processor
		
		processor = get_task_processor()
		stats = processor.get_statistics()
		
		return {
			"success": True,
			"stats": stats,
			"timestamp": datetime.utcnow().isoformat()
		}
		
	except Exception as e:
		logger.error(f"获取系统统计失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"获取系统统计失败: {str(e)}")


@router.get("/kb/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(
	kb_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	获取单个知识库详情
	
	特性：
	- 自动权限验证
	- 异步查询
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		result = await kb_service.get_knowledge_base(
			kb_id=kb_id,
			user_id=current_user.id
		)
		
		if not result:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		return result
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"获取知识库失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"获取知识库失败: {str(e)}")


@router.put("/kb/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(
	kb_id: str,
	kb_data: KnowledgeBaseUpdate,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	更新知识库
	
	特性：
	- 原子操作
	- 权限验证
	- 异步更新
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		result = await kb_service.update_knowledge_base(
			kb_id=kb_id,
			user_id=current_user.id,
			kb_data=kb_data
		)
		
		if not result:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		return result
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"更新知识库失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"更新知识库失败: {str(e)}")


@router.delete("/kb/{kb_id}")
async def delete_knowledge_base(
	kb_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	删除知识库
	
	特性：
	- 删除所有关联文档
	- 异步删除向量数据（后台任务）
	- 原子操作
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		success = await kb_service.delete_knowledge_base(
			kb_id=kb_id,
			user_id=current_user.id
		)
		
		if not success:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		return {"success": True, "message": "知识库已删除"}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"删除知识库失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"删除知识库失败: {str(e)}")


@router.get("/kb/{kb_id}/documents")
async def list_documents(
	kb_id: str,
	skip: int = 0,
	limit: int = 100,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	获取知识库的文档列表
	
	特性：
	- 支持分页
	- 异步查询
	- 按创建时间倒序
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		
		# 获取文档列表
		result = await kb_service.get_documents(
			kb_id=kb_id,
			user_id=current_user.id,
			skip=skip,
			limit=limit
		)
		
		# 获取文档总数（用于分页）
		total = await kb_service.count_documents(kb_id, current_user.id)
		
		return {
			"success": True,
			"documents": result,
			"pagination": {
				"page": (skip // limit) + 1,
				"page_size": limit,
				"total": total,
				"total_pages": (total + limit - 1) // limit if limit > 0 else 0
			}
		}
		
	except Exception as e:
		logger.error(f"获取文档列表失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")


@router.post("/kb/{kb_id}/upload")
async def upload_document(
	kb_id: str,
	file: UploadFile = File(...),
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	【新】仅上传文档到服务器（不解析）
	
	流程：
	1. 验证文件格式
	2. 上传到 MinIO（用户隔离）
	3. 创建文档记录（status=uploaded）
	4. 返回文档信息
	
	用户需要手动调用 /parse 接口进行解析
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..services.document_upload_service import DocumentUploadService
		from ..utils.minio_client import minio_client
		import mimetypes
		
		# 验证知识库存在
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		if not kb:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 获取知识库的 collection_name（用于 MinIO 路径）
		collection_name = kb.collection_name
		if not collection_name:
			raise HTTPException(status_code=500, detail="知识库配置错误：缺少 collection_name")
		
		# 验证文件格式
		upload_service = DocumentUploadService()
		is_valid, error = upload_service.validate_file(file.filename)
		if not is_valid:
			raise HTTPException(status_code=400, detail=error)
		
		# 读取文件内容
		file_content = await file.read()
		file_size = len(file_content)
		file_type = Path(file.filename).suffix.lower()
		
		# 创建文档记录（status=uploaded）
		doc = await kb_service.create_document(
			kb_id=kb_id,
			user_id=current_user.id,
			filename=file.filename,
			file_size=file_size,
			file_type=file_type
		)
		
		# 上传文件到 MinIO（用户隔离）
		# 使用 collection_name 作为路径前缀（而非 kb_id），因为用户可能修改知识库名称
		content_type = mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
		file_url = minio_client.upload_kb_document(
			file_data=file_content,
			user_id=current_user.id,
			collection_name=collection_name,  # 使用 collection_name 代替 kb_id
			doc_id=str(doc.id),
			filename=file.filename,
			content_type=content_type
		)
		
		# 更新文档记录，添加 file_url 和 status=uploaded
		await kb_service.update_document_file_url(
			doc_id=str(doc.id),
			file_url=file_url,
			status="uploaded"
		)
		
		logger.info(f"✅ 文档上传成功: {file.filename}, doc_id={doc.id}")
		
		return {
			"success": True,
			"message": "文档上传成功，请点击解析按钮开始处理",
			"doc_id": str(doc.id),
			"filename": file.filename,
			"file_size": file_size,
			"file_url": file_url,
			"status": "uploaded"
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"上传文档失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"上传文档失败: {str(e)}")


@router.post("/kb/{kb_id}/documents/{doc_id}/parse")
async def parse_document(
	kb_id: str,
	doc_id: str,
	priority: str = "normal",
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	【新】解析已上传的文档（从 MinIO 读取）
	
	流程：
	1. 验证文档存在且状态为 uploaded
	2. 从 MinIO 下载文档
	3. 提交解析任务到后台队列
	4. 返回任务ID
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..services.document_processor import get_document_processor
		from ..services.async_task_processor import TaskPriority
		from ..utils.minio_client import minio_client
		import tempfile
		import os
		
		# 验证知识库存在
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		if not kb:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 获取文档记录
		doc = await kb_service.get_document(doc_id)
		if not doc:
			raise HTTPException(status_code=404, detail="文档不存在")
		
		if doc.get("kb_id") != kb_id:
			raise HTTPException(status_code=403, detail="文档不属于此知识库")
		
		# 检查文档状态
		if not doc.get("file_url"):
			raise HTTPException(status_code=400, detail="文档尚未上传到服务器")
		
		# 从 MinIO 下载文档
		file_content = minio_client.download_kb_document(doc["file_url"])
		
		# 保存到临时目录（供解析器使用）
		temp_dir = tempfile.gettempdir()
		file_hash = hashlib.md5(file_content).hexdigest()
		file_path = os.path.join(temp_dir, f"{file_hash}_{doc['filename']}")
		
		with open(file_path, 'wb') as f:
			f.write(file_content)
		
		# 提交到异步任务队列（内部会更新状态为 processing）
		processor = await get_document_processor(db[settings.mongodb_db_name])
		
		# 转换优先级
		priority_map = {
			"low": TaskPriority.LOW,
			"normal": TaskPriority.NORMAL,
			"high": TaskPriority.HIGH,
			"urgent": TaskPriority.URGENT
		}
		task_priority = priority_map.get(priority.lower(), TaskPriority.NORMAL)
		
		try:
			task_id = await processor.submit_document_processing(
				kb_id=kb_id,
				doc_id=doc_id,
				user_id=current_user.id,
				file_path=file_path,
				filename=doc["filename"],
				kb_settings=kb.kb_settings,
				priority=task_priority
			)
			
			# 更新任务ID
			await kb_service.update_document_task_id(doc_id, task_id)
		except Exception as e:
			# 任务提交失败，确保文档状态不会卡在 processing
			await kb_service.update_document_status(
				doc_id,
				"failed",
				error_message=str(e)
			)
			raise
		
		logger.info(f"✅ 文档解析任务已提交: {doc['filename']}, task_id={task_id}")
		
		return {
			"success": True,
			"message": "文档解析任务已提交",
			"task_id": task_id,
			"doc_id": doc_id,
			"status": "processing"
		}
		
	except HTTPException:
		raise
	except RuntimeError as e:
		raise HTTPException(status_code=429, detail=str(e))
	except Exception as e:
		logger.error(f"解析文档失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"解析文档失败: {str(e)}")


@router.post("/kb/{kb_id}/documents/batch-parse")
async def batch_parse_documents(
	kb_id: str,
	doc_ids: List[str] = Body(..., embed=True),
	priority: str = "normal",
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	批量解析已上传的文档
	
	Args:
		kb_id: 知识库ID
		doc_ids: 文档ID列表
		priority: 任务优先级 (low/normal/high/urgent)
	
	Returns:
		{
			"success": True,
			"message": "批量解析任务已提交",
			"total": 总文档数,
			"submitted": 成功提交数,
			"failed": 失败数,
			"task_ids": [任务ID列表],
			"errors": [错误信息列表]
		}
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..services.document_processor import get_document_processor
		from ..services.async_task_processor import TaskPriority
		from ..utils.minio_client import minio_client
		import tempfile
		import os
		
		# 验证参数
		if not doc_ids:
			raise HTTPException(status_code=422, detail="文档ID列表不能为空")
		
		logger.info(f"🔄 开始批量解析文档: kb_id={kb_id}, 文档数={len(doc_ids)}")
		
		# 验证知识库存在
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		if not kb:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 获取文档处理器
		processor = await get_document_processor(db[settings.mongodb_db_name])
		
		# 转换优先级
		priority_map = {
			"low": TaskPriority.LOW,
			"normal": TaskPriority.NORMAL,
			"high": TaskPriority.HIGH,
			"urgent": TaskPriority.URGENT
		}
		task_priority = priority_map.get(priority.lower(), TaskPriority.NORMAL)
		
		# 批量处理文档（并发处理以提高效率）
		results = {
			"submitted": 0,
			"failed": 0,
			"task_ids": [],
			"errors": []
		}
		
		async def process_single_document(doc_id: str):
			"""处理单个文档的异步函数"""
			try:
				# 获取文档记录
				doc = await kb_service.get_document(doc_id)
				if not doc:
					return {"success": False, "error": f"文档 {doc_id} 不存在"}
				
				if doc.get("kb_id") != kb_id:
					return {"success": False, "error": f"文档 {doc_id} 不属于此知识库"}
				
				# 检查文档状态
				if not doc.get("file_url"):
					return {"success": False, "error": f"文档 {doc['filename']} 尚未上传到服务器"}
				
				# 从 MinIO 下载文档
				file_content = minio_client.download_kb_document(doc["file_url"])
				
				# 保存到临时目录（供解析器使用）
				temp_dir = tempfile.gettempdir()
				file_hash = hashlib.md5(file_content).hexdigest()
				file_path = os.path.join(temp_dir, f"{file_hash}_{doc['filename']}")
				
				with open(file_path, 'wb') as f:
					f.write(file_content)
				
				# 提交到异步任务队列（内部会更新状态为 processing）
				task_id = await processor.submit_document_processing(
					kb_id=kb_id,
					doc_id=doc_id,
					user_id=current_user.id,
					file_path=file_path,
					filename=doc["filename"],
					kb_settings=kb.kb_settings,
					priority=task_priority
				)
				
				# 更新任务ID
				await kb_service.update_document_task_id(doc_id, task_id)
				
				logger.info(f"✅ 文档解析任务已提交: {doc['filename']}, task_id={task_id}")
				return {"success": True, "task_id": task_id, "filename": doc['filename']}
				
			except Exception as e:
				error_msg = f"文档 {doc_id} 处理失败: {str(e)}"
				logger.error(error_msg)
				return {"success": False, "error": error_msg}
		
		# 🚀 并发处理所有文档（使用 asyncio.gather）
		logger.info(f"🚀 开始并发提交 {len(doc_ids)} 个文档解析任务")
		processing_results = await asyncio.gather(
			*[process_single_document(doc_id) for doc_id in doc_ids],
			return_exceptions=True
		)
		
		# 统计结果
		for result in processing_results:
			if isinstance(result, Exception):
				results["failed"] += 1
				results["errors"].append(f"异常: {str(result)}")
			elif result.get("success"):
				results["submitted"] += 1
				results["task_ids"].append(result["task_id"])
			else:
				results["failed"] += 1
				error_msg = result.get("error", "未知错误")
				results["errors"].append(error_msg)
				logger.error(f"文档处理失败: {error_msg}", exc_info=True)
				# 注意：单个文档处理失败时，错误处理已在process_single_document中完成
				# 这里不需要再次回滚状态
		
		logger.info(f"✅ 批量解析完成: 提交={results['submitted']}, 失败={results['failed']}")
		
		return {
			"success": True,
			"message": f"批量解析任务已提交: 成功 {results['submitted']} 个，失败 {results['failed']} 个",
			"total": len(doc_ids),
			"submitted": results["submitted"],
			"failed": results["failed"],
			"task_ids": results["task_ids"],
			"errors": results["errors"]
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"批量解析文档失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"批量解析文档失败: {str(e)}")


@router.post("/kb/{kb_id}/documents/batch-parse-all")
async def batch_parse_all_documents(
	kb_id: str,
	priority: str = "normal",
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	批量解析知识库中所有未解析的文档（不受分页限制）
	
	自动筛选出状态为 'uploaded' 的文档进行解析
	
	Args:
		kb_id: 知识库ID
		priority: 任务优先级 (low/normal/high/urgent)
	
	Returns:
		{
			"success": True,
			"message": "批量解析任务已提交",
			"total": 总文档数,
			"submitted": 成功提交数,
			"failed": 失败数,
			"task_ids": [任务ID列表],
			"errors": [错误信息列表]
		}
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..services.document_processor import get_document_processor
		from ..services.async_task_processor import TaskPriority
		from ..utils.minio_client import minio_client
		import tempfile
		import os
		
		logger.info(f"🔄 开始批量解析所有文档: kb_id={kb_id}")
		
		# 验证知识库存在
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		if not kb:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 获取所有状态为 'uploaded' 的文档（不分页，查询全部）
		collection = db[settings.mongodb_db_name].documents
		cursor = collection.find({
			"kb_id": kb_id,
			"status": "uploaded"
		})
		
		unparsed_docs = await cursor.to_list(length=None)  # length=None 表示获取全部
		
		if not unparsed_docs:
			return {
				"success": True,
				"message": "没有需要解析的文档",
				"total": 0,
				"submitted": 0,
				"failed": 0,
				"task_ids": [],
				"errors": []
			}
		
		doc_ids = [str(doc["_id"]) for doc in unparsed_docs]
		logger.info(f"📋 找到 {len(doc_ids)} 个未解析的文档")
		
		# 获取文档处理器
		processor = await get_document_processor(db[settings.mongodb_db_name])
		
		# 转换优先级
		priority_map = {
			"low": TaskPriority.LOW,
			"normal": TaskPriority.NORMAL,
			"high": TaskPriority.HIGH,
			"urgent": TaskPriority.URGENT
		}
		task_priority = priority_map.get(priority.lower(), TaskPriority.NORMAL)
		
		# 批量处理文档（并发处理以提高效率）
		results = {
			"submitted": 0,
			"failed": 0,
			"task_ids": [],
			"errors": []
		}
		
		async def process_single_document(doc_id: str):
			"""处理单个文档的异步函数"""
			try:
				# 获取文档记录
				doc = await kb_service.get_document(doc_id)
				if not doc:
					return {"success": False, "error": f"文档 {doc_id} 不存在"}
				
				if doc.get("kb_id") != kb_id:
					return {"success": False, "error": f"文档 {doc_id} 不属于此知识库"}
				
				# 检查文档状态
				if not doc.get("file_url"):
					return {"success": False, "error": f"文档 {doc['filename']} 尚未上传到服务器"}
				
				# 从 MinIO 下载文档
				file_content = minio_client.download_kb_document(doc["file_url"])
				
				# 保存到临时目录（供解析器使用）
				temp_dir = tempfile.gettempdir()
				file_hash = hashlib.md5(file_content).hexdigest()
				file_path = os.path.join(temp_dir, f"{file_hash}_{doc['filename']}")
				
				with open(file_path, 'wb') as f:
					f.write(file_content)
				
				# 提交到异步任务队列（内部会更新状态为 processing）
				task_id = await processor.submit_document_processing(
					kb_id=kb_id,
					doc_id=doc_id,
					user_id=current_user.id,
					file_path=file_path,
					filename=doc["filename"],
					kb_settings=kb.kb_settings,
					priority=task_priority
				)
				
				# 更新任务ID
				await kb_service.update_document_task_id(doc_id, task_id)
				
				logger.info(f"✅ 文档解析任务已提交: {doc['filename']}, task_id={task_id}")
				return {"success": True, "task_id": task_id, "filename": doc['filename']}
				
			except Exception as e:
				error_msg = f"文档 {doc_id} 处理失败: {str(e)}"
				logger.error(error_msg)
				return {"success": False, "error": error_msg}
		
		# 🚀 并发处理所有文档（使用 asyncio.gather）
		logger.info(f"🚀 开始并发提交 {len(doc_ids)} 个文档解析任务")
		processing_results = await asyncio.gather(
			*[process_single_document(doc_id) for doc_id in doc_ids],
			return_exceptions=True
		)
		
		# 统计结果
		for result in processing_results:
			if isinstance(result, Exception):
				results["failed"] += 1
				results["errors"].append(f"异常: {str(result)}")
			elif result.get("success"):
				results["submitted"] += 1
				results["task_ids"].append(result["task_id"])
			else:
				results["failed"] += 1
				error_msg = result.get("error", "未知错误")
				results["errors"].append(error_msg)
				logger.error(f"文档处理失败: {error_msg}", exc_info=True)
		
		logger.info(f"✅ 批量解析完成: 提交={results['submitted']}, 失败={results['failed']}")
		
		return {
			"success": True,
			"message": f"批量解析任务已提交: 成功 {results['submitted']} 个，失败 {results['failed']} 个",
			"total": len(doc_ids),
			"submitted": results["submitted"],
			"failed": results["failed"],
			"task_ids": results["task_ids"],
			"errors": results["errors"]
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"批量解析所有文档失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"批量解析所有文档失败: {str(e)}")


@router.post("/kb/{kb_id}/documents/{doc_id}/reset-status")
async def reset_document_status(
    kb_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    重置文档状态（将 processing 或 failed 状态重置为 uploaded）
    
    用于清理卡住的文档，使其可以重新解析
    """
    try:
        from ..services.knowledge_base_service import KnowledgeBaseService
        
        kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
        
        # 验证知识库存在
        kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
        
        # 获取文档记录
        doc = await kb_service.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        
        if doc.get("kb_id") != kb_id:
            raise HTTPException(status_code=403, detail="文档不属于此知识库")
        
        current_status = doc.get("status")
        
        # 只允许重置 processing 或 failed 状态的文档
        if current_status not in ["processing", "failed"]:
            raise HTTPException(
                status_code=400,
                detail=f"只能重置 processing 或 failed 状态的文档，当前状态: {current_status}"
            )
        
        # 重置为 uploaded 状态
        await kb_service.update_document_status(
            doc_id,
            "uploaded",
            error_message=None
        )
        
        # 清除任务ID
        await db[settings.mongodb_db_name].kb_documents.update_one(
            {"_id": ObjectId(doc_id)},
            {
                "$unset": {"task_id": ""},
                "$set": {"updated_at": datetime.utcnow().isoformat()}
            }
        )
        
        logger.info(f"✅ 文档状态已重置: {doc['filename']} ({current_status} -> uploaded)")
        
        return {
            "success": True,
            "message": f"文档状态已重置为 uploaded，可以重新解析",
            "doc_id": doc_id,
            "old_status": current_status,
            "new_status": "uploaded"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置文档状态失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重置文档状态失败: {str(e)}")


@router.get("/kb/{kb_id}/documents/{doc_id}/download")
async def download_document(
	kb_id: str,
	doc_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	【新】下载原始文档（从 MinIO）
	
	返回原始文件供用户下载
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..utils.minio_client import minio_client
		from fastapi.responses import StreamingResponse
		from bson import ObjectId
		import io
		
		# 验证知识库存在（先尝试用户自己的知识库）
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		
		# 如果找不到，检查是否是拉取的知识库（通过 original_kb_id 查找）
		has_access = False
		if kb:
			has_access = True
		else:
			# 检查用户是否拉取了这个知识库
			pulled_kb = await db[settings.mongodb_db_name].pulled_knowledge_bases.find_one({
				"user_id": current_user.id,
				"original_kb_id": kb_id,
				"enabled": True
			})
			if pulled_kb:
				has_access = True
		
		if not has_access:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 获取文档记录
		doc = await kb_service.get_document(doc_id)
		if not doc:
			raise HTTPException(status_code=404, detail="文档不存在")
		
		if doc.get("kb_id") != kb_id:
			raise HTTPException(status_code=403, detail="文档不属于此知识库")
		
		if not doc.get("file_url"):
			raise HTTPException(status_code=400, detail="文档原文件不存在")
		
		# 从 MinIO 下载文档
		file_content = minio_client.download_kb_document(doc["file_url"])
		
		# 返回文件流
		import mimetypes
		content_type = mimetypes.guess_type(doc["filename"])[0] or "application/octet-stream"
		
		return StreamingResponse(
			io.BytesIO(file_content),
			media_type=content_type,
			headers={
				"Content-Disposition": f'attachment; filename="{doc["filename"]}"'
			}
		)
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"下载文档失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"下载文档失败: {str(e)}")


@router.get("/kb/{kb_id}/documents/{doc_id}/content")
async def get_document_content(
	kb_id: str,
	doc_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	【新】获取文档原文内容（用于前端预览）
	
	返回文档的原文内容（文本格式），用于在前端显示
	与下载接口不同，此接口返回 JSON 格式，包含文档内容和元数据
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..utils.minio_client import minio_client
		from app.utils.document_parsers import DocumentParserFactory
		from bson import ObjectId
		
		# 验证知识库存在（先尝试用户自己的知识库）
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		
		# 如果找不到，检查是否是拉取的知识库（通过 original_kb_id 查找）
		has_access = False
		if kb:
			has_access = True
		else:
			# 检查用户是否拉取了这个知识库
			pulled_kb = await db[settings.mongodb_db_name].pulled_knowledge_bases.find_one({
				"user_id": current_user.id,
				"original_kb_id": kb_id,
				"enabled": True
			})
			if pulled_kb:
				has_access = True
		
		if not has_access:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 获取文档记录
		doc = await kb_service.get_document(doc_id)
		if not doc:
			raise HTTPException(status_code=404, detail="文档不存在")
		
		if doc.get("kb_id") != kb_id:
			raise HTTPException(status_code=403, detail="文档不属于此知识库")
		
		if not doc.get("file_url"):
			raise HTTPException(status_code=400, detail="文档原文件不存在")
		
		# 从 MinIO 下载文档
		file_content = minio_client.download_kb_document(doc["file_url"])
		
		# 解析文档内容（提取文本）
		# 初始化解析器（如果尚未初始化）
		if not hasattr(DocumentParserFactory, '_initialized'):
			DocumentParserFactory.initialize_default_parsers()
			DocumentParserFactory._initialized = True
		
		# 解析文档
		parse_result = await DocumentParserFactory.parse_document(
			file_content,
			doc["filename"]
		)
		
		if not parse_result.success:
			raise HTTPException(status_code=500, detail=f"文档解析失败: {parse_result.error_message}")
		
		# 返回文档内容和元数据
		return {
			"success": True,
			"document": {
				"id": str(doc["_id"]),
				"kb_id": kb_id,
				"filename": doc["filename"],
				"file_type": doc.get("file_type"),
				"file_size": doc.get("file_size"),
				"content": parse_result.text,
				"chunk_count": doc.get("chunk_count", 0),
				"upload_time": doc.get("created_at"),
				"metadata": parse_result.metadata
			}
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"获取文档内容失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"获取文档内容失败: {str(e)}")


@router.get("/kb/{kb_id}/documents/{doc_id}/chunks")
async def get_document_chunks(
	kb_id: str,
	doc_id: str,
	page: int = 1,
	page_size: int = 20,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	获取文档的分片列表
	
	特性：
	- 从ChromaDB获取分片数据
	- 支持分页
	- 异步非阻塞
	- 包含分片内容和元数据
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from bson import ObjectId
		import asyncio
		
		# 验证知识库存在和权限（先尝试用户自己的知识库）
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		
		# 如果找不到，检查是否是拉取的知识库（通过 original_kb_id 查找）
		has_access = False
		if kb:
			has_access = True
		else:
			# 检查用户是否拉取了这个知识库
			pulled_kb = await db[settings.mongodb_db_name].pulled_knowledge_bases.find_one({
				"user_id": current_user.id,
				"original_kb_id": kb_id,
				"enabled": True
			})
			if pulled_kb:
				has_access = True
		
		if not has_access:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 验证文档存在
		doc = await kb_service.get_document(doc_id)
		if not doc:
			raise HTTPException(status_code=404, detail="文档不存在")
		
		if doc.get("kb_id") != kb_id:
			raise HTTPException(status_code=403, detail="文档不属于此知识库")
		
		# 检查文档是否已解析
		if doc.get("status") != "completed":
			raise HTTPException(
				status_code=400, 
				detail=f"文档尚未完成解析，当前状态: {doc.get('status', 'unknown')}"
			)
		
		# 从ChromaDB获取分片（异步非阻塞）
		kb_settings = kb.kb_settings if kb.kb_settings else {}
		
		async def get_chunks_from_vectorstore():
			"""异步获取向量存储中的分片"""
			loop = asyncio.get_event_loop()
			
			def _get_chunks():
				"""同步获取分片（在线程池中执行）"""
				import time
				
				# 获取vectorstore组件
				_, vectorstore, _ = _get_kb_components(kb_settings)
				vector_db = kb_settings.get("vector_db", "chroma")
				
				# 根据不同的向量数据库类型采用不同的获取方式
				if vector_db == "faiss":
					# ========== FAISS 获取方式 ==========
					try:
						chunks = []
						
						# FAISS 使用 docstore 存储文档，遍历所有文档查找匹配的 doc_id
						if hasattr(vectorstore._store, 'docstore') and vectorstore._store.docstore:
							docstore = vectorstore._store.docstore
							
							# 遍历 docstore 中的所有文档
							for chunk_id, doc in docstore._dict.items():
								metadata = doc.metadata if hasattr(doc, 'metadata') else {}
								
								# 检查是否属于该文档
								if metadata.get('doc_id') == doc_id:
									chunk = {
										"id": chunk_id,
										"content": doc.page_content if hasattr(doc, 'page_content') else "",
										"metadata": metadata,
										"chunk_index": metadata.get('chunk_index', 0)
									}
									chunks.append(chunk)
							
							# 按 chunk_index 排序
							chunks.sort(key=lambda x: x['chunk_index'])
							logger.info(f"✅ 从 FAISS 成功读取 {len(chunks)} 个分片")
							return chunks
						else:
							logger.error("❌ FAISS vectorstore 缺少 docstore")
							return []
							
					except Exception as e:
						logger.error(f"❌ 从 FAISS 获取分片失败: {e}", exc_info=True)
						raise
						
				else:
					# ========== ChromaDB 获取方式 ==========
					max_retries = 3
					retry_delay = 2.0  # 每次重试等待2秒
					
					for attempt in range(max_retries):
						try:
							# 获取ChromaDB collection (ChromaVectorStore._store._collection)
							chroma_collection = vectorstore._store._collection
							
							# 🔥 在读取前先触发一次compaction（通过count()）并等待
							if attempt == 0:
								try:
									doc_count = chroma_collection.count()
									logger.info(f"📖 [读取前检查] collection文档数: {doc_count}，等待compaction完成...")
									time.sleep(2.0)  # 等待2秒让compaction完成
								except Exception as check_err:
									logger.warning(f"⚠️ 读取前检查失败（可忽略）: {check_err}")
							
							# 查询该文档的所有chunks
							results = chroma_collection.get(
								where={"doc_id": doc_id},
								include=["metadatas", "documents"]  # 包含元数据和文档内容
							)
							
							if not results or not results['ids']:
								return []
							
							# 构建分片列表
							chunks = []
							for idx, chunk_id in enumerate(results['ids']):
								chunk = {
									"id": chunk_id,
									"content": results['documents'][idx] if idx < len(results['documents']) else "",
									"metadata": results['metadatas'][idx] if idx < len(results['metadatas']) else {},
									"chunk_index": results['metadatas'][idx].get('chunk_index', idx) if idx < len(results['metadatas']) else idx
								}
								chunks.append(chunk)
							
							# 按chunk_index排序
							chunks.sort(key=lambda x: x['chunk_index'])
							
							logger.info(f"✅ 从 ChromaDB 成功读取 {len(chunks)} 个分片")
							return chunks
							
						except Exception as e:
							error_msg = str(e)
							is_compaction_error = (
								"Error loading hnsw index" in error_msg or
								"Error constructing hnsw segment reader" in error_msg or
								"Error sending backfill request to compactor" in error_msg
							)
							
							if is_compaction_error and attempt < max_retries - 1:
								logger.warning(
									f"⚠️ 检测到compaction未完成错误（第{attempt + 1}次尝试），"
									f"等待{retry_delay}秒后重试..."
								)
								time.sleep(retry_delay)
								continue  # 重试
							else:
								# 不是compaction错误，或者已经重试次数用完
								logger.error(f"❌ 从ChromaDB获取分片失败: {error_msg}", exc_info=True)
								raise
			
			# 在线程池中执行同步操作
			return await loop.run_in_executor(None, _get_chunks)
		
		# 异步获取所有分片
		all_chunks = await get_chunks_from_vectorstore()
		
		# 分页处理
		total_chunks = len(all_chunks)
		start_idx = (page - 1) * page_size
		end_idx = start_idx + page_size
		chunks = all_chunks[start_idx:end_idx]
		
		return {
			"success": True,
			"document": {
				"id": str(doc["_id"]),
				"filename": doc["filename"],
				"file_type": doc.get("file_type"),
			},
			"chunks": chunks,
			"pagination": {
				"page": page,
				"page_size": page_size,
				"total": total_chunks,
				"total_pages": (total_chunks + page_size - 1) // page_size
			}
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"获取文档分片失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"获取文档分片失败: {str(e)}")


@router.delete("/kb/{kb_id}/documents/{doc_id}")
async def delete_document(
	kb_id: str,
	doc_id: str,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	删除文档
	
	特性：
	- 删除文档记录
	- 删除 MinIO 中的原文件
	- 异步删除向量数据
	- 更新统计信息
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..utils.minio_client import minio_client
		
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		
		# 获取文档信息（用于删除 MinIO 文件）
		doc = await kb_service.get_document(doc_id)
		if doc and doc.get("file_url"):
			# 删除 MinIO 中的文件
			minio_client.delete_kb_document(doc["file_url"])
		
		# 删除文档记录和向量数据
		success = await kb_service.delete_document(
			doc_id=doc_id,
			kb_id=kb_id,
			user_id=current_user.id
		)
		
		if not success:
			raise HTTPException(status_code=404, detail="文档不存在或无权限访问")
		
		return {"success": True, "message": "文档已删除"}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"删除文档失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"删除文档失败: {str(e)}")


@router.post("/kb/{kb_id}/search", response_model=KBSearchResponse)
async def search_knowledge_base(
	kb_id: str,
	search_request: KBSearchRequest,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	搜索知识库（语义搜索）
	
	特性：
	- 异步向量搜索
	- 不阻塞其他用户
	- 支持混合搜索
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		
		# 验证知识库存在
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
		if not kb:
			raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
		
		# 执行异步搜索
		from ..utils.embedding.pipeline import Retriever
		from ..utils.embedding.path_utils import build_chroma_persist_dir, get_chroma_collection_name
		from ..services.embedding_manager import get_embedding_manager
		from ..services.vectorstore_manager import get_vectorstore_manager
		
		# 构建知识库组件（使用全局单例）
		_, vectorstore, _ = _get_kb_components(kb.kb_settings)
		
		# 获取距离度量和阈值（优先使用请求参数，其次使用知识库配置）
		distance_metric = search_request.distance_metric
		if distance_metric is None:
			search_params = kb.kb_settings.get("search_params", {})
			distance_metric = search_params.get("distance_metric", "cosine")
		
		similarity_threshold = search_request.similarity_threshold
		if similarity_threshold is None:
			similarity_threshold = kb.kb_settings.get("similarity_threshold")
		
		retriever = Retriever(
			vector_store=vectorstore,
			similarity_threshold=similarity_threshold,
			distance_metric=distance_metric
		)
		
		# 🐛 打印调试信息
		logger.info(f"🔍 [检索调试] 查询文本: {search_request.query[:100]}")
		logger.info(f"🔍 [检索调试] top_k: {search_request.top_k}, 相似度阈值: {similarity_threshold}, 距离度量: {distance_metric}")
		
		# 直接执行异步搜索（传入阈值和top_k）
		results = await retriever.search(
			query=search_request.query,
			top_k=search_request.top_k,
			similarity_threshold=similarity_threshold
		)
		
		logger.info(f"🔍 [检索调试] 原始结果数: {len(results)}")
		
		# 格式化结果 + 批量查询文档名称
		search_results = []
		
		# 🔧 收集所有 doc_id，批量查询文档名称
		doc_ids = []
		for doc, _ in results:
			doc_id = doc.metadata.get("doc_id")
			if doc_id:
				doc_ids.append(doc_id)
		
		# 批量查询文档名称
		filename_map = {}
		if doc_ids:
			try:
				from bson import ObjectId
				docs_cursor = db[settings.mongodb_db_name].documents.find(
					{"_id": {"$in": [ObjectId(did) for did in doc_ids if ObjectId.is_valid(did)]}},
					{"_id": 1, "filename": 1}
				)
				async for doc_record in docs_cursor:
					filename_map[str(doc_record["_id"])] = doc_record.get("filename", "")
			except Exception as e:
				logger.warning(f"⚠️ 批量查询filename失败: {e}")
		
		for idx, (doc, distance) in enumerate(results):
			# 根据距离度量类型计算相似度分数
			similarity_score = calculate_score_from_distance(float(distance), distance_metric)
			
			# 🐛 打印每个结果的详细信息
			logger.info(f"🔍 [结果 {idx+1}] 距离={distance:.4f}, 相似度={similarity_score:.4f}, 内容前50字: {doc.page_content[:50]}")
			
			# 获取文档名称
			doc_id = doc.metadata.get("doc_id")
			filename = doc.metadata.get("filename") or filename_map.get(doc_id, "")
			
			# 🆕 添加 document_name 字段（前端需要）
			metadata_with_name = doc.metadata.copy()
			if filename:
				metadata_with_name["filename"] = filename
			
			search_results.append(
				KBSearchResult(
					content=doc.page_content,
					score=similarity_score,
					distance=float(distance),
					metadata=metadata_with_name,
					chunk_id=doc.metadata.get("chunk_id"),
					doc_id=doc_id,
					document_name=filename or doc.metadata.get("source", "未知文档")  # 🆕 添加文档名称
				)
			)
		
		return KBSearchResponse(
			success=True,
			results=search_results,
			total=len(search_results)
		)
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"搜索失败: {str(e)}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.post("/kb/multi-search", response_model=MultiKBSearchResponse)
async def search_multiple_knowledge_bases(
	search_request: MultiKBSearchRequest,
	current_user: User = Depends(get_current_user),
	db: AsyncIOMotorClient = Depends(get_database)
):
	"""
	多知识库并行检索（企业级高性能）
	
	特性：
	✅ 完全异步并行 - 不阻塞主线程
	✅ 信号量控制并发 - 避免资源耗尽
	✅ 智能结果合并 - 支持多种策略
	✅ 用户级隔离 - 互不影响
	
	使用场景：
	- 同时检索"论文库"和"人工智能库"
	- 跨多个知识库查找相关内容
	- 提高检索覆盖率
	
	Args:
		search_request: 多知识库检索请求
			- kb_ids: 知识库ID列表
			- query: 查询文本
			- top_k_per_kb: 每个库返回结果数
			- final_top_k: 最终返回总数
			- merge_strategy: 合并策略
	
	Returns:
		MultiKBSearchResponse: 合并后的检索结果
	"""
	try:
		from ..services.knowledge_base_service import KnowledgeBaseService
		from ..services.multi_kb_retriever import get_multi_kb_retriever
		
		logger.info(f"🔍 多知识库检索请求: user={current_user.id}, kb_count={len(search_request.kb_ids)}, "
		           f"query='{search_request.query[:50]}...'")
		
		# 1. 验证并获取所有知识库配置
		kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
		kb_configs = []
		
		for kb_id in search_request.kb_ids:
			# 验证知识库存在且有权限
			kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
			if not kb:
				logger.warning(f"⚠️ 知识库 {kb_id} 不存在或无权限,跳过")
				continue
			
			kb_configs.append({
				'kb_id': kb_id,
				'kb_name': kb.name,
				'kb_settings': kb.kb_settings
			})
		
		if not kb_configs:
			raise HTTPException(
				status_code=404,
				detail="所有指定的知识库都不存在或无权限访问"
			)
		
		# 2. 获取多知识库检索器单例
		retriever = await get_multi_kb_retriever()
		
		# 3. 并行检索（完全异步,不阻塞）
		results = await retriever.retrieve_from_multiple_kbs(
			query=search_request.query,
			kb_configs=kb_configs,
			top_k_per_kb=search_request.top_k_per_kb,
			similarity_threshold=search_request.similarity_threshold,
			merge_strategy=search_request.merge_strategy,
			final_top_k=search_request.final_top_k
		)
		
		# 4. 格式化响应
		formatted_results = retriever.format_results_for_api(results)
		
		logger.info(f"✅ 多知识库检索完成: 返回 {len(formatted_results)} 个结果")
		
		return MultiKBSearchResponse(
			success=True,
			results=formatted_results,
			total_results=len(formatted_results),
			kb_count=len(kb_configs),
			merge_strategy=search_request.merge_strategy
		)
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"❌ 多知识库检索失败: {e}", exc_info=True)
		raise HTTPException(status_code=500, detail=f"多知识库检索失败: {str(e)}")


@router.get("/kb/task/{task_id}/status")
async def get_task_status_detail(
	task_id: str,
	current_user: User = Depends(get_current_user)
):
	"""
	获取任务详细状态
	
	特性：
	- 实时查询任务状态
	- 不阻塞主服务
	"""
	try:
		from ..services.async_task_processor import get_task_processor
		
		processor = get_task_processor()
		status = await processor.get_task_status(task_id)
		
		if not status:
			raise HTTPException(status_code=404, detail="任务不存在")
		
		return {
			"success": True,
			**status
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"获取任务状态失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")


@router.post("/kb/task/{task_id}/cancel")
async def cancel_task_detail(
	task_id: str,
	current_user: User = Depends(get_current_user)
):
	"""
	取消任务
	
	特性：
	- 异步取消
	- 更新文档状态
	"""
	try:
		from ..services.async_task_processor import get_task_processor
		
		processor = get_task_processor()
		success = await processor.cancel_task(task_id)
		
		if not success:
			raise HTTPException(status_code=404, detail="任务不存在或无法取消")
		
		return {
			"success": True,
			"message": "任务已取消"
		}
		
	except HTTPException:
		raise
	except Exception as e:
		logger.error(f"取消任务失败: {str(e)}")
		raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")