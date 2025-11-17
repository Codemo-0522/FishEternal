"""
MCP 工具基类和类型定义
提供统一的工具接口，所有工具都应继承 BaseTool
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field
from mcp import types


class ToolMetadata(BaseModel):
    """工具元数据"""
    name: str = Field(..., description="工具名称，必须唯一")
    description: str = Field(..., description="工具描述，AI 会根据此描述决定是否调用")
    input_schema: Dict[str, Any] = Field(..., description="输入参数的 JSON Schema")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "search_knowledge",
                "description": "搜索知识库获取相关文档片段",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询"}
                    },
                    "required": ["query"]
                }
            }
        }


class ToolContext(BaseModel):
    """工具执行上下文
    包含工具执行所需的全局信息（数据库、会话等）
    """
    db: Optional[Any] = None  # MongoDB 客户端
    session_id: Optional[str] = None  # 当前会话 ID
    user_id: Optional[str] = None  # 当前用户 ID
    extra: Dict[str, Any] = Field(default_factory=dict)  # 额外的上下文数据
    
    class Config:
        arbitrary_types_allowed = True


class BaseTool(ABC):
    """
    工具基类
    
    所有 MCP 工具都应该继承此类并实现以下方法：
    - get_metadata(): 返回工具的元数据
    - execute(): 执行工具逻辑
    
    Example:
        ```python
        class MyTool(BaseTool):
            def get_metadata(self) -> ToolMetadata:
                return ToolMetadata(
                    name="my_tool",
                    description="我的工具",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "param": {"type": "string"}
                        }
                    }
                )
            
            async def execute(self, arguments: dict, context: ToolContext) -> str:
                return f"执行结果: {arguments['param']}"
        ```
    """
    
    @abstractmethod
    def get_metadata(self, context: Optional["ToolContext"] = None) -> Optional[ToolMetadata]:
        """
        返回工具的元数据
        
        Args:
            context: 可选的上下文信息，用于动态生成参数（例如根据 session_id 读取配置）
        
        Returns:
            Optional[ToolMetadata]: 工具元数据，如果工具在当前上下文中不可用（例如功能未启用），返回 None
        """
        pass
    
    @abstractmethod
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行工具逻辑
        
        Args:
            arguments: 工具参数（由 AI 传递）
            context: 执行上下文（包含数据库、会话信息等）
        
        Returns:
            str: 工具执行结果（文本格式，会返回给 AI）
        """
        pass
    
    def to_mcp_tool(self, context: Optional["ToolContext"] = None) -> types.Tool:
        """将工具转换为 MCP Tool 对象"""
        metadata = self.get_metadata(context)
        return types.Tool(
            name=metadata.name,
            description=metadata.description,
            inputSchema=metadata.input_schema
        )
    
    def validate_arguments(self, arguments: Dict[str, Any], context: Optional["ToolContext"] = None) -> bool:
        """
        验证参数是否符合 schema（可选，子类可以覆盖）
        
        Args:
            arguments: 需要验证的参数
            context: 可选的上下文信息
        
        Returns:
            bool: 是否有效
        """
        # 基础验证：检查必需参数
        metadata = self.get_metadata(context)
        schema = metadata.input_schema
        required = schema.get("required", [])
        
        for field in required:
            if field not in arguments:
                return False
        
        return True


class ToolExecutionError(Exception):
    """工具执行错误"""
    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        self.message = message
        super().__init__(f"工具 '{tool_name}' 执行失败: {message}")


__all__ = [
    "BaseTool",
    "ToolMetadata",
    "ToolContext",
    "ToolExecutionError"
]

