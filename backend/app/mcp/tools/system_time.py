"""
系统时间工具

提供获取当前系统时间的功能（带时区）
这是一个简单的示例工具，展示如何实现 MCP 工具
"""
from datetime import datetime
import time
from typing import Dict, Any, Optional
from ..base import BaseTool, ToolMetadata, ToolContext


class SystemTimeTool(BaseTool):
    """获取当前系统时间（带时区）"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """
        获取工具元数据
        
        Args:
            context: 上下文（此工具不需要上下文）
        """
        return ToolMetadata(
            name="get_current_time",
            description="使用该工具可以获取当前系统时间",
            input_schema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "时间格式（可选），默认为 'YYYY-MM-DD HH:MM:SS'",
                        "enum": ["datetime", "date", "time", "timestamp"]
                    }
                }
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行时间获取
        
        Args:
            arguments: {"format": "datetime" | "date" | "time" | "timestamp"}
            context: 执行上下文（此工具不需要上下文）
        
        Returns:
            str: 格式化的时间字符串
        """
        now = datetime.now()
        fmt = arguments.get("format", "datetime")
        
        # 获取时区信息
        if time.daylight:
            offset = time.altzone
        else:
            offset = time.timezone
        offset_hours = -offset // 3600
        timezone_str = f"UTC{offset_hours:+d}"
        
        if fmt == "date":
            return now.strftime("%Y-%m-%d")
        elif fmt == "time":
            return now.strftime("%H:%M:%S")
        elif fmt == "timestamp":
            return str(int(now.timestamp()))
        else:  # datetime
            time_str = now.strftime("%Y-%m-%d %H:%M:%S")
            return f"{time_str} ({timezone_str})"

