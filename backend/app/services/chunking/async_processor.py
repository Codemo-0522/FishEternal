"""
异步分片处理器
使用线程池或进程池进行并发分片，避免阻塞主线程
"""

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Callable
import logging
from dataclasses import dataclass
from enum import Enum
import time

from .base_chunker import ChunkResult, ChunkingConfig
from .factory import ChunkerFactory

logger = logging.getLogger(__name__)


class ExecutorType(str, Enum):
    """执行器类型"""
    THREAD = "thread"  # 线程池（适合I/O密集型）
    PROCESS = "process"  # 进程池（适合CPU密集型）


@dataclass
class ChunkingTask:
    """分片任务"""
    task_id: str
    content: str
    file_type: str
    config: ChunkingConfig
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ChunkingResult:
    """分片结果"""
    task_id: str
    chunks: List[ChunkResult]
    success: bool
    error: Optional[str] = None
    duration: float = 0.0  # 处理耗时（秒）


class AsyncChunkingProcessor:
    """异步分片处理器"""
    
    def __init__(
        self,
        max_workers: int = 4,
        executor_type: ExecutorType = ExecutorType.THREAD,
        batch_size: int = 100
    ):
        """
        初始化异步处理器
        
        Args:
            max_workers: 最大工作线程/进程数
            executor_type: 执行器类型（thread/process）
            batch_size: 批次大小
        """
        self.max_workers = max_workers
        self.executor_type = executor_type
        self.batch_size = batch_size
        
        # 创建执行器
        if executor_type == ExecutorType.THREAD:
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
        else:
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
        
        logger.info(f"Initialized AsyncChunkingProcessor with {max_workers} {executor_type} workers")
    
    def process_single(self, task: ChunkingTask) -> ChunkingResult:
        """
        处理单个分片任务
        
        Args:
            task: 分片任务
            
        Returns:
            分片结果
        """
        start_time = time.time()
        
        try:
            # 创建分片器
            chunker = ChunkerFactory.create_chunker(
                file_type=task.file_type,
                content=task.content,
                config=task.config
            )
            
            # 执行分片
            chunks = chunker.chunk(task.content, task.metadata)
            
            duration = time.time() - start_time
            
            logger.info(
                f"Task {task.task_id} completed: {len(chunks)} chunks in {duration:.2f}s"
            )
            
            return ChunkingResult(
                task_id=task.task_id,
                chunks=chunks,
                success=True,
                duration=duration
            )
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
            
            return ChunkingResult(
                task_id=task.task_id,
                chunks=[],
                success=False,
                error=str(e),
                duration=duration
            )
    
    def process_batch(
        self,
        tasks: List[ChunkingTask],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[ChunkingResult]:
        """
        批量处理分片任务（并发）
        
        Args:
            tasks: 任务列表
            progress_callback: 进度回调函数 (completed, total)
            
        Returns:
            结果列表
        """
        if not tasks:
            return []
        
        logger.info(f"Processing {len(tasks)} tasks in parallel...")
        
        results = []
        completed = 0
        
        # 提交所有任务
        future_to_task = {
            self.executor.submit(self.process_single, task): task
            for task in tasks
        }
        
        # 收集结果
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            
            try:
                result = future.result()
                results.append(result)
                completed += 1
                
                # 调用进度回调
                if progress_callback:
                    progress_callback(completed, len(tasks))
                
            except Exception as e:
                logger.error(f"Task {task.task_id} raised exception: {e}")
                results.append(ChunkingResult(
                    task_id=task.task_id,
                    chunks=[],
                    success=False,
                    error=str(e)
                ))
                completed += 1
                
                if progress_callback:
                    progress_callback(completed, len(tasks))
        
        logger.info(f"Batch processing completed: {completed}/{len(tasks)} tasks")
        
        return results
    
    def process_stream(
        self,
        tasks: List[ChunkingTask],
        progress_callback: Optional[Callable[[ChunkingResult], None]] = None
    ):
        """
        流式处理任务（生成器模式）
        
        Args:
            tasks: 任务列表
            progress_callback: 进度回调函数（接收每个完成的结果）
            
        Yields:
            ChunkingResult: 每个完成的任务结果
        """
        if not tasks:
            return
        
        logger.info(f"Stream processing {len(tasks)} tasks...")
        
        # 提交所有任务
        future_to_task = {
            self.executor.submit(self.process_single, task): task
            for task in tasks
        }
        
        # 流式返回结果
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            
            try:
                result = future.result()
                
                if progress_callback:
                    progress_callback(result)
                
                yield result
                
            except Exception as e:
                logger.error(f"Task {task.task_id} raised exception: {e}")
                error_result = ChunkingResult(
                    task_id=task.task_id,
                    chunks=[],
                    success=False,
                    error=str(e)
                )
                
                if progress_callback:
                    progress_callback(error_result)
                
                yield error_result
    
    def shutdown(self, wait: bool = True):
        """
        关闭执行器
        
        Args:
            wait: 是否等待所有任务完成
        """
        logger.info("Shutting down AsyncChunkingProcessor...")
        self.executor.shutdown(wait=wait)
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.shutdown(wait=True)


# 全局处理器实例（单例模式）
_global_processor: Optional[AsyncChunkingProcessor] = None


def get_global_processor(
    max_workers: int = 4,
    executor_type: ExecutorType = ExecutorType.THREAD
) -> AsyncChunkingProcessor:
    """
    获取全局处理器实例
    
    Args:
        max_workers: 最大工作线程数
        executor_type: 执行器类型
        
    Returns:
        全局处理器实例
    """
    global _global_processor
    
    if _global_processor is None:
        _global_processor = AsyncChunkingProcessor(
            max_workers=max_workers,
            executor_type=executor_type
        )
    
    return _global_processor


def shutdown_global_processor():
    """关闭全局处理器"""
    global _global_processor
    
    if _global_processor is not None:
        _global_processor.shutdown()
        _global_processor = None

