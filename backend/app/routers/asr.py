from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from motor.motor_asyncio import AsyncIOMotorClient
import logging
from typing import Optional

from ..models.user import User, get_current_active_user
from ..database import get_database
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/asr",
    tags=["asr"]
)

@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    语音识别接口
    接收音频文件，使用用户配置的默认 ASR 服务进行识别
    """
    logger.info(f"🎤 收到 ASR 转录请求 - 用户: {current_user.account}, 文件名: {audio.filename}")
    
    try:
        # 1. 获取用户默认的 ASR 提供商
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户信息不存在"
            )
        
        default_provider = user_doc.get("default_asr_provider")
        if not default_provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="未设置默认 ASR 服务商，请先在模型配置中设置"
            )
        
        # 2. 获取该提供商的配置
        asr_configs = user_doc.get("asr_configs", {})
        if default_provider not in asr_configs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ASR 服务商 {default_provider} 未配置"
            )
        
        provider_config = asr_configs[default_provider]
        
        # 检查是否启用
        if not provider_config.get("enabled"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ASR 服务商 {default_provider} 未启用"
            )
        
        # 3. 读取音频文件
        audio_data = await audio.read()
        
        if len(audio_data) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="音频文件为空"
            )
        
        # 4. 根据不同的提供商调用相应的 ASR 服务
        if default_provider == "siliconflow":
            from ..utils.asr.silicon_flow_asr import SiliconFlowASR
            
            asr_client = SiliconFlowASR(
                api_key=provider_config.get("api_key"),
                base_url=provider_config.get("base_url"),
                model_name=provider_config.get("default_model")
            )
            
            try:
                text = await asr_client.transcribe_from_bytes_async(
                    audio_data, 
                    audio.filename or "audio.wav"
                )
                
                # 🔍 调试日志：打印转录结果
                logger.info(f"==================== ASR 转录结果 ====================")
                logger.info(f"用户: {current_user.account}")
                logger.info(f"音频大小: {len(audio_data)} bytes")
                logger.info(f"提供商: {default_provider}")
                logger.info(f"模型: {provider_config.get('default_model')}")
                logger.info(f"转录文本: 「{text or ''}」")
                logger.info(f"文本长度: {len(text) if text else 0} 字符")
                logger.info(f"====================================================")
                
                return {
                    "success": True,
                    "text": text or "",
                    "provider": default_provider,
                    "model": provider_config.get("default_model")
                }
            except RuntimeError as e:
                logger.error(f"SiliconFlow ASR 识别失败: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"语音识别失败: {str(e)}"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的 ASR 提供商: {default_provider}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"语音识别失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"语音识别失败: {str(e)}"
        )

