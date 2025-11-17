from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import logging
import httpx
import io

from ..models.user import User, get_current_active_user
from ..database import get_database
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/asr-config",
    tags=["asr-config"]
)

class AsrProviderConfig(BaseModel):
    """ASR 服务商配置"""
    id: str
    name: str
    base_url: str
    api_key: str
    default_model: str
    enabled: bool
    models: List[str] = []

class AsrConfigResponse(BaseModel):
    """ASR 配置响应"""
    success: bool
    message: str
    config: Optional[AsrProviderConfig] = None

@router.get("/providers")
async def get_available_asr_providers(
    current_user: User = Depends(get_current_active_user)
):
    """获取可用的 ASR 服务商列表"""
    # 这个接口已废弃，前端直接使用 defaultAsrProviders
    # 保留接口是为了向后兼容
    return {"providers": []}

@router.get("/user/{provider_id}")
async def get_user_asr_provider_config(
    provider_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户特定 ASR 服务商的配置"""
    try:
        # 从用户文档中获取 asr 配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if user_doc and user_doc.get("asr_configs") and provider_id in user_doc["asr_configs"]:
            return AsrConfigResponse(
                success=True,
                message="配置获取成功",
                config=AsrProviderConfig(**user_doc["asr_configs"][provider_id])
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该服务商的配置"
            )
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户 ASR 配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/user/{provider_id}")
async def save_user_asr_provider_config(
    provider_id: str,
    config: AsrProviderConfig,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """保存用户特定 ASR 服务商的配置"""
    try:
        # 验证配置
        if not config.api_key.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API Key 不能为空"
            )
        if not config.base_url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API 地址不能为空"
            )
        
        # 保存到用户文档的 asr_configs 字段中
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    f"asr_configs.{provider_id}": config.dict(),
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 保存了 {provider_id} 的 ASR 配置")
        
        return AsrConfigResponse(
            success=True,
            message="配置保存成功",
            config=config
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存用户 ASR 配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存配置失败"
        )

@router.get("/user")
async def get_all_user_asr_configs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户所有 ASR 配置"""
    try:
        # 从用户文档中获取所有 asr 配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        result = {}
        if user_doc and user_doc.get("asr_configs"):
            for provider_id, config_data in user_doc["asr_configs"].items():
                result[provider_id] = AsrProviderConfig(**config_data)
        
        return {
            "success": True,
            "message": "配置获取成功",
            "configs": result
        }
        
    except Exception as e:
        logger.error(f"获取用户所有 ASR 配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/test/{provider_id}")
async def test_asr_provider_config(
    provider_id: str,
    config: AsrProviderConfig,
    current_user: User = Depends(get_current_active_user)
):
    """测试 ASR 服务商配置"""
    try:
        # 生成一个测试音频（1秒的静音 wav 文件）
        import wave
        import struct
        
        # 创建一个内存中的 wav 文件
        audio_buffer = io.BytesIO()
        
        # WAV 文件参数
        sample_rate = 16000
        duration = 1  # 1秒
        num_samples = sample_rate * duration
        
        # 创建 WAV 文件
        with wave.open(audio_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # 单声道
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            
            # 写入静音数据
            for _ in range(num_samples):
                wav_file.writeframes(struct.pack('<h', 0))
        
        # 获取音频数据
        audio_buffer.seek(0)
        audio_data = audio_buffer.read()
        
        # 根据不同的提供商构建请求
        if provider_id == "siliconflow":
            # 使用 SiliconFlowASR 类（与 TTS 模式保持一致）
            from ..utils.asr.silicon_flow_asr import SiliconFlowASR
            
            # 每次测试都实例化新的客户端
            asr_client = SiliconFlowASR(
                api_key=config.api_key,
                base_url=config.base_url,
                model_name=config.default_model
            )
            
            try:
                # 使用异步方法从字节数据识别
                text = await asr_client.transcribe_from_bytes_async(audio_data, "test.wav")
                return {
                    "success": True,
                    "message": f"连接测试成功！\n模型: {config.default_model}\n状态: 正常\n响应: {text if text else '无文本输出（静音测试音频）'}"
                }
            except RuntimeError as e:
                return {
                    "success": False,
                    "message": f"连接测试失败\n错误信息: {str(e)}"
                }
        else:
            return {
                "success": False,
                "message": f"不支持的 ASR 提供商: {provider_id}"
            }
            
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "连接超时，请检查网络连接和 API 地址是否正确"
        }
    except httpx.ConnectError:
        return {
            "success": False,
            "message": "无法连接到服务器，请检查 API 地址是否正确"
        }
    except Exception as e:
        logger.error(f"测试 ASR 配置失败: {str(e)}")
        return {
            "success": False,
            "message": f"测试失败: {str(e)}"
        }

@router.post("/default")
async def set_default_asr_provider(
    provider_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """设置默认 ASR 服务商"""
    try:
        # 检查该提供商是否已配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if not user_doc or not user_doc.get("asr_configs") or provider_id not in user_doc["asr_configs"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该服务商未配置，无法设置为默认"
            )
        
        # 检查是否启用
        provider_config = user_doc["asr_configs"][provider_id]
        if not provider_config.get("enabled"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该服务商未启用，无法设置为默认"
            )
        
        # 更新默认提供商
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    "default_asr_provider": provider_id,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 设置默认 ASR 提供商为 {provider_id}")
        
        return {
            "success": True,
            "message": "默认服务商设置成功",
            "provider_id": provider_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认 ASR 提供商失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="设置失败"
        )

@router.get("/default")
async def get_default_asr_provider(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取默认 ASR 服务商"""
    try:
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        default_provider = user_doc.get("default_asr_provider") if user_doc else None
        
        return {
            "success": True,
            "provider_id": default_provider
        }
        
    except Exception as e:
        logger.error(f"获取默认 ASR 提供商失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取失败"
        )

