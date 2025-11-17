# -*- coding:utf-8 -*-
"""
TTS连接池基类
提供通用的WebSocket连接池管理功能，所有TTS提供商都应继承此类
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态枚举"""
    IDLE = "idle"  # 空闲
    CONNECTING = "connecting"  # 连接中
    CONNECTED = "connected"  # 已连接
    BUSY = "busy"  # 忙碌中
    ERROR = "error"  # 错误
    CLOSED = "closed"  # 已关闭


@dataclass
class ConnectionInfo:
    """连接信息"""
    connection_id: str
    websocket: Any
    state: ConnectionState
    created_at: float
    last_used_at: float
    error_count: int = 0
    current_task_id: Optional[str] = None


class BaseTTSConnectionPool(ABC):
    """
    TTS连接池基类
    
    所有TTS提供商都应继承此类并实现抽象方法
    """
    
    def __init__(
        self,
        max_connections: int = 5,
        connection_timeout: float = 30.0,
        idle_timeout: float = 300.0,
        max_retries: int = 3
    ):
        """
        初始化连接池
        
        Args:
            max_connections: 最大连接数
            connection_timeout: 连接超时时间（秒）
            idle_timeout: 空闲连接超时时间（秒）
            max_retries: 最大重试次数
        """
        self.max_connections = max_connections
        self.connection_timeout = connection_timeout
        self.idle_timeout = idle_timeout
        self.max_retries = max_retries
        
        # 连接池
        self.connections: Dict[str, ConnectionInfo] = {}
        self.lock = asyncio.Lock()
        
        # 等待队列：(task_id, future) 元组列表
        self.waiting_queue: list[Tuple[str, asyncio.Future]] = []
        
        # 统计信息
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        
        logger.info(f"初始化TTS连接池: max_connections={max_connections}, "
                   f"connection_timeout={connection_timeout}s, idle_timeout={idle_timeout}s")
    
    @abstractmethod
    async def create_connection(self) -> Any:
        """
        创建新的WebSocket连接（由子类实现）
        
        Returns:
            WebSocket连接对象
        """
        pass
    
    @abstractmethod
    async def send_request(
        self,
        websocket: Any,
        text: str,
        callback: Callable[[bytes], None],
        **kwargs
    ) -> bool:
        """
        发送TTS请求并处理响应（由子类实现）
        
        Args:
            websocket: WebSocket连接
            text: 要合成的文本
            callback: 音频数据回调函数
            **kwargs: 其他参数（如voice_type等）
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    async def close_connection(self, websocket: Any):
        """
        关闭WebSocket连接（由子类实现）
        
        Args:
            websocket: 要关闭的WebSocket连接
        """
        pass
    
    @abstractmethod
    async def ping_connection(self, websocket: Any) -> bool:
        """
        检查连接是否存活（由子类实现）
        
        Args:
            websocket: 要检查的WebSocket连接
            
        Returns:
            连接是否存活
        """
        pass
    
    async def get_connection(self, task_id: str) -> Optional[ConnectionInfo]:
        """
        从连接池获取一个可用连接
        
        Args:
            task_id: 任务ID
            
        Returns:
            连接信息，如果无法获取则返回None
        """
        async with self.lock:
            # 1. 清理过期的空闲连接
            await self._cleanup_idle_connections()
            
            # 2. 查找空闲连接（使用list()创建副本，避免迭代时修改字典）
            for conn_id, conn_info in list(self.connections.items()):
                if conn_info.state == ConnectionState.IDLE:
                    # 检查连接是否存活
                    if await self.ping_connection(conn_info.websocket):
                        conn_info.state = ConnectionState.BUSY
                        conn_info.last_used_at = time.time()
                        conn_info.current_task_id = task_id
                        logger.info(f"复用连接 {conn_id} 用于任务 {task_id}")
                        return conn_info
                    else:
                        # 连接已断开，移除
                        logger.warning(f"连接 {conn_id} 已断开，移除")
                        await self._remove_connection(conn_id)
            
            # 3. 如果没有空闲连接且未达到最大连接数，创建新连接
            if len(self.connections) < self.max_connections:
                return await self._create_new_connection(task_id)
            
            # 4. 连接池已满，加入等待队列
            logger.info(f"连接池已满({len(self.connections)}/{self.max_connections})，"
                       f"任务 {task_id} 加入等待队列（当前等待: {len(self.waiting_queue)}）")
            
            # 创建一个Future用于等待
            future: asyncio.Future[Optional[ConnectionInfo]] = asyncio.Future()
            self.waiting_queue.append((task_id, future))
        
        # 在锁外等待，设置超时
        try:
            # 等待最多connection_timeout秒
            conn_info = await asyncio.wait_for(future, timeout=self.connection_timeout)
            if conn_info:
                logger.info(f"任务 {task_id} 从等待队列获得连接")
            return conn_info
        except asyncio.TimeoutError:
            # 超时，从队列中移除
            async with self.lock:
                try:
                    self.waiting_queue.remove((task_id, future))
                    logger.warning(f"任务 {task_id} 等待连接超时，从队列移除")
                except ValueError:
                    pass  # 已经被处理了
            return None
    
    async def release_connection(self, connection_id: str, success: bool = True):
        """
        释放连接回连接池
        
        Args:
            connection_id: 连接ID
            success: 任务是否成功
        """
        async with self.lock:
            if connection_id not in self.connections:
                logger.warning(f"尝试释放不存在的连接: {connection_id}")
                return
            
            conn_info = self.connections[connection_id]
            
            if success:
                # 成功，将连接标记为空闲
                conn_info.state = ConnectionState.IDLE
                conn_info.current_task_id = None
                conn_info.error_count = 0
                logger.info(f"连接 {connection_id} 已释放，返回连接池")
                
                # 检查是否有等待的任务
                await self._notify_waiting_task(conn_info)
            else:
                # 失败，增加错误计数
                conn_info.error_count += 1
                if conn_info.error_count >= 5:  # 提高阈值，更宽容
                    # 错误次数过多，关闭连接
                    logger.warning(f"连接 {connection_id} 错误次数过多({conn_info.error_count})，关闭连接")
                    await self._remove_connection(connection_id)
                else:
                    # 标记为空闲，允许重试（更宽容的策略）
                    conn_info.state = ConnectionState.IDLE
                    conn_info.current_task_id = None
                    logger.warning(f"连接 {connection_id} 保持连接（错误: {conn_info.error_count}/5）")
                    
                    # 即使有错误，也尝试分配给等待任务
                    await self._notify_waiting_task(conn_info)
    
    async def synthesize_streaming(
        self,
        text: str,
        callback: Callable[[bytes], None],
        task_id: Optional[str] = None,
        **kwargs
    ) -> bool:
        """
        流式合成语音（统一接口）
        
        Args:
            text: 要合成的文本
            callback: 音频数据回调函数
            task_id: 任务ID（可选）
            **kwargs: 其他参数
            
        Returns:
            是否成功
        """
        if task_id is None:
            task_id = f"task_{int(time.time() * 1000)}"
        
        self.total_requests += 1
        
        # 获取连接
        conn_info = await self.get_connection(task_id)
        if conn_info is None:
            logger.error(f"任务 {task_id} 无法获取连接")
            self.failed_requests += 1
            return False
        
        try:
            # 发送请求
            success = await self.send_request(
                conn_info.websocket,
                text,
                callback,
                **kwargs
            )
            
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
            
            # 释放连接
            await self.release_connection(conn_info.connection_id, success)
            
            return success
            
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            self.failed_requests += 1
            await self.release_connection(conn_info.connection_id, False)
            return False
    
    async def _notify_waiting_task(self, conn_info: ConnectionInfo):
        """
        通知等待队列中的任务
        
        Args:
            conn_info: 可用的连接信息
        """
        if not self.waiting_queue:
            return
        
        # 取出队列第一个任务
        task_id, future = self.waiting_queue.pop(0)
        
        # 将连接分配给等待的任务
        conn_info.state = ConnectionState.BUSY
        conn_info.last_used_at = time.time()
        conn_info.current_task_id = task_id
        
        # 通过Future返回连接
        if not future.done():
            future.set_result(conn_info)
            logger.info(f"连接 {conn_info.connection_id} 已分配给等待任务 {task_id}")
    
    async def _create_new_connection(self, task_id: str) -> Optional[ConnectionInfo]:
        """
        创建新连接
        
        Args:
            task_id: 任务ID
            
        Returns:
            连接信息
        """
        connection_id = f"conn_{len(self.connections)}_{int(time.time() * 1000)}"
        
        try:
            logger.info(f"为任务 {task_id} 创建新连接: {connection_id}")
            websocket = await asyncio.wait_for(
                self.create_connection(),
                timeout=self.connection_timeout
            )
            
            conn_info = ConnectionInfo(
                connection_id=connection_id,
                websocket=websocket,
                state=ConnectionState.BUSY,
                created_at=time.time(),
                last_used_at=time.time(),
                current_task_id=task_id
            )
            
            self.connections[connection_id] = conn_info
            logger.info(f"连接 {connection_id} 创建成功")
            return conn_info
            
        except asyncio.TimeoutError:
            logger.error(f"创建连接超时: {connection_id}")
            return None
        except Exception as e:
            logger.error(f"创建连接失败: {e}")
            return None
    
    async def _remove_connection(self, connection_id: str):
        """
        移除连接
        
        Args:
            connection_id: 连接ID
        """
        if connection_id not in self.connections:
            return
        
        conn_info = self.connections[connection_id]
        
        try:
            await self.close_connection(conn_info.websocket)
        except Exception as e:
            logger.error(f"关闭连接 {connection_id} 失败: {e}")
        
        del self.connections[connection_id]
        logger.info(f"连接 {connection_id} 已移除")
    
    async def _cleanup_idle_connections(self):
        """清理过期的空闲连接"""
        current_time = time.time()
        to_remove = []
        
        for conn_id, conn_info in self.connections.items():
            if conn_info.state == ConnectionState.IDLE:
                idle_time = current_time - conn_info.last_used_at
                if idle_time > self.idle_timeout:
                    to_remove.append(conn_id)
        
        for conn_id in to_remove:
            logger.info(f"清理空闲连接: {conn_id}")
            await self._remove_connection(conn_id)
    
    async def close_all(self):
        """关闭所有连接"""
        async with self.lock:
            logger.info(f"关闭所有连接，共 {len(self.connections)} 个")
            for conn_id in list(self.connections.keys()):
                await self._remove_connection(conn_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "total_connections": len(self.connections),
            "idle_connections": sum(1 for c in self.connections.values() 
                                   if c.state == ConnectionState.IDLE),
            "busy_connections": sum(1 for c in self.connections.values() 
                                   if c.state == ConnectionState.BUSY),
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": (self.successful_requests / self.total_requests * 100 
                           if self.total_requests > 0 else 0)
        }

