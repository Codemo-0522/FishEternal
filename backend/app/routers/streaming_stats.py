"""
流式输出统计和监控API
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any
import logging

from ..utils.llm.streaming_manager import streaming_manager
from ..utils.llm.streaming_config import streaming_config
from ..utils.auth import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/streaming", tags=["streaming"])
logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_streaming_stats(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    获取流式输出统计信息
    
    需要用户认证
    """
    
    try:
        # 获取会话统计
        session_stats = await streaming_manager.get_session_stats()
        
        # 获取配置信息
        config_info = streaming_config.to_dict()
        
        return {
            "success": True,
            "data": {
                "session_stats": session_stats,
                "config": config_info,
                "manager_info": {
                    "has_thread_pool": streaming_manager.thread_pool is not None,
                    "cleanup_task_running": streaming_manager._cleanup_task is not None and not streaming_manager._cleanup_task.done()
                }
            }
        }
        
    except Exception as e:
        logger.error(f"获取流式统计失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/config/update")
async def update_streaming_config(
    config_updates: Dict[str, Any],
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    动态更新流式输出配置
    
    需要用户认证，仅管理员可用
    """
    
    # 这里可以添加管理员权限检查
    # if not current_user.is_admin:
    #     raise HTTPException(status_code=403, detail="需要管理员权限")
    
    try:
        # 更新配置
        for key, value in config_updates.items():
            if hasattr(streaming_config, key):
                setattr(streaming_config, key, value)
                logger.info(f"更新配置: {key} = {value}")
        
        return {
            "success": True,
            "message": "配置更新成功",
            "updated_config": streaming_config.to_dict()
        }
        
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/health")
async def streaming_health_check() -> Dict[str, Any]:
    """
    流式输出健康检查
    
    无需认证的健康检查端点
    """
    
    try:
        session_stats = await streaming_manager.get_session_stats()
        
        # 简单的健康检查逻辑
        is_healthy = (
            session_stats["active_sessions"] < streaming_config.max_concurrent_sessions and
            streaming_manager._cleanup_task is not None and
            not streaming_manager._cleanup_task.done()
        )
        
        return {
            "status": "healthy" if is_healthy else "degraded",
            "active_sessions": session_stats["active_sessions"],
            "max_sessions": streaming_config.max_concurrent_sessions,
            "cleanup_running": streaming_manager._cleanup_task is not None and not streaming_manager._cleanup_task.done()
        }
        
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@router.post("/sessions/{session_id}/terminate")
async def terminate_session(
    session_id: str,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    终止指定的流式会话
    
    需要用户认证，用户只能终止自己的会话
    """
    
    try:
        # 检查会话是否存在且属于当前用户
        if session_id not in streaming_manager.active_sessions:
            return {
                "success": False,
                "error": "会话不存在"
            }
        
        session = streaming_manager.active_sessions[session_id]
        if session.user_id != current_user.id:
            return {
                "success": False,
                "error": "无权限操作此会话"
            }
        
        # 终止会话
        await streaming_manager.unregister_session(session_id)
        
        return {
            "success": True,
            "message": f"会话 {session_id} 已终止"
        }
        
    except Exception as e:
        logger.error(f"终止会话失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }
