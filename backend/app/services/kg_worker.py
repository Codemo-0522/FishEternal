"""
知识图谱任务Worker

持续从Redis队列中获取任务并处理
支持并发控制和优雅关闭
"""

import asyncio
import logging
import signal
from typing import Optional
from datetime import datetime

from app.services.kg_task_queue import get_task_queue
from app.knowledge_graph import KnowledgeGraphBuilder
from app.knowledge_graph.neo4j_client import get_client
from app.config import settings

logger = logging.getLogger(__name__)


class KGWorker:
    """知识图谱任务Worker"""
    
    def __init__(self, max_concurrent_tasks: int = 3):
        """
        初始化Worker
        
        Args:
            max_concurrent_tasks: 最大并发任务数
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.running = False
        self.task_queue = get_task_queue()
        self.semaphore: Optional[asyncio.Semaphore] = None
        self.workers: list[asyncio.Task] = []
        
    async def start(self):
        """启动Worker"""
        if self.running:
            logger.warning("⚠️ Worker已经在运行")
            return
        
        self.running = True
        self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        
        logger.info(f"🚀 启动知识图谱Worker，并发数: {self.max_concurrent_tasks}")
        
        # 创建多个消费者协程
        for i in range(self.max_concurrent_tasks):
            worker = asyncio.create_task(self._worker_loop(i))
            self.workers.append(worker)
        
        logger.info(f"✅ {len(self.workers)} 个Worker协程已启动")
    
    async def stop(self):
        """停止Worker"""
        if not self.running:
            return
        
        logger.info("🛑 正在停止Worker...")
        self.running = False
        
        # 等待所有Worker完成当前任务
        for worker in self.workers:
            worker.cancel()
        
        await asyncio.gather(*self.workers, return_exceptions=True)
        
        logger.info("✅ Worker已停止")
    
    async def _worker_loop(self, worker_id: int):
        """
        Worker主循环
        
        Args:
            worker_id: Worker ID
        """
        logger.info(f"🔄 Worker-{worker_id} 开始监听任务队列")
        
        while self.running:
            try:
                # 从队列获取任务（阻塞5秒）
                task = await self.task_queue.get_next_task(timeout=5)
                
                if not task:
                    # 队列为空，继续等待
                    continue
                
                # 获取信号量（控制并发）
                async with self.semaphore:
                    await self._process_task(worker_id, task)
                    
            except asyncio.CancelledError:
                logger.info(f"🛑 Worker-{worker_id} 收到取消信号")
                break
                
            except Exception as e:
                logger.error(f"❌ Worker-{worker_id} 发生异常: {e}", exc_info=True)
                await asyncio.sleep(1)  # 避免异常循环
        
        logger.info(f"✅ Worker-{worker_id} 已退出")
    
    async def _process_task(self, worker_id: int, task: dict):
        """
        处理单个任务
        
        Args:
            worker_id: Worker ID
            task: 任务信息
        """
        task_id = task["task_id"]
        doc_id = task["doc_id"]
        kb_id = task["kb_id"]
        
        logger.info(f"🔨 [Worker-{worker_id}] 开始处理任务: {task_id}")
        
        import tempfile
        import json
        from pathlib import Path
        from app.utils.minio_client import minio_client
        from app.services.knowledge_base_service import KnowledgeBaseService
        from app.database import get_database
        
        temp_file = None
        
        try:
            # 获取MongoDB服务
            db = await get_database()
            kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            
            # 获取文档记录
            doc = await kb_service.get_document(doc_id)
            
            if not doc:
                raise Exception(f"文档不存在: {doc_id}")
            
            # 更新状态为"构建中"
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="building"
            )
            
            file_url = doc.get("file_url")
            if not file_url:
                raise Exception(f"文档缺少file_url: {doc_id}")
            
            # 从MinIO下载文档
            logger.info(f"📥 [Worker-{worker_id}] 从MinIO下载: {file_url}")
            file_content = minio_client.download_kb_document(file_url)
            
            # 验证JSON格式
            filename = doc.get("filename", "")
            if not filename.endswith('.json'):
                raise Exception(f"文档不是JSON格式: {filename}")
            
            # 解析JSON
            json_data = json.loads(file_content.decode('utf-8'))
            logger.info(f"✅ [Worker-{worker_id}] JSON解析成功，包含 {len(json_data)} 条记录")
            
            # 保存到临时文件
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"kg_{doc_id}.json"
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False)
            
            # 构建知识图谱
            logger.info(f"🔨 [Worker-{worker_id}] 开始写入Neo4j")
            builder = KnowledgeGraphBuilder()
            await builder.build_from_json(str(temp_file), clear_existing=False)
            
            logger.info(f"✅ [Worker-{worker_id}] Neo4j写入完成")
            
            # 更新MongoDB状态为成功
            await kb_service.update_document_kg_status(
                doc_id=doc_id,
                kg_status="success",
                kg_built_time=datetime.utcnow().isoformat()
            )
            
            # 清理临时文件
            if temp_file and temp_file.exists():
                temp_file.unlink()
            
            # 标记任务完成
            await self.task_queue.mark_task_completed(task_id)
            
            logger.info(f"🎉 [Worker-{worker_id}] 任务完成: {task_id}")
            
        except Exception as e:
            error_msg = f"任务失败: {str(e)}"
            logger.error(f"❌ [Worker-{worker_id}] {error_msg}", exc_info=True)
            
            # 标记任务失败
            await self.task_queue.mark_task_failed(task_id, error_msg, retry=True)
            
            # 更新MongoDB状态为失败
            try:
                db = await get_database()
                kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
                await kb_service.update_document_kg_status(
                    doc_id=doc_id,
                    kg_status="failed",
                    kg_error_message=error_msg
                )
            except Exception as update_error:
                logger.error(f"❌ 更新失败状态时出错: {update_error}")
            
            # 清理临时文件
            try:
                if temp_file and temp_file.exists():
                    temp_file.unlink()
            except Exception as cleanup_error:
                logger.error(f"清理临时文件失败: {cleanup_error}")


# 全局Worker实例
_worker: Optional[KGWorker] = None


async def start_worker(max_concurrent_tasks: int = 3):
    """
    启动全局Worker
    
    Args:
        max_concurrent_tasks: 最大并发任务数
    """
    global _worker
    
    if _worker is not None:
        logger.warning("⚠️ Worker已经在运行")
        return
    
    _worker = KGWorker(max_concurrent_tasks)
    await _worker.start()


async def stop_worker():
    """停止全局Worker"""
    global _worker
    
    if _worker is not None:
        await _worker.stop()
        _worker = None


def get_worker() -> Optional[KGWorker]:
    """获取全局Worker实例"""
    return _worker

