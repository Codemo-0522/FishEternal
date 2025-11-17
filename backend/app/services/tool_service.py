"""
工具服务
提供工具列表和配置管理功能
"""
from typing import Dict, List, Optional
import json
from pathlib import Path
from ..mcp.registry import registry
from ..mcp.base import ToolContext
import logging

logger = logging.getLogger(__name__)

# 工具元数据配置文件路径
TOOLS_METADATA_PATH = Path(__file__).parent.parent / "mcp" / "tools" / "mcp_tools.json"

# 工具分类缓存
_tools_category_cache: Optional[Dict[str, str]] = None


def _load_tools_category_map() -> Dict[str, str]:
    """
    从配置文件加载工具分类映射
    
    Returns:
        Dict[str, str]: 工具名 -> 分类名的映射
    """
    global _tools_category_cache
    
    if _tools_category_cache is not None:
        return _tools_category_cache
    
    try:
        with open(TOOLS_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 直接从 JSON 读取 category 字段，构建工具名到分类的映射
            category_map = {}
            for tool in data.get("tools", []):
                category_map[tool["name"]] = tool.get("category", "其他")
            
            _tools_category_cache = category_map
            logger.info(f"✅ 加载工具分类映射成功: {len(category_map)} 个工具")
            return category_map
    except Exception as e:
        logger.error(f"❌ 加载工具分类映射失败: {e}")
        return {}


async def get_available_tools(context: Optional[ToolContext] = None) -> Dict[str, Dict[str, str]]:
    """
    获取所有可用的MCP工具列表
    
    Args:
        context: 工具上下文（用于动态工具）
    
    Returns:
        Dict[str, Dict]: 工具字典，key为工具名称，value包含工具信息
        格式: {
            "tool_name": {
                "name": "tool_name",
                "description": "工具描述",
                "category": "分类"
            }
        }
    """
    tools_dict = {}
    
    # 加载工具分类映射
    category_map = _load_tools_category_map()
    
    # 获取所有工具的元数据
    metadata_list = registry.list_metadata(context)
    
    for metadata in metadata_list:
        if metadata:  # 过滤掉 None（动态工具在没有上下文时可能返回None）
            # 从配置文件获取分类，如果没有则使用默认
            category = category_map.get(metadata.name, "其他")
            
            tools_dict[metadata.name] = {
                "name": metadata.name,
                "description": metadata.description,
                "category": category,
            }
    
    return tools_dict


async def get_enabled_tools_for_user(user_id: str, context: Optional[ToolContext] = None) -> List[str]:
    """
    获取用户启用的工具列表
    
    Args:
        user_id: 用户ID
        context: 工具上下文
    
    Returns:
        List[str]: 启用的工具名称列表
    """
    from ..database import user_tool_configs_collection
    
    # 查询用户配置
    user_config = await user_tool_configs_collection.find_one({"user_id": user_id})
    
    if user_config and "enabled_tools" in user_config:
        return user_config["enabled_tools"]
    
    # 如果没有配置，返回所有工具（默认全部启用）
    all_tools = await get_available_tools(context)
    return list(all_tools.keys())


async def filter_tools_by_user_config(
    tools: List[Dict],
    user_id: str,
    context: Optional[ToolContext] = None
) -> List[Dict]:
    """
    根据用户配置过滤工具列表
    
    Args:
        tools: 工具列表（OpenAI format或MCP format）
        user_id: 用户ID
        context: 工具上下文
    
    Returns:
        List[Dict]: 过滤后的工具列表
    """
    # 获取用户启用的工具
    enabled_tools = await get_enabled_tools_for_user(user_id, context)
    
    # 过滤工具
    filtered_tools = [
        tool for tool in tools
        if tool.get("name") in enabled_tools or tool.get("function", {}).get("name") in enabled_tools
    ]
    
    return filtered_tools

