"""
模型能力数据模型
用于记录LLM模型支持的功能（如工具调用、视觉等）
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ModelCapability(BaseModel):
    """模型能力记录"""
    
    model_name: str = Field(..., description="模型标识符（如 gpt-4、deepseek-chat）")
    supports_tools: bool = Field(..., description="是否支持工具调用/函数调用")
    supports_vision: Optional[bool] = Field(None, description="是否支持视觉输入（可选扩展）")
    supports_json_mode: Optional[bool] = Field(None, description="是否支持JSON模式（可选扩展）")
    
    # 元数据
    first_seen: datetime = Field(default_factory=datetime.utcnow, description="首次发现时间")
    last_checked: datetime = Field(default_factory=datetime.utcnow, description="最后检查时间")
    check_count: int = Field(default=1, description="检查次数（统计用）")
    
    # 错误信息
    error_message: Optional[str] = Field(None, description="最后一次失败的错误信息")
    
    # 备注
    notes: Optional[str] = Field(None, description="人工备注")
    
    class Config:
        json_schema_extra = {
            "example": {
                "model_name": "gpt-3.5-turbo",
                "supports_tools": False,
                "first_seen": "2025-10-15T12:00:00",
                "last_checked": "2025-10-15T12:00:00",
                "check_count": 3,
                "error_message": "function call is not supported by this model",
                "notes": "官方确认不支持工具调用"
            }
        }

