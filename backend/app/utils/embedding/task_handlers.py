"""
任务处理器初始化和注册
"""
import logging
from typing import Dict, Any, Callable, Optional

from .task_queue import get_task_queue, EmbeddingTask
from .async_pipeline import process_embedding_task

logger = logging.getLogger(__name__)


async def handle_embedding_task(
    task_data: EmbeddingTask,
    progress_callback: Optional[Callable[[float], None]] = None
) -> Dict[str, Any]:
    """处理嵌入任务的包装器"""
    try:
        # 调用异步管道处理
        result = await process_embedding_task(task_data, progress_callback)
        
        # 如果有session_id，更新会话状态
        if task_data.session_id and task_data.user_id:
            try:
                from ...database import get_database
                from ...config import settings
                
                db = await get_database()
                await db[settings.mongodb_db_name].chat_sessions.update_one(
                    {"_id": task_data.session_id, "user_id": task_data.user_id},
                    {"$set": {
                        "kb_parsed": True,
                        "kb_settings": task_data.kb_settings
                    }}
                )
                logger.info(f"已更新会话 {task_data.session_id} 的知识库状态")
            except Exception as e:
                logger.warning(f"更新会话状态失败: {str(e)}")
                # 不影响主要处理流程
        
        return result
        
    except Exception as e:
        logger.error(f"处理嵌入任务失败: {str(e)}")
        raise


async def initialize_task_handlers():
    """初始化任务处理器"""
    try:
        task_queue = await get_task_queue()
        
        # 注册嵌入任务处理器
        task_queue.register_handler("embedding", handle_embedding_task)
        
        logger.info("任务处理器初始化完成")
        
    except Exception as e:
        logger.error(f"初始化任务处理器失败: {str(e)}")
        raise


__all__ = [
    "handle_embedding_task",
    "initialize_task_handlers"
]
