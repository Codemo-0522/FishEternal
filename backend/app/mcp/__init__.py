"""
FishEternal MCP 模块

提供 Model Context Protocol 工具集成
支持知识库检索、系统信息查询等功能
"""
from .base import BaseTool, ToolMetadata, ToolContext, ToolExecutionError
from .registry import ToolRegistry, registry
from .manager import MCPManager, mcp_manager
from .client import MCPClient, InProcessMCPClient

__all__ = [
    # 基础类
    "BaseTool",
    "ToolMetadata",
    "ToolContext",
    "ToolExecutionError",
    
    # 注册器
    "ToolRegistry",
    "registry",
    
    # 管理器
    "MCPManager",
    "mcp_manager",
    
    # 客户端
    "MCPClient",
    "InProcessMCPClient",
]

__version__ = "1.0.0"

