"""
模型能力管理器
负责记录和查询LLM模型的能力（如是否支持工具调用）

架构：三层缓存
1. 本地内存缓存（进程级，最快）
2. Redis缓存（跨进程共享，快）
3. MongoDB持久化（永久存储）

流程：
- 启动时：MongoDB → Redis → 本地缓存
- 查询时：本地缓存 → Redis → 未知（允许尝试）
- 发现不支持：同时写 MongoDB + Redis + 本地缓存
"""
import logging
import asyncio
from typing import Optional, Set, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

class ModelCapabilityManager:
    """模型能力管理器（三层缓存架构）"""
    
    # Redis Key常量
    REDIS_KEY_UNSUPPORTED_MODELS = "mcp:unsupported_models"
    REDIS_KEY_SUPPORTED_MODELS = "mcp:supported_models"  # 可选：缓存支持的模型
    
    def __init__(self):
        self._redis: Optional[Redis] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        
        # 本地内存缓存（进程级）
        self._unsupported_cache: Set[str] = set()
        self._supported_cache: Set[str] = set()  # 可选：缓存已知支持的模型
    
    async def initialize(self, db: AsyncIOMotorDatabase, redis: Redis):
        """
        初始化管理器：从MongoDB加载数据到Redis和本地缓存
        
        Args:
            db: MongoDB数据库实例
            redis: Redis客户端实例
        """
        if self._initialized:
            logger.debug("ModelCapabilityManager 已初始化，跳过")
            return
        
        async with self._init_lock:
            # 双重检查锁
            if self._initialized:
                return
            
            self._db = db
            self._redis = redis
            
            try:
                logger.info("🔄 正在初始化模型能力管理器...")
                
                # 1. 从MongoDB加载不支持工具的模型
                cursor = db["model_capabilities"].find({"supports_tools": False})
                unsupported_models = []
                
                async for doc in cursor:
                    unsupported_models.append(doc["model_name"])
                
                # 2. 批量写入Redis（先清空再写入，保证数据一致性）
                if unsupported_models:
                    await redis.delete(self.REDIS_KEY_UNSUPPORTED_MODELS)
                    await redis.sadd(self.REDIS_KEY_UNSUPPORTED_MODELS, *unsupported_models)
                    logger.info(f"✅ 已将 {len(unsupported_models)} 个不支持工具的模型加载到Redis")
                else:
                    logger.info("ℹ️ 当前没有已知不支持工具的模型")
                
                # 3. 加载到本地缓存
                self._unsupported_cache = set(unsupported_models)
                
                # 4. 可选：加载支持工具的模型（用于统计和优化）
                cursor = db["model_capabilities"].find({"supports_tools": True})
                supported_models = [doc["model_name"] async for doc in cursor]
                self._supported_cache = set(supported_models)
                
                if supported_models:
                    logger.info(f"ℹ️ 已知支持工具的模型: {len(supported_models)} 个")
                
                self._initialized = True
                logger.info("✅ 模型能力管理器初始化完成")
                
            except Exception as e:
                logger.error(f"❌ 初始化模型能力管理器失败: {e}", exc_info=True)
                self._initialized = False
                raise
    
    async def check_supports_tools(self, model_name: str) -> bool:
        """
        检查模型是否支持工具调用
        
        Args:
            model_name: 模型标识符（如 "gpt-4", "deepseek-chat"）
        
        Returns:
            True: 支持或未知（需要尝试MCP）
            False: 已知不支持（跳过MCP）
        """
        if not self._initialized:
            logger.warning("⚠️ ModelCapabilityManager 未初始化，默认允许尝试工具调用")
            return True
        
        if not model_name:
            logger.warning("⚠️ 模型名称为空，默认允许尝试")
            return True
        
        # 1️⃣ 本地缓存检查（最快，0网络开销）
        if model_name in self._unsupported_cache:
            logger.debug(f"🎯 本地缓存命中: {model_name} 不支持工具")
            return False
        
        # 可选：如果已知支持，直接返回
        if model_name in self._supported_cache:
            logger.debug(f"🎯 本地缓存命中: {model_name} 支持工具")
            return True
        
        # 2️⃣ Redis检查（快，<1ms）
        try:
            is_unsupported = await self._redis.sismember(
                self.REDIS_KEY_UNSUPPORTED_MODELS, 
                model_name
            )
            
            if is_unsupported:
                # 更新本地缓存
                self._unsupported_cache.add(model_name)
                logger.info(f"🚫 Redis缓存命中: {model_name} 不支持工具调用")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ Redis查询失败，跳过缓存检查: {e}")
        
        # 3️⃣ 未命中任何缓存 = 未知模型 = 允许尝试
        logger.debug(f"ℹ️ 模型 {model_name} 未知，允许尝试工具调用")
        return True
    
    async def mark_unsupported(
        self, 
        model_name: str, 
        error_message: Optional[str] = None,
        notes: Optional[str] = None
    ):
        """
        标记模型不支持工具调用
        同时写入MongoDB（持久化）、Redis（共享缓存）、本地缓存（进程缓存）
        
        Args:
            model_name: 模型标识符
            error_message: 错误信息
            notes: 备注
        """
        if not self._initialized:
            logger.warning("⚠️ ModelCapabilityManager 未初始化，跳过标记")
            return
        
        if not model_name:
            logger.warning("⚠️ 模型名称为空，跳过标记")
            return
        
        try:
            now = datetime.utcnow()
            
            # 1️⃣ 写入MongoDB（持久化存储）
            result = await self._db["model_capabilities"].update_one(
                {"model_name": model_name},
                {
                    "$set": {
                        "supports_tools": False,
                        "last_checked": now,
                        "error_message": error_message,
                        "notes": notes
                    },
                    "$setOnInsert": {
                        "first_seen": now,
                    },
                    "$inc": {
                        "check_count": 1
                    }
                },
                upsert=True
            )
            
            if result.upserted_id:
                logger.info(f"💾 新增模型能力记录: {model_name}")
            else:
                logger.info(f"💾 更新模型能力记录: {model_name}")
            
            # 2️⃣ 写入Redis（跨进程共享缓存）
            await self._redis.sadd(self.REDIS_KEY_UNSUPPORTED_MODELS, model_name)
            logger.debug(f"⚡ 已更新Redis缓存: {model_name}")
            
            # 3️⃣ 更新本地缓存（进程级缓存）
            self._unsupported_cache.add(model_name)
            # 如果之前在支持列表中，移除
            self._supported_cache.discard(model_name)
            
            logger.warning(f"⚠️ 已将模型 {model_name} 标记为不支持工具调用")
            
        except Exception as e:
            logger.error(f"❌ 标记模型能力失败 ({model_name}): {e}", exc_info=True)
    
    async def mark_supported(
        self, 
        model_name: str,
        notes: Optional[str] = None
    ):
        """
        标记模型支持工具调用（用于手动修正或测试验证）
        
        Args:
            model_name: 模型标识符
            notes: 备注
        """
        if not self._initialized:
            logger.warning("⚠️ ModelCapabilityManager 未初始化，跳过标记")
            return
        
        if not model_name:
            return
        
        try:
            now = datetime.utcnow()
            
            # 1️⃣ 更新MongoDB
            await self._db["model_capabilities"].update_one(
                {"model_name": model_name},
                {
                    "$set": {
                        "supports_tools": True,
                        "last_checked": now,
                        "error_message": None,  # 清空错误信息
                        "notes": notes
                    },
                    "$setOnInsert": {
                        "first_seen": now,
                    },
                    "$inc": {
                        "check_count": 1
                    }
                },
                upsert=True
            )
            
            # 2️⃣ 从Redis黑名单中移除
            await self._redis.srem(self.REDIS_KEY_UNSUPPORTED_MODELS, model_name)
            
            # 3️⃣ 更新本地缓存
            self._unsupported_cache.discard(model_name)
            self._supported_cache.add(model_name)
            
            logger.info(f"✅ 已将模型 {model_name} 标记为支持工具调用")
            
        except Exception as e:
            logger.error(f"❌ 更新模型能力失败 ({model_name}): {e}", exc_info=True)
    
    async def get_all_unsupported_models(self) -> List[str]:
        """
        获取所有不支持工具的模型列表（用于管理界面）
        
        Returns:
            模型名称列表
        """
        if not self._initialized:
            return []
        
        try:
            cursor = self._db["model_capabilities"].find({"supports_tools": False})
            return [doc["model_name"] async for doc in cursor]
        except Exception as e:
            logger.error(f"❌ 查询失败: {e}")
            return []
    
    async def get_all_supported_models(self) -> List[str]:
        """
        获取所有支持工具的模型列表（用于管理界面）
        
        Returns:
            模型名称列表
        """
        if not self._initialized:
            return []
        
        try:
            cursor = self._db["model_capabilities"].find({"supports_tools": True})
            return [doc["model_name"] async for doc in cursor]
        except Exception as e:
            logger.error(f"❌ 查询失败: {e}")
            return []
    
    async def get_model_info(self, model_name: str) -> Optional[dict]:
        """
        获取模型的详细信息
        
        Args:
            model_name: 模型标识符
        
        Returns:
            模型信息字典，如果不存在返回None
        """
        if not self._initialized:
            return None
        
        try:
            doc = await self._db["model_capabilities"].find_one({"model_name": model_name})
            return doc
        except Exception as e:
            logger.error(f"❌ 查询模型信息失败: {e}")
            return None
    
    async def clear_cache(self):
        """清空所有缓存（用于调试或刷新）"""
        if not self._initialized:
            return
        
        try:
            # 清空Redis
            await self._redis.delete(self.REDIS_KEY_UNSUPPORTED_MODELS)
            await self._redis.delete(self.REDIS_KEY_SUPPORTED_MODELS)
            
            # 清空本地缓存
            self._unsupported_cache.clear()
            self._supported_cache.clear()
            
            logger.info("🗑️ 已清空所有缓存")
            
        except Exception as e:
            logger.error(f"❌ 清空缓存失败: {e}")
    
    async def reload_from_db(self):
        """从MongoDB重新加载数据到缓存"""
        if not self._initialized:
            logger.warning("⚠️ 管理器未初始化")
            return
        
        try:
            # 先清空缓存
            await self.clear_cache()
            
            # 重新加载
            cursor = self._db["model_capabilities"].find({"supports_tools": False})
            unsupported_models = [doc["model_name"] async for doc in cursor]
            
            if unsupported_models:
                await self._redis.sadd(self.REDIS_KEY_UNSUPPORTED_MODELS, *unsupported_models)
                self._unsupported_cache = set(unsupported_models)
            
            logger.info(f"🔄 已重新加载 {len(unsupported_models)} 个模型数据")
            
        except Exception as e:
            logger.error(f"❌ 重新加载失败: {e}")


# 全局单例
model_capability_manager = ModelCapabilityManager()

