"""
MCP Client 包装器

封装 MCP Client 的连接、调用逻辑
提供简洁的 API 供 FastAPI 应用使用
"""
import asyncio
import json
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession
from mcp.types import Tool

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP Client 包装器
    
    用于连接到 MCP Server 并调用工具
    支持两种模式：
    1. 独立进程模式：启动独立的 MCP Server 进程
    2. 进程内模式：直接在当前进程中执行工具（推荐用于生产环境）
    """
    
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.stdio = None
        self.is_connected = False
        self._tools_cache: List[Tool] = []
    
    async def connect_to_server(self, server_script: str):
        """
        连接到独立的 MCP Server 进程
        
        Args:
            server_script: MCP Server 脚本路径（如 "backend/app/mcp/server.py"）
        """
        if self.is_connected:
            logger.warning("⚠️ 已经连接到 MCP Server，跳过重复连接")
            return
        
        try:
            # 配置 Server 启动参数
            server_params = StdioServerParameters(
                command="python",
                args=["-m", "backend.app.mcp.server"],  # 使用模块方式启动
                env=None
            )
            
            logger.info("🔌 正在连接到 MCP Server...")
            
            # 建立 stdio 连接
            self.stdio = stdio_client(server_params)
            self.read_stream, self.write_stream = await self.stdio.__aenter__()
            
            # 创建会话
            self.session = ClientSession(self.read_stream, self.write_stream)
            await self.session.__aenter__()
            await self.session.initialize()
            
            self.is_connected = True
            logger.info("✅ 已连接到 MCP Server")
            
            # 缓存工具列表
            await self._refresh_tools_cache()
        
        except Exception as e:
            logger.error(f"❌ 连接 MCP Server 失败: {e}", exc_info=True)
            await self.close()
            raise
    
    async def _refresh_tools_cache(self):
        """刷新工具缓存"""
        if not self.is_connected or not self.session:
            return
        
        try:
            response = await self.session.list_tools()
            self._tools_cache = response.tools
            logger.info(f"📋 已缓存 {len(self._tools_cache)} 个工具")
        except Exception as e:
            logger.error(f"❌ 刷新工具列表失败: {e}")
    
    async def list_tools(self) -> List[Tool]:
        """
        获取可用工具列表
        
        Returns:
            List[Tool]: 工具列表
        """
        if not self.is_connected:
            logger.warning("⚠️ 未连接到 MCP Server，返回空工具列表")
            return []
        
        # 返回缓存的工具列表（避免频繁请求）
        if self._tools_cache:
            return self._tools_cache
        
        try:
            response = await self.session.list_tools()
            self._tools_cache = response.tools
            return self._tools_cache
        except Exception as e:
            logger.error(f"❌ 获取工具列表失败: {e}")
            return []
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """
        调用工具
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
        
        Returns:
            str | None: 工具执行结果，失败返回 None
        """
        if not self.is_connected or not self.session:
            logger.error("❌ 未连接到 MCP Server")
            return None
        
        try:
            logger.info(f"🔧 调用工具: {tool_name}")
            response = await self.session.call_tool(tool_name, arguments)
            
            if response.content:
                result = response.content[0].text
                logger.info(f"✅ 工具调用成功: {tool_name}")
                return result
            else:
                logger.warning(f"⚠️ 工具返回空内容: {tool_name}")
                return None
        
        except Exception as e:
            logger.error(f"❌ 调用工具失败: {tool_name}, 错误: {e}", exc_info=True)
            return None
    
    async def close(self):
        """关闭连接"""
        if not self.is_connected:
            return
        
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
            if self.stdio:
                await self.stdio.__aexit__(None, None, None)
            
            self.is_connected = False
            self._tools_cache.clear()
            logger.info("👋 已断开 MCP Server 连接")
        
        except Exception as e:
            logger.error(f"❌ 关闭连接时出错: {e}")
    
    def __repr__(self) -> str:
        status = "已连接" if self.is_connected else "未连接"
        return f"MCPClient(status={status}, tools={len(self._tools_cache)})"


class InProcessMCPClient:
    """
    进程内 MCP Client（推荐用于生产环境）
    
    不启动独立进程，直接在当前进程中执行工具
    优点：
    - 无需额外进程通信开销
    - 可以直接访问数据库等资源
    - 更容易调试和维护
    """
    
    def __init__(self, db=None):
        from .registry import registry
        self.registry = registry
        self.db = db  # 共享数据库连接
        logger.info("🚀 进程内 MCP Client 已初始化")
    
    async def connect(self):
        """进程内模式无需连接，直接返回"""
        # 自动发现并注册工具
        from .tools import discover_and_register_tools
        discover_and_register_tools()
        logger.info(f"✅ 已加载 {len(self.registry)} 个工具")
    
    async def list_tools(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        db_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取工具列表（OpenAI 格式）
        
        Args:
            session_id: 会话 ID，用于获取会话配置
            user_id: 用户 ID
            db_name: 数据库名称（可选，默认使用配置文件中的值）
        
        Returns:
            List[Dict]: OpenAI 格式的工具列表
        """
        from .base import ToolContext
        from ..config import settings
        
        # 使用配置文件中的数据库名称
        if db_name is None:
            db_name = settings.mongodb_db_name
        
        # 如果提供了 session_id，获取会话的 kb_settings
        kb_settings = None
        if session_id and self.db:
            try:
                session_data = await self.db[db_name].chat_sessions.find_one(
                    {"_id": session_id}
                )
                if session_data:
                    kb_settings = session_data.get("kb_settings")
                    logger.info(f"🔧 已加载会话 {session_id} 的 kb_settings: {kb_settings}")
                else:
                    logger.warning(f"⚠️ 未找到会话 {session_id} 的数据")
            except Exception as e:
                logger.warning(f"⚠️ 获取会话配置失败: {e}")
        
        # 构建上下文（用于动态生成工具参数）
        context = ToolContext(
            db=self.db,
            session_id=session_id,
            user_id=user_id,
            extra={
                "db_name": db_name,
                "kb_settings": kb_settings  # 将 kb_settings 放入 extra
            }
        ) if session_id else None
        
        tools = []
        for tool in self.registry.list_tools():
            metadata = tool.get_metadata(context)
            # 如果工具返回 None（不可用），跳过该工具
            if metadata is None:
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": metadata.name,
                    "description": metadata.description,
                    "parameters": metadata.input_schema
                }
            })
        
        # 🔐 根据用户配置过滤工具
        if user_id:
            try:
                from ..services.tool_service import filter_tools_by_user_config
                tools = await filter_tools_by_user_config(tools, user_id, context)
                logger.info(f"🔐 已根据用户 {user_id} 的配置过滤工具: {len(tools)} 个可用")
            except Exception as e:
                logger.warning(f"⚠️ 用户工具过滤失败，使用全部工具: {e}")
        
        logger.info(f"📋 已生成 {len(tools)} 个可用工具（过滤后）")
        return tools
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        db_name: Optional[str] = None
    ) -> str:
        """
        调用工具（进程内执行）
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            session_id: 会话 ID
            user_id: 用户 ID
            db_name: 数据库名称（可选，默认使用配置文件中的值）
        
        Returns:
            str: 工具执行结果
        """
        from .base import ToolContext, ToolExecutionError
        from ..config import settings
        
        # 使用配置文件中的数据库名称
        if db_name is None:
            db_name = settings.mongodb_db_name
        
        # 先获取会话的 kb_settings（用于动态工具查找）
        kb_settings = None
        if session_id and self.db:
            try:
                session_data = await self.db[db_name].chat_sessions.find_one(
                    {"_id": session_id}
                )
                if session_data:
                    kb_settings = session_data.get("kb_settings")
            except Exception as e:
                logger.warning(f"⚠️ 获取会话配置失败: {e}")
        
        # 构建上下文（用于动态工具查找和执行）
        context = ToolContext(
            db=self.db,
            session_id=session_id,
            user_id=user_id,
            extra={
                "db_name": db_name,
                "kb_settings": kb_settings
            }
        )
        
        # 查找工具（传递 context 以支持动态工具）
        tool = self.registry.get_tool(tool_name, context=context)
        if not tool:
            return json.dumps({"error": f"未找到工具: {tool_name}"}, ensure_ascii=False)
        
        try:
            logger.info(f"🔧 开始执行工具: {tool_name}")
            logger.info(f"   参数: {json.dumps(arguments, ensure_ascii=False)}")
            
            # 执行工具
            result = await tool.execute(arguments, context)
            logger.info(f"✅ 工具执行成功: {tool_name}")
            logger.info(f"   结果: {result}")
            return result
        
        except ToolExecutionError as e:
            logger.error(f"❌ 工具执行失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        
        except Exception as e:
            logger.error(f"❌ 工具执行异常: {e}", exc_info=True)
            return json.dumps({"error": f"工具执行异常: {str(e)}"}, ensure_ascii=False)
    
    async def close(self):
        """进程内模式无需关闭"""
        pass


__all__ = ["MCPClient", "InProcessMCPClient"]

