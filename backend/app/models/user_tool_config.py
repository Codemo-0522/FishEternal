"""
用户工具配置模型
用于存储每个用户自定义的MCP工具开关状态
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class UserToolConfig(BaseModel):
    """用户工具配置"""
    user_id: str = Field(..., description="用户ID")
    enabled_tools: List[str] = Field(default_factory=list, description="启用的工具名称列表")
    disabled_tools: List[str] = Field(default_factory=list, description="禁用的工具名称列表")
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="更新时间")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "68e3f064e309231253729e1c",
                "enabled_tools": ["get_user_info", "schedule_moment"],
                "disabled_tools": ["like_moment", "cancel_moment"],
                "updated_at": "2024-10-16T10:00:00Z"
            }
        }
    }


class ToolInfo(BaseModel):
    """工具信息（用于前端展示）"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    category: Optional[str] = Field(None, description="工具分类")
    enabled: bool = Field(True, description="是否启用")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "get_user_info",
                "description": "获取当前用户的个人信息",
                "category": "用户信息",
                "enabled": True
            }
        }
    }


class UpdateToolConfigRequest(BaseModel):
    """更新工具配置请求"""
    enabled_tools: List[str] = Field(..., description="启用的工具名称列表")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "enabled_tools": ["get_user_info", "schedule_moment", "get_my_moments"]
            }
        }
    }


class ToolConfigResponse(BaseModel):
    """工具配置响应"""
    available_tools: List[ToolInfo] = Field(..., description="可用工具列表")
    enabled_tools: List[str] = Field(..., description="当前启用的工具")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "available_tools": [
                    {
                        "name": "get_user_info",
                        "description": "获取用户信息",
                        "category": "用户信息",
                        "enabled": True
                    }
                ],
                "enabled_tools": ["get_user_info", "schedule_moment"]
            }
        }
    }

