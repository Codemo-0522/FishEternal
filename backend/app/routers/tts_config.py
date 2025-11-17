from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import logging

from ..models.user import User, get_current_active_user
from ..database import get_database
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tts-config",
    tags=["tts-config"]
)

class TtsProviderConfig(BaseModel):
    """TTS服务商配置"""
    id: str
    name: str
    config: Dict[str, str]  # 包含 appId, apiKey 等
    voice_settings: Dict[str, Any]  # 音色设置
    enabled: bool

class TtsConfigResponse(BaseModel):
    """TTS配置响应"""
    success: bool
    message: str
    config: Optional[TtsProviderConfig] = None

@router.get("/user")
async def get_all_user_tts_configs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户所有TTS配置"""
    try:
        # 从用户文档中获取所有TTS配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        result = {}
        if user_doc and user_doc.get("tts_configs"):
            result = user_doc["tts_configs"]
        
        return {
            "success": True,
            "message": "配置获取成功",
            "configs": result
        }
        
    except Exception as e:
        logger.error(f"获取用户所有TTS配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/user/{provider_id}")
async def save_user_tts_config(
    provider_id: str,
    config: TtsProviderConfig,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """保存用户特定TTS服务商的配置"""
    try:
        # 验证配置
        if not config.config.get("appId", "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="App ID不能为空"
            )
        
        # 根据provider_id验证必需字段
        if provider_id == "xfyun":
            if not config.config.get("apiKey", "").strip() or not config.config.get("apiSecret", "").strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="讯飞云需要提供apiKey和apiSecret"
                )
        elif provider_id == "bytedance":
            if not config.config.get("token", "").strip() or not config.config.get("cluster", "").strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="字节跳动需要提供token和cluster"
                )
        
        # 保存到用户文档的 tts_configs 字段中
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    f"tts_configs.{provider_id}": config.dict(),
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 保存了 {provider_id} 的TTS配置")
        
        return TtsConfigResponse(
            success=True,
            message="配置保存成功",
            config=config
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存用户TTS配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存配置失败"
        )

@router.post("/test/{provider_id}")
async def test_tts_config(
    provider_id: str,
    config: TtsProviderConfig,
    current_user: User = Depends(get_current_active_user)
):
    """测试TTS配置"""
    try:
        # 这里可以添加实际的测试逻辑
        # 例如调用TTS API测试是否能正常连接
        
        if provider_id == "xfyun":
            # 验证讯飞云配置
            if not config.config.get("appId") or not config.config.get("apiKey") or not config.config.get("apiSecret"):
                return {
                    "success": False,
                    "message": "配置不完整：缺少必需的认证信息"
                }
        elif provider_id == "bytedance":
            # 验证字节跳动配置
            if not config.config.get("appId") or not config.config.get("token") or not config.config.get("cluster"):
                return {
                    "success": False,
                    "message": "配置不完整：缺少必需的认证信息"
                }
        
        # 简单的验证通过，返回成功
        # TODO: 实际应该调用TTS API进行测试
        return {
            "success": True,
            "message": f"✅ {config.name} 配置验证通过\n\n配置信息：\n- App ID: {config.config.get('appId', '')[:8]}***\n- 音色: {config.voice_settings.get('voiceType', '未设置')}\n\n注意：这是基础验证，实际使用时会调用API进行完整测试。"
        }
        
    except Exception as e:
        logger.error(f"测试TTS配置失败: {str(e)}")
        return {
            "success": False,
            "message": f"测试失败: {str(e)}"
        }

@router.get("/default")
async def get_default_tts_provider(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取默认TTS服务商"""
    try:
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        default_tts = user_doc.get("default_tts_provider", "") if user_doc else ""
        
        return {
            "success": True,
            "provider_id": default_tts
        }
        
    except Exception as e:
        logger.error(f"获取默认TTS服务商失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取默认TTS服务商失败"
        )

@router.post("/default")
async def set_default_tts_provider(
    provider_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """设置默认TTS服务商"""
    try:
        # 验证provider_id是否有效
        if provider_id not in ["xfyun", "bytedance"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的TTS服务商ID"
            )
        
        # 更新默认TTS服务商
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    "default_tts_provider": provider_id,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 设置默认TTS服务商为 {provider_id}")
        
        return {
            "success": True,
            "message": "默认TTS服务商设置成功",
            "provider_id": provider_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认TTS服务商失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="设置默认TTS服务商失败"
        )

@router.get("/default/config")
async def get_default_tts_config(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户默认TTS服务商的完整配置（包括密钥和音色）"""
    try:
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        default_tts = user_doc.get("default_tts_provider", "")
        
        if not default_tts:
            return {
                "success": False,
                "message": "未设置默认TTS服务商",
                "provider_id": None,
                "config": None
            }
        
        # 获取该服务商的配置
        tts_configs = user_doc.get("tts_configs", {})
        provider_config = tts_configs.get(default_tts)
        
        if not provider_config:
            return {
                "success": False,
                "message": f"默认TTS服务商 {default_tts} 未配置",
                "provider_id": default_tts,
                "config": None
            }
        
        return {
            "success": True,
            "message": "获取配置成功",
            "provider_id": default_tts,
            "config": provider_config
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取默认TTS配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取默认TTS配置失败"
        )

