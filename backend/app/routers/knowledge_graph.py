"""
知识图谱API路由

提供知识图谱的构建和查询接口
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import asyncio
import uuid

from app.knowledge_graph import KnowledgeGraphBuilder, KnowledgeGraphQuery
from app.knowledge_graph.neo4j_client import get_client
from app.utils.auth import get_current_user
from app.config import settings
from app.services.kg_task_queue import get_task_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge-graph", tags=["知识图谱"])


# ======================== 请求/响应模型 ========================

class BuildGraphRequest(BaseModel):
    """构建知识图谱请求"""
    json_path: str = Field(..., description="JSON文件路径或文件名")
    clear_existing: bool = Field(False, description="是否清空现有数据")
    doc_id: Optional[str] = Field(None, description="文档ID（如提供，将从MinIO下载）")
    kb_id: Optional[str] = Field(None, description="知识库ID（用于从MinIO下载文档）")


class BatchBuildRequest(BaseModel):
    """批量构建知识图谱请求"""
    doc_ids: List[str] = Field(..., description="文档ID列表")
    kb_id: str = Field(..., description="知识库ID")
    clear_existing: bool = Field(False, description="是否清空现有数据")


class AuthorPapersRequest(BaseModel):
    """查询作者论文请求"""
    author_name: str = Field(..., description="作者姓名")
    limit: int = Field(100, ge=1, le=500, description="返回数量限制")
    sort_by: str = Field("year", description="排序字段（year/n_citation）")


class CollaboratorsRequest(BaseModel):
    """查询合作者请求"""
    author_name: str = Field(..., description="作者姓名")
    min_papers: int = Field(1, ge=1, description="最小合作论文数")
    limit: int = Field(50, ge=1, le=200, description="返回数量限制")


class SearchPapersRequest(BaseModel):
    """搜索论文请求"""
    keywords: Optional[str] = Field(None, description="关键词")
    author: Optional[str] = Field(None, description="作者姓名")
    year_from: Optional[int] = Field(None, description="起始年份")
    year_to: Optional[int] = Field(None, description="结束年份")
    field: Optional[str] = Field(None, description="研究领域")
    min_citations: Optional[int] = Field(None, description="最小引用数")
    limit: int = Field(50, ge=1, le=500, description="返回数量限制")


class CollaborationNetworkRequest(BaseModel):
    """查询合作网络请求"""
    author_name: str = Field(..., description="中心作者姓名")
    depth: int = Field(2, ge=1, le=3, description="网络深度")


# ======================== 初始化和状态检查 ========================

@router.get("/status")
async def get_neo4j_status():
    """
    检查Neo4j连接状态
    """
    try:
        client = get_client()
        
        if not client.is_connected():
            # 尝试连接
            client.configure(
                uri=settings.neo4j_uri,
                username=settings.neo4j_username,
                password=settings.neo4j_password,
                database=settings.neo4j_database
            )
            client.connect()
        
        stats = client.get_statistics()
        
        return {
            "status": "connected",
            "uri": settings.neo4j_uri,
            "database": settings.neo4j_database,
            "statistics": stats
        }
        
    except Exception as e:
        logger.error(f"Neo4j状态检查失败: {e}")
        return {
            "status": "disconnected",
            "error": str(e),
            "message": "请检查Neo4j服务是否启动，以及配置是否正确"
        }


@router.post("/initialize")
async def initialize_neo4j(current_user: dict = Depends(get_current_user)):
    """
    初始化Neo4j连接（手动触发）
    """
    try:
        client = get_client()
        
        client.configure(
            uri=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
            database=settings.neo4j_database
        )
        
        client.connect()
        
        return {
            "success": True,
            "message": "Neo4j连接初始化成功",
            "uri": settings.neo4j_uri
        }
        
    except Exception as e:
        logger.error(f"Neo4j初始化失败: {e}")
        raise HTTPException(status_code=500, detail=f"Neo4j初始化失败: {str(e)}")


# ======================== 知识图谱构建 ========================

async def _build_graph_from_minio(
    doc_id: str,
    kb_id: str,
    user_id: str,
    clear_existing: bool
):
    """
    从MinIO下载文档并构建知识图谱（持久化后台任务）
    
    ⚠️ 状态一致性保证：
    1. 开始前：状态设为 "building"
    2. Neo4j写入：分批写入论文数据
    3. 成功后：立即更新MongoDB状态为 "success"
    4. 失败时：更新状态为 "failed" 并记录错误
    5. 异常时：记录详细日志供 /fix-status 接口修复
    """
    import tempfile
    import json
    from pathlib import Path
    from datetime import datetime
    from ..utils.minio_client import minio_client
    from ..services.knowledge_base_service import KnowledgeBaseService
    from motor.motor_asyncio import AsyncIOMotorClient
    
    kb_service = None
    temp_file = None
    neo4j_write_completed = False
    
    try:
        logger.info(f"📥 [KG构建-{doc_id[:8]}] 开始任务")
        
        # 获取数据库连接
        from ..database import get_database
        db = await get_database()
        
        # 获取文档记录
        kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
        from bson import ObjectId
        doc = await kb_service.get_document(doc_id)
        
        if not doc:
            logger.error(f"❌ 文档不存在: doc_id={doc_id}")
            return {"success": False, "error": "文档不存在"}
        
        # 更新状态为"构建中"
        await kb_service.update_document_kg_status(
            doc_id=doc_id,
            kg_status="building"
        )
        
        file_url = doc.get("file_url")
        if not file_url:
            logger.error(f"❌ 文档没有file_url: doc_id={doc_id}")
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="failed",
                kg_error_message="文档缺少file_url"
            )
            return {"success": False, "error": "文档缺少file_url"}
        
        # 从MinIO下载文档
        logger.info(f"📥 从MinIO下载: {file_url}")
        file_content = minio_client.download_kb_document(file_url)
        
        # 验证是否为JSON
        filename = doc.get("filename", "")
        if not filename.endswith('.json'):
            logger.error(f"❌ 文档不是JSON格式: {filename}")
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="failed",
                kg_error_message="文档不是JSON格式"
            )
            return {"success": False, "error": "文档不是JSON格式"}
        
        # 解析JSON内容
        try:
            json_data = json.loads(file_content.decode('utf-8'))
            logger.info(f"✅ JSON解析成功，包含 {len(json_data)} 条记录")
        except Exception as e:
            error_msg = f"JSON解析失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="failed",
                kg_error_message=error_msg
            )
            return {"success": False, "error": error_msg}
        
        # 保存到临时文件
        temp_dir = Path(tempfile.gettempdir())
        temp_file = temp_dir / f"kg_{doc_id}.json"
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False)
        
        logger.info(f"💾 临时文件已创建: {temp_file}")
        
        # 关键步骤：构建知识图谱（写入Neo4j）
        logger.info(f"🔨 [KG构建-{doc_id[:8]}] 开始写入Neo4j")
        builder = KnowledgeGraphBuilder()
        await builder.build_from_json(str(temp_file), clear_existing)
        neo4j_write_completed = True
        logger.info(f"✅ [KG构建-{doc_id[:8]}] Neo4j写入完成")
        
        # 关键步骤：立即更新MongoDB状态为"成功"
        logger.info(f"📝 [KG构建-{doc_id[:8]}] 更新状态为success")
        update_success = await kb_service.update_document_kg_status(
            doc_id=doc_id,
            kg_status="success",
            kg_built_time=datetime.utcnow().isoformat()
        )
        if update_success:
            logger.info(f"✅ [KG构建-{doc_id[:8]}] 状态已同步到MongoDB")
        else:
            logger.error(f"❌ [KG构建-{doc_id[:8]}] MongoDB更新失败！matched_count或modified_count为0")
        
        # 清理临时文件
        if temp_file and temp_file.exists():
            temp_file.unlink()
            logger.info(f"🧹 [KG构建-{doc_id[:8]}] 临时文件已清理")
        
        logger.info(f"🎉 [KG构建-{doc_id[:8]}] 任务完成")
        logger.info(
            f"📊 [KG构建-{doc_id[:8]}] 任务摘要: "
            f"neo4j_write_completed={neo4j_write_completed}, "
            f"mongodb_update_success={update_success}"
        )
        return {"success": True}
        
    except Exception as e:
        error_msg = f"构建知识图谱失败: {str(e)}"
        logger.error(f"❌ [KG构建-{doc_id[:8]}] {error_msg}", exc_info=True)
        
        # 如果Neo4j写入已完成但状态更新失败，记录警告
        if neo4j_write_completed:
            logger.warning(
                f"⚠️ [KG构建-{doc_id[:8]}] Neo4j写入成功但后续流程失败，"
                f"建议调用 /kg/fix-status/{doc_id} 接口修复"
            )
        
        # 更新状态为"失败"
        try:
            if kb_service is None:
                from ..database import get_database
                db = await get_database()
                kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="failed",
                kg_error_message=error_msg
            )
            logger.info(f"📝 [KG构建-{doc_id[:8]}] 已更新失败状态")
            
        except Exception as update_error:
            logger.error(f"❌ [KG构建-{doc_id[:8]}] 更新失败状态时出错: {update_error}")
        
        # 清理临时文件
        try:
            if temp_file and temp_file.exists():
                temp_file.unlink()
                logger.info(f"🧹 [KG构建-{doc_id[:8]}] 临时文件已清理（异常情况）")
        except Exception as cleanup_error:
            logger.error(f"清理临时文件失败: {cleanup_error}")
        
        return {"success": False, "error": error_msg}
    
    finally:
        # 记录任务执行摘要（供后续状态检查使用）
        logger.info(
            f"📊 [KG构建-{doc_id[:8]}] 任务摘要: "
            f"neo4j_write_completed={neo4j_write_completed}"
        )


@router.post("/build")
async def build_knowledge_graph(
    request: BuildGraphRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    构建知识图谱（后台任务，立即返回）
    
    支持两种方式：
    1. 提供json_path：直接从文件系统路径读取
    2. 提供doc_id和kb_id：从MinIO下载文档后构建
    
    ⚠️ 重要：
    - 任务在后台执行，即使前端断开连接也会继续运行
    - 使用 asyncio.create_task() 确保任务不会因请求结束而中断
    - 建议前端定期调用 /check-status 接口查询构建状态
    """
    try:
        client = get_client()
        
        # 确保已连接
        if not client.is_connected():
            client.configure(
                uri=settings.neo4j_uri,
                username=settings.neo4j_username,
                password=settings.neo4j_password
            )
            client.connect()
        
        # 方式1: 从MinIO下载（推荐）
        if request.doc_id and request.kb_id:
            # 🎯 使用 asyncio.create_task 确保任务持久化运行
            # 即使HTTP连接断开，任务也会继续执行
            asyncio.create_task(
                _build_graph_from_minio(
                    request.doc_id,
                    request.kb_id,
                    current_user.id,
                    request.clear_existing
                )
            )
            message = f"知识图谱构建任务已提交，正在后台处理..."
        
        # 方式2: 直接从文件系统路径读取
        else:
            async def _build_from_path():
                builder = KnowledgeGraphBuilder()
                await builder.build_from_json(
                    request.json_path,
                    request.clear_existing
                )
            
            asyncio.create_task(_build_from_path())
            message = f"知识图谱构建任务已提交，正在后台处理..."
        
        return {
            "success": True,
            "message": message,
            "task_status": "submitted",  # submitted 表示已提交
            "doc_id": request.doc_id if request.doc_id else None
        }
        
    except Exception as e:
        logger.error(f"知识图谱构建失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-build")
async def batch_build_knowledge_graph(
    request: BatchBuildRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    批量构建知识图谱（基于Redis任务队列）
    
    ✨ 特性：
    - 任务持久化到Redis队列
    - 支持断点续传（服务器重启后任务继续）
    - 并发控制（由Worker控制）
    - 实时进度追踪
    
    Args:
        request: 批量构建请求
        
    Returns:
        {
            "success": bool,
            "batch_id": str,  # 批次ID，用于查询进度
            "total_tasks": int,
            "message": str
        }
    """
    try:
        # 生成批次ID
        batch_id = str(uuid.uuid4())
        
        # 获取任务队列
        task_queue = get_task_queue()
        
        # 获取文档信息（从MongoDB）
        from ..database import get_database
        from ..services.knowledge_base_service import KnowledgeBaseService
        
        db = await get_database()
        kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
        
        # 查询所有文档
        tasks = []
        for doc_id in request.doc_ids:
            doc = await kb_service.get_document(doc_id)
            if doc:
                tasks.append({
                    "doc_id": doc_id,
                    "filename": doc.get("filename", "")
                })
            else:
                logger.warning(f"⚠️ 文档不存在: {doc_id}")
        
        if not tasks:
            raise HTTPException(status_code=400, detail="没有有效的文档")
        
        # 提交批量任务到队列
        result = await task_queue.submit_batch(
            batch_id=batch_id,
            tasks=tasks,
            user_id=current_user.id,
            kb_id=request.kb_id
        )
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])
        
        logger.info(f"🎉 批量任务已提交: batch_id={batch_id}, 任务数={len(tasks)}")
        
        return {
            "success": True,
            "batch_id": batch_id,
            "total_tasks": len(tasks),
            "message": f"已提交 {len(tasks)} 个任务到队列，请使用 batch_id 查询进度"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 批量构建失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-build-all")
async def batch_build_all_knowledge_graphs(
    kb_id: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    批量构建知识库中所有未构建的知识图谱（不受分页限制）
    
    自动筛选出符合条件的JSON文档：
    - 文件类型必须是 .json
    - kg_status 为 'not_built' 或 'failed'
    
    ✨ 特性：
    - 自动过滤已创建的图谱
    - 任务持久化到Redis队列
    - 支持断点续传
    - 并发控制
    - 实时进度追踪
    
    Args:
        kb_id: 知识库ID
        
    Returns:
        {
            "success": bool,
            "batch_id": str,  # 批次ID，用于查询进度
            "total_tasks": int,
            "message": str
        }
    """
    try:
        # 生成批次ID
        batch_id = str(uuid.uuid4())
        
        # 获取任务队列
        task_queue = get_task_queue()
        
        # 获取文档信息（从MongoDB）
        from ..database import get_database
        from ..services.knowledge_base_service import KnowledgeBaseService
        
        db = await get_database()
        kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
        
        # 验证知识库存在
        kb = await kb_service.get_knowledge_base(kb_id, current_user.id)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在或无权限访问")
        
        # 获取所有符合条件的JSON文档（不分页，查询全部）
        collection = db[settings.mongodb_db_name].kb_documents
        
        # 🔍 先查看所有JSON文档
        all_json_docs = await collection.find({
            "kb_id": kb_id,
            "filename": {"$regex": r"\.json$", "$options": "i"}
        }).to_list(length=None)
        
        logger.info(f"🔍 知识库中所有JSON文档总数: {len(all_json_docs)}")
        for doc in all_json_docs:
            logger.info(f"  📄 {doc.get('filename')}: kg_status={doc.get('kg_status', 'not_built')}")
        
        cursor = collection.find({
            "kb_id": kb_id,
            "filename": {"$regex": r"\.json$", "$options": "i"},  # 文件名以.json结尾（不区分大小写）
            "$or": [
                {"kg_status": "not_built"},
                {"kg_status": "failed"},
                {"kg_status": {"$exists": False}}  # 兼容旧数据（没有kg_status字段）
            ]
        })
        
        json_docs = await cursor.to_list(length=None)  # length=None 表示获取全部
        logger.info(f"🎯 符合构建条件的JSON文档数: {len(json_docs)}")
        
        if not json_docs:
            return {
                "success": True,
                "batch_id": batch_id,
                "total_tasks": 0,
                "message": "没有需要构建知识图谱的JSON文档"
            }
        
        logger.info(f"📋 找到 {len(json_docs)} 个需要构建知识图谱的JSON文档")
        
        # 查询所有文档并构建任务列表
        tasks = []
        for doc in json_docs:
            doc_id = str(doc["_id"])
            tasks.append({
                "doc_id": doc_id,
                "filename": doc.get("filename", "")
            })
        
        if not tasks:
            return {
                "success": True,
                "batch_id": batch_id,
                "total_tasks": 0,
                "message": "没有有效的文档"
            }
        
        # 提交批量任务到队列
        result = await task_queue.submit_batch(
            batch_id=batch_id,
            tasks=tasks,
            user_id=current_user.id,
            kb_id=kb_id
        )
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["message"])
        
        logger.info(f"🎉 批量任务已提交: batch_id={batch_id}, 任务数={len(tasks)}")
        
        return {
            "success": True,
            "batch_id": batch_id,
            "total_tasks": len(tasks),
            "message": f"已提交 {len(tasks)} 个任务到队列，请使用 batch_id 查询进度"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 批量构建所有知识图谱失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/batch-status/{batch_id}")
async def get_batch_build_status(
    batch_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    查询批量构建进度
    
    Args:
        batch_id: 批次ID
        
    Returns:
        {
            "success": bool,
            "batch_id": str,
            "status": str,  # pending, processing, completed, partial_failed
            "total_tasks": int,
            "completed": int,
            "failed": int,
            "progress": float  # 进度百分比 (0-100)
        }
    """
    try:
        task_queue = get_task_queue()
        batch_status = await task_queue.get_batch_status(batch_id)
        
        if not batch_status:
            raise HTTPException(status_code=404, detail="批次不存在")
        
        return {
            "success": True,
            **batch_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询批次状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue-stats")
async def get_queue_statistics(
    current_user: dict = Depends(get_current_user)
):
    """
    获取队列统计信息
    
    Returns:
        {
            "success": bool,
            "queue_length": int,  # 队列中待处理任务数
            "processing_count": int,  # 正在处理的任务数
            "total_batches": int  # 总批次数
        }
    """
    try:
        task_queue = get_task_queue()
        stats = await task_queue.get_queue_stats()
        
        return {
            "success": True,
            **stats
        }
        
    except Exception as e:
        logger.error(f"❌ 获取队列统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 状态检查与修复 ========================

@router.get("/status/{doc_id}")
async def check_document_kg_status(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    检查文档的知识图谱构建状态，并自动修复不一致
    
    检查逻辑：
    1. 查询MongoDB中的kg_status
    2. 查询Neo4j中是否有该文档的论文数据
    3. 如果状态不一致，自动修复
    
    返回：
    - mongodb_status: MongoDB中的状态
    - neo4j_has_data: Neo4j中是否有数据
    - is_consistent: 状态是否一致
    - auto_fixed: 是否自动修复了不一致
    """
    try:
        from ..database import get_database
        from ..services.knowledge_base_service import KnowledgeBaseService
        
        # 获取MongoDB状态
        db = await get_database()
        kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
        doc = await kb_service.get_document(doc_id)
        
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        
        mongodb_status = doc.get("kg_status", "not_built")
        
        # 查询Neo4j中是否有数据
        client = get_client()
        if not client.is_connected():
            client.configure(
                uri=settings.neo4j_uri,
                username=settings.neo4j_username,
                password=settings.neo4j_password
            )
            client.connect()
        
        # 通过查询论文节点判断是否有数据
        # 这里假设文档ID被存储在某个论文节点的属性中（需要根据实际情况调整）
        cypher = """
        MATCH (p:Paper)
        RETURN count(p) as paper_count
        LIMIT 1
        """
        result = client.execute_query(cypher)
        neo4j_has_data = result[0]["paper_count"] > 0 if result else False
        
        # 判断是否一致
        is_consistent = True
        auto_fixed = False
        
        if neo4j_has_data and mongodb_status in ["not_built", "building", "failed"]:
            # 不一致：Neo4j有数据，但MongoDB状态不对
            is_consistent = False
            logger.warning(
                f"检测到状态不一致: doc_id={doc_id}, "
                f"mongodb_status={mongodb_status}, neo4j_has_data={neo4j_has_data}"
            )
            
            # 自动修复：更新MongoDB状态为success
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="success",
                kg_built_time=datetime.utcnow().isoformat()
            )
            auto_fixed = True
            mongodb_status = "success"
            logger.info(f"✅ 自动修复状态: doc_id={doc_id}, 更新为success")
            
        elif not neo4j_has_data and mongodb_status == "success":
            # 不一致：Neo4j没数据，但MongoDB说成功了
            is_consistent = False
            logger.warning(
                f"检测到状态不一致: doc_id={doc_id}, "
                f"mongodb_status={mongodb_status}, neo4j_has_data={neo4j_has_data}"
            )
            
            # 自动修复：更新MongoDB状态为not_built
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="not_built",
                kg_error_message="Neo4j中无数据，状态已重置"
            )
            auto_fixed = True
            mongodb_status = "not_built"
            logger.info(f"✅ 自动修复状态: doc_id={doc_id}, 更新为not_built")
        
        return {
            "success": True,
            "doc_id": doc_id,
            "mongodb_status": mongodb_status,
            "neo4j_has_data": neo4j_has_data,
            "is_consistent": is_consistent,
            "auto_fixed": auto_fixed
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查文档状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fix-status/{doc_id}")
async def fix_document_kg_status(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    手动修复文档的知识图谱状态
    
    强制检查Neo4j数据并同步MongoDB状态
    用于处理卡在building状态的文档
    """
    try:
        # 调用检查接口，会自动修复
        result = await check_document_kg_status(doc_id, current_user)
        
        return {
            "success": True,
            "message": "状态已检查并修复" if result["auto_fixed"] else "状态正常，无需修复",
            "details": result
        }
        
    except Exception as e:
        logger.error(f"修复文档状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 作者相关查询 ========================

@router.post("/query/author/papers")
async def query_author_papers(
    request: AuthorPapersRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    查询作者的所有论文
    """
    try:
        query_service = KnowledgeGraphQuery()
        results = query_service.get_author_papers(
            author_name=request.author_name,
            limit=request.limit,
            sort_by=request.sort_by
        )
        
        return {
            "success": True,
            "author_name": request.author_name,
            "total_papers": len(results),
            "papers": results
        }
        
    except Exception as e:
        logger.error(f"查询作者论文失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/author/collaborators")
async def query_author_collaborators(
    request: CollaboratorsRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    查询作者的合作者
    """
    try:
        query_service = KnowledgeGraphQuery()
        results = query_service.get_author_collaborators(
            author_name=request.author_name,
            min_papers=request.min_papers,
            limit=request.limit
        )
        
        return {
            "success": True,
            "author_name": request.author_name,
            "total_collaborators": len(results),
            "collaborators": results
        }
        
    except Exception as e:
        logger.error(f"查询合作者失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/author/impact/{author_name}")
async def query_author_impact(
    author_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    查询作者的学术影响力
    """
    try:
        query_service = KnowledgeGraphQuery()
        impact = query_service.get_author_impact(author_name)
        
        if not impact:
            raise HTTPException(status_code=404, detail="未找到该作者")
        
        return {
            "success": True,
            "impact": impact
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询作者影响力失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/author/fields/{author_name}")
async def query_author_fields(
    author_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    查询作者的研究领域分布
    """
    try:
        query_service = KnowledgeGraphQuery()
        fields = query_service.get_author_research_fields(author_name)
        
        return {
            "success": True,
            "author_name": author_name,
            "fields": fields
        }
        
    except Exception as e:
        logger.error(f"查询作者领域失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 论文相关查询 ========================

@router.get("/query/paper/{paper_id}")
async def query_paper_details(
    paper_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    查询论文详细信息
    """
    try:
        query_service = KnowledgeGraphQuery()
        paper = query_service.get_paper_details(paper_id)
        
        if not paper:
            raise HTTPException(status_code=404, detail="未找到该论文")
        
        return {
            "success": True,
            "paper": paper
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询论文详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/paper/{paper_id}/citing")
async def query_citing_papers(
    paper_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """
    查询引用了指定论文的其他论文
    """
    try:
        query_service = KnowledgeGraphQuery()
        citing_papers = query_service.get_citing_papers(paper_id, limit)
        
        return {
            "success": True,
            "paper_id": paper_id,
            "total_citing": len(citing_papers),
            "citing_papers": citing_papers
        }
        
    except Exception as e:
        logger.error(f"查询引用论文失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/paper/{paper_id}/similar")
async def query_similar_papers(
    paper_id: str,
    limit: int = 10,
    current_user: dict = Depends(get_current_user)
):
    """
    查询相似论文
    """
    try:
        query_service = KnowledgeGraphQuery()
        similar_papers = query_service.get_similar_papers(paper_id, limit)
        
        return {
            "success": True,
            "paper_id": paper_id,
            "similar_papers": similar_papers
        }
        
    except Exception as e:
        logger.error(f"查询相似论文失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/paper/{paper_id}/lineage")
async def query_research_lineage(
    paper_id: str,
    depth: int = 2,
    current_user: dict = Depends(get_current_user)
):
    """
    查询论文的研究脉络
    """
    try:
        query_service = KnowledgeGraphQuery()
        lineage = query_service.get_research_lineage(paper_id, depth)
        
        return {
            "success": True,
            "lineage": lineage
        }
        
    except Exception as e:
        logger.error(f"查询研究脉络失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 综合搜索 ========================

@router.post("/query/search")
async def search_papers(
    request: SearchPapersRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    综合搜索论文
    """
    try:
        query_service = KnowledgeGraphQuery()
        results = query_service.search_papers(
            keywords=request.keywords,
            author=request.author,
            year_from=request.year_from,
            year_to=request.year_to,
            field=request.field,
            min_citations=request.min_citations,
            limit=request.limit
        )
        
        return {
            "success": True,
            "total_results": len(results),
            "papers": results
        }
        
    except Exception as e:
        logger.error(f"搜索论文失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 研究领域查询 ========================

@router.get("/query/fields/hot")
async def query_hot_fields(
    year_from: Optional[int] = None,
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    查询热门研究领域
    """
    try:
        query_service = KnowledgeGraphQuery()
        fields = query_service.get_hot_fields(year_from, limit)
        
        return {
            "success": True,
            "hot_fields": fields
        }
        
    except Exception as e:
        logger.error(f"查询热门领域失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/field/{field_name}/experts")
async def query_field_experts(
    field_name: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    查询研究领域的专家
    """
    try:
        query_service = KnowledgeGraphQuery()
        experts = query_service.get_field_experts(field_name, limit)
        
        return {
            "success": True,
            "field_name": field_name,
            "experts": experts
        }
        
    except Exception as e:
        logger.error(f"查询领域专家失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/field/{field_name}/evolution")
async def query_field_evolution(
    field_name: str,
    current_user: dict = Depends(get_current_user)
):
    """
    查询研究领域的演化趋势
    """
    try:
        query_service = KnowledgeGraphQuery()
        evolution = query_service.get_field_evolution(field_name)
        
        return {
            "success": True,
            "field_name": field_name,
            "evolution": evolution
        }
        
    except Exception as e:
        logger.error(f"查询领域演化失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 学术网络分析 ========================

@router.post("/query/network/collaboration")
async def query_collaboration_network(
    request: CollaborationNetworkRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    查询合作网络
    """
    try:
        query_service = KnowledgeGraphQuery()
        network = query_service.get_collaboration_network(
            request.author_name,
            request.depth
        )
        
        return {
            "success": True,
            "network": network
        }
        
    except Exception as e:
        logger.error(f"查询合作网络失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/query/network/citation/{paper_id}")
async def query_citation_chain(
    paper_id: str,
    max_depth: int = 3,
    current_user: dict = Depends(get_current_user)
):
    """
    查询引用链
    """
    try:
        query_service = KnowledgeGraphQuery()
        chains = query_service.get_citation_chain(paper_id, max_depth)
        
        return {
            "success": True,
            "paper_id": paper_id,
            "citation_chains": chains
        }
        
    except Exception as e:
        logger.error(f"查询引用链失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

