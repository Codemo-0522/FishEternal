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
from bson import ObjectId

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
        self.server_params: Optional[StdioServerParameters] = None

    async def connect(self, server_script_path: str):
        """
        连接到 MCP Server

        Args:
            server_script_path: MCP Server 脚本路径
        """
        script_path = Path(server_script_path)
        if not script_path.exists():
            raise FileNotFoundError(f"MCP Server script not found: {server_script_path}")

        self.server_params = StdioServerParameters(
            command="python",
            args=[str(script_path)],
            env=None
        )

        # 使用 stdio_client 上下文管理器
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                self.session = session
                await session.initialize()

    async def list_tools(self) -> List[Tool]:
        """
        获取可用工具列表

        Returns:
            List[Tool]: 工具列表
        """
        if not self.session:
            raise RuntimeError("MCP Client not connected")

        response = await self.session.list_tools()
        return response.tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        调用工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            Any: 工具返回结果
        """
        if not self.session:
            raise RuntimeError("MCP Client not connected")

        result = await self.session.call_tool(tool_name, arguments=arguments)
        return result

    async def close(self):
        """关闭连接"""
        if self.session:
            # Session will be closed by context manager
            self.session = None


class InProcessMCPClient:
    """
    进程内 MCP Client

    直接在当前进程中执行工具，无需启动独立的 Server 进程
    适合生产环境使用，性能更好
    """

    def __init__(self, db=None):
        """
        初始化进程内客户端

        Args:
            db: 数据库连接（可选，用于需要数据库访问的工具）
        """
        from .registry import registry
        self.registry = registry
        self.db = db
        logger.info("✅ 进程内 MCP Client 已初始化")

    async def connect(self):
        """进程内模式无需连接，提供此方法仅为兼容管理器接口"""
        pass

    def set_db(self, db):
        """设置���据库连接"""
        self.db = db
        logger.info("✅ 数据库连接已设置到 MCP Client")

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

        # 🎨 获取用户的图片生成配置（用于 generate_image 工具）
        image_generation_configs = None
        default_image_provider = None
        if user_id and self.db:
            try:
                # 将字符串ID转换为ObjectId
                user_object_id = ObjectId(user_id)
                logger.info(f"🔍 开始查询用户图片生成配置: user_id={user_id} (ObjectId: {user_object_id}), db_name={db_name}")

                user_data = await self.db[db_name].users.find_one(
                    {"_id": user_object_id}
                )
                logger.info(f"🔍 查询结果: user_data存在={user_data is not None}")

                if user_data:
                    # 获取所有图片生成配置
                    all_configs = user_data.get("image_generation_configs", {})
                    logger.info(f"🔍 原始配置数量: {len(all_configs)}, 配置keys: {list(all_configs.keys())}")

                    # 只保留已启用的配置
                    image_generation_configs = {
                        provider_id: config
                        for provider_id, config in all_configs.items()
                        if config.get("enabled", False)
                    }
                    logger.info(f"🔍 启用的配置数量: {len(image_generation_configs)}")

                    # 获取默认服务商
                    default_image_provider = user_data.get("default_image_generation_provider")
                    logger.info(f"🔍 默认服务商: {default_image_provider}")

                    if image_generation_configs:
                        logger.info(f"🎨 已加载用户 {user_id} 的图片生成配置: {len(image_generation_configs)} 个服务商")
                    else:
                        logger.info(f"🎨 用户 {user_id} 未配置任何图片生成服务")
                else:
                    logger.warning(f"⚠️ 未找到用户数据: user_id={user_id}")
            except Exception as e:
                logger.warning(f"⚠️ 获取用户图片生成配置失败: {e}", exc_info=True)

        # 构建上下文（用于动态生成工具参数）
        context = ToolContext(
            db=self.db,
            session_id=session_id,
            user_id=user_id,
            extra={
                "db_name": db_name,
                "kb_settings": kb_settings,  # 将 kb_settings 放入 extra
                "image_generation_configs": image_generation_configs,  # 图片生成配置
                "default_image_provider": default_image_provider  # 默认服务商
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
                logger.warning(f"⚠️ ���取会话配置失败: {e}")

        # 🎨 获取用户的图片生成配置（用于 generate_image 工具）
        image_generation_configs = None
        default_image_provider = None
        if user_id and self.db:
            try:
                from bson import ObjectId
                user_object_id = ObjectId(user_id)
                user_data = await self.db[db_name].users.find_one(
                    {"_id": user_object_id}
                )
                if user_data:
                    all_configs = user_data.get("image_generation_configs", {})
                    image_generation_configs = {
                        provider_id: config
                        for provider_id, config in all_configs.items()
                        if config.get("enabled", False)
                    }
                    default_image_provider = user_data.get("default_image_generation_provider")
                    logger.info(f"🎨 [call_tool] 已加载用户图片生成配置: {len(image_generation_configs)} 个服务商")
            except Exception as e:
                logger.warning(f"⚠️ [call_tool] 获取用户图片生成配置失败: {e}")

        # 构建上下文（用于动态工具查找和执行）
        context = ToolContext(
            db=self.db,
            session_id=session_id,
            user_id=user_id,
            extra={
                "db_name": db_name,
                "kb_settings": kb_settings,
                "image_generation_configs": image_generation_configs,
                "default_image_provider": default_image_provider
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
