"""
朋友圈发布器 - 处理延迟发布队列

每分钟检查一次队列，发布所有到期的朋友圈
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging
import uuid
import asyncio
import time
import base64
import httpx
from bson import ObjectId

from ..config import settings
from ..utils.minio_client import minio_client
from ..utils.image_generation.modelscope import ModelScopeImageGenerationService

logger = logging.getLogger(__name__)


async def get_user_image_generation_providers(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    """获取用户已配置并启用的图片生成服务商"""
    try:
        user_object_id = ObjectId(user_id)
        user_doc = await db[settings.mongodb_db_name].users.find_one({"_id": user_object_id})
        if not user_doc or not user_doc.get("image_generation_configs"):
            return {}
        configs = user_doc.get("image_generation_configs", {})
        enabled_configs = {p_id: cfg for p_id, cfg in configs.items() if cfg.get("enabled", False)}
        return enabled_configs
    except Exception as e:
        logger.error(f"❌ 获取用户图片生成配置失败: {str(e)}", exc_info=True)
        return {}


async def download_image(image_url: str, timeout: int = 600) -> bytes:
    """从URL下载图片"""
    async with httpx.AsyncClient() as client:
        response = await client.get(image_url, timeout=timeout)
        response.raise_for_status()
        return response.content


async def upload_generated_image_to_minio(image_bytes: bytes, session_id: str, user_id: str, moment_id: str, image_index: int = 0) -> str:
    """上传生成的图片到MinIO，使用朋友圈ID作为路径"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    # 使用朋友圈ID作为唯一标识
    minio_path_id = f"moment_{moment_id}_{image_index}"
    minio_url = minio_client.upload_image(
        image_base64=base64_image,
        session_id=session_id,
        message_id=minio_path_id, # 使用自定义路径
        user_id=user_id
    )
    return minio_url


class MomentPublisher:
    """朋友圈发布器"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._db = None
        self._started = False
    
    async def initialize(self, db):
        self._db = db
        logger.info("✅ 朋友圈发布器已初始化")
    
    def start(self):
        if self._started:
            return
        if not self._db:
            logger.error("❌ 数据库连接未初始化，无法启动发布器")
            return
        self.scheduler.add_job(self.publish_pending_moments, 'interval', minutes=1, id='moment_publisher', replace_existing=True)
        self.scheduler.start()
        self._started = True
        logger.info("✅ 朋友圈发布器已启动（检查频率：每 1 分钟）")
    
    def stop(self):
        if self._started and self.scheduler.running:
            self.scheduler.shutdown()
            self._started = False
            logger.info("👋 朋友圈发布器已停止")
    
    async def publish_pending_moments(self):
        if not self._db:
            return
        now = datetime.now()
        try:
            sessions_with_pending = await self._db[settings.mongodb_db_name].chat_sessions.find({
                "moment_queue": {
                    "$elemMatch": {"status": "pending", "publish_at": {"$lte": now.isoformat()}}
                }
            }).to_list(None)
            
            if not sessions_with_pending:
                return

            pending_moments = []
            for session in sessions_with_pending:
                user_id = str(session["user_id"])
                for queue_item in session.get("moment_queue", []):
                    if queue_item["status"] == "pending" and queue_item["publish_at"] <= now.isoformat():
                        queue_item["session_id"] = session["_id"]
                        queue_item["user_id"] = user_id # 注入user_id
                        pending_moments.append(queue_item)
            
            if not pending_moments:
                return

            logger.info(f"🔍 检查到 {len(pending_moments)} 条待发布朋友圈")
            
            semaphore = asyncio.Semaphore(5) # 并发数降低到5
            async def publish_with_semaphore(queue_item):
                async with semaphore:
                    try:
                        await self._publish_moment(queue_item)
                        logger.info(f"✅ 发布朋友圈成功: {queue_item['content'][:30]}...")
                    except Exception as e:
                        logger.error(f"❌ 发布朋友圈失败 [{queue_item['_id']}]: {e}", exc_info=True)
                        await self._db[settings.mongodb_db_name].chat_sessions.update_one(
                            {"_id": queue_item["session_id"], "moment_queue._id": queue_item["_id"]},
                            {"$set": {"moment_queue.$.status": "error", "moment_queue.$.error_message": str(e)}}
                        )
            
            await asyncio.gather(*[publish_with_semaphore(item) for item in pending_moments], return_exceptions=True)
        
        except Exception as e:
            logger.error(f"❌ 检查待发布朋友圈时出错: {e}", exc_info=True)

    async def _publish_moment(self, queue_item: dict):
        """发布单条朋友圈，并在需要时生成图片"""
        image_urls = []
        if queue_item.get("need_image") and queue_item.get("image_prompt"):
            logger.info("🎨 开始为朋友圈生成图片...")
            image_urls = await self._generate_images_for_moment(queue_item) or []

        moment = {
            "_id": str(uuid.uuid4()),
            "content": queue_item["content"],
            "images": image_urls,
            "mood": queue_item.get("mood"),
            "created_at": datetime.now().isoformat(),
            "scheduled_at": queue_item["created_at"],
            "likes": [],
            "comments": []
        }
        
        await self._db[settings.mongodb_db_name].chat_sessions.update_one(
            {"_id": queue_item["session_id"], "moment_queue._id": queue_item["_id"]},
            {
                "$push": {"moments": moment},
                "$set": {
                    "moment_queue.$.status": "published",
                    "moment_queue.$.published_moment_id": moment["_id"],
                    "moment_queue.$.generated_images": image_urls  # <-- 修复：将图片URL保存回队列项
                }
            }
        )
        
        logger.info(f"📝 朋友圈已发布并保存到会话文档: {moment['_id']}")
        await self._notify_frontend(queue_item["session_id"], moment)

    async def _generate_images_for_moment(self, queue_item: dict) -> Optional[List[str]]:
        """使用ModelScope为朋友圈生成、下载并上传图片"""
        user_id = queue_item.get("user_id")
        session_id = queue_item.get("session_id")
        prompt = queue_item.get("image_prompt")
        image_size = queue_item.get("image_size")
        negative_prompt = queue_item.get("negative_prompt")
        n = queue_item.get("n")
        steps = queue_item.get("steps")
        seed = queue_item.get("seed")

        if not all([user_id, session_id, prompt]):
            logger.error("缺少生成图片所需信息 (user_id, session_id, prompt)")
            return None

        user_providers = await get_user_image_generation_providers(self._db, user_id)
        if not user_providers:
            logger.warning(f"用户 {user_id} 未配置任何图片生成服务，无法为朋友圈生成图片")
            return None

        # 使用默认或第一个可用的服务商
        user_doc = await self._db[settings.mongodb_db_name].users.find_one({"_id": ObjectId(user_id)})
        provider_id = user_doc.get("default_image_generation_provider") if user_doc else None
        if not provider_id or provider_id not in user_providers:
            provider_id = list(user_providers.keys())[0]
        
        provider_config = user_providers[provider_id]
        model = provider_config.get("default_model")
        if not model:
            logger.warning(f"服务商 {provider_id} 未配置默认模型")
            return None

        service = ModelScopeImageGenerationService(api_key=provider_config["api_key"])
        
        # 构建任务参数
        task_params = {
            "prompt": prompt,
            "model": model
        }
        if image_size:
            task_params["size"] = image_size
        if negative_prompt:
            task_params["negative_prompt"] = negative_prompt
        if n:
            task_params["n"] = n
        if steps:
            task_params["steps"] = steps
        if seed:
            task_params["seed"] = seed
            
        task_id = await service.submit_task(**task_params)

        if not task_id:
            logger.error("ModelScope 任务提交失败")
            return None

        start_time = time.time()
        timeout = 600  # 10分钟
        while time.time() - start_time < timeout:
            result = await service.get_task_result(task_id)
            task_status = result.get("task_status")

            if task_status == "SUCCEED":
                output_images = result.get("output_images", [])
                if not output_images:
                    logger.warning("ModelScope 任务成功但未返回图片")
                    return None

                minio_urls = []
                for idx, image_url in enumerate(output_images):
                    try:
                        image_bytes = await download_image(image_url)
                        minio_url = await upload_generated_image_to_minio(
                            image_bytes=image_bytes, 
                            session_id=session_id, 
                            user_id=user_id, 
                            moment_id=queue_item["_id"], # 使用队列ID确保路径唯一
                            image_index=idx
                        )
                        minio_urls.append(minio_url)
                    except Exception as e:
                        logger.error(f"处理图片 {idx+1} 失败: {e}")
                        continue
                return minio_urls

            elif task_status == "FAILED":
                logger.error(f"ModelScope 任务失败: {result.get('output', {}).get('message')}")
                return None
            
            await asyncio.sleep(5)

        logger.warning("ModelScope 任务超时")
        return None

    async def _notify_frontend(self, session_id: str, moment: dict):
        pass # 预留接口


# 全局单例
_moment_publisher: Optional[MomentPublisher] = None

async def get_moment_publisher(db=None) -> MomentPublisher:
    global _moment_publisher
    if _moment_publisher is None:
        _moment_publisher = MomentPublisher()
        if db:
            await _moment_publisher.initialize(db)
    return _moment_publisher

