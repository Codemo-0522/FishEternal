"""
工具注册管理器
负责工具的注册、查找、列举
"""
from typing import Dict, List, Optional
from .base import BaseTool, ToolMetadata, ToolExecutionError
from mcp import types
import logging

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册中心
    
    单例模式，全局唯一的工具注册表
    所有工具必须先注册才能被 MCP Server 使用
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
        return cls._instance
    
    def register(self, tool: BaseTool) -> None:
        """
        注册一个工具
        
        Args:
            tool: 工具实例
        
        Raises:
            ValueError: 如果工具名称已存在
        
        Note:
            对于动态工具（get_metadata() 可能返回 None），会使用类名作为 key
        """
        metadata = tool.get_metadata()
        
        # 对于动态工具（如知识库工具），启动时 get_metadata() 可能返回 None
        # 使用类名作为 registry key，实际使用时再根据 context 获取真实名称
        if metadata is None:
            tool_name = tool.__class__.__name__
            self._tools[tool_name] = tool
            logger.info(f"✅ 已注册动态工具: {tool_name}（工具名称将在运行时确定）")
            return
        
        tool_name = metadata.name
        
        if tool_name in self._tools:
            logger.warning(f"工具 '{tool_name}' 已存在，将被覆盖")
        
        self._tools[tool_name] = tool
        logger.info(f"✅ 已注册工具: {tool_name} - {metadata.description}")
    
    def register_multiple(self, tools: List[BaseTool]) -> None:
        """批量注册工具"""
        for tool in tools:
            self.register(tool)
    
    def unregister(self, tool_name: str) -> None:
        """取消注册工具"""
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info(f"已取消注册工具: {tool_name}")
    
    def get_tool(self, tool_name: str, context=None) -> Optional[BaseTool]:
        """
        根据名称获取工具
        
        Args:
            tool_name: 工具名称
            context: 可选的上下文（用于动态工具）
        
        Returns:
            BaseTool | None: 工具实例，如果不存在则返回 None
        """
        # 1. 先尝试直接查找（用于静态工具）
        if tool_name in self._tools:
            return self._tools.get(tool_name)
        
        # 2. 对于动态工具（如知识库工具），需要遍历所有工具并检查元数据
        for tool in self._tools.values():
            metadata = tool.get_metadata(context)
            if metadata and metadata.name == tool_name:
                return tool
        
        return None
    
    def list_tools(self) -> List[BaseTool]:
        """获取所有已注册的工具"""
        return list(self._tools.values())
    
    def list_metadata(self, context=None) -> List[ToolMetadata]:
        """获取所有工具的元数据"""
        return [tool.get_metadata(context) for tool in self._tools.values()]
    
    def to_mcp_tools(self, context=None) -> List[types.Tool]:
        """将所有工具转换为 MCP Tool 对象列表"""
        return [tool.to_mcp_tool(context) for tool in self._tools.values()]
    
    def clear(self) -> None:
        """清空所有工具（主要用于测试）"""
        self._tools.clear()
        logger.info("已清空所有工具")
    
    def __len__(self) -> int:
        """返回已注册工具的数量"""
        return len(self._tools)
    
    def __contains__(self, tool_name: str) -> bool:
        """检查工具是否已注册"""
        return tool_name in self._tools
    
    def __repr__(self) -> str:
        tool_names = list(self._tools.keys())
        return f"ToolRegistry({len(tool_names)} tools: {tool_names})"


# 全局单例
registry = ToolRegistry()


__all__ = ["ToolRegistry", "registry"]

