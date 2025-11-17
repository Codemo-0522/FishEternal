"""
知识图谱任务队列管理器

基于Redis实现的持久化任务队列，支持：
- 任务提交和持久化
- 任务状态跟踪
- 断点续传（重启后恢复）
- 并发控制
"""

import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from redis import asyncio as aioredis

logger = logging.getLogger(__name__)


class KGTaskQueue:
    """知识图谱任务队列"""
    
    # Redis键前缀
    QUEUE_KEY = "kg:task:queue"  # 任务队列（List）
    TASK_STATUS_PREFIX = "kg:task:status:"  # 任务状态（Hash）
    BATCH_STATUS_PREFIX = "kg:batch:status:"  # 批次状态（Hash）
    PROCESSING_SET = "kg:task:processing"  # 正在处理的任务集合（Set）
    
    def __init__(self, redis_url: str = "redis://localhost:6379/1"):
        """
        初始化任务队列
        
        Args:
            redis_url: Redis连接URL
        """
        self.redis_url = redis_url
        self.redis: Optional[aioredis.Redis] = None
        
    async def connect(self):
        """连接Redis"""
        if self.redis is None:
            self.redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            logger.info(f"✅ 任务队列已连接Redis: {self.redis_url}")
    
    async def close(self):
        """关闭连接"""
        if self.redis:
            await self.redis.close()
            self.redis = None
    
    async def submit_batch(
        self,
        batch_id: str,
        tasks: List[Dict[str, Any]],
        user_id: str,
        kb_id: str
    ) -> Dict[str, Any]:
        """
        提交批量任务
        
        Args:
            batch_id: 批次ID
            tasks: 任务列表，每个任务包含 {doc_id, filename}
            user_id: 用户ID
            kb_id: 知识库ID
            
        Returns:
            {
                "success": bool,
                "batch_id": str,
                "total_tasks": int,
                "message": str
            }
        """
        await self.connect()
        
        try:
            # 保存批次信息（Redis hset需要所有值都是字符串）
            batch_info = {
                "batch_id": batch_id,
                "user_id": user_id,
                "kb_id": kb_id,
                "total_tasks": str(len(tasks)),
                "completed": str(0),
                "failed": str(0),
                "status": "pending",  # pending, processing, completed, failed
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            batch_key = f"{self.BATCH_STATUS_PREFIX}{batch_id}"
            # 使用hmset兼容Redis 3.x（hset的mapping参数需要Redis 4.0+）
            await self.redis.hmset(batch_key, batch_info)
            
            # 将任务添加到队列
            task_count = 0
            for task in tasks:
                task_data = {
                    "batch_id": batch_id,
                    "task_id": f"{batch_id}:{task['doc_id']}",
                    "doc_id": task["doc_id"],
                    "kb_id": kb_id,
                    "user_id": user_id,
                    "filename": task.get("filename", ""),
                    "status": "pending",
                    "created_at": datetime.utcnow().isoformat(),
                    "retries": "0",
                    "max_retries": "3"
                }
                
                # 保存任务状态
                task_key = f"{self.TASK_STATUS_PREFIX}{task_data['task_id']}"
                await self.redis.hmset(task_key, task_data)
                
                # 添加到队列
                await self.redis.rpush(self.QUEUE_KEY, task_data["task_id"])
                task_count += 1
            
            logger.info(f"✅ 批次 {batch_id} 已提交：{task_count} 个任务")
            
            return {
                "success": True,
                "batch_id": batch_id,
                "total_tasks": task_count,
                "message": f"已提交 {task_count} 个任务到队列"
            }
            
        except Exception as e:
            logger.error(f"❌ 提交批次失败: {e}", exc_info=True)
            return {
                "success": False,
                "batch_id": batch_id,
                "total_tasks": 0,
                "message": f"提交失败: {str(e)}"
            }
    
    async def get_next_task(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        获取下一个待处理任务（阻塞式）
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            任务信息，如果队列为空则返回None
        """
        await self.connect()
        
        try:
            # 从队列头部取出任务（阻塞）
            result = await self.redis.blpop(self.QUEUE_KEY, timeout=timeout)
            
            if not result:
                return None
            
            _, task_id = result
            
            # 获取任务详情
            task_key = f"{self.TASK_STATUS_PREFIX}{task_id}"
            task_data = await self.redis.hgetall(task_key)
            
            if not task_data:
                logger.warning(f"⚠️ 任务 {task_id} 详情不存在")
                return None
            
            # 标记为处理中
            await self.redis.sadd(self.PROCESSING_SET, task_id)
            await self.redis.hset(task_key, "status", "processing")
            await self.redis.hset(task_key, "started_at", datetime.utcnow().isoformat())
            
            # 转换为字典
            task = dict(task_data)
            task["retries"] = int(task.get("retries", 0))
            task["max_retries"] = int(task.get("max_retries", 3))
            
            return task
            
        except Exception as e:
            logger.error(f"❌ 获取任务失败: {e}", exc_info=True)
            return None
    
    async def mark_task_completed(self, task_id: str):
        """
        标记任务完成
        
        Args:
            task_id: 任务ID
        """
        await self.connect()
        
        try:
            task_key = f"{self.TASK_STATUS_PREFIX}{task_id}"
            
            # 更新任务状态
            await self.redis.hset(task_key, "status", "completed")
            await self.redis.hset(task_key, "completed_at", datetime.utcnow().isoformat())
            
            # 从处理中集合移除
            await self.redis.srem(self.PROCESSING_SET, task_id)
            
            # 更新批次进度
            task_data = await self.redis.hgetall(task_key)
            batch_id = task_data.get("batch_id")
            
            if batch_id:
                batch_key = f"{self.BATCH_STATUS_PREFIX}{batch_id}"
                await self.redis.hincrby(batch_key, "completed", 1)
                await self.redis.hset(batch_key, "updated_at", datetime.utcnow().isoformat())
                
                # 检查批次是否全部完成
                await self._check_batch_completion(batch_id)
            
            logger.info(f"✅ 任务完成: {task_id}")
            
        except Exception as e:
            logger.error(f"❌ 标记任务完成失败: {e}", exc_info=True)
    
    async def mark_task_failed(self, task_id: str, error: str, retry: bool = True):
        """
        标记任务失败
        
        Args:
            task_id: 任务ID
            error: 错误信息
            retry: 是否重试
        """
        await self.connect()
        
        try:
            task_key = f"{self.TASK_STATUS_PREFIX}{task_id}"
            task_data = await self.redis.hgetall(task_key)
            
            if not task_data:
                logger.warning(f"⚠️ 任务 {task_id} 不存在")
                return
            
            retries = int(task_data.get("retries", 0))
            max_retries = int(task_data.get("max_retries", 3))
            
            # 从处理中集合移除
            await self.redis.srem(self.PROCESSING_SET, task_id)
            
            # 判断是否重试
            if retry and retries < max_retries:
                # 重试：重新加入队列
                retries += 1
                await self.redis.hset(task_key, "retries", str(retries))
                await self.redis.hset(task_key, "status", "pending")
                await self.redis.hset(task_key, "last_error", error)
                await self.redis.rpush(self.QUEUE_KEY, task_id)
                
                logger.warning(f"⚠️ 任务失败，重试 {retries}/{max_retries}: {task_id}")
                
            else:
                # 最终失败
                await self.redis.hset(task_key, "status", "failed")
                await self.redis.hset(task_key, "error", error)
                await self.redis.hset(task_key, "failed_at", datetime.utcnow().isoformat())
                
                # 更新批次失败计数
                batch_id = task_data.get("batch_id")
                if batch_id:
                    batch_key = f"{self.BATCH_STATUS_PREFIX}{batch_id}"
                    await self.redis.hincrby(batch_key, "failed", 1)
                    await self.redis.hset(batch_key, "updated_at", datetime.utcnow().isoformat())
                    
                    # 检查批次是否完成
                    await self._check_batch_completion(batch_id)
                
                logger.error(f"❌ 任务最终失败: {task_id}, 错误: {error}")
            
        except Exception as e:
            logger.error(f"❌ 标记任务失败时出错: {e}", exc_info=True)
    
    async def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """
        获取批次状态
        
        Args:
            batch_id: 批次ID
            
        Returns:
            批次状态信息
        """
        await self.connect()
        
        try:
            batch_key = f"{self.BATCH_STATUS_PREFIX}{batch_id}"
            batch_data = await self.redis.hgetall(batch_key)
            
            if not batch_data:
                return None
            
            # 转换数字字段
            batch_info = dict(batch_data)
            batch_info["total_tasks"] = int(batch_info.get("total_tasks", 0))
            batch_info["completed"] = int(batch_info.get("completed", 0))
            batch_info["failed"] = int(batch_info.get("failed", 0))
            batch_info["progress"] = (
                batch_info["completed"] / batch_info["total_tasks"] * 100
                if batch_info["total_tasks"] > 0 else 0
            )
            
            return batch_info
            
        except Exception as e:
            logger.error(f"❌ 获取批次状态失败: {e}", exc_info=True)
            return None
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        获取队列统计信息
        
        Returns:
            {
                "queue_length": int,  # 队列长度
                "processing_count": int,  # 正在处理的任务数
                "total_batches": int  # 批次总数
            }
        """
        await self.connect()
        
        try:
            queue_length = await self.redis.llen(self.QUEUE_KEY)
            processing_count = await self.redis.scard(self.PROCESSING_SET)
            
            # 统计批次数（简化版）
            total_batches = 0  # 需要扫描所有批次键，这里简化处理
            
            return {
                "queue_length": queue_length,
                "processing_count": processing_count,
                "total_batches": total_batches
            }
            
        except Exception as e:
            logger.error(f"❌ 获取队列统计失败: {e}", exc_info=True)
            return {
                "queue_length": 0,
                "processing_count": 0,
                "total_batches": 0
            }
    
    async def _check_batch_completion(self, batch_id: str):
        """
        检查批次是否完成
        
        Args:
            batch_id: 批次ID
        """
        try:
            batch_key = f"{self.BATCH_STATUS_PREFIX}{batch_id}"
            batch_data = await self.redis.hgetall(batch_key)
            
            total_tasks = int(batch_data.get("total_tasks", 0))
            completed = int(batch_data.get("completed", 0))
            failed = int(batch_data.get("failed", 0))
            
            if completed + failed >= total_tasks:
                # 批次完成
                final_status = "completed" if failed == 0 else "partial_failed"
                await self.redis.hset(batch_key, "status", final_status)
                await self.redis.hset(batch_key, "finished_at", datetime.utcnow().isoformat())
                
                logger.info(
                    f"🎉 批次 {batch_id} 完成: "
                    f"总计={total_tasks}, 成功={completed}, 失败={failed}"
                )
            
        except Exception as e:
            logger.error(f"❌ 检查批次完成状态失败: {e}", exc_info=True)


# 全局任务队列实例
_task_queue: Optional[KGTaskQueue] = None


def get_task_queue() -> KGTaskQueue:
    """获取任务队列单例"""
    global _task_queue
    
    if _task_queue is None:
        from app.config import settings
        # 使用独立的Redis database (1) 避免与主应用冲突
        if settings.redis_password:
            redis_url = f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/1"
        else:
            redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/1"
        _task_queue = KGTaskQueue(redis_url)
    
    return _task_queue

