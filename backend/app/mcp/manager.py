"""
MCP 生命周期管理器

负责 MCP Client 的启动、关闭、健康检查
提供单例访问点供 FastAPI 应用使用
"""
import asyncio
import logging
from typing import Optional
from .client import InProcessMCPClient

logger = logging.getLogger(__name__)


class MCPManager:
    """
    MCP 管理器（单例）
    
    负责管理 MCP Client 的生命周期
    推荐使用进程内模式（InProcessMCPClient）
    """
    
    _instance: Optional['MCPManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.client: Optional[InProcessMCPClient] = None
        self._db = None
        self._initialized = True
        logger.info("🎯 MCP Manager 已创建")
    
    async def initialize(self, db=None, use_in_process: bool = True):
        """
        初始化 MCP Client
        
        Args:
            db: 数据库连接（MongoDB 客户端）
            use_in_process: 是否使用进程内模式（推荐 True）
        """
        if self.client is not None:
            logger.warning("⚠️ MCP Client 已初始化，跳过重复初始化")
            return
        
        self._db = db
        
        try:
            if use_in_process:
                # 进程内模式（推荐）
                logger.info("🚀 使用进程内 MCP Client")
                self.client = InProcessMCPClient(db=db)
                await self.client.connect()
            else:
                # 独立进程模式（备用）
                from .client import MCPClient
                logger.info("🚀 使用独立进程 MCP Client")
                self.client = MCPClient()
                await self.client.connect_to_server("backend/app/mcp/server.py")
            
            # 验证工具加载
            tools = await self.client.list_tools()
            logger.info(f"✅ MCP Client 已启动，加载了 {len(tools)} 个工具")
            
            # 打印工具列表
            for tool in tools:
                if hasattr(tool, 'name'):
                    # 独立进程模式返回 Tool 对象
                    logger.info(f"  📦 {tool.name}: {tool.description}")
                elif isinstance(tool, dict):
                    # 进程内模式返回字典
                    logger.info(f"  📦 {tool['function']['name']}: {tool['function']['description']}")
        
        except Exception as e:
            logger.error(f"❌ MCP Client 初始化失败: {e}", exc_info=True)
            self.client = None
            raise
    
    async def shutdown(self):
        """关闭 MCP Client"""
        if self.client is None:
            return
        
        try:
            await self.client.close()
            self.client = None
            logger.info("👋 MCP Client 已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭 MCP Client 时出错: {e}")
    
    def get_client(self) -> Optional[InProcessMCPClient]:
        """
        获取 MCP Client 实例
        
        Returns:
            InProcessMCPClient | None: MCP 客户端实例
        """
        return self.client
    
    def is_ready(self) -> bool:
        """检查 MCP Client 是否就绪"""
        return self.client is not None
    
    async def health_check(self) -> dict:
        """
        健康检查
        
        Returns:
            dict: 健康状态信息
        """
        if not self.is_ready():
            return {
                "status": "unhealthy",
                "message": "MCP Client 未初始化",
                "tools": 0
            }
        
        try:
            tools = await self.client.list_tools()
            return {
                "status": "healthy",
                "message": "MCP Client 运行正常",
                "tools": len(tools)
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": f"健康检查失败: {str(e)}",
                "tools": 0
            }


# 全局单例
mcp_manager = MCPManager()


__all__ = ["MCPManager", "mcp_manager"]

