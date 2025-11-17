"""
知识库广场 API
提供知识库共享、拉取、管理功能
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

from ..utils.auth import get_current_user
from ..models.user import User
from ..database import get_database
from ..config import settings
from ..services.kb_marketplace_service import KBMarketplaceService
from ..models.kb_marketplace import (
    ShareKBRequest,
    UnshareKBRequest,
    PullKBRequest,
    UpdatePulledKBRequest,
    SharedKBResponse,
    PulledKBResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kb-marketplace", tags=["知识库广场"])


@router.post("/share", response_model=SharedKBResponse)
async def share_knowledge_base(
    request: ShareKBRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    共享知识库到广场
    
    - 只有知识库所有者可以共享
    - 不会复制向量数据，只共享元数据
    - 不包含API Key等敏感信息
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        result = await service.share_knowledge_base(
            kb_id=request.kb_id,
            user_id=current_user.id,
            description=request.description
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"共享知识库失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"共享知识库失败: {str(e)}")


@router.post("/unshare")
async def unshare_knowledge_base(
    request: UnshareKBRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    取消共享知识库
    
    - 只有知识库所有者可以取消共享
    - 已拉取的用户仍可继续使用
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        await service.unshare_knowledge_base(
            kb_id=request.kb_id,
            user_id=current_user.id
        )
        return {"success": True, "message": "已取消共享"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"取消共享失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消共享失败: {str(e)}")


@router.get("/list")
async def list_shared_knowledge_bases(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    获取知识库广场列表
    
    - 展示所有公开的知识库
    - 支持搜索功能
    - 显示作者信息和统计数据
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        result = await service.list_shared_knowledge_bases(
            user_id=current_user.id,
            skip=skip,
            limit=limit,
            search=search
        )
        return result
    except Exception as e:
        logger.error(f"获取广场列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取广场列表失败: {str(e)}")


@router.post("/pull", response_model=PulledKBResponse)
async def pull_knowledge_base(
    request: PullKBRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    拉取共享知识库
    
    - 需要配置自己的嵌入模型
    - 使用原作者的collection（只读）
    - 可以调整相似度阈值和top_k
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        result = await service.pull_knowledge_base(
            shared_kb_id=request.shared_kb_id,
            user_id=current_user.id,
            embedding_config=request.embedding_config,
            distance_metric=request.distance_metric or 'cosine',
            similarity_threshold=request.similarity_threshold or 0.5,
            top_k=request.top_k or 5
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"拉取知识库失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"拉取知识库失败: {str(e)}")


@router.get("/pulled")
async def list_pulled_knowledge_bases(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    获取用户已拉取的知识库列表
    
    - 只显示当前用户拉取的知识库
    - 包含最新的统计信息
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        result = await service.list_pulled_knowledge_bases(
            user_id=current_user.id,
            skip=skip,
            limit=limit
        )
        return result
    except Exception as e:
        logger.error(f"获取已拉取列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取已拉取列表失败: {str(e)}")


@router.put("/pulled/{pulled_kb_id}", response_model=PulledKBResponse)
async def update_pulled_knowledge_base(
    pulled_kb_id: str,
    request: UpdatePulledKBRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    更新已拉取知识库的配置
    
    - 只能修改embedding配置、相似度阈值和top_k
    - 不能修改分片参数（使用原作者的配置）
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        result = await service.update_pulled_knowledge_base(
            pulled_kb_id=pulled_kb_id,
            user_id=current_user.id,
            update_data=request
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.delete("/pulled/{pulled_kb_id}")
async def delete_pulled_knowledge_base(
    pulled_kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    删除已拉取的知识库
    
    - 只删除拉取记录，不影响原知识库
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        await service.delete_pulled_knowledge_base(
            pulled_kb_id=pulled_kb_id,
            user_id=current_user.id
        )
        return {"success": True, "message": "已删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"删除失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/check-shared/{kb_id}")
async def check_knowledge_base_shared(
    kb_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    检查知识库是否已共享
    
    - 用于在知识库详情页显示共享状态
    """
    try:
        service = KBMarketplaceService(db[settings.mongodb_db_name])
        shared_kb = await service.get_shared_kb_by_original_id(
            original_kb_id=kb_id,
            user_id=current_user.id
        )
        
        if shared_kb:
            return {
                "is_shared": True,
                "shared_kb": shared_kb
            }
        else:
            return {
                "is_shared": False,
                "shared_kb": None
            }
    except Exception as e:
        logger.error(f"检查共享状态失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查共享状态失败: {str(e)}")

