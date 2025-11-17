"""
异步任务处理器
用于后台处理耗时任务，不阻塞主服务

特性：
1. 基于 asyncio 的异步任务队列
2. 支持任务优先级
3. 并发控制和资源限制
4. 任务状态跟踪
5. 错误重试机制
6. 完全隔离用户操作
"""
import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, Callable, Coroutine
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass(order=True)
class Task:
    """任务定义"""
    priority: int = field(compare=True)  # 用于优先级队列排序
    task_id: str = field(compare=False)
    task_type: str = field(compare=False)
    user_id: str = field(compare=False)
    handler: Callable[..., Coroutine] = field(compare=False)
    args: tuple = field(default_factory=tuple, compare=False)
    kwargs: dict = field(default_factory=dict, compare=False)
    max_retries: int = field(default=3, compare=False)
    retry_count: int = field(default=0, compare=False)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(), compare=False)
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False)
    result: Any = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    progress: float = field(default=0.0, compare=False)  # 任务进度 (0.0-1.0)
    progress_message: str = field(default="", compare=False)  # 进度描述信息


class AsyncTaskProcessor:
    """
    异步任务处理器
    
    完全异步、非阻塞的后台任务处理系统
    用户之间的任务完全隔离，互不影响
    """
    
    def __init__(
        self,
        max_concurrent_tasks: int = 10,
        max_queue_size: int = 1000
    ):
        """
        初始化任务处理器
        
        Args:
            max_concurrent_tasks: 最大并发任务数
            max_queue_size: 最大队列大小
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.max_queue_size = max_queue_size
        
        # 优先级队列（使用 asyncio.PriorityQueue）
        self.task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        
        # 任务状态跟踪
        self.tasks: Dict[str, Task] = {}
        
        # 并发控制
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        
        # 运行状态
        self.is_running = False
        self.worker_tasks: list[asyncio.Task] = []
        
        # 统计信息
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "cancelled_tasks": 0
        }
        
        logger.info(
            f"任务处理器初始化: max_concurrent={max_concurrent_tasks}, "
            f"max_queue={max_queue_size}"
        )
    
    async def start(self, num_workers: Optional[int] = None):
        """
        启动任务处理器
        
        Args:
            num_workers: 工作协程数量（默认为 max_concurrent_tasks）
        """
        if self.is_running:
            logger.warning("任务处理器已在运行")
            return
        
        self.is_running = True
        num_workers = num_workers or self.max_concurrent_tasks
        
        # 创建多个 worker 协程
        for i in range(num_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self.worker_tasks.append(worker)
        
        logger.info(f"任务处理器已启动，{num_workers} 个工作协程")
    
    async def stop(self, timeout: float = 30.0):
        """
        停止任务处理器
        
        Args:
            timeout: 等待超时时间（秒）
        """
        if not self.is_running:
            return
        
        logger.info("正在停止任务处理器...")
        self.is_running = False
        
        # 等待所有 worker 完成
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.worker_tasks, return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning("任务处理器停止超时，强制取消")
            for task in self.worker_tasks:
                task.cancel()
        
        self.worker_tasks.clear()
        logger.info("任务处理器已停止")
    
    async def submit_task(
        self,
        task_type: str,
        user_id: str,
        handler: Callable[..., Coroutine],
        *args,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 3,
        **kwargs
    ) -> str:
        """
        提交任务到队列
        
        Args:
            task_type: 任务类型
            user_id: 用户ID
            handler: 异步处理函数
            args: 位置参数
            priority: 任务优先级
            max_retries: 最大重试次数
            kwargs: 关键字参数
            
        Returns:
            任务ID
            
        Raises:
            RuntimeError: 队列已满
        """
        task_id = str(uuid.uuid4())
        
        # 创建任务（优先级取负值，因为 PriorityQueue 是最小堆）
        task = Task(
            priority=-priority.value,  # 负值使优先级高的先出队
            task_id=task_id,
            task_type=task_type,
            user_id=user_id,
            handler=handler,
            args=args,
            kwargs=kwargs,
            max_retries=max_retries
        )
        
        # 添加到队列
        try:
            self.task_queue.put_nowait(task)
            self.tasks[task_id] = task
            self.stats["total_tasks"] += 1
            
            logger.info(
                f"任务已提交: {task_id} (类型: {task_type}, 用户: {user_id}, "
                f"优先级: {priority.name}, 队列长度: {self.task_queue.qsize()})"
            )
            
            return task_id
            
        except asyncio.QueueFull:
            logger.error("任务队列已满，无法提交新任务")
            raise RuntimeError("任务队列已满，请稍后重试")
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务状态信息，如果任务不存在则返回 None
        """
        task = self.tasks.get(task_id)
        if not task:
            return None
        
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "retry_count": task.retry_count,
            "created_at": task.created_at,
            "progress": task.progress,
            "progress_message": task.progress_message
        }
    
    async def update_task_progress(
        self,
        task_id: str,
        progress: float,
        message: str = ""
    ) -> bool:
        """
        更新任务进度
        
        Args:
            task_id: 任务ID
            progress: 进度值 (0.0-1.0)
            message: 进度描述信息
            
        Returns:
            是否更新成功
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        task.progress = max(0.0, min(1.0, progress))  # 确保在 0-1 范围内
        task.progress_message = message
        return True
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否取消成功
        """
        task = self.tasks.get(task_id)
        if not task:
            return False
        
        if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
            task.status = TaskStatus.CANCELLED
            self.stats["cancelled_tasks"] += 1
            logger.info(f"任务已取消: {task_id}")
            return True
        
        return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        return {
            **self.stats,
            "queue_size": self.task_queue.qsize(),
            "is_running": self.is_running,
            "active_workers": len(self.worker_tasks)
        }
    
    async def _worker(self, worker_name: str):
        """
        工作协程
        
        Args:
            worker_name: 工作协程名称
        """
        logger.info(f"{worker_name} 已启动")
        
        while self.is_running:
            try:
                # 从队列获取任务（带超时，避免永久阻塞）
                try:
                    task = await asyncio.wait_for(
                        self.task_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # 检查任务是否已取消
                if task.status == TaskStatus.CANCELLED:
                    self.task_queue.task_done()
                    continue
                
                # 处理任务（带并发控制）
                async with self.semaphore:
                    await self._process_task(task, worker_name)
                
                self.task_queue.task_done()
                
            except Exception as e:
                logger.error(f"{worker_name} 发生错误: {str(e)}", exc_info=True)
        
        logger.info(f"{worker_name} 已停止")
    
    async def _process_task(self, task: Task, worker_name: str):
        """
        处理单个任务
        
        Args:
            task: 任务对象
            worker_name: 工作协程名称
        """
        try:
            task.status = TaskStatus.PROCESSING
            
            logger.info(
                f"{worker_name} 开始处理任务: {task.task_id} "
                f"(类型: {task.task_type}, 用户: {task.user_id})"
            )
            
            # 执行任务处理函数
            result = await task.handler(*task.args, **task.kwargs)
            
            # 任务成功
            task.status = TaskStatus.COMPLETED
            task.result = result
            self.stats["completed_tasks"] += 1
            
            logger.info(f"{worker_name} 任务完成: {task.task_id}")
            
        except asyncio.CancelledError:
            # 任务被取消
            task.status = TaskStatus.CANCELLED
            self.stats["cancelled_tasks"] += 1
            logger.info(f"{worker_name} 任务被取消: {task.task_id}")
            
        except Exception as e:
            # 任务失败
            error_msg = f"{type(e).__name__}: {str(e)}"
            task.error = error_msg
            task.retry_count += 1
            
            logger.error(
                f"{worker_name} 任务失败: {task.task_id} "
                f"(重试: {task.retry_count}/{task.max_retries})",
                exc_info=True
            )
            
            # 重试逻辑
            if task.retry_count < task.max_retries:
                # 重新提交任务
                task.status = TaskStatus.PENDING
                try:
                    await self.task_queue.put(task)
                    logger.info(f"任务重新提交: {task.task_id}")
                except asyncio.QueueFull:
                    task.status = TaskStatus.FAILED
                    self.stats["failed_tasks"] += 1
                    logger.error(f"任务重试失败（队列已满）: {task.task_id}")
            else:
                # 超过最大重试次数
                task.status = TaskStatus.FAILED
                self.stats["failed_tasks"] += 1
                logger.error(f"任务最终失败: {task.task_id}")


# 全局任务处理器实例（单例模式）
_task_processor: Optional[AsyncTaskProcessor] = None


def get_task_processor() -> AsyncTaskProcessor:
    """
    获取全局任务处理器实例
    
    Returns:
        任务处理器实例
    """
    global _task_processor
    
    if _task_processor is None:
        # 从配置读取参数
        from ..config import settings
        
        _task_processor = AsyncTaskProcessor(
            max_concurrent_tasks=getattr(settings, 'max_concurrent_tasks', 10),
            max_queue_size=getattr(settings, 'max_task_queue_size', 1000)
        )
    
    return _task_processor


async def init_task_processor():
    """初始化并启动任务处理器"""
    processor = get_task_processor()
    await processor.start()
    logger.info("全局任务处理器已启动")


async def shutdown_task_processor():
    """关闭任务处理器"""
    global _task_processor
    
    if _task_processor:
        await _task_processor.stop()
        _task_processor = None
        logger.info("全局任务处理器已关闭")

