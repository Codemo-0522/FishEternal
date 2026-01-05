"""
工具调用配置管理 API

提供全局工具调用配置的查询和修改接口
同时提供用户工具启用/禁用配置接口
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging
import json
from pathlib import Path
from datetime import datetime

from app.utils.llm.tool_config import tool_config, update_config, reset_config
from app.models.user import User, get_current_active_user
from app.database import user_tool_configs_collection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tool-config", tags=["工具配置"])

# 工具元数据配置文件路径
TOOLS_METADATA_PATH = Path(__file__).parent.parent / "mcp" / "tools" / "mcp_tools.json"


class ToolConfigUpdate(BaseModel):
    """工具配置更新请求"""
    max_iterations: Optional[int] = Field(None, ge=1, le=100, description="最大工具调用迭代次数 (1-100)")
    tool_execution_timeout: Optional[int] = Field(None, ge=1, description="单个工具执行超时（秒）")
    llm_call_timeout: Optional[int] = Field(None, ge=1, description="LLM调用超时（秒）")
    total_timeout: Optional[int] = Field(None, ge=1, description="总超时（秒）")
    max_concurrent_tools: Optional[int] = Field(None, ge=1, le=20, description="最大并发工具数 (1-20)")
    max_retries: Optional[int] = Field(None, ge=0, le=10, description="工具调用失败重试次数 (0-10)")
    retry_delay: Optional[float] = Field(None, ge=0, description="重试延迟（秒）")
    enable_tool_cache: Optional[bool] = Field(None, description="是否启用工具结果缓存")
    verbose_logging: Optional[bool] = Field(None, description="是否启用详细日志")
    force_reply_on_max_iterations: Optional[bool] = Field(None, description="达到最大迭代次数时是否强制返回")
    enable_tool_stats: Optional[bool] = Field(None, description="是否启用工具调用统计")
    max_tool_result_size: Optional[int] = Field(None, ge=1024, description="单次工具调用最大返回大小（字节）")
    allow_continue_on_error: Optional[bool] = Field(None, description="是否允许工具调用失败后继续")


class ToolConfigResponse(BaseModel):
    """工具配置响应"""
    max_iterations: int
    tool_execution_timeout: int
    llm_call_timeout: int
    total_timeout: int
    max_concurrent_tools: int
    max_retries: int
    retry_delay: float
    enable_tool_cache: bool
    verbose_logging: bool
    force_reply_on_max_iterations: bool
    enable_tool_stats: bool
    max_tool_result_size: int
    allow_continue_on_error: bool
    custom_config: Dict[str, Any]


@router.get("/", response_model=ToolConfigResponse)
async def get_tool_config():
    """
    获取当前工具调用全局配置
    
    Returns:
        当前配置的所有参数
    """
    try:
        config_dict = tool_config.to_dict()
        logger.info(f"📋 查询工具配置: {config_dict}")
        return config_dict
    except Exception as e:
        logger.error(f"获取工具配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.patch("/", response_model=ToolConfigResponse)
async def update_tool_config(config: ToolConfigUpdate):
    """
    更新工具调用全局配置
    
    Args:
        config: 要更新的配置项（只需提供要修改的字段）
        
    Returns:
        更新后的完整配置
    """
    try:
        # 只更新提供的字段
        update_dict = config.dict(exclude_unset=True)
        
        if not update_dict:
            raise HTTPException(status_code=400, detail="没有提供要更新的配置项")
        
        logger.info(f"🔧 更新工具配置: {update_dict}")
        update_config(**update_dict)
        
        # 返回更新后的配置
        updated_config = tool_config.to_dict()
        logger.info(f"✅ 工具配置更新成功: {updated_config}")
        
        return updated_config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新工具配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.post("/reset", response_model=ToolConfigResponse)
async def reset_tool_config():
    """
    重置工具调用配置为默认值
    
    Returns:
        重置后的配置
    """
    try:
        logger.info("🔄 重置工具配置为默认值")
        reset_config()
        
        reset_config_dict = tool_config.to_dict()
        logger.info(f"✅ 工具配置已重置: {reset_config_dict}")
        
        return reset_config_dict
    except Exception as e:
        logger.error(f"重置工具配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"重置配置失败: {str(e)}")


@router.get("/max-iterations")
async def get_max_iterations():
    """
    快捷接口：获取最大迭代次数
    
    Returns:
        {"max_iterations": int}
    """
    return {"max_iterations": tool_config.max_iterations}


class MaxIterationsUpdate(BaseModel):
    """最大迭代次数更新请求"""
    max_iterations: int = Field(..., ge=1, le=100, description="最大迭代次数 (1-100)")


@router.post("/max-iterations")
async def set_max_iterations(request: MaxIterationsUpdate):
    """
    快捷接口：设置最大迭代次数
    
    Args:
        request: 包含 max_iterations 的请求体
        
    Returns:
        {"max_iterations": int, "message": str}
    """
    try:
        logger.info(f"🔧 设置最大迭代次数: {request.max_iterations}")
        tool_config.max_iterations = request.max_iterations
        logger.info(f"✅ 最大迭代次数已设置为: {request.max_iterations}")
        
        return {
            "max_iterations": request.max_iterations,
            "message": f"最大迭代次数已设置为 {request.max_iterations}"
        }
    except Exception as e:
        logger.error(f"设置最大迭代次数失败: {e}")
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")


# ==================== 用户工具配置接口 ====================

class ToolInfo(BaseModel):
    """工具信息"""
    name: str
    description: str
    category: str = "其他"
    enabled: bool = True


class ToolConfigResponse(BaseModel):
    """工具配置响应"""
    available_tools: List[ToolInfo]
    enabled_tools: List[str]


class UpdateToolConfigRequest(BaseModel):
    """更新工具配置请求"""
    enabled_tools: List[str]


class UserToolConfig(BaseModel):
    """用户工具配置"""
    user_id: str
    enabled_tools: List[str]
    disabled_tools: List[str]
    updated_at: Optional[datetime] = None


@router.get("/tools-metadata")
async def get_tools_metadata():
    """
    获取所有工具的元数据（名称、中文名、描述）
    供前端动态显示使用
    """
    try:
        with open(TOOLS_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "success": True,
                "tools": data.get("tools", [])
            }
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="工具元数据配置文件不存在")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"工具元数据配置文件格式错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取工具元数据失败: {str(e)}")


@router.get("/available-tools", response_model=ToolConfigResponse)
async def get_available_tools_config(
    current_user: User = Depends(get_current_active_user)
):
    """
    获取可用工具列表及当前用户的配置
    直接从 JSON 配置文件读取，保证前后端一致
    """
    # 1. 从 JSON 配置文件读取所有工具
    try:
        with open(TOOLS_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            tools_from_json = data.get("tools", [])
    except Exception as e:
        logger.error(f"❌ 读取工具配置失败: {e}")
        raise HTTPException(status_code=500, detail="读取工具配置失败")
    
    # 2. 转换为ToolInfo列表
    available_tools = []
    for tool in tools_from_json:
        available_tools.append(
            ToolInfo(
                name=tool["name"],
                description=tool.get("description", ""),
                category=tool.get("category", "其他"),
                enabled=True  # 默认启用，后续会根据用户配置更新
            )
        )
    
    # 3. 获取用户当前配置
    user_config = await user_tool_configs_collection.find_one(
        {"user_id": current_user.id}
    )
    
    # 4. 确定启用的工具列表
    if user_config:
        # 从数据库获取用户配置的已启用工具
        stored_enabled_tools = user_config.get("enabled_tools", [])
        # 获取当前所有合法的工具名称
        all_tool_names = [tool["name"] for tool in tools_from_json]
        # 过滤掉已失效的工具，只保留当前仍然存在的工具
        enabled_tools = [tool for tool in stored_enabled_tools if tool in all_tool_names]
        
        # 如果过滤后启用的工具列表与存储的不同，说明有过时工具被清理，记录日志
        if len(enabled_tools) != len(stored_enabled_tools):
            removed_tools = [tool for tool in stored_enabled_tools if tool not in all_tool_names]
            logger.info(f"🧹 用户 {current_user.id} 的配置中包含 {len(removed_tools)} 个已失效的工具，已自动清理: {removed_tools}")
    else:
        # 如果用户没有配置，默认全部启用
        enabled_tools = [tool["name"] for tool in tools_from_json]
    
    # 5. 更新工具的启用状态
    for tool in available_tools:
        tool.enabled = tool.name in enabled_tools
    
    return ToolConfigResponse(
        available_tools=available_tools,
        enabled_tools=enabled_tools
    )


@router.post("/update")
async def update_user_tool_config(
    request: UpdateToolConfigRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    更新用户工具配置
    """
    # 1. 从 JSON 配置文件读取所有工具名称
    try:
        with open(TOOLS_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            all_tool_names = [tool["name"] for tool in data.get("tools", [])]
    except Exception as e:
        raise HTTPException(status_code=500, detail="读取工具配置失败")
    
    # 2. 验证工具名称是否有效
    invalid_tools = [
        tool for tool in request.enabled_tools 
        if tool not in all_tool_names
    ]
    
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=f"无效的工具名称: {', '.join(invalid_tools)}"
        )
    
    # 3. 计算禁用的工具列表
    all_tools = set(all_tool_names)
    enabled_set = set(request.enabled_tools)
    disabled_tools = list(all_tools - enabled_set)
    
    # 4. 更新或创建用户配置
    update_data = {
        "user_id": current_user.id,
        "enabled_tools": request.enabled_tools,
        "disabled_tools": disabled_tools,
        "updated_at": datetime.utcnow()
    }
    
    result = await user_tool_configs_collection.update_one(
        {"user_id": current_user.id},
        {"$set": update_data},
        upsert=True
    )
    
    return {
        "success": True,
        "message": "工具配置更新成功",
        "enabled_count": len(request.enabled_tools),
        "disabled_count": len(disabled_tools)
    }


@router.get("/my-config", response_model=UserToolConfig)
async def get_my_tool_config(
    current_user: User = Depends(get_current_active_user)
):
    """
    获取当前用户的工具配置
    """
    user_config = await user_tool_configs_collection.find_one(
        {"user_id": current_user.id}
    )
    
    if not user_config:
        # 如果没有配置，返回默认配置（全部启用）
        try:
            with open(TOOLS_METADATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                all_tool_names = [tool["name"] for tool in data.get("tools", [])]
        except Exception:
            all_tool_names = []
        
        return UserToolConfig(
            user_id=current_user.id,
            enabled_tools=all_tool_names,
            disabled_tools=[]
        )
    
    # 移除MongoDB的_id字段
    user_config.pop("_id", None)
    
    return UserToolConfig(**user_config)


@router.delete("/reset-user-config")
async def reset_user_tool_config(
    current_user: User = Depends(get_current_active_user)
):
    """
    重置用户工具配置（全部启用）
    """
    # 删除用户配置，这样会使用默认的全部启用
    result = await user_tool_configs_collection.delete_one(
        {"user_id": current_user.id}
    )
    
    return {
        "success": True,
        "message": "工具配置已重置为默认（全部启用）",
        "deleted_count": result.deleted_count
    }
