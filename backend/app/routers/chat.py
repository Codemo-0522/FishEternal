from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import uuid
import json
import logging
import traceback
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from jose import jwt
from ..utils.auth import get_current_user
from ..models.user import User
from ..utils.llm.llm_service import LLMService
# 移除向量存储相关导入
# from ..utils.vector_store.vector_store import VectorStore
from ..utils.content_filter import prepare_content_for_context
from ..config import settings
from ..database import get_database
from ..utils.tts.xfyun_tts import XfyunTTSClient, clean_text_for_tts
from ..utils.tts.byte_dance_tts import ByteDanceTTS
from ..utils.streaming_tts_manager import streaming_tts_manager
import os
from fastapi.encoders import jsonable_encoder

# 添加知识库检索相关导入
import httpx

# 添加异步支持
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== TTS 异步优化 ====================
# 创建TTS专用线程池，避免同步WebSocket阻塞主事件循环
tts_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="TTS")

async def _synthesize_xfyun_tts_async(
    tts_client: XfyunTTSClient,
    text: str,
    pcm_file: str,
    vcn: str
) -> bool:
    """
    异步包装讯飞云TTS合成
    
    使用线程池执行同步的WebSocket调用，避免阻塞主事件循环
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        tts_executor,
        tts_client.synthesize,
        text,
        pcm_file,
        vcn
    )

async def _synthesize_bytedance_tts_async(
    tts_client: ByteDanceTTS,
    text: str,
    output_file: str,
    voice_type: str
) -> bool:
    """
    异步包装字节跳动TTS合成
    
    使用线程池执行同步的WebSocket调用，避免阻塞主事件循环
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        tts_executor,
        tts_client.synthesize_to_file,
        text,
        output_file,
        voice_type
    )

async def _pcm_to_wav_async(
    pcm_file: str,
    wav_file: str,
    channels: int = 1,
    sample_width: int = 2,
    sample_rate: int = 16000
) -> bool:
    """
    异步包装PCM到WAV转换
    
    使用线程池执行文件I/O操作，避免阻塞主事件循环
    """
    from ..utils.tts.xfyun_tts import pcm_to_wav
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        tts_executor,
        pcm_to_wav,
        pcm_file,
        wav_file,
        channels,
        sample_width,
        sample_rate
    )
# ======================================================

# 时间戳归一化函数：统一转换为不带时区的 ISO 格式
def normalize_timestamp(ts):
    """
    归一化时间戳字符串，用于精确匹配
    - 移除时区后缀 'Z' 和 '+00:00'
    - 统一 datetime 和 str 格式
    """
    if isinstance(ts, str):
        # 已经是字符串，统一格式
        ts_clean = ts.replace('Z', '').replace('+00:00', '')
        return ts_clean
    elif isinstance(ts, datetime):
        # datetime 对象转字符串（去除 Z 和时区）
        return ts.isoformat().replace('Z', '').replace('+00:00', '')
    return str(ts)

# 注意：音频现在通过WebSocket直接发送Base64数据，不再保存到文件系统
# 因此不需要清理音频文件

router = APIRouter(prefix="/chat", tags=["chat"])

class ModelSettings(BaseModel):
    modelService: str
    baseUrl: str
    apiKey: str
    modelName: str
    modelParams: Optional[dict] = None

class CreateSessionRequest(BaseModel):
    name: str
    model_settings: ModelSettings
    system_prompt: Optional[str] = None

class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[datetime] = None

class ChatSession(BaseModel):
    session_id: str
    name: str
    messages: List[ChatMessage]
    created_at: str
    system_prompt: Optional[str] = None
    context_count: Optional[int] = None  # None表示不限制上下文

# 创建DeepSeek服务实例
model_service = LLMService()
# vector_store = VectorStore() # 移除向量存储实例


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """创建新会话"""
    logger.info(f"开始创建新会话 - 用户ID: {current_user.id}")
    logger.info(f"会话名称: {request.name}")
    # 安全日志：不打印完整模型配置，避免泄露API密钥
    model_service = request.model_settings.modelService if hasattr(request.model_settings, 'modelService') else 'unknown'
    model_name = request.model_settings.modelName if hasattr(request.model_settings, 'modelName') else 'unknown'
    logger.info(f"模型配置: service={model_service}, model={model_name}")

    try:
        session_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        logger.info(f"生成会话ID: {session_id}")
        
        session = {
            "_id": session_id,
            "name": request.name,
            "user_id": str(current_user.id),
            "created_at": created_at,
            "model_settings": request.model_settings.dict(),
            "system_prompt": request.system_prompt,  # 保存system_prompt
            "context_count": 20,  # 默认上下文数量为20
            "session_type": "personal",  # 会话类型：personal(传统会话) 或 group(群聊)
            "history": [],
            "moments": [],  # 朋友圈列表（已发布）
            "moment_queue": []  # 朋友圈队列（待发布）
        }
        logger.info(f"准备保存的会话数据: {session}")
        
        # 保存到数据库
        await db[settings.mongodb_db_name].chat_sessions.insert_one(session)
        logger.info(f"会话已成功保存到数据库")
        
        response_data = {
            "session_id": session_id,
            "name": request.name,
            "created_at": created_at,
            "model_settings": request.model_settings,
            "system_prompt": request.system_prompt,  # 返回system_prompt
            "context_count": 20,  # 返回默认的context_count
            "message_count": 0  # 新会话的消息数量为0
        }
        logger.info(f"返回给客户端的数据: {response_data}")
        return response_data

    except Exception as e:
        logger.error(f"创建会话失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建会话失败")

@router.get("/sessions")
async def get_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户的所有会话"""
    logger.info(f"开始获取会话列表 - 用户ID: {current_user.id}")
    try:
        sessions = await db[settings.mongodb_db_name].chat_sessions.find(
            {"user_id": str(current_user.id)}
        ).to_list(None)
        
        # 为每个会话添加消息数量统计
        for session in sessions:
            if "history" in session:
                session["message_count"] = len(session["history"])
            else:
                session["message_count"] = 0
        
        logger.info(f"成功获取会话列表 - 数量: {len(sessions)}")
        return sessions
    except Exception as e:
        logger.error(f"获取会话列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取会话列表失败")

@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取特定会话的详细信息"""
    try:
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        return session
    except Exception as e:
        logger.error(f"获取会话详情失败: {str(e)}")
        raise HTTPException(status_code=500, detail="获取会话详情失败")

@router.post("/sessions/{session_id}/messages")
async def add_message(
    session_id: str,
    message: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """添加消息到会话"""
    try:
        # 设置消息时间戳
        if not message.timestamp:
            message.timestamp = datetime.utcnow().isoformat() + 'Z'  # 使用ISO字符串格式
            
        # 更新数据库
        result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {
                "_id": session_id,
                "user_id": str(current_user.id)
            },
            {
                "$push": {
                    "history": message.dict()
                }
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="会话不存在")
            
        return {"status": "success"}
    except Exception as e:
        logger.error(f"添加消息失败: {str(e)}")
        raise HTTPException(status_code=500, detail="添加消息失败")

async def _build_vectorstore_for_session(session_id: str, db: AsyncIOMotorClient):
	"""
	根据会话的 kb_settings 构建与入库一致的 vectorstore。
	只用于传统 RAG 模式（需要 kb_prompt_template 包含 {knowledge}）。
	若未启用或使用 MCP 模式则返回 None。
	"""
	session_data = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id})
	kb_settings = session_data.get("kb_settings") if session_data else None
	if not kb_settings or not kb_settings.get("enabled"):
		return None, None
	
	# 检查是否为传统 RAG 模式（需要 kb_prompt_template 包含 {knowledge}）
	kb_prompt_template = kb_settings.get("kb_prompt_template") if isinstance(kb_settings, dict) else None
	if not kb_prompt_template or not kb_prompt_template.strip():
		logger.info("💡 使用 MCP 工具模式，跳过传统引用检索")
		return None, None
	
	# 如果模板不包含 {knowledge}，说明不需要自动检索（可能只需要 {time}）
	if "{knowledge}" not in kb_prompt_template:
		logger.info("💡 kb_prompt_template 未包含 {knowledge}，跳过传统引用检索")
		return None, None
	
	from .kb import _get_kb_components
	_, vectorstore, _ = _get_kb_components(kb_settings)
	return kb_settings, vectorstore

async def _build_vectorstore_for_history(session_id: str, db: AsyncIOMotorClient):
	"""
	为历史引用展开构建 vectorstore。
	只要知识库启用就构建，不检查是否为传统RAG模式。
	用于展开历史消息中的精简引用（document_id, chunk_id）。
	"""
	session_data = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id})
	kb_settings = session_data.get("kb_settings") if session_data else None
	if not kb_settings or not kb_settings.get("enabled"):
		return None, None
	
	from .kb import _get_kb_components
	_, vectorstore, _ = _get_kb_components(kb_settings)
	return kb_settings, vectorstore

async def _retrieve_references(user_message: str, kb_settings: dict, vectorstore, db: AsyncIOMotorClient = None) -> Dict[str, List[Dict[str, Any]]]:
	"""执行本地检索，返回 rich_refs 与 lean_refs。"""
	from ..utils.embedding.pipeline import Retriever
	from bson import ObjectId
	
	# ✅ 尝试从数据库加载知识库真实配置（传统RAG模式）
	actual_similarity_threshold = None
	actual_distance_metric = "cosine"
	
	if db and kb_settings:
		try:
			from ..services.knowledge_base_service import KnowledgeBaseService
			from ..config import settings as app_settings
			
			# 传统RAG模式：通过collection_name查找知识库
			collection_name = kb_settings.get("collection_name")
			if collection_name:
				kb_service = KnowledgeBaseService(db[app_settings.mongodb_db_name])
				# 查找使用该collection的知识库
				kb = await db[app_settings.mongodb_db_name].knowledge_bases.find_one({
					"kb_settings.collection_name": collection_name
				})
				if kb and kb.get("kb_settings"):
					actual_similarity_threshold = kb["kb_settings"].get("similarity_threshold")
					search_params = kb["kb_settings"].get("search_params", {})
					actual_distance_metric = search_params.get("distance_metric", "cosine")
					logger.info(f"📊 传统RAG模式 - 从数据库加载知识库配置: 阈值={actual_similarity_threshold}, 距离度量={actual_distance_metric}")
		except Exception as e:
			logger.warning(f"⚠️ 加载知识库配置失败，使用默认值: {e}")
	
	# 使用知识库配置或默认值
	similarity_threshold = actual_similarity_threshold if actual_similarity_threshold is not None else 0.5
	distance_metric = actual_distance_metric
	
	top_k = kb_settings.get("top_k", 3) if isinstance(kb_settings, dict) else 3
	# 限制 top_k 范围在 1-12 之间
	top_k = max(1, min(12, top_k))
	retriever = Retriever(
		vector_store=vectorstore, 
		top_k=top_k, 
		similarity_threshold=similarity_threshold,
		distance_metric=distance_metric
	)
	# ✅ 使用异步检索，避免阻塞事件循环
	search_results = await retriever.search(user_message, top_k=top_k)
	rich_refs: List[Dict[str, Any]] = []
	lean_refs: List[Dict[str, Any]] = []
	
	# 🆕 收集需要查询的doc_id，用于批量查询filename
	doc_ids_to_query = set()
	for doc, score in (search_results or []):
		meta = doc.metadata or {}
		doc_id = meta.get("doc_id")
		filename = meta.get("filename")
		# 如果filename为空且doc_id存在，记录需要查询
		if doc_id and not filename:
			doc_ids_to_query.add(doc_id)
	
	# 🆕 批量查询filename
	filename_map = {}
	if doc_ids_to_query and db:
		try:
			from ..config import settings
			doc_ids_obj = [ObjectId(doc_id) for doc_id in doc_ids_to_query if ObjectId.is_valid(doc_id)]
			if doc_ids_obj:
				cursor = db[settings.mongodb_db_name].kb_documents.find(
					{"_id": {"$in": doc_ids_obj}},
					{"_id": 1, "filename": 1}
				)
				async for doc_record in cursor:
					filename_map[str(doc_record["_id"])] = doc_record.get("filename", "")
				logger.info(f"📝 从数据库补充了 {len(filename_map)} 个文档的filename")
		except Exception as e:
			logger.warning(f"⚠️ 批量查询filename失败: {e}")
	
	for doc, score in (search_results or []):
		meta = doc.metadata or {}
		doc_id = meta.get("doc_id")
		# 🆕 如果metadata中filename为空，尝试从数据库查询结果中获取
		filename = meta.get("filename") or filename_map.get(doc_id, "")
		
		lean = {
			"document_id": meta.get("document_id") or meta.get("source"),
			"chunk_id": meta.get("chunk_id"),
			"score": float(score),
			# 🆕 添加用于查看原文的必要字段
			"doc_id": doc_id,
			"kb_id": meta.get("kb_id"),
			"filename": filename,
		}
		lean_refs.append(lean)
		rich = {
			"document_id": lean["document_id"],
			"chunk_id": lean["chunk_id"],
			"score": lean["score"],
			"document_name": meta.get("source"),
			"content": doc.page_content,
			"metadata": meta,
			# 🆕 添加用于查看原文的必要字段
			"doc_id": doc_id,
			"kb_id": meta.get("kb_id"),
			"filename": filename,
		}
		rich_refs.append(rich)
	return {"rich": rich_refs, "lean": lean_refs}

async def _expand_history_references(messages: List[Dict[str, Any]], kb_settings: Optional[dict], vectorstore, db) -> List[Dict[str, Any]]:
	"""将历史消息中的精简引用（document_id, chunk_id, score）展开为富引用，仅在下发历史时使用。"""
	if not messages:
		logger.info("📝 历史引用展开: 无消息需要处理")
		return messages
	if not kb_settings or not kb_settings.get("enabled"):
		logger.info("📝 历史引用展开: 知识库未启用")
		return messages
	
	# 收集所有 chunk_id，并按 document_id 分组
	chunk_to_ref = {}  # chunk_id -> 引用数据
	for msg in messages:
		refs = msg.get("reference") or []
		if isinstance(refs, dict):
			refs = [refs]
		for r in refs:
			if r and r.get("chunk_id"):
				chunk_to_ref[r["chunk_id"]] = r
	
	chunk_ids = list(chunk_to_ref.keys())
	logger.info(f"📝 历史引用展开: 收集到 {len(chunk_ids)} 个唯一 chunk_id")
	logger.info(f"📝 历史引用展开: chunk_to_ref 示例: {list(chunk_to_ref.items())[:2]}")
	
	if not chunk_ids:
		logger.info("📝 历史引用展开: 没有需要展开的引用")
		return messages
	
	# 从多知识库检索
	try:
		from ..services.vectorstore_manager import get_vectorstore_manager
		from ..services.embedding_manager import get_embedding_manager
		from ..utils.embedding.path_utils import build_chroma_persist_dir, get_chroma_collection_name
		
		vectorstore_manager = get_vectorstore_manager()
		embedding_manager = get_embedding_manager()
		
		# 🔧 修复：从引用数据中提取实际使用的 kb_id，而不是使用会话配置中的 kb_ids
		# 原因：用户可能重新拉取共享知识库，导致会话配置中的 kb_ids 更新，但历史引用中的 kb_id 仍是旧的
		kb_ids_from_refs = set()
		for cid in chunk_ids:
			kb_id = chunk_to_ref[cid].get("kb_id")
			if kb_id:
				kb_ids_from_refs.add(kb_id)
		
		kb_ids = list(kb_ids_from_refs)
		logger.info(f"📝 历史引用展开: 从引用数据中提取到 {len(kb_ids)} 个唯一的 kb_id: {kb_ids}")
		
		if not kb_ids:
			logger.warning("📝 历史引用展开: 引用数据中没有 kb_id")
			return messages
		
		# 获取Embedding配置（从会话配置中获取，用于创建embedding function）
		emb_cfg = kb_settings.get("embeddings", {})
		provider = emb_cfg.get("provider", "local")
		model = emb_cfg.get("model", "all-MiniLM-L6-v2")
		base_url = emb_cfg.get("base_url")
		api_key = emb_cfg.get("api_key")
		local_model_path = emb_cfg.get("local_model_path", "checkpoints/embeddings/all-MiniLM-L6-v2")
		
		# 获取embedding function
		embedding_function = embedding_manager.get_or_create(
			provider=provider,
			model=model,
			base_url=base_url,
			api_key=api_key,
			local_model_path=local_model_path
		)
		
		# 按document_id分组查询
		docs_by_kb = {}
		for kb_id in kb_ids:
			logger.info(f"📝 历史引用展开: 正在处理知识库 kb_id={kb_id}")
			
			# 🔧 修复：支持拉取的共享知识库
			# 直接查询知识库（不区分是否是拉取的，因为kb_id就是原始知识库ID）
			kb_doc = await db[settings.mongodb_db_name].knowledge_bases.find_one({"_id": ObjectId(kb_id)})
			
			if not kb_doc:
				logger.warning(f"📝 历史引用展开: 知识库 {kb_id} 不存在")
				continue
			
			collection_name_raw = kb_doc.get("collection_name")
			if not collection_name_raw:
				logger.warning(f"📝 历史引用展开: 知识库 {kb_id} 没有 collection_name")
				continue
			
			logger.info(f"📝 历史引用展开: 知识库 {kb_id} 的 collection_name={collection_name_raw}")
			
			# 获取Chroma的collection_name和persist_dir
			collection_name = get_chroma_collection_name(collection_name_raw)
			persist_dir = build_chroma_persist_dir(collection_name_raw)
			
			# 获取该知识库的向量存储
			try:
				vs = vectorstore_manager.get_or_create(
					collection_name=collection_name,
					persist_dir=persist_dir,
					embedding_function=embedding_function,
					vector_db_type="chroma"
				)
				logger.info(f"📝 历史引用展开: 获取到 VectorStore，类型={type(vs).__name__}, has_get_by_ids={hasattr(vs, 'get_by_ids')}")
				
				# 🔧 修复：按照引用中的 kb_id 字段来匹配知识库（而不是 document_id）
				kb_chunks = [
					cid for cid in chunk_ids 
					if chunk_to_ref[cid].get("kb_id") == kb_id
				]
				logger.info(f"📝 历史引用展开: 按 kb_id={kb_id} 匹配到 {len(kb_chunks)} 个 chunk")
				if kb_chunks:
					logger.info(f"📝 历史引用展开: 匹配的 chunk_ids: {kb_chunks[:3]}{'...' if len(kb_chunks) > 3 else ''}")
				
				if kb_chunks and hasattr(vs, "get_by_ids"):
					logger.info(f"📝 历史引用展开: 准备调用 get_by_ids 查询 {len(kb_chunks)} 个文档")
					docs = await vs.get_by_ids(kb_chunks)
					logger.info(f"📝 历史引用展开: get_by_ids 返回了 {len(docs)} 个文档")
					for doc in docs:
						cid = doc.metadata.get("chunk_id")
						if cid:
							docs_by_kb[cid] = doc
					logger.info(f"📝 历史引用展开: 从知识库 {collection_name} 查询到 {len(docs)} 个文档")
				else:
					logger.warning(f"📝 历史引用展开: kb_chunks={len(kb_chunks) if kb_chunks else 0}, has_get_by_ids={hasattr(vs, 'get_by_ids')}")
			except Exception as e:
				logger.error(f"📝 历史引用展开: 查询知识库 {collection_name} 失败: {e}", exc_info=True)
				continue
		
		logger.info(f"📝 历史引用展开: 总共查询到 {len(docs_by_kb)} 个文档")
		
		# 展开引用
		for msg in messages:
			refs = msg.get("reference") or []
			if isinstance(refs, dict):
				refs = [refs]
			rich_refs = []
			for r in refs:
				cid = r.get("chunk_id") if isinstance(r, dict) else None
				if not cid:
					continue
				
				doc = docs_by_kb.get(cid)
				if not doc:
					logger.warning(f"📝 历史引用展开: chunk_id={cid} 在所有知识库中未找到")
					continue
				
				meta = doc.metadata or {}
				rich_refs.append({
					"ref_marker": r.get("ref_marker"),
					"document_id": meta.get("source") or r.get("document_id"),
					"chunk_id": cid,
					"score": r.get("score"),
					"document_name": meta.get("source"),
					"content": doc.page_content,
					"metadata": meta,
					# 🆕 添加用于查看原文的必要字段（从metadata中提取，如果不存在则从原始引用中获取）
					"doc_id": meta.get("doc_id") or r.get("doc_id"),
					"kb_id": meta.get("kb_id") or r.get("kb_id"),
					"filename": meta.get("filename") or r.get("filename"),
				})
			
			logger.info(f"📝 历史引用展开: 消息展开了 {len(rich_refs)} 个引用")
			msg["reference"] = rich_refs
		
		return messages
	except Exception as e:
		logger.error(f"📝 历史引用展开失败: {str(e)}")
		logger.error(traceback.format_exc())
		return messages

@router.websocket("/ws/chat/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    db: AsyncIOMotorClient = Depends(get_database)
):
    logger.info(f"收到WebSocket连接请求 - 会话ID: {session_id}")
    
    try:
        await websocket.accept()
        logger.info("WebSocket连接已接受")

        # 等待接收认证消息
        auth_data = await websocket.receive_json()
        logger.info("收到认证消息")

        if auth_data.get('type') != 'authorization' or not auth_data.get('token'):
            logger.error("无效的认证消息格式")
            await websocket.close(code=4001, reason="Invalid authentication message")
            return

        # 从token中提取Bearer token
        auth_token = auth_data['token']
        if not auth_token.startswith('Bearer '):
            logger.error("无效的token格式")
            await websocket.close(code=4001, reason="Invalid token format")
            return

        token = auth_token.split(' ')[1]
        logger.info("开始验证token")

        # 验证用户 - 复用utils/auth.py的逻辑确保与REST API一致
        try:
            from ..utils.auth import get_current_user
            # 先验证token有效性
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            account = payload.get("sub")
            if not account:
                raise ValueError("Token中没有账号")

            # 使用与REST API相同的逻辑获取用户信息
            user_doc = await db[settings.mongodb_db_name].users.find_one({"account": account})
            if not user_doc:
                raise ValueError("未找到用户")

            # 将 MongoDB 的 ObjectId 转换为字符串，并使用 id 字段
            if "_id" in user_doc and isinstance(user_doc["_id"], ObjectId):
                user_doc["id"] = str(user_doc["_id"])
            
            user = User(**user_doc)  # 创建User对象，确保与REST API返回类型一致
            logger.info(f"用户认证成功: {account}, user_id: {user.id}")

        except Exception as e:
            logger.error(f"Token验证失败: {str(e)}")
            await websocket.close(code=4001, reason="Authentication failed")
            return

        # 获取会话历史
        # 🔥 特殊处理：如果是群聊会话（session_id 以 group_ 开头），查询群聊信息
        if session_id.startswith("group_"):
            group_id = session_id.replace("group_", "", 1)  # 提取群聊ID
            
            # 查询群聊信息
            group = await db[settings.mongodb_db_name].group_chats.find_one({
                "_id": group_id
            })
            
            if not group:
                logger.error(f"未找到群聊: {group_id} (session_id: {session_id})")
                await websocket.close(code=4004, reason="Group chat not found")
                return
            
            # 检查用户是否是群聊成员
            if user.id not in group.get("human_member_ids", []):
                logger.error(f"用户 {user.id} 不是群聊 {group_id} 的成员")
                await websocket.close(code=4003, reason="Not a member of this group")
                return
            
            logger.info(f"找到群聊会话: {session_id} (group_id: {group_id})")
            # 为群聊创建虚拟会话对象，以便后续代码能正常工作
            session = {
                "_id": session_id,
                "user_id": user.id,
                "group_id": group_id,
                "is_group_chat": True
            }
        else:
            # 普通聊天会话
            session = await db[settings.mongodb_db_name].chat_sessions.find_one({
                "_id": session_id,
                "user_id": user.id
            })
            
            if not session:
                logger.error(f"未找到会话: {session_id}")
                await websocket.close(code=4004, reason="Session not found")
                return
            
            logger.info(f"找到会话: {session_id}")

        # 认证成功后立即通知前端
        try:
            await websocket.send_json(jsonable_encoder({"type": "auth_success"}))
        except Exception:
            logger.warning("发送auth_success消息失败，但继续处理连接")
        
        # 获取历史消息（懒加载优化：只发送最近20条）
        # 企业级优化：初始只加载最近20条消息
        INITIAL_LOAD_LIMIT = 20
        
        # 🔥 群聊会话：从群聊消息集合获取，普通会话：从会话历史获取
        if session_id.startswith("group_"):
            # 群聊消息存储在 group_messages 集合中
            group_id = session_id.replace("group_", "", 1)
            cursor = db[settings.mongodb_db_name].group_messages.find(
                {"group_id": group_id}
            ).sort("timestamp", -1).limit(INITIAL_LOAD_LIMIT)
            messages_docs = await cursor.to_list(length=INITIAL_LOAD_LIMIT)
            # 转换为普通消息格式（倒序，最新的在前）
            history = []
            for msg_doc in reversed(messages_docs):
                # 转换群聊消息格式为普通消息格式
                history.append({
                    "role": "ai" if msg_doc.get("sender_type") == "ai" else "user",
                    "content": msg_doc.get("content", ""),
                    "timestamp": msg_doc.get("timestamp"),
                    "message_id": msg_doc.get("message_id"),
                    "images": msg_doc.get("images", [])
                })
            session = {"_id": session_id, "history": history}  # 为了兼容后续代码
        else:
            session = await db[settings.mongodb_db_name].chat_sessions.find_one(
                {"_id": session_id}
            )
            history = session.get("history", []) if session else []
        total_messages = len(history)
        recent_history = history[-INITIAL_LOAD_LIMIT:] if len(history) > INITIAL_LOAD_LIMIT else history
        has_more = len(history) > INITIAL_LOAD_LIMIT
        
        # 展开历史中的精简引用为富引用（使用专用函数，不检查RAG模式）
        try:
            kb_settings, vectorstore = await _build_vectorstore_for_history(session_id, db)
            history_to_send = await _expand_history_references([m.copy() for m in recent_history], kb_settings, vectorstore, db)
        except Exception:
            history_to_send = recent_history
        
        # 发送历史消息（带元数据）
        if history:
            logger.info(f"发送历史消息（懒加载），显示最近{len(recent_history)}条，总共{total_messages}条，还有更多: {has_more}")
            # 调试：检查第一条消息的 timestamp
            if history_to_send:
                first_msg = history_to_send[0]
                logger.info(f"🔍 第一条历史消息的 timestamp: {first_msg.get('timestamp')} (类型: {type(first_msg.get('timestamp'))})")
            
            await websocket.send_json(jsonable_encoder({
                "type": "history",
                "messages": history_to_send,
                "total": total_messages,
                "loaded": len(recent_history),
                "has_more": has_more
            }))
        
        while True:
            try:
                # 接收消息
                data = await websocket.receive_text()
                logger.info(f"收到WebSocket消息: {data}")
                message_data = json.loads(data)

                # 心跳处理：回复pong
                if message_data.get("type") == "ping":
                    await websocket.send_json(jsonable_encoder({"type": "pong"}))
                    continue

                user_message = message_data.get("message", "")
                images_base64 = message_data.get("images", [])  # 获取多张图片base64数据
                model_settings = message_data.get("model_settings")  # 获取模型配置
                enable_voice = message_data.get("enable_voice", False)  # 获取语音开关状态
                referenced_docs = message_data.get("referenced_docs", [])  # 🆕 获取引用文档列表
                
                # 🆕 重置当前会话的全局引用序号（新一轮对话开始）
                from ..mcp.tools.knowledge_retrieval import _marker_manager
                _marker_manager.reset_session(session_id)
                
                # 安全日志：记录模型配置信息但不包含敏感数据
                if model_settings:
                    logger.info("收到会话特定的模型配置:")
                    logger.info(f"- 模型服务: {model_settings.get('modelService')}")
                    logger.info(f"- 基础URL: {model_settings.get('baseUrl')}")
                    logger.info(f"- 模型名称: {model_settings.get('modelName')}")
                    has_api_key = bool(model_settings.get('apiKey'))
                    logger.info(f"- API密钥: {'已提供' if has_api_key else '未提供'}")
                else:
                    logger.info("未收到会话特定的模型配置，将使用系统默认配置")
                
                if not user_message.strip() and len(images_base64) == 0:
                    logger.warning("收到空消息且无图片")
                    continue
                
                # 准备用户消息文档，但暂不保存
                message_id = f"{session_id}_{len(history)}"
                base_time = datetime.utcnow()
                user_time = base_time.isoformat() + 'Z'  # 转换为ISO字符串格式，与前端保持一致
                user_message_doc = {
                    "role": "user",
                    "content": user_message,  # 保存原始用户消息（不包含注入的引用文档）
                    "timestamp": user_time,  # 使用ISO字符串格式，便于前后端匹配
                    "images": []  # 初始化图片字段
                }

                # 生成AI回复
                try:
                    logger.info("开始生成AI回复")
                    complete_response = ""  # 用于累积完整响应
                    # 获取会话的system_prompt
                    session_data = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id})
                    system_prompt = session_data.get("system_prompt") if session_data else None
                    logger.info(f"使用会话的system_prompt: {system_prompt}")
                    
                    # 如果未从前端收到模型配置，则从会话中加载
                    if not model_settings and session_data:
                        model_settings = session_data.get("model_settings")
                        logger.info("从会话中加载模型配置用于生成回复")
                    
                    # 获取会话的上下文数量设置
                    session_data = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id})
                    context_count = session_data.get("context_count", 20) if session_data else 20
                    logger.info(f"使用上下文数量: {context_count}")
                    
                    # 获取指定数量的历史消息用于上下文
                    if context_count is None:
                        # 当context_count为None时，获取所有历史消息（不限制）
                        recent_history = await db[settings.mongodb_db_name].chat_sessions.find_one(
                            {"_id": session_id},
                            {"history": 1}
                        )
                        recent_history = recent_history.get("history", []) if recent_history else []
                        logger.info(f"上下文数量为None，使用所有历史消息: {len(recent_history)}")
                    elif context_count > 0:
                        recent_history = await db[settings.mongodb_db_name].chat_sessions.find_one(
                            {"_id": session_id},
                            {"history": {"$slice": -context_count}}  # 获取最后context_count条消息
                        )
                        recent_history = recent_history.get("history", []) if recent_history else []
                        logger.info(f"获取到历史消息数量: {len(recent_history)}")
                    else:
                        # 当context_count为0时，不使用历史上下文
                        recent_history = []
                        logger.info("上下文数量为0，不使用历史上下文")
                    
                    # 过滤历史消息内容，移除深度思考标签用于上下文传递
                    filtered_history = []
                    for msg in recent_history:
                        filtered_msg = msg.copy()
                        if 'content' in filtered_msg:
                            filtered_msg['content'] = prepare_content_for_context(filtered_msg['content'])
                        filtered_history.append(filtered_msg)
                    logger.info(f"历史消息已过滤，移除深度思考内容用于上下文传递")
                    
                    # 🆕 处理引用文档（智能策略：@文档注入用户消息，@知识库注入系统提示词）
                    user_message_addition = None  # 注入到用户消息的内容（@文档）
                    kb_system_prompt_addition = None  # 注入到系统提示词的内容（@知识库）
                    
                    if referenced_docs:
                        from ..services.referenced_docs_handler import ReferencedDocsHandler
                        ref_handler = ReferencedDocsHandler(db, settings.mongodb_db_name)
                        user_message_addition, kb_system_prompt_addition = await ref_handler.process_referenced_docs(
                            referenced_docs, user.id, user_message
                        )
                        if user_message_addition:
                            logger.info(f"📄 引用文档处理完成，用户消息注入内容长度: {len(user_message_addition)}")
                        if kb_system_prompt_addition:
                            logger.info(f"📚 知识库提示词生成完成，长度: {len(kb_system_prompt_addition)}")
                    
                    # 知识库检索：如果会话启用了知识库，则构建完整的系统提示词（不与原提示词拼接）
                    kb_system_prompt = await retrieve_knowledge_for_session(user_message, session_id, db, user.id)
                    if kb_system_prompt:
                        system_prompt = kb_system_prompt
                        logger.info("已使用知识库提示词覆盖system_prompt")
                    
                    # 🆕 如果用户@了知识库，将知识库提示词追加到系统提示词
                    if kb_system_prompt_addition:
                        system_prompt = (system_prompt or "") + kb_system_prompt_addition
                        logger.info("📚 @知识库 提示词已注入到 system_prompt")
                    
                    # 🆕 将 @文档 内容注入到用户消息中
                    final_user_message = user_message
                    if user_message_addition:
                        # 将引用文档放在用户消息前面，用 XML 标签包裹
                        final_user_message = f"{user_message_addition}\n\n{user_message}"
                        logger.info("📄 @文档 内容已注入到用户消息")
                        logger.info(f"📄 最终用户消息长度: {len(final_user_message)}")
                    
                    # 组装并发送引用（富 -> 前端；精简 -> 持久化）
                    lean_refs: List[Dict[str, Any]] = []
                    rich_refs_cache: List[Dict[str, Any]] = []
                    try:
                        kb_settings, vectorstore = await _build_vectorstore_for_session(session_id, db)
                        logger.info(f"🔍 本地RAG - kb_settings存在: {kb_settings is not None}, vectorstore存在: {vectorstore is not None}")
                        
                        if kb_settings and vectorstore:
                            logger.info(f"🔍 本地RAG - 开始检索引用，查询: {user_message[:100]}")
                            refs = await _retrieve_references(user_message, kb_settings, vectorstore, db)
                            lean_refs = refs.get("lean", [])
                            rich_refs_cache = refs.get("rich", [])
                            logger.info(f"🔍 本地RAG - 检索完成，lean_refs数量: {len(lean_refs)}, rich_refs数量: {len(rich_refs_cache)}")
                            
                            if rich_refs_cache:
                                await websocket.send_json(jsonable_encoder({
                                    "type": "reference",
                                    "reference": {"chunks": rich_refs_cache},
                                    "content": ""
                                }))
                                logger.info(f"✅ 已发送知识库引用到前端，条数: {len(rich_refs_cache)}")
                                logger.info(f"📄 引用示例: {rich_refs_cache[0] if rich_refs_cache else None}")
                            else:
                                logger.info(f"⚠️ 本地RAG未检索到任何引用（可能超出相似度阈值或知识库为空）")
                        else:
                            logger.info(f"⚠️ 会话未启用本地RAG知识库或向量存储未构建")
                    except Exception as ref_err:
                        logger.error(f"❌ 引用构建或下发失败: {ref_err}", exc_info=True)
                        lean_refs = []
                    
                    # 生成回复（使用 MCP 工具调用模式）
                    saved_images = []
                    # 用于累积 MCP 工具返回的引用（如果有的话）
                    mcp_rich_refs: List[Dict[str, Any]] = []
                    mcp_lean_refs: List[Dict[str, Any]] = []
                    
                    # 🚀 使用新的通用流式管理器
                    # 首先注册WebSocket会话
                    from ..utils.llm.streaming_manager import streaming_manager
                    await streaming_manager.register_session(
                        session_id=session_id,
                        user_id=user.id,
                        websocket=websocket
                    )
                    
                    # 选择使用新的流式管理器还是原方法
                    from ..utils.llm.streaming_config import streaming_config
                    use_new_streaming = streaming_config.enable_universal_streaming
                    
                    if use_new_streaming:
                        try:
                            stream_generator = model_service.generate_stream_universal(
                                user_message=final_user_message,  # 使用注入了引用文档的消息
                                history=filtered_history,  # 使用过滤后的历史消息
                                model_settings=model_settings,
                                system_prompt=system_prompt or "",
                                session_id=session_id,
                                user_id=user.id,  # 传递用户ID用于MinIO路径隔离，与REST API认证保持一致
                                images_base64=images_base64,  # 传递多张图片base64数据
                                enable_tools=True,  # 启用工具调用
                                message_id=message_id,
                                # max_tool_iterations 参数已移除，使用 tool_config.max_iterations 全局配置
                            )
                        except Exception as streaming_error:
                            logger.error(f"通用流式生成初始化失败，回退到原方法: {streaming_error}")
                            use_new_streaming = False
                    
                    if not use_new_streaming:
                        # 回退到原来的方法（使用全局配置的 max_iterations）
                        stream_generator = model_service.generate_with_tools(
                            final_user_message,  # 使用注入了引用文档的消息
                            history=filtered_history,  # 使用过滤后的历史消息
                            model_settings=model_settings,
                            system_prompt=system_prompt or "",
                            session_id=session_id,
                            message_id=message_id,
                            user_id=user.id,  # 传递用户ID用于MinIO路径隔离，与REST API认证保持一致
                            images_base64=images_base64,  # 传递多张图片base64数据
                            # max_tool_iterations 参数已移除，使用 tool_config.max_iterations 全局配置
                        )
                    
                    # 🎙️ 初始化流式TTS会话（如果启用语音）
                    tts_session = None
                    if enable_voice:
                        try:
                            # 获取TTS配置
                            # 获取文本清洗配置
                            enable_text_cleaning = message_data.get("enable_text_cleaning", True)
                            cleaning_patterns = message_data.get("text_cleaning_patterns")
                            preserve_quotes = message_data.get("preserve_quotes", True)
                            
                            # 获取会话的TTS配置
                            session_data = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id})
                            tts_settings = session_data.get("tts_settings") if session_data else None
                            
                            tts_type = None
                            tts_config = {}
                            voice_settings = {}
                            
                            if tts_settings and tts_settings.get("provider"):
                                # 使用会话级TTS配置
                                tts_type = tts_settings["provider"]
                                voice_settings = tts_settings.get("voice_settings", {})
                                tts_config = tts_settings.get("config", {})
                                
                                if not tts_config:
                                    # 从用户的全局TTS配置中读取密钥
                                    user_doc = await db[settings.mongodb_db_name].users.find_one({"_id": ObjectId(user.id)})
                                    if user_doc:
                                        tts_configs = user_doc.get("tts_configs", {})
                                        if tts_type in tts_configs:
                                            tts_config = tts_configs[tts_type].get("config", {})
                            else:
                                # 使用用户的默认TTS配置
                                user_doc = await db[settings.mongodb_db_name].users.find_one({"_id": ObjectId(user.id)})
                                if user_doc:
                                    default_tts = user_doc.get("default_tts_provider", "")
                                    tts_configs = user_doc.get("tts_configs", {})
                                    
                                    if default_tts and default_tts in tts_configs:
                                        default_config = tts_configs[default_tts]
                                        tts_type = default_tts
                                        tts_config = default_config.get("config", {})
                                        voice_settings = default_config.get("voice_settings", {})
                            
                            # 创建流式TTS会话（音频数据通过WebSocket直接发送，不再保存文件）
                            if tts_type and tts_config:
                                tts_session = streaming_tts_manager.create_session(
                                    session_id=session_id,
                                    websocket=websocket,
                                    tts_type=tts_type,
                                    tts_config=tts_config,
                                    voice_settings=voice_settings,
                                    enable_text_cleaning=enable_text_cleaning,
                                    cleaning_patterns=cleaning_patterns,
                                    preserve_quotes=preserve_quotes
                                )
                                await tts_session.start()
                                logger.info(f"✨ 流式TTS会话已启动: {tts_type}")
                            else:
                                logger.info("未配置TTS或配置无效，跳过流式TTS")
                        except Exception as e:
                            logger.error(f"初始化流式TTS失败: {e}", exc_info=True)
                    
                    async for chunk in stream_generator:
                        if chunk:
                            # 🎯 检查是否是工具状态消息（特殊格式）
                            if chunk.startswith("__TOOL_STATUS__") and chunk.endswith("__END__"):
                                # 提取工具状态JSON，但不发送到前端（避免显示多余气泡）
                                try:
                                    status_json = chunk[15:-7]  # 去掉 __TOOL_STATUS__ 和 __END__
                                    status_data = json.loads(status_json)
                                    # 只记录日志，不发送到前端
                                    logger.debug(f"🔧 工具状态（不发送到前端）: {status_data}")
                                except Exception as e:
                                    logger.error(f"解析工具状态失败: {e}")
                            # 🎯 检查是否是引用数据消息（新增）
                            elif chunk.startswith("__REFERENCES__") and chunk.endswith("__END__"):
                                # 提取引用数据JSON
                                try:
                                    refs_json = chunk[14:-7]  # 去掉 __REFERENCES__ 和 __END__
                                    refs_data = json.loads(refs_json)
                                    mcp_rich_refs.extend(refs_data.get("rich", []))
                                    mcp_lean_refs.extend(refs_data.get("lean", []))
                                    
                                    # 发送引用到前端（与旧 RAG 格式一致）
                                    await websocket.send_json(jsonable_encoder({
                                        "type": "reference",
                                        "reference": {"chunks": refs_data.get("rich", [])},
                                        "content": ""
                                    }))
                                    logger.info(f"📚 已接收并发送 MCP 工具引用到前端，条数: {len(refs_data.get('rich', []))}")
                                except Exception as e:
                                    logger.error(f"解析引用数据失败: {e}")
                            else:
                                # 正常的消息内容
                                complete_response += chunk  # 累积响应
                                logger.debug(f"发送回复片段(len={len(chunk)}): {chunk[:120]}{'...' if len(chunk) > 120 else ''}")
                                await websocket.send_json(jsonable_encoder({
                                    "type": "message",
                                    "content": chunk
                                }))
                                # 关键修复：强制将控制权交还给事件循环，以确保WebSocket消息被及时发送
                                # 尤其是在日志被禁用的情况下，可以防止输出缓冲
                                await asyncio.sleep(0)
                                
                                # 🎙️ 添加文本到流式TTS会话
                                if tts_session:
                                    await tts_session.add_text(chunk)
                    
                    # 获取保存的图片信息（如果有的话）
                    if hasattr(model_service, 'last_saved_images'):
                        saved_images = model_service.last_saved_images
                        logger.info(f"获取到保存的图片: {saved_images}")
                    else:
                        logger.warning("⚠️ 无法获取保存的图片信息")
                    
                    # API调用成功，保存用户消息和AI回复
                    if complete_response:
                        # 如果有图片，更新用户消息文档中的图片字段
                        if images_base64 and len(images_base64) > 0:
                            # 使用实际保存的图片URL
                            if saved_images and len(saved_images) > 0:
                                user_message_doc["images"] = saved_images
                                logger.info(f"✅ 使用实际保存的图片URL: {user_message_doc['images']}")
                            else:
                                # 如果有图片但没有获取到实际URL，记录警告但不保存默认路径
                                logger.warning("⚠️ 有图片但未能获取到保存的URL，不保存图片路径到数据库")
                                user_message_doc["images"] = []
                        
                        # 🎯 合并引用：优先使用 MCP 工具返回的引用，如果没有则使用传统 RAG 引用
                        final_lean_refs = mcp_lean_refs if mcp_lean_refs else lean_refs
                        
                        # 🔍 详细日志：检查引用数据来源
                        logger.info(f"📊 引用数据统计:")
                        logger.info(f"  - 本地RAG引用数量: {len(lean_refs)}")
                        logger.info(f"  - MCP工具引用数量: {len(mcp_lean_refs)}")
                        logger.info(f"  - 最终保存引用数量: {len(final_lean_refs)}")
                        
                        if final_lean_refs:
                            logger.info(f"💾 保存引用到数据库: {len(final_lean_refs)} 条 (来源: {'MCP工具' if mcp_lean_refs else '传统RAG'})")
                            logger.info(f"📄 引用数据示例: {final_lean_refs[0] if final_lean_refs else None}")
                        else:
                            logger.warning("⚠️ 没有任何引用数据需要保存（本地RAG和MCP工具都没有返回引用）")
                        
                        # 保存用户消息和AI回复
                        # AI回复使用序列号确保在用户消息之后
                        assistant_time = (base_time + timedelta(seconds=1)).isoformat() + 'Z'  # 转换为ISO字符串格式
                        
                        ai_message_doc = {
                            "role": "assistant",
                            "content": complete_response,
                            "timestamp": assistant_time,  # 使用ISO字符串格式，便于前后端匹配
                            "reference": final_lean_refs,  # 使用合并后的引用
                        }
                        # 一次性保存用户消息和AI回复，并更新消息数量
                        await db[settings.mongodb_db_name].chat_sessions.update_one(
                            {"_id": session_id},
                            {
                                "$push": {
                                    "history": {
                                        "$each": [user_message_doc, ai_message_doc]
                                    }
                                },
                                "$inc": {
                                    "message_count": 2  # 增加2条消息（用户消息 + AI回复）
                                }
                            }
                        )
                        # 更新本地历史记录
                        history.extend([user_message_doc, ai_message_doc])
                        logger.info("用户消息和AI回复已一起保存到数据库，消息数量已更新")

                        # 🎙️ 完成流式TTS（处理剩余文本）
                        if tts_session:
                            try:
                                # 完成TTS会话，处理缓冲区剩余文本
                                await tts_session.finish()
                                # 移除会话
                                streaming_tts_manager.remove_session(session_id)
                                logger.info(f"✅ 流式TTS已完成并清理: {session_id}")
                            except Exception as e:
                                logger.error(f"完成流式TTS失败: {e}", exc_info=True)
                        
                        # 发送成功完成信号，包含图片信息和用户/AI消息的时间戳
                        done_message = {
                            "type": "done",
                            "success": True,
                            "user_timestamp": user_time,  # 🔑 返回用户消息的时间戳，用于前端更新
                            "assistant_timestamp": assistant_time  # 🔑 返回AI消息的时间戳，确保前后端一致
                        }
                        
                        # 如果有保存的图片，添加到完成消息中
                        if saved_images and len(saved_images) > 0:
                            done_message["saved_images"] = saved_images
                            logger.info(f"✅ 在完成消息中包含图片信息: {saved_images}")
                        
                        await websocket.send_json(jsonable_encoder(done_message))
                    else:
                        # 没有生成任何内容
                        await websocket.send_json(jsonable_encoder({
                            "type": "done",
                            "success": False,
                            "error": "未能生成有效回复"
                        }))
                    
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"生成AI回复失败: {error_message}")
                    
                    # 检测是否是异常数据注入错误（ValueError）
                    if isinstance(e, ValueError) and ('异常数据' in error_message or '过长' in error_message):
                        # 对于异常数据注入，发送error类型消息（触发前端弹窗）
                        await websocket.send_json(jsonable_encoder({
                            "type": "error",
                            "content": error_message
                        }))
                    else:
                        # 其他错误，发送done消息
                        await websocket.send_json(jsonable_encoder({
                            "type": "done",
                            "success": False,
                            "error": error_message
                        }))

            except WebSocketDisconnect:
                logger.info(f"WebSocket连接断开 - 会话ID: {session_id}")
                # 清理流式会话
                try:
                    await streaming_manager.unregister_session(session_id)
                except:
                    pass
                break
            except Exception as e:
                logger.error(f"WebSocket消息处理失败: {str(e)}")
                try:
                    await websocket.send_json(jsonable_encoder({
                        "type": "done",
                        "success": False,
                        "error": "消息处理失败"
                    }))
                except:
                    pass
                    break

    except WebSocketDisconnect:
        logger.info("WebSocket连接已断开")
        # 清理流式会话
        try:
            await streaming_manager.unregister_session(session_id)
        except:
            pass
    except Exception as e:
        logger.error(f"WebSocket连接处理失败: {str(e)}")
        # 清理流式会话
        try:
            await streaming_manager.unregister_session(session_id)
        except:
            pass
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass

@router.put("/sessions/{session_id}")
async def update_session(
	session_id: str,
	update_data: dict,
	db: AsyncIOMotorClient = Depends(get_database),
	current_user: User = Depends(get_current_user)
):
	"""更新会话信息"""
	logger.info(f"更新会话请求 - 会话ID: {session_id}, 用户ID: {current_user.id}")
	
	try:
		# 验证会话所有权
		session = await db[settings.mongodb_db_name].chat_sessions.find_one({
			"_id": session_id,
			"user_id": str(current_user.id)
		})
		
		if not session:
			logger.error(f"未找到会话或无权限: {session_id}")
			raise HTTPException(status_code=404, detail="Session not found")
			
		# 更新会话
		update_result = await db[settings.mongodb_db_name].chat_sessions.update_one(
			{"_id": session_id, "user_id": str(current_user.id)},
			{"$set": update_data}
		)
		
		# 兼容未修改内容的情况：若 matched=1 且 modified=0 也视为成功
		if getattr(update_result, 'matched_count', 0) == 0:
			logger.error(f"会话更新失败（未匹配到文档）: {session_id}")
			raise HTTPException(status_code=404, detail="Session not found")
		
		# 获取更新后的会话
		updated_session = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id, "user_id": str(current_user.id)})
		logger.info(f"会话更新成功: {session_id}")
		
		return updated_session
		
	except Exception as e:
		logger.error(f"更新会话时出错: {str(e)}")
		raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: User = Depends(get_current_user)
):
    """删除会话"""
    try:
        # 验证会话所有权
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
            
        # 删除会话记录
        result = await db[settings.mongodb_db_name].chat_sessions.delete_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="删除失败，会话不存在")
        
        # 尝试按DB中存储的URL精确删除头像（以防前缀不匹配造成遗漏）
        try:
            from ..utils.minio_client import minio_client
            if "role_avatar_url" in session and session["role_avatar_url"]:
                minio_client.delete_image(session["role_avatar_url"])
                logger.info(f"已按URL精确删除会话头像: {session['role_avatar_url']}")
        except Exception as e:
            logger.error(f"按URL删除会话头像失败: {str(e)}")
            # 不影响主流程
        
        # 删除会话的向量存储
        try:
            # model_service.vector_store.delete_session(session_id) # 移除向量存储删除
            logger.info(f"成功删除会话 {session_id} 的向量存储")
        except Exception as e:
            logger.error(f"删除会话向量存储失败: {str(e)}")
            # 不影响主流程，继续返回成功
        
        # 删除MinIO中的会话头像文件夹（传统会话角色头像）
        try:
            from ..utils.minio_client import minio_client
            # 统一确定资源所属用户（若会话记录存在 user_id 则按其删除，更稳妥）
            owner_user_id = str(session.get("user_id")) if session.get("user_id") else str(current_user.id)

            # 现用路径（仅头像）
            prefix_avatar = f"users/{owner_user_id}/sessions/{session_id}/role_avatar"
            minio_client.delete_prefix(prefix_avatar)
            logger.info(f"成功删除会话头像前缀: {prefix_avatar}")

            # 删除传统会话消息图片
            prefix_message_image = f"users/{owner_user_id}/sessions/{session_id}/message_image"
            minio_client.delete_prefix(prefix_message_image)
            logger.info(f"成功删除传统会话消息图片前缀: {prefix_message_image}")

            # 同时清理该会话下所有资源（更稳妥）
            prefix_session_root = f"users/{owner_user_id}/sessions/{session_id}"
            minio_client.delete_prefix(prefix_session_root)
            logger.info(f"成功删除会话资源根前缀: {prefix_session_root}")

            # 若记录中存在具体的 role_avatar_url，则按该URL反推出精确前缀进行删除（覆盖上传者与会话所属不一致的情况）
            role_avatar_url = session.get("role_avatar_url")
            if isinstance(role_avatar_url, str) and role_avatar_url.startswith("minio://"):
                try:
                    path_after_bucket = role_avatar_url.split("//", 1)[1].split("/", 1)[1]
                    last_slash_index = path_after_bucket.rfind("/")
                    if last_slash_index > 0:
                        precise_prefix = path_after_bucket[:last_slash_index + 1]
                        logger.info(f"尝试通过role_avatar_url删除精确前缀: {precise_prefix}")
                        minio_client.delete_prefix(precise_prefix)
                except Exception as e2:
                    logger.warning(f"解析 role_avatar_url 失败，跳过精确前缀清理: {e2}")

            # 兼容历史遗留路径（早期实现可能使用此前缀）
            legacy_prefix = f"roles/{session_id}"
            minio_client.delete_prefix(legacy_prefix)
            logger.info(f"成功删除会话头像历史前缀: {legacy_prefix}")
        except Exception as e:
            logger.error(f"删除会话头像MinIO前缀失败: {str(e)}")
            # 不影响主流程，继续返回成功
        
        return {"status": "success", "message": "会话已删除"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {str(e)}")
        raise HTTPException(status_code=500, detail="删除会话失败")

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    获取会话的历史消息（支持懒加载）
    
    Args:
        session_id: 会话ID
        limit: 限制返回的消息数量（从offset开始的N条）
        offset: 从第N条消息开始（0为最早的消息）
        
    Returns:
        {
            "messages": [...],
            "total": 总消息数,
            "has_more": 是否还有更多消息
        }
    """
    logger.info(f"开始获取会话消息 - 会话ID: {session_id}, 用户ID: {current_user.id}, limit: {limit}, offset: {offset}")
    try:
        # 查找会话并验证所有权
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            logger.error(f"会话不存在或无权访问 - 会话ID: {session_id}")
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        # 获取完整历史
        all_messages = session.get("history", [])
        total_count = len(all_messages)
        
        # 🔧 展开引用：将 lean 格式转换为 rich 格式（包含文本内容）
        try:
            kb_settings, vectorstore = await _build_vectorstore_for_history(session_id, db)
            all_messages = await _expand_history_references([m.copy() for m in all_messages], kb_settings, vectorstore, db)
            logger.info(f"✅ 成功展开历史消息引用")
        except Exception as e:
            logger.warning(f"⚠️ 展开历史引用失败，返回原始数据: {e}")
        
        # 如果没有指定limit，返回所有消息（向后兼容）
        if limit is None:
            logger.info(f"成功获取会话消息 - 消息数量: {total_count}")
            # 使用 jsonable_encoder 确保 datetime 被转换为 ISO 字符串
            return jsonable_encoder(all_messages)
        
        # 懒加载模式：按offset和limit切片
        offset = offset or 0
        end_index = offset + limit
        
        # 确保索引不越界
        offset = min(offset, total_count)
        end_index = min(end_index, total_count)
        
        messages = all_messages[offset:end_index]
        has_more = end_index < total_count
        
        logger.info(f"成功获取会话消息（懒加载） - 返回: {len(messages)}条, 总数: {total_count}, 还有更多: {has_more}")
        
        # 使用 jsonable_encoder 确保 datetime 被转换为 ISO 字符串
        return jsonable_encoder({
            "messages": messages,
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": has_more
        })
        
    except Exception as e:
        logger.error(f"获取会话消息失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取会话消息失败")

@router.delete("/sessions/{session_id}/messages/{message_index}")
async def delete_message(
    session_id: str,
    message_index: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    删除会话中的指定消息
    
    支持两种定位方式：
    1. 时间戳定位（推荐）：body 中传递 {"timestamp": xxx}
    2. 索引定位（向后兼容）：使用 URL 中的 message_index
    """
    logger.info(f"开始删除消息 - 会话ID: {session_id}, 消息索引: {message_index}, 用户ID: {current_user.id}")
    try:
        # 获取会话
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            logger.error(f"会话不存在或无权访问 - 会话ID: {session_id}")
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        history = session.get("history", [])
        
        # 尝试从 body 中获取时间戳（优先）
        body = {}
        try:
            body = await request.json()
        except:
            pass
        
        target_timestamp = body.get("timestamp")
        
        # 调试：打印收到的 timestamp
        logger.info(f"🔍 收到的 body: {body}")
        logger.info(f"🔍 收到的 timestamp: {target_timestamp} (类型: {type(target_timestamp)})")
        if history:
            logger.info(f"🔍 第一条消息的 timestamp: {history[0].get('timestamp')} (类型: {type(history[0].get('timestamp'))})")
        
        # 强制使用时间戳定位，避免懒加载场景下的索引错位问题
        if not target_timestamp:
            raise HTTPException(
                status_code=400, 
                detail="必须提供消息时间戳用于精确定位，索引定位已废弃"
            )
        
        # 使用时间戳定位（兼容字符串和datetime类型）
        actual_index = None
        
        target_normalized = normalize_timestamp(target_timestamp)
        
        for i, msg in enumerate(history):
            msg_timestamp = msg.get("timestamp")
            msg_normalized = normalize_timestamp(msg_timestamp)
            
            # 归一化后比较（忽略时区后缀和微秒位数差异）
            if target_normalized.startswith(msg_normalized[:19]) or msg_normalized.startswith(target_normalized[:19]):
                # 至少匹配到秒级别
                actual_index = i
                logger.info(f"✅ 使用时间戳定位到消息索引: {actual_index}, timestamp: {target_timestamp}")
                break
        
        if actual_index is None:
            logger.error(f"❌ 未找到匹配的消息 - 目标 timestamp: {target_timestamp}, 历史消息数量: {len(history)}")
            raise HTTPException(status_code=404, detail="未找到指定时间戳的消息")
        
        # 删除指定索引的消息
        deleted_message = history.pop(actual_index)
        logger.info(f"已从内存中删除消息 - 角色: {deleted_message.get('role')}, 内容预览: {deleted_message.get('content', '')[:50]}...")
        
        # 检查并删除MinIO中的图片文件
        try:
            from ..utils.minio_client import minio_client
            
            # 检查消息是否包含图片
            images = deleted_message.get('images', [])
            if images and len(images) > 0:
                logger.info(f"发现消息包含 {len(images)} 张图片，开始删除MinIO文件")
                
                deleted_images_count = 0
                for image_url in images:
                    if image_url.startswith('minio://'):
                        if minio_client.delete_image(image_url):
                            deleted_images_count += 1
                            logger.info(f"成功删除MinIO图片: {image_url}")
                        else:
                            logger.warning(f"删除MinIO图片失败: {image_url}")
                    else:
                        logger.info(f"跳过非MinIO图片: {image_url}")
                
                logger.info(f"MinIO图片删除完成，成功删除 {deleted_images_count}/{len(images)} 张图片")
            else:
                logger.info("消息不包含图片，跳过MinIO删除操作")
        except Exception as e:
            logger.warning(f"删除MinIO图片失败: {str(e)}")
        
        # 从向量存储中删除消息
        try:
            # from ..utils.vector_store.vector_store import VectorStore # 移除向量存储导入
            # vector_store = VectorStore() # 移除向量存储实例
            
            # 获取被删除消息的内容、角色和时间戳
            deleted_content = deleted_message.get('content', '')
            deleted_role = deleted_message.get('role', '')
            deleted_timestamp = deleted_message.get('timestamp', '')
            
            if deleted_content and deleted_role and deleted_timestamp:
                # 删除向量存储中的对应消息
                # vector_store.delete_message(session_id, deleted_content, deleted_role, deleted_timestamp) # 移除向量存储删除
                logger.info(f"成功从向量存储删除消息 - 角色: {deleted_role}, 内容长度: {len(deleted_content)}, 时间戳: {deleted_timestamp}")
            else:
                logger.warning("被删除的消息缺少内容、角色或时间戳信息，无法从向量存储中删除")
        except Exception as e:
            logger.warning(f"从向量存储删除消息失败: {str(e)}")
        
        # 更新数据库
        result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {
                "_id": session_id,
                "user_id": str(current_user.id)
            },
            {
                "$set": {
                    "history": history,
                    "message_count": len(history)
                }
            }
        )
        
        if result.modified_count == 0:
            logger.error(f"数据库更新失败 - 会话ID: {session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
            
        logger.info(f"成功删除消息 - 会话ID: {session_id}, 消息索引: {message_index}")
        return {"status": "success", "message": "消息已删除"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除消息失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除消息失败")

@router.put("/sessions/{session_id}/messages/{message_index}")
async def update_message(
    session_id: str,
    message_index: int,
    request: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    修改会话中的指定消息
    
    使用时间戳定位（必须在 request 中传递 {"timestamp": xxx, ...}）
    """
    logger.info(f"开始修改消息 - 会话ID: {session_id}, 消息索引: {message_index}, 用户ID: {current_user.id}")
    try:
        # 获取会话
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            logger.error(f"会话不存在或无权访问 - 会话ID: {session_id}")
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        history = session.get("history", [])
        
        # 强制使用时间戳定位，避免懒加载场景下的索引错位问题
        target_timestamp = request.get("timestamp")
        
        if not target_timestamp:
            raise HTTPException(
                status_code=400, 
                detail="必须提供消息时间戳用于精确定位，索引定位已废弃"
            )
        
        # 使用时间戳定位（兼容字符串和datetime类型）
        actual_index = None
        
        target_normalized = normalize_timestamp(target_timestamp)
        
        for i, msg in enumerate(history):
            msg_timestamp = msg.get("timestamp")
            msg_normalized = normalize_timestamp(msg_timestamp)
            
            # 归一化后比较（忽略时区后缀和微秒位数差异）
            if target_normalized.startswith(msg_normalized[:19]) or msg_normalized.startswith(target_normalized[:19]):
                # 至少匹配到秒级别
                actual_index = i
                logger.info(f"✅ 使用时间戳定位到消息索引: {actual_index}, timestamp: {target_timestamp}")
                break
        
        if actual_index is None:
            logger.error(f"❌ 未找到匹配的消息 - 目标 timestamp: {target_timestamp}, 历史消息数量: {len(history)}")
            raise HTTPException(status_code=404, detail="未找到指定时间戳的消息")
        
        # 获取要修改的消息
        message_to_update = history[actual_index]
        original_content = message_to_update.get('content', '')
        original_images = message_to_update.get('images', [])
        
        # 获取修改内容
        new_content = request.get('content', original_content)
        new_images = request.get('images', original_images)
        images_to_delete = request.get('images_to_delete', [])
        
        logger.info(f"修改消息内容 - 原内容长度: {len(original_content)}, 新内容长度: {len(new_content)}")
        logger.info(f"图片处理 - 原图片数量: {len(original_images)}, 新图片数量: {len(new_images)}, 待删除图片数量: {len(images_to_delete)}")
        
        # 处理需要删除的图片
        if images_to_delete:
            try:
                from ..utils.minio_client import minio_client
                
                deleted_images_count = 0
                for image_url in images_to_delete:
                    if image_url.startswith('minio://'):
                        if minio_client.delete_image(image_url):
                            deleted_images_count += 1
                            logger.info(f"成功删除MinIO图片: {image_url}")
                        else:
                            logger.warning(f"删除MinIO图片失败: {image_url}")
                    else:
                        logger.info(f"跳过非MinIO图片: {image_url}")
                
                logger.info(f"MinIO图片删除完成，成功删除 {deleted_images_count}/{len(images_to_delete)} 张图片")
                
                # 从新图片列表中移除已删除的图片
                new_images = [img for img in new_images if img not in images_to_delete]
                
            except Exception as e:
                logger.warning(f"删除MinIO图片失败: {str(e)}")
        
        # 更新消息内容
        history[actual_index]['content'] = new_content
        history[actual_index]['images'] = new_images
        history[actual_index]['updated_at'] = datetime.utcnow().isoformat() + 'Z'
        
        # 更新数据库
        result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {
                "_id": session_id,
                "user_id": str(current_user.id)
            },
            {
                "$set": {
                    "history": history
                }
            }
        )
        
        if result.modified_count == 0:
            logger.error(f"数据库更新失败 - 会话ID: {session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
            
        logger.info(f"成功修改消息 - 会话ID: {session_id}, 消息索引: {message_index}")
        return {
            "status": "success", 
            "message": "消息已修改",
            "updated_message": history[message_index]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改消息失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="修改消息失败")

@router.get("/sessions/{session_id}/export")
async def export_session_data(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """导出会话的对话数据"""
    logger.info(f"开始导出会话数据 - 会话ID: {session_id}, 用户ID: {current_user.id}")
    try:
        # 获取会话并验证所有权
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            logger.error(f"会话不存在或无权访问 - 会话ID: {session_id}")
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        # 获取历史消息
        history = session.get("history", [])
        session_name = session.get("name", "未命名会话")
        
        # 添加调试日志
        logger.info(f"会话历史记录数量: {len(history)}")
        for i, msg in enumerate(history):
            logger.info(f"消息 {i}: role={msg.get('role')}, content_length={len(msg.get('content', ''))}")
        
        # 生成对话文本
        conversation_text = f"会话名称: {session_name}\n"
        conversation_text += f"创建时间: {session.get('created_at', '未知')}\n"
        conversation_text += "=" * 50 + "\n\n"
        
        conversation_count = 1
        i = 0
        
        while i < len(history):
            message = history[i]
            role = message.get('role', '')
            content = message.get('content', '')
            
            if role == 'user':
                conversation_text += f"{conversation_count}. 我：{content}\n"
                
                # 查找下一个助手消息
                if i + 1 < len(history) and history[i + 1].get('role') == 'assistant':
                    assistant_content = history[i + 1].get('content', '')
                    conversation_text += f"   {session_name}：{assistant_content}\n"
                    i += 2  # 跳过已处理的助手消息
                else:
                    i += 1
                
                conversation_text += "\n"  # 对话间隔空行
                conversation_count += 1
            elif role == 'assistant':
                # 如果遇到单独的助手消息，也记录
                conversation_text += f"{conversation_count}. {session_name}：{content}\n"
                conversation_text += "\n"  # 对话间隔空行
                conversation_count += 1
                i += 1
            else:
                # 跳过其他类型的消息（如system等）
                i += 1
        
        # 如果没有对话内容
        if conversation_count == 1:
            conversation_text += "暂无对话内容\n"
        
        logger.info(f"成功导出会话数据 - 会话ID: {session_id}, 对话数量: {conversation_count - 1}")
        logger.info(f"生成的对话文本长度: {len(conversation_text)}")
        logger.info(f"对话文本预览: {conversation_text[:200]}...")
        
        return {
            "status": "success",
            "data": {
                "session_name": session_name,
                "conversation_text": conversation_text,
                "conversation_count": conversation_count - 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出会话数据失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="导出会话数据失败") 

@router.get("/sessions/{session_id}/tts-config")
async def get_session_tts_config(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取会话的TTS配置"""
    logger.info(f"开始查询会话TTS配置 - 会话ID: {session_id}, 用户ID: {current_user.id}")
    
    try:
        # 查找会话并验证所有权
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            logger.error(f"会话不存在或无权访问 - 会话ID: {session_id}, 用户ID: {current_user.id}")
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        # 获取TTS配置
        tts_settings = session.get("tts_settings")
        
        if tts_settings:
            logger.info(f"找到TTS配置 - 会话ID: {session_id}")
            logger.info(f"TTS服务商: {tts_settings.get('provider', 'unknown')}")
            logger.info(f"配置字段数量: {len(tts_settings.get('config', {}))}")
            logger.info(f"音色设置: {tts_settings.get('voice_settings', {})}")
            
            return {
                "success": True,
                "has_config": True,
                "tts_settings": tts_settings
            }
        else:
            logger.info(f"未找到TTS配置 - 会话ID: {session_id}")
            return {
                "success": True,
                "has_config": False,
                "tts_settings": None
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询会话TTS配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询TTS配置失败")

@router.get("/test-ollama-config")
async def test_ollama_config(
    base_url: str,
    model_name: str,
    current_user: User = Depends(get_current_user)
):
    """测试 Ollama 模型配置"""
    try:
        logger.info(f"开始测试 Ollama 配置: base_url={base_url}, model_name={model_name}")
        
        # 导入 OpenAI 客户端
        from openai import OpenAI
        
        # 配置 OpenAI 客户端（指向 Ollama 服务器）
        client = OpenAI(
            base_url=f"{base_url}/v1",  # Ollama API 地址
            api_key="ollama",  # 任意字符串即可
        )
        
        # 构建测试请求
        test_messages = [
            {
                "role": "user",
                "content": "你好，请回复一个简单的测试消息"
            }
        ]
        
        logger.info(f"发送测试请求到: {base_url}/v1/chat/completions")
        logger.info(f"测试消息: {test_messages}")
        
        # 调用 Ollama API
        response = client.chat.completions.create(
            model=model_name,
            messages=test_messages,
            stream=False,
            temperature=0.7,
            max_tokens=50  # 限制回复长度，只用于测试
        )
        
        # 获取回复内容
        if response.choices and response.choices[0].message:
            reply_content = response.choices[0].message.content
            logger.info(f"Ollama 测试成功，模型回复: {reply_content}")
            
            return {
                "success": True,
                "message": "Ollama 模型配置测试成功",
                "model_reply": reply_content,
                "model_name": model_name,
                "base_url": base_url
            }
        else:
            logger.error("Ollama 响应格式不正确")
            return {
                "success": False,
                "message": "Ollama 响应格式不正确，未找到有效的回复内容"
            }
            
    except Exception as e:
        logger.error(f"Ollama 配置测试失败: {str(e)}")
        return {
            "success": False,
            "message": f"Ollama 配置测试失败: {str(e)}"
        }

@router.get("/ollama/tags")
async def get_ollama_tags(
    base_url: str,
    current_user: User = Depends(get_current_user)
):
    """代理获取 Ollama 已拉取模型列表 (/api/tags)"""
    try:
        import httpx
        url = base_url.rstrip('/') + '/api/tags'
        logger.info(f"代理请求 Ollama 模型列表: {url}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.error(f"Ollama /api/tags 请求失败: {resp.status_code} {resp.text}")
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            # 规范返回结构，确保前端可读取 data.models[].name
            models = data.get('models') or []
            return {"models": models}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 Ollama 模型列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取 Ollama 模型列表失败: {str(e)}") 


#====================================================================
@router.delete("/sessions/{session_id}/messages/{message_index}/after")
async def delete_messages_after(
    session_id: str,
    message_index: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    删除某条消息之后的所有历史消息（不包含该条消息），并删除这些消息中的 MinIO 图片
    
    使用时间戳定位（必须在 body 中传递 {"timestamp": xxx}）
    """
    try:
        # 获取会话并校验归属
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")

        history = session.get("history", [])
        
        # 特殊处理：message_index = -1 表示清空全部消息，不需要 timestamp
        if message_index == -1:
            messages_to_delete = history[:]
            actual_index = -1
            logger.info(f"🗑️ 清空会话所有消息 - 会话ID: {session_id}, 消息数量: {len(messages_to_delete)}")
        else:
            # 从 body 中获取时间戳
            body = {}
            try:
                body = await request.json()
            except:
                pass
            
            target_timestamp = body.get("timestamp")
            
            # 强制使用时间戳定位，避免懒加载场景下的索引错位问题
            if not target_timestamp:
                raise HTTPException(
                    status_code=400, 
                    detail="必须提供消息时间戳用于精确定位，索引定位已废弃"
                )
            
            # 使用时间戳定位（兼容字符串和datetime类型）
            actual_index = None
            
            target_normalized = normalize_timestamp(target_timestamp)
            
            for i, msg in enumerate(history):
                msg_timestamp = msg.get("timestamp")
                msg_normalized = normalize_timestamp(msg_timestamp)
                
                # 归一化后比较（忽略时区后缀和微秒位数差异）
                if target_normalized.startswith(msg_normalized[:19]) or msg_normalized.startswith(target_normalized[:19]):
                    # 至少匹配到秒级别
                    actual_index = i
                    logger.info(f"✅ 使用时间戳定位到消息索引: {actual_index}, timestamp: {target_timestamp}")
                    break
            
            if actual_index is None:
                logger.error(f"❌ 未找到匹配的消息 - 目标 timestamp: {target_timestamp}, 历史消息数量: {len(history)}")
                raise HTTPException(status_code=404, detail="未找到指定时间戳的消息")

            # 将要删除的消息列表（严格大于 actual_index）
            messages_to_delete = history[actual_index + 1:] if actual_index >= 0 else history[:]
        if not messages_to_delete:
            return {"status": "success", "message": "没有需要删除的消息"}

        # 删除 MinIO 图片
        try:
            from ..utils.minio_client import minio_client
            deleted_images_total = 0
            for msg in messages_to_delete:
                images = msg.get("images", []) or []
                for image_url in images:
                    if isinstance(image_url, str) and image_url.startswith("minio://"):
                        if minio_client.delete_image(image_url):
                            deleted_images_total += 1
            logger.info(f"从索引 {message_index} 之后删除消息中的 MinIO 图片总数: {deleted_images_total}")
        except Exception as e:
            logger.warning(f"删除 MinIO 图片时出错: {str(e)}")

        # 截断历史
        new_history = history[:actual_index + 1]
        update_result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {"_id": session_id, "user_id": str(current_user.id)},
            {"$set": {"history": new_history, "message_count": len(new_history)}}
        )
        if update_result.modified_count == 0:
            raise HTTPException(status_code=500, detail="更新会话失败")

        # 可选：同步删除向量存储中被截断的部分（若有）
        try:
            # 如果有向量存储实现，这里执行相应的删除逻辑
            pass
        except Exception as e:
            logger.warning(f"删除向量存储记录失败: {str(e)}")

        return {
            "status": "success",
            "message": "已删除该消息之后的所有历史消息",
            "remaining_count": len(new_history)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除后续消息失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除后续消息失败")

# 知识库检索函数
async def retrieve_knowledge_for_session(user_message: str, session_id: str, db: AsyncIOMotorClient, user_id: str) -> str:
    """
    为会话检索知识库内容，返回最终用于 system_prompt 的完整提示词（若未启用或无内容则返回空字符串）
    """
    try:
        # 获取会话的知识库配置
        session_data = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id})
        if not session_data:
            logger.warning(f"未找到会话 {session_id}")
            return ""
        
        kb_settings = session_data.get("kb_settings")
        if not kb_settings or not kb_settings.get("enabled"):
            logger.info("会话未启用知识库，跳过检索")
            return ""
        
        logger.info(f"开始为会话 {session_id} 检索知识库")
        logger.info(f"知识库配置: {kb_settings}")
        
        # ⚠️ 新逻辑：只有当 kb_prompt_template 存在且包含 {knowledge} 时才触发检索
        kb_prompt_template = kb_settings.get("kb_prompt_template") if isinstance(kb_settings, dict) else None
        
        # 如果没有配置模板或模板为空，跳过检索
        if not kb_prompt_template or not kb_prompt_template.strip():
            logger.info("❌ kb_prompt_template 为空，跳过知识库检索")
            return ""
        
        # 如果模板不包含 {knowledge} 占位符，跳过检索
        if "{knowledge}" not in kb_prompt_template:
            logger.info("❌ kb_prompt_template 未包含 {knowledge} 占位符，跳过知识库检索")
            # 仅当存在 {time} 占位符时才获取系统时间并替换
            if "{time}" in kb_prompt_template:
                from datetime import datetime
                formatted_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return kb_prompt_template.replace("{time}", formatted_time)
            return kb_prompt_template
        
        # 工具函数：基于模板构建提示词；当无检索结果时用 "None" 替换 {knowledge}
        def _build_prompt_with_knowledge_text(knowledge_text: str) -> str:
            local_template = kb_settings.get("kb_prompt_template") if isinstance(kb_settings, dict) else None
            if isinstance(local_template, str) and local_template.strip() and "{knowledge}" in local_template:
                final_prompt = local_template.replace("{knowledge}", knowledge_text)
                if "{time}" in final_prompt:
                    from datetime import datetime
                    formatted_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    final_prompt = final_prompt.replace("{time}", formatted_time)
                return final_prompt
            # # 回退默认模板
            # return None
        
        # 🆕 直接使用 kb_ids 进行检索
        kb_ids = kb_settings.get("kb_ids", [])
        if not kb_ids:
            logger.warning("kb_ids 为空，跳过检索")
            return _build_prompt_with_knowledge_text("None")
        
        # 判断单库还是多库检索
        if len(kb_ids) == 1:
            # 单知识库检索
            from .kb import _get_kb_components
            from ..utils.embedding.pipeline import Retriever
            from ..services.knowledge_base_service import KnowledgeBaseService
            
            # 获取知识库配置
            kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            kb = await kb_service.get_knowledge_base(kb_ids[0], user_id)
            if not kb:
                logger.warning(f"知识库不存在: {kb_ids[0]}")
                return _build_prompt_with_knowledge_text("None")
            
            # 使用知识库的配置构建vectorstore
            _, vectorstore, _ = _get_kb_components(kb.kb_settings)
            
            # ✅ 保存知识库真实配置，后续检索时使用
            actual_kb_settings = kb.kb_settings
        else:
            # 多知识库并行检索
            from ..services.multi_kb_retriever import get_multi_kb_retriever
            from ..services.knowledge_base_service import KnowledgeBaseService
            
            kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            kb_configs = []
            
            for kb_id in kb_ids:
                kb = await kb_service.get_knowledge_base(kb_id, user_id)
                if kb:
                    kb_configs.append({
                        'kb_id': kb_id,
                        'kb_name': kb.name,
                        'kb_settings': kb.kb_settings
                    })
            
            if not kb_configs:
                logger.warning("所有知识库都不存在或无权限")
                return _build_prompt_with_knowledge_text("None")
            
            # 使用多知识库检索器
            retriever = await get_multi_kb_retriever()
            top_k_per_kb = kb_settings.get("top_k_per_kb", 3)
            final_top_k = kb_settings.get("final_top_k", 10)
            merge_strategy = kb_settings.get("merge_strategy", "weighted_score")
            # ❌ 不要传递会话级别的相似度阈值，让每个知识库使用自己的配置
            # similarity_threshold = kb_settings.get("similarity_threshold", 10)
            
            results = await retriever.retrieve_from_multiple_kbs(
                query=user_message,
                kb_configs=kb_configs,
                top_k_per_kb=top_k_per_kb,
                similarity_threshold=None,  # ✅ 传 None，让每个知识库使用自己的阈值
                merge_strategy=merge_strategy,
                final_top_k=final_top_k
            )
            
            # 格式化多库检索结果
            knowledge_only = ""
            for i, result in enumerate(results, 1):
                logger.info(f"检索到片段 {i} (来自{result.kb_name}): 距离={result.distance:.3f}")
                knowledge_only += f"\n片段 {i} (来源: {result.kb_name}, 距离: {result.distance:.3f}):\n{result.content}\n"
            
            final_system_prompt = kb_prompt_template.replace("{knowledge}", knowledge_only.strip())
            if "{time}" in final_system_prompt:
                from datetime import datetime
                formatted_time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
                final_system_prompt = final_system_prompt.replace("{time}", formatted_time)
            
            logger.info(f"✅ 多库检索完成: {len(results)} 个结果")
            return final_system_prompt
        
        # === 以下是单知识库检索的逻辑 ===
        # 检查向量数据库是否有数据
        try:
            # 使用正确的API检查集合中的文档数量
            collection_data = vectorstore._store.get()
            doc_count = len(collection_data.get("ids", []))
            logger.info(f"向量数据库中文档数量: {doc_count}")
            
            if doc_count == 0:
                logger.warning("向量数据库为空，请先上传文档")
                return _build_prompt_with_knowledge_text("None")
                
        except Exception as e:
            logger.error(f"检查向量数据库状态失败: {str(e)}")
            return _build_prompt_with_knowledge_text("None")
        
        # 创建检索器并执行检索，应用相似度阈值过滤
        # ✅ 优先使用知识库自己的配置，如果不存在则使用会话配置作为兜底
        if len(kb_ids) == 1 and 'actual_kb_settings' in locals():
            # 单知识库模式：使用知识库自己的配置
            kb_similarity_threshold = actual_kb_settings.get("similarity_threshold")
            kb_distance_metric = actual_kb_settings.get("search_params", {}).get("distance_metric", "cosine")
            similarity_threshold = kb_similarity_threshold if kb_similarity_threshold is not None else 0.5
            logger.info(f"📊 使用知识库自己的相似度阈值: {similarity_threshold}, 距离度量: {kb_distance_metric}")
        else:
            # 兜底：使用会话配置（理论上不应该走到这里）
            similarity_threshold = kb_settings.get("similarity_threshold", 0.5) if isinstance(kb_settings, dict) else 0.5
            kb_distance_metric = "cosine"
            logger.warning(f"⚠️ 使用会话默认阈值: {similarity_threshold}")
        
        top_k = kb_settings.get("top_k", 3) if isinstance(kb_settings, dict) else 3
        # 限制 top_k 范围在 1-12 之间
        top_k = max(1, min(12, top_k))
        retriever = Retriever(
            vector_store=vectorstore, 
            top_k=top_k, 
            similarity_threshold=similarity_threshold,
            distance_metric=kb_distance_metric
        )
        # ✅ 使用异步检索，避免阻塞事件循环
        search_results = await retriever.search(user_message, top_k=top_k)
        
        logger.info(f"检索结果数量（过滤后）: {len(search_results) if search_results else 0}, top_k: {top_k}, 相似度阈值: {similarity_threshold}")
        
        if not search_results:
            logger.info(f"未检索到距离小于 {similarity_threshold} 的相关内容")
            # 尝试不带阈值检索，看看实际的距离分数
            test_retriever = Retriever(vector_store=vectorstore, top_k=3, distance_metric=kb_distance_metric)  # 不设置阈值
            # ✅ 使用异步检索
            test_results = await test_retriever.search(user_message, top_k=3)
            if test_results:
                logger.info(f"不带阈值检索到 {len(test_results)} 个结果，距离分数范围:")
                for i, (doc, score) in enumerate(test_results[:3], 1):
                    logger.info(f"  结果 {i}: 距离={score:.4f}")
                logger.warning(f"建议：当前阈值 {similarity_threshold} 可能过低，实际距离分数都大于此值。请尝试提高阈值或设置为 None 以禁用过滤。")
            else:
                logger.warning("向量数据库检索失败，可能是嵌入模型配置问题")
            return _build_prompt_with_knowledge_text("None")
        
        # 将检索结果拼接为纯知识文本，供模板占位符替换
        knowledge_only = ""
        for i, (doc, score) in enumerate(search_results, 1):
            logger.info(f"检索到片段 {i}: 距离={score:.3f}, 内容长度={len(doc.page_content)}")
            knowledge_only += f"\n片段 {i} (距离: {score:.3f}):\n{doc.page_content}\n"

        # 使用自定义模板（替换 {knowledge} 占位符）
        # 注意：代码执行到这里，kb_prompt_template 一定包含 {knowledge}（已在前面检查过）
        final_system_prompt = kb_prompt_template.replace("{knowledge}", knowledge_only.strip())
        
        # 如果存在 {time} 占位符，替换为当前时间
        if "{time}" in final_system_prompt:
            from datetime import datetime
            formatted_time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            final_system_prompt = final_system_prompt.replace("{time}", formatted_time)

        logger.info(f"✅ 检索到 {len(search_results)} 个相关片段，已构建知识库提示词")
        return final_system_prompt
        
    except Exception as e:
        logger.error(f"知识库检索失败: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        return ""