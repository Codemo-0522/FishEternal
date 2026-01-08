"""
MCP Server 核心

独立进程运行的 MCP 服务器，通过 stdio 与客户端通信
负责接收工具调用请求并执行
"""
import asyncio
import sys
import json
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from .registry import registry
from .base import ToolContext, ToolExecutionError

# 配置日志（输出到文件，避免干扰 stdio）
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/mcp_server.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)


class FishEternalMCPServer:
    """FishEternal MCP Server 包装器"""
    
    def __init__(self, server_name: str = "fisheternal-mcp"):
        self.app = Server(server_name)
        self.context_data = {}  # 存储上下文数据（由客户端传递）
        self._setup_handlers()
        logger.info(f"🚀 MCP Server '{server_name}' 已初始化")
    
    def _setup_handlers(self):
        """设置 MCP 协议处理器"""
        
        @self.app.list_tools()
        async def list_tools() -> list[types.Tool]:
            """返回所有可用工具"""
            tools = registry.to_mcp_tools()
            logger.info(f"📋 返回工具列表: {len(tools)} 个工具")
            return tools
        
        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            """执行工具调用"""
            logger.info(f"🔧 收到工具调用: {name}, 参数: {arguments}")
            
            # 获取工具
            tool = registry.get_tool(name)
            if not tool:
                error_msg = f"未找到工具: {name}"
                logger.error(f"❌ {error_msg}")
                return [types.TextContent(type="text", text=error_msg)]
            
            try:
                # 验证参数
                if not tool.validate_arguments(arguments):
                    error_msg = f"参数验证失败"
                    logger.error(f"❌ {error_msg}: {arguments}")
                    return [types.TextContent(type="text", text=error_msg)]
                
                # 构建执行上下文
                # 注意：这里的上下文数据应该由客户端在 arguments 中传递
                # 因为 MCP Server 是独立进程，无法直接访问 FastAPI 的数据库等资源
                context = ToolContext(
                    session_id=arguments.get("_session_id"),
                    user_id=arguments.get("_user_id"),
                    db=None,  # 独立进程模式下无法直接访问 DB
                    extra=self.context_data
                )
                
                # 执行工具
                result = await tool.execute(arguments, context)
                
                logger.info(f"✅ 工具执行成功: {name}")
                return [types.TextContent(type="text", text=result)]
            
            except ToolExecutionError as e:
                error_msg = str(e)
                logger.error(f"❌ {error_msg}")
                return [types.TextContent(type="text", text=error_msg)]
            
            except Exception as e:
                error_msg = f"工具执行异常: {str(e)}"
                logger.error(f"❌ {error_msg}", exc_info=True)
                return [types.TextContent(type="text", text=error_msg)]
    
    async def run(self):
        """运行 MCP Server（通过 stdio）"""
        logger.info("📡 MCP Server 开始监听 stdio...")
        async with stdio_server() as (read_stream, write_stream):
            await self.app.run(
                read_stream,
                write_stream,
                self.app.create_initialization_options()
            )


async def main():
    """主入口（用于独立进程启动）"""
    # 自动发现并注册工具
    from .tools import discover_and_register_tools
    discover_and_register_tools()
    
    logger.info(f"📦 已注册 {len(registry)} 个工具")
    
    # 启动服务器
    server = FishEternalMCPServer()
    await server.run()


if __name__ == "__main__":
    """
    独立进程模式启动方式：
    python -m backend.app.mcp.server
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 MCP Server 已停止")
    except Exception as e:
        logger.error(f"💥 MCP Server 崩溃: {e}", exc_info=True)
        sys.exit(1)

