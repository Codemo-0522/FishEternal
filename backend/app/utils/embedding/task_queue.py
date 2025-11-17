"""
企业级任务队列系统
支持优先级队列、任务持久化、失败重试、监控等企业级特性
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Union, Tuple
from datetime import datetime, timedelta
import pickle
import os
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running" 
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_type: str
    priority: TaskPriority
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: float = 300.0
    progress: float = 0.0
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass 
class EmbeddingTask:
    """嵌入任务数据"""
    text: str
    filename: str
    kb_settings: Dict[str, Any]
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class TaskPersistence:
    """任务持久化"""
    
    def __init__(self, storage_dir: str = "data/tasks"):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
    
    def save_task(self, task_info: TaskInfo, task_data: Any = None):
        """保存任务"""
        task_file = os.path.join(self.storage_dir, f"{task_info.task_id}.json")
        data_file = os.path.join(self.storage_dir, f"{task_info.task_id}.pkl")
        
        # 保存任务信息
        task_dict = asdict(task_info)
        task_dict['created_at'] = task_info.created_at.isoformat()
        if task_info.started_at:
            task_dict['started_at'] = task_info.started_at.isoformat()
        if task_info.completed_at:
            task_dict['completed_at'] = task_info.completed_at.isoformat()
        task_dict['priority'] = task_info.priority.value
        task_dict['status'] = task_info.status.value
        
        with open(task_file, 'w', encoding='utf-8') as f:
            json.dump(task_dict, f, ensure_ascii=False, indent=2)
        
        # 保存任务数据
        if task_data is not None:
            with open(data_file, 'wb') as f:
                pickle.dump(task_data, f)
    
    def load_task(self, task_id: str) -> Optional[Tuple[TaskInfo, Any]]:
        """加载任务"""
        task_file = os.path.join(self.storage_dir, f"{task_id}.json")
        data_file = os.path.join(self.storage_dir, f"{task_id}.pkl")
        
        if not os.path.exists(task_file):
            return None
        
        try:
            # 加载任务信息
            with open(task_file, 'r', encoding='utf-8') as f:
                task_dict = json.load(f)
            
            task_dict['created_at'] = datetime.fromisoformat(task_dict['created_at'])
            if task_dict.get('started_at'):
                task_dict['started_at'] = datetime.fromisoformat(task_dict['started_at'])
            if task_dict.get('completed_at'):
                task_dict['completed_at'] = datetime.fromisoformat(task_dict['completed_at'])
            task_dict['priority'] = TaskPriority(task_dict['priority'])
            task_dict['status'] = TaskStatus(task_dict['status'])
            
            task_info = TaskInfo(**task_dict)
            
            # 加载任务数据
            task_data = None
            if os.path.exists(data_file):
                with open(data_file, 'rb') as f:
                    task_data = pickle.load(f)
            
            return task_info, task_data
        except Exception as e:
            logger.error(f"加载任务失败 {task_id}: {str(e)}")
            return None
    
    def delete_task(self, task_id: str):
        """删除任务"""
        task_file = os.path.join(self.storage_dir, f"{task_id}.json")
        data_file = os.path.join(self.storage_dir, f"{task_id}.pkl")
        
        for file_path in [task_file, data_file]:
            if os.path.exists(file_path):
                os.remove(file_path)
    
    def list_tasks(self) -> List[str]:
        """列出所有任务ID"""
        task_ids = []
        for filename in os.listdir(self.storage_dir):
            if filename.endswith('.json'):
                task_ids.append(filename[:-5])  # 移除.json后缀
        return task_ids


class TaskQueue:
    """企业级任务队列"""
    
    def __init__(
        self,
        max_workers: int = 4,
        max_queue_size: int = 1000,
        enable_persistence: bool = True,
        storage_dir: str = "data/tasks"
    ):
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        
        # 优先级队列
        self.queues = {
            TaskPriority.URGENT: asyncio.Queue(),
            TaskPriority.HIGH: asyncio.Queue(), 
            TaskPriority.NORMAL: asyncio.Queue(),
            TaskPriority.LOW: asyncio.Queue()
        }
        
        # 任务管理
        self.tasks: Dict[str, TaskInfo] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        
        # 工作线程池
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="task_worker"
        )
        
        # 持久化
        self.persistence = TaskPersistence(storage_dir) if enable_persistence else None
        
        # 监控
        self.stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'running_tasks': 0
        }
        
        # 工作协程
        self.workers: List[asyncio.Task] = []
        self.is_running = False
        
        # 任务处理器注册
        self.task_handlers: Dict[str, Callable] = {}
    
    def register_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self.task_handlers[task_type] = handler
    
    async def start(self):
        """启动队列"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # 恢复持久化任务
        if self.persistence:
            await self._restore_tasks()
        
        # 启动工作协程
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self.workers.append(worker)
        
        logger.info(f"任务队列已启动，工作线程数: {self.max_workers}")
    
    async def stop(self):
        """停止队列"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # 取消所有工作协程
        for worker in self.workers:
            worker.cancel()
        
        # 等待工作协程结束
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        logger.info("任务队列已停止")
    
    async def submit_task(
        self,
        task_type: str,
        task_data: Any,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: float = 300.0,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """提交任务"""
        if not self.is_running:
            raise RuntimeError("任务队列未启动")
        
        # 检查队列大小
        total_queued = sum(q.qsize() for q in self.queues.values())
        if total_queued >= self.max_queue_size:
            raise RuntimeError(f"队列已满，当前任务数: {total_queued}")
        
        # 创建任务
        task_id = str(uuid.uuid4())
        task_info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            priority=priority,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            timeout=timeout,
            max_retries=max_retries,
            metadata=metadata or {}
        )
        
        # 保存任务
        self.tasks[task_id] = task_info
        if self.persistence:
            self.persistence.save_task(task_info, task_data)
        
        # 加入队列
        await self.queues[priority].put((task_id, task_data))
        
        self.stats['total_tasks'] += 1
        
        logger.info(f"任务已提交: {task_id} (类型: {task_type}, 优先级: {priority.name})")
        return task_id
    
    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务状态"""
        return self.tasks.get(task_id)
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.running_tasks:
            # 取消正在运行的任务
            self.running_tasks[task_id].cancel()
            return True
        elif task_id in self.tasks:
            # 标记为已取消
            self.tasks[task_id].status = TaskStatus.CANCELLED
            if self.persistence:
                self.persistence.save_task(self.tasks[task_id])
            return True
        return False
    
    async def _worker(self, worker_name: str):
        """工作协程"""
        logger.info(f"工作线程 {worker_name} 已启动")
        
        while self.is_running:
            try:
                # 按优先级获取任务
                task_item = await self._get_next_task()
                if task_item is None:
                    continue
                
                task_id, task_data = task_item
                task_info = self.tasks.get(task_id)
                
                if not task_info or task_info.status == TaskStatus.CANCELLED:
                    continue
                
                # 执行任务
                await self._execute_task(task_id, task_data, worker_name)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"工作线程 {worker_name} 异常: {str(e)}")
                await asyncio.sleep(1)
        
        logger.info(f"工作线程 {worker_name} 已停止")
    
    async def _get_next_task(self) -> Optional[Tuple[str, Any]]:
        """按优先级获取下一个任务"""
        # 按优先级顺序检查队列
        for priority in [TaskPriority.URGENT, TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW]:
            queue = self.queues[priority]
            if not queue.empty():
                try:
                    return await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
        
        # 没有任务时等待
        await asyncio.sleep(0.1)
        return None
    
    async def _execute_task(self, task_id: str, task_data: Any, worker_name: str):
        """执行任务"""
        task_info = self.tasks[task_id]
        
        # 更新任务状态
        task_info.status = TaskStatus.RUNNING
        task_info.started_at = datetime.now()
        self.stats['running_tasks'] += 1
        
        if self.persistence:
            self.persistence.save_task(task_info, task_data)
        
        logger.info(f"开始执行任务 {task_id} (工作线程: {worker_name})")
        
        try:
            # 获取任务处理器
            handler = self.task_handlers.get(task_info.task_type)
            if not handler:
                raise ValueError(f"未找到任务处理器: {task_info.task_type}")
            
            # 创建任务协程
            task_coro = asyncio.create_task(
                asyncio.wait_for(
                    handler(task_data, self._create_progress_callback(task_id)),
                    timeout=task_info.timeout
                )
            )
            
            # 注册运行中的任务
            self.running_tasks[task_id] = task_coro
            
            # 执行任务
            result = await task_coro
            
            # 任务成功
            task_info.status = TaskStatus.COMPLETED
            task_info.completed_at = datetime.now()
            task_info.result = result
            task_info.progress = 1.0
            
            self.stats['completed_tasks'] += 1
            
            logger.info(f"任务执行成功 {task_id}")
            
        except asyncio.CancelledError:
            task_info.status = TaskStatus.CANCELLED
            logger.info(f"任务被取消 {task_id}")
            
        except Exception as e:
            # 任务失败
            task_info.error = str(e)
            
            if task_info.retry_count < task_info.max_retries:
                # 重试
                task_info.retry_count += 1
                task_info.status = TaskStatus.RETRYING
                
                # 重新加入队列
                retry_delay = min(2 ** task_info.retry_count, 60)  # 最大60秒
                await asyncio.sleep(retry_delay)
                await self.queues[task_info.priority].put((task_id, task_data))
                
                logger.warning(f"任务重试 {task_id} (第 {task_info.retry_count}/{task_info.max_retries} 次): {str(e)}")
            else:
                # 最终失败
                task_info.status = TaskStatus.FAILED
                task_info.completed_at = datetime.now()
                self.stats['failed_tasks'] += 1
                
                logger.error(f"任务最终失败 {task_id}: {str(e)}")
        
        finally:
            # 清理
            self.stats['running_tasks'] -= 1
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
            
            # 持久化任务状态
            if self.persistence:
                self.persistence.save_task(task_info, task_data)
    
    def _create_progress_callback(self, task_id: str) -> Callable[[float], None]:
        """创建进度回调"""
        async def update_progress(progress: float):
            if task_id in self.tasks:
                self.tasks[task_id].progress = min(max(progress, 0.0), 1.0)
                if self.persistence:
                    self.persistence.save_task(self.tasks[task_id])
        
        return update_progress
    
    async def _restore_tasks(self):
        """恢复持久化任务"""
        if not self.persistence:
            return
        
        task_ids = self.persistence.list_tasks()
        restored_count = 0
        
        for task_id in task_ids:
            try:
                result = self.persistence.load_task(task_id)
                if result is None:
                    continue
                
                task_info, task_data = result
                
                # 只恢复未完成的任务
                if task_info.status in [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.RETRYING]:
                    task_info.status = TaskStatus.PENDING
                    self.tasks[task_id] = task_info
                    
                    # 重新加入队列
                    await self.queues[task_info.priority].put((task_id, task_data))
                    restored_count += 1
                    
            except Exception as e:
                logger.error(f"恢复任务失败 {task_id}: {str(e)}")
        
        if restored_count > 0:
            logger.info(f"已恢复 {restored_count} 个未完成任务")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        queue_sizes = {f"{p.name.lower()}_queue": q.qsize() for p, q in self.queues.items()}
        
        return {
            **self.stats,
            **queue_sizes,
            'total_queued': sum(queue_sizes.values())
        }


# 全局任务队列实例
_task_queue = None

async def get_task_queue() -> TaskQueue:
    """获取全局任务队列"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue(
            max_workers=4,
            max_queue_size=1000,
            enable_persistence=True
        )
        await _task_queue.start()
    return _task_queue


__all__ = [
    "TaskStatus",
    "TaskPriority", 
    "TaskInfo",
    "EmbeddingTask",
    "TaskQueue",
    "get_task_queue"
]
