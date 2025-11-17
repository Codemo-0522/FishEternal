"""
知识图谱可视化数据缓存管理器（基于Redis）

设计思路：
1. 工具执行时：将可视化数据存储到Redis（key包含session_id和timestamp，确保隔离）
2. streaming_manager：在流式响应结束后，从Redis提取数据并发送给前端
3. 发送完成后：自动清理Redis缓存

缓存隔离：
- Key格式：kg_viz:{session_id}:{timestamp_ms}
- 每个会话独立存储，避免冲突
- 使用timestamp_ms确保同一会话的多次检索不会覆盖
"""

import json
import logging
import time
from typing import Dict, Any, List, Optional
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class GraphVisualizationCache:
    """图谱可视化数据Redis缓存管理器"""
    
    # Redis Key前缀
    KEY_PREFIX = "kg_viz"
    
    # 默认过期时间（5分钟，避免长时间占用内存）
    DEFAULT_TTL = 300
    
    @classmethod
    def _build_key(cls, session_id: str, timestamp_ms: int = None) -> str:
        """
        构建Redis Key
        
        Args:
            session_id: 会话ID
            timestamp_ms: 时间戳（毫秒）
        
        Returns:
            Redis Key（格式：kg_viz:{session_id}:{timestamp_ms}）
        """
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        return f"{cls.KEY_PREFIX}:{session_id}:{timestamp_ms}"
    
    @classmethod
    def _build_pattern(cls, session_id: str) -> str:
        """
        构建Redis Key匹配模式（用于查询会话的所有可视化数据）
        
        Args:
            session_id: 会话ID
        
        Returns:
            Redis Key Pattern（格式：kg_viz:{session_id}:*）
        """
        return f"{cls.KEY_PREFIX}:{session_id}:*"
    
    @classmethod
    async def store_visualization(
        cls,
        redis: Redis,
        session_id: str,
        visualization_data: Dict[str, Any],
        ttl: int = DEFAULT_TTL
    ) -> str:
        """
        存储图谱可视化数据到Redis
        
        Args:
            redis: Redis客户端
            session_id: 会话ID
            visualization_data: 可视化数据（包含nodes、edges、metadata）
            ttl: 过期时间（秒）
        
        Returns:
            Redis Key
        """
        try:
            # 生成唯一Key（包含时间戳）
            timestamp_ms = int(time.time() * 1000)
            key = cls._build_key(session_id, timestamp_ms)
            
            # 序列化数据
            data_json = json.dumps(visualization_data, ensure_ascii=False)
            
            # 存储到Redis（设置过期时间）
            await redis.setex(key, ttl, data_json)
            
            logger.info(f"✅ 图谱可视化数据已存储到Redis: {key}, "
                       f"{visualization_data['metadata']['total_nodes']} 个节点, "
                       f"{visualization_data['metadata']['total_edges']} 条边, "
                       f"TTL={ttl}秒")
            
            return key
        
        except Exception as e:
            logger.error(f"❌ 存储图谱可视化数据到Redis失败: {e}", exc_info=True)
            return None
    
    @classmethod
    async def get_all_visualizations(
        cls,
        redis: Redis,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """
        获取会话的所有图谱可视化数据
        
        Args:
            redis: Redis客户端
            session_id: 会话ID
        
        Returns:
            可视化数据列表（按时间戳排序）
        """
        try:
            # 查找所有匹配的Key
            pattern = cls._build_pattern(session_id)
            keys = []
            
            # 使用SCAN遍历（避免KEYS命令阻塞Redis）
            cursor = 0
            while True:
                cursor, partial_keys = await redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                keys.extend(partial_keys)
                if cursor == 0:
                    break
            
            if not keys:
                logger.debug(f"📭 未找到会话的图谱可视化数据: {session_id}")
                return []
            
            # 批量获取数据
            visualizations = []
            for key in keys:
                try:
                    data_json = await redis.get(key)
                    if data_json:
                        data = json.loads(data_json)
                        # 提取时间戳（用于排序）
                        timestamp_str = key.split(":")[-1]
                        data["_timestamp"] = int(timestamp_str)
                        visualizations.append(data)
                except Exception as e:
                    logger.warning(f"⚠️ 解析可视化数据失败: {key}, {e}")
            
            # 按时间戳排序
            visualizations.sort(key=lambda x: x.get("_timestamp", 0))
            
            logger.info(f"✅ 获取到 {len(visualizations)} 个图谱可视化数据: {session_id}")
            return visualizations
        
        except Exception as e:
            logger.error(f"❌ 获取图谱可视化数据失败: {e}", exc_info=True)
            return []
    
    @classmethod
    async def delete_session_visualizations(
        cls,
        redis: Redis,
        session_id: str
    ) -> int:
        """
        删除会话的所有图谱可视化数据
        
        Args:
            redis: Redis客户端
            session_id: 会话ID
        
        Returns:
            删除的Key数量
        """
        try:
            # 查找所有匹配的Key
            pattern = cls._build_pattern(session_id)
            keys = []
            
            cursor = 0
            while True:
                cursor, partial_keys = await redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                keys.extend(partial_keys)
                if cursor == 0:
                    break
            
            if not keys:
                return 0
            
            # 批量删除
            deleted_count = await redis.delete(*keys)
            
            logger.info(f"🗑️ 已删除 {deleted_count} 个图谱可视化缓存: {session_id}")
            return deleted_count
        
        except Exception as e:
            logger.error(f"❌ 删除图谱可视化缓存失败: {e}", exc_info=True)
            return 0
    
    @classmethod
    async def delete_single_visualization(
        cls,
        redis: Redis,
        key: str
    ) -> bool:
        """
        删除单个可视化数据
        
        Args:
            redis: Redis客户端
            key: Redis Key
        
        Returns:
            是否删除成功
        """
        try:
            result = await redis.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"❌ 删除单个可视化缓存失败: {key}, {e}")
            return False

