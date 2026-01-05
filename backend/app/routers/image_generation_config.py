from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional, Dict, List
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import logging
import httpx
import asyncio
import time
import base64
import base64
import base64
import base64

from ..models.user import User, get_current_active_user
from ..database import get_database
from ..config import settings
from ..utils.image_generation.modelscope import ModelScopeImageGenerationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/image-generation-config",
    tags=["image-generation-config"]
)

class CustomModel(BaseModel):
    id: str
    displayName: str
    supportsImage: bool

class ImageGenerationProviderConfig(BaseModel):
    """图片生成服务商配置"""
    id: str
    api_key: str
    enabled: bool
    default_model: str
    models: List[str] = []
    custom_models: Optional[List[CustomModel]] = None

@router.get("/user")
async def get_all_user_image_generation_configs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户所有图片生成配置"""
    try:
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        result = {}
        if user_doc and user_doc.get("image_generation_configs"):
            for provider_id, config_data in user_doc["image_generation_configs"].items():
                result[provider_id] = ImageGenerationProviderConfig(**config_data)
        
        return {
            "success": True,
            "message": "配置获取成功",
            "configs": result
        }
        
    except Exception as e:
        logger.error(f"获取用户所有图片生成配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/user/{provider_id}")
async def save_user_image_generation_provider_config(
    provider_id: str,
    config: ImageGenerationProviderConfig,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """保存用户特定图片生成服务商的配置"""
    try:
        if not config.api_key.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API Key 不能为空"
            )
        
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    f"image_generation_configs.{provider_id}": config.dict(),
                    "updated_at": datetime.utcnow().isoformat()
                }
            },
            upsert=True
        )
        
        logger.info(f"用户 {current_user.id} 保存了 {provider_id} 的图片生成配置")
        
        return {"success": True, "message": "配置保存成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存用户图片生成配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存配置失败"
        )

class TestImageGenerationPayload(BaseModel):
    config: ImageGenerationProviderConfig
    prompt: str

@router.post("/test/{provider_id}")
async def test_image_generation_provider_config(
    provider_id: str,
    payload: TestImageGenerationPayload,
    current_user: User = Depends(get_current_active_user)
):
    """测试图片生成服务商配置（完整流程）"""
    try:
        config = payload.config
        prompt = payload.prompt

        if not prompt.strip():
            raise HTTPException(status_code=400, detail="提示词不能为空")

        if provider_id == "modelscope":
            service = ModelScopeImageGenerationService(api_key=config.api_key)
            
            task_id = await service.submit_task(
                prompt=prompt,
                model=config.default_model
            )
            if not task_id:
                raise HTTPException(status_code=500, detail="任务提交失败，请检查API Key或模型名称是否正确")

            start_time = time.time()
            timeout = 180  # 3分钟超时
            while time.time() - start_time < timeout:
                result = await service.get_task_result(task_id)
                task_status = result.get("task_status")
                
                if task_status == "SUCCEED":
                    output_images = result.get("output_images")
                    image_url = None
                    if output_images and isinstance(output_images, list) and len(output_images) > 0:
                        image_url = output_images[0]

                    if image_url:
                        # 获取图片数据并转为Base64
                        async with httpx.AsyncClient() as client:
                            image_response = await client.get(image_url, timeout=60)
                            image_response.raise_for_status()
                            image_bytes = image_response.content
                            base64_image = base64.b64encode(image_bytes).decode('utf-8')
                            image_data_uri = f"data:image/png;base64,{base64_image}"
                        return {"success": True, "message": "图片生成成功", "image_data": image_data_uri}
                    else:
                        raise HTTPException(status_code=500, detail=f"任务成功但未找到图片URL。完整响应: {result}")
                
                elif task_status == "FAILED":
                    error_message = result.get("output", {}).get("message", "未知错误")
                    raise HTTPException(status_code=500, detail=f"任务失败: {error_message}")
                
                elif task_status in ["PENDING", "RUNNING", "PROCESSING"]:
                    await asyncio.sleep(5)  # 任务进行中，等待5秒
                else:
                    # 未知状态
                    raise HTTPException(status_code=500, detail=f"未知的任务状态: {task_status}。完整响应: {result}")
            
            raise HTTPException(status_code=408, detail="任务超时")

        else:
            raise HTTPException(status_code=400, detail=f"不支持的提供商: {provider_id}")

    except Exception as e:
        logger.error(f"图片生成测试失败: {str(e)}")
        detail = e.detail if isinstance(e, HTTPException) else str(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试失败: {detail}"
        )

@router.post("/default")
async def set_default_image_generation_provider(
    provider_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """设置默认图片生成服务商"""
    try:
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if not user_doc or not user_doc.get("image_generation_configs") or provider_id not in user_doc["image_generation_configs"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该服务商未配置，无法设置为默认"
            )
        
        provider_config = user_doc["image_generation_configs"][provider_id]
        if not provider_config.get("enabled"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该服务商未启用，无法设置为默认"
            )
        
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    "default_image_generation_provider": provider_id,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 设置默认图片生成提供商为 {provider_id}")
        
        return {
            "success": True,
            "message": "默认服务商设置成功",
            "provider_id": provider_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认图片生成提供商失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="设置失败"
        )

@router.get("/default")
async def get_default_image_generation_provider(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取默认图片生成服务商"""
    try:
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        default_provider = user_doc.get("default_image_generation_provider") if user_doc else None
        
        return {
            "success": True,
            "provider_id": default_provider
        }
        
    except Exception as e:
        logger.error(f"获取默认图片生成提供商失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取失败"
        )
