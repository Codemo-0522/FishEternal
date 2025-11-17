"""
朋友圈发布器 - 处理延迟发布队列

每分钟检查一次队列，发布所有到期的朋友圈

设计特点：
1. 定时任务：使用 APScheduler 每分钟执行一次
2. 批量处理：一次处理所有到期的朋友圈
3. 错误容忍：单条失败不影响其他朋友圈发布
4. 资源管理：支持图片等外部资源（如果可用）
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from typing import Optional
import logging
import uuid

from ..config import settings

logger = logging.getLogger(__name__)


class MomentPublisher:
    """朋友圈发布器"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._db = None
        self._started = False
    
    async def initialize(self, db):
        """
        初始化发布器
        
        Args:
            db: 数据库连接
        """
        self._db = db
        logger.info("✅ 朋友圈发布器已初始化")
    
    def start(self):
        """启动定时任务"""
        
        if self._started:
            logger.warning("⚠️ 朋友圈发布器已启动，跳过")
            return
        
        if not self._db:
            logger.error("❌ 数据库连接未初始化，无法启动发布器")
            return
        
        # 每 1 分钟检查一次队列
        self.scheduler.add_job(
            func=self.publish_pending_moments,
            trigger='interval',
            minutes=1,
            id='moment_publisher',
            replace_existing=True  # 如果已存在则替换
        )
        
        self.scheduler.start()
        self._started = True
        logger.info("✅ 朋友圈发布器已启动（检查频率：每 1 分钟）")
    
    def stop(self):
        """停止定时任务"""
        if self._started and self.scheduler.running:
            self.scheduler.shutdown()
            self._started = False
            logger.info("👋 朋友圈发布器已停止")
    
    async def publish_pending_moments(self):
        """
        发布所有到期的朋友圈（并发优化版本）
        
        这个方法会：
        1. 查找所有 status="pending" 且 publish_at <= 当前时间的记录
        2. 并发发布到 moments 集合（使用 asyncio.gather）
        3. 更新队列状态为 "published"
        4. 如果图片尚未生成但需要图片，尝试生成（如果服务可用）
        
        并发优化：
        - 使用 asyncio.gather 并发处理多条朋友圈
        - 限制并发数量（最多 10 个并发任务）避免资源耗尽
        - 单个任务失败不影响其他任务
        """
        
        if not self._db:
            logger.error("❌ 数据库连接未初始化")
            return
        
        now = datetime.now()
        
        try:
            # 查找所有包含待发布朋友圈的会话
            sessions_with_pending = await self._db[settings.mongodb_db_name].chat_sessions.find({
                "moment_queue": {
                    "$elemMatch": {
                        "status": "pending",
                        "publish_at": {"$lte": now.isoformat()}
                    }
                }
            }).to_list(None)
            
            if not sessions_with_pending:
                # 没有待发布的朋友圈，静默跳过
                return
            
            # 提取所有待发布的朋友圈
            pending_moments = []
            for session in sessions_with_pending:
                for queue_item in session.get("moment_queue", []):
                    if queue_item["status"] == "pending" and queue_item["publish_at"] <= now.isoformat():
                        # 附加 session_id 信息
                        queue_item["session_id"] = session["_id"]
                        pending_moments.append(queue_item)
            
            logger.info(f"🔍 检查到 {len(pending_moments)} 条待发布朋友圈")
            
            # 🚀 并发处理优化：使用 asyncio.gather + Semaphore 限流
            import asyncio
            
            # 最多 10 个并发任务（避免资源耗尽）
            semaphore = asyncio.Semaphore(10)
            
            async def publish_with_semaphore(queue_item):
                """带信号量的发布函数"""
                async with semaphore:
                    try:
                        await self._publish_moment(queue_item)
                        logger.info(f"✅ 发布朋友圈成功: {queue_item['content'][:30]}...")
                    except Exception as e:
                        logger.error(f"❌ 发布朋友圈失败 [{queue_item['_id']}]: {e}", exc_info=True)
                        
                        # 更新队列状态为 error（在会话文档中）
                        await self._db[settings.mongodb_db_name].chat_sessions.update_one(
                            {"_id": queue_item["session_id"], "moment_queue._id": queue_item["_id"]},
                            {"$set": {
                                "moment_queue.$.status": "error",
                                "moment_queue.$.error_message": str(e),
                                "moment_queue.$.error_at": datetime.now().isoformat()
                            }}
                        )
            
            # 并发执行所有任务
            await asyncio.gather(
                *[publish_with_semaphore(item) for item in pending_moments],
                return_exceptions=True  # 单个任务失败不影响其他任务
            )
        
        except Exception as e:
            logger.error(f"❌ 检查待发布朋友圈时出错: {e}", exc_info=True)
    
    async def _publish_moment(self, queue_item: dict):
        """
        发布单条朋友圈（直接写入会话文档）
        
        Args:
            queue_item: 队列记录（包含 session_id）
        """
        
        # 1. 如果需要图片但尚未生成，尝试生成
        if queue_item.get("need_image") and not queue_item.get("generated_images"):
            image_prompt = queue_item.get("image_prompt")
            if image_prompt:
                logger.info(f"🎨 检测到朋友圈需要图片，尝试生成...")
                images = await self._try_generate_images(image_prompt)
                if images:
                    queue_item["generated_images"] = images
                    logger.info(f"✅ 成功生成 {len(images)} 张图片")
        
        # 2. 创建朋友圈记录
        moment = {
            "_id": str(uuid.uuid4()),
            "content": queue_item["content"],
            "images": queue_item.get("generated_images", []),
            "mood": queue_item.get("mood"),
            "created_at": datetime.now().isoformat(),  # 实际发布时间
            "scheduled_at": queue_item["created_at"],  # AI 决定发布的时间
            "likes": [],
            "comments": []
        }
        
        # 3. 原子操作：将朋友圈添加到 moments 数组，同时更新队列状态
        session_id = queue_item["session_id"]
        queue_id = queue_item["_id"]
        
        await self._db[settings.mongodb_db_name].chat_sessions.update_one(
            {"_id": session_id, "moment_queue._id": queue_id},
            {
                "$push": {"moments": moment},  # 添加到朋友圈列表
                "$set": {
                    "moment_queue.$.status": "published",
                    "moment_queue.$.published_moment_id": moment["_id"],
                    "moment_queue.$.published_at": datetime.now().isoformat()
                }
            }
        )
        
        logger.info(f"📝 朋友圈已发布并保存到会话文档: {moment['_id']}")
        
        # 4. 可选：通知前端（WebSocket）
        await self._notify_frontend(session_id, moment)
    
    async def _try_generate_images(self, image_prompt: str) -> list:
        """
        尝试生成图片（如果资源管理器可用）
        
        Args:
            image_prompt: 图片描述
        
        Returns:
            list: 图片 URL 列表，失败返回空列表
        
        超时保护：
        - 图片生成最多等待 30 秒（避免阻塞其他朋友圈发布）
        - 超时则跳过图片，发布纯文字朋友圈
        """
        import asyncio
        
        try:
            from .resource_manager import get_resource_manager
            
            resource_mgr = await get_resource_manager()
            
            # 检查是否有可用的图片生成器
            available_generators = resource_mgr.get_available_generators(
                resource_type="image"
            )
            
            if not available_generators:
                logger.info("ℹ️ 暂无可用的图片生成服务")
                return []
            
            # ⏱️ 生成图片（带超时保护，最多 30 秒）
            try:
                image_urls = await asyncio.wait_for(
                    resource_mgr.generate_image(
                        prompt=image_prompt,
                        generator_name=available_generators[0]
                    ),
                    timeout=30.0  # 30 秒超时
                )
                
                return image_urls or []
            
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ 图片生成超时（30秒），跳过配图")
                return []
            
        except Exception as e:
            logger.error(f"❌ 生成图片失败: {e}")
            return []
    
    async def _notify_frontend(self, session_id: str, moment: dict):
        """
        通知前端有新朋友圈（通过 WebSocket）
        
        Args:
            session_id: 会话 ID
            moment: 朋友圈记录
        
        注意：这是一个预留接口，如果你的项目有 WebSocket 支持，可以在这里实现推送
        """
        # TODO: 如果你有 WebSocket 管理器，可以在这里推送
        # 示例：
        # from ..websocket import websocket_manager
        # await websocket_manager.broadcast({
        #     "type": "new_moment",
        #     "session_id": session_id,
        #     "moment": moment
        # })
        pass


# 全局单例
_moment_publisher: Optional[MomentPublisher] = None


async def get_moment_publisher(db=None) -> MomentPublisher:
    """
    获取朋友圈发布器单例
    
    Args:
        db: 数据库连接（首次调用时必须提供）
    
    Returns:
        MomentPublisher: 发布器实例
    """
    global _moment_publisher
    
    if _moment_publisher is None:
        _moment_publisher = MomentPublisher()
        if db:
            await _moment_publisher.initialize(db)
    
    return _moment_publisher

