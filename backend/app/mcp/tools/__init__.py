"""
MCP 工具模块

此模块会自动发现和导入所有工具
每个工具都应该是一个独立的 .py 文件，并实现 BaseTool 接口

自动发现规则：
1. 忽略以 _ 开头的文件
2. 自动导入并实例化工具类
3. 注册到全局 registry
"""
import os
import importlib
import inspect
from pathlib import Path
from typing import List
from ..base import BaseTool
from ..registry import registry
import logging

logger = logging.getLogger(__name__)


def discover_and_register_tools() -> List[BaseTool]:
    """
    自动发现并注册 tools/ 目录下的所有工具
    
    Returns:
        List[BaseTool]: 已注册的工具列表
    """
    tools_dir = Path(__file__).parent
    registered_tools = []
    
    # 遍历 tools/ 目录下的所有 .py 文件
    for file_path in tools_dir.glob("*.py"):
        # 忽略 __init__.py 和私有文件
        if file_path.name.startswith("_"):
            continue
        
        module_name = file_path.stem
        
        try:
            # 动态导入模块
            module = importlib.import_module(f".{module_name}", package=__package__)
            
            # 查找模块中所有继承自 BaseTool 的类
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # 确保是 BaseTool 的子类且不是 BaseTool 本身
                if issubclass(obj, BaseTool) and obj is not BaseTool:
                    # 实例化工具
                    tool_instance = obj()
                    
                    # 注册到全局 registry
                    registry.register(tool_instance)
                    registered_tools.append(tool_instance)
                    
                    # 获取元数据（可能返回 None，用于动态工具）
                    metadata = tool_instance.get_metadata()
                    tool_name = metadata.name if metadata else obj.__name__
                    logger.info(f"📦 已从 {module_name}.py 加载工具: {tool_name}")
        
        except Exception as e:
            logger.error(f"❌ 加载工具模块 {module_name} 失败: {e}")
    
    return registered_tools


# 模块导入时自动发现并注册工具
_auto_registered_tools = discover_and_register_tools()

logger.info(f"🚀 MCP 工具加载完成，共注册 {len(_auto_registered_tools)} 个工具")


__all__ = ["discover_and_register_tools"]

