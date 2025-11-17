"""
全局Redis客户端管理器
提供单例模式的Redis连接池，支持异步操作
"""
import logging
from typing import Optional
import redis.asyncio as aioredis
from redis.asyncio import Redis
from .config import settings

logger = logging.getLogger(__name__)

class RedisClient:
    """Redis客户端单例管理器"""
    
    _instance: Optional[Redis] = None
    _initialized: bool = False
    
    @classmethod
    async def get_instance(cls) -> Redis:
        """
        获取Redis客户端单例
        
        Returns:
            Redis客户端实例
        """
        if cls._instance is None:
            await cls.initialize()
        return cls._instance
    
    @classmethod
    async def initialize(cls, max_retries: int = 3, retry_delay: float = 1.0):
        """初始化Redis连接池（带重试机制）"""
        if cls._initialized:
            logger.debug("Redis客户端已初始化，跳过")
            return
        
        import asyncio
        
        for attempt in range(max_retries):
            try:
                # 构建Redis连接URL
                if settings.redis_password:
                    redis_url = f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
                else:
                    redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
                
                # 创建Redis连接池
                cls._instance = await aioredis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,  # 自动解码为字符串
                    max_connections=settings.redis_max_connections,
                    socket_connect_timeout=settings.redis_socket_timeout,
                    socket_keepalive=True,
                )
                
                # 测试连接
                await cls._instance.ping()
                
                cls._initialized = True
                logger.info(f"✅ Redis连接成功: {settings.redis_host}:{settings.redis_port} (DB: {settings.redis_db})")
                return
                
            except Exception as e:
                logger.warning(f"⚠️ Redis连接尝试 {attempt + 1}/{max_retries} 失败: {e}")
                cls._instance = None
                cls._initialized = False
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"❌ Redis连接失败，已重试 {max_retries} 次")
                    raise
    
    @classmethod
    async def close(cls):
        """关闭Redis连接"""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
            cls._initialized = False
            logger.info("Redis连接已关闭")


# 全局便捷函数
async def get_redis() -> Redis:
    """
    获取Redis客户端实例（全局单例）
    
    Usage:
        redis = await get_redis()
        await redis.set("key", "value")
        value = await redis.get("key")
    
    Returns:
        Redis客户端实例
    """
    return await RedisClient.get_instance()


async def close_redis():
    """关闭Redis连接"""
    await RedisClient.close()

