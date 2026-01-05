from app.config import settings
from .base import AsyncImageGenerationService
from .modelscope import ModelScopeImageGenerationService

_image_generation_service: AsyncImageGenerationService = None

def get_image_generation_service() -> AsyncImageGenerationService:
    """根据配置获取图片生成服务的单例"""
    global _image_generation_service
    if _image_generation_service is None:
        if settings.IMAGE_GENERATION_PROVIDER == "modelscope":
            _image_generation_service = ModelScopeImageGenerationService(
                api_key=settings.MODELSCOPE_API_KEY
            )
        else:
            raise ValueError(f"Unsupported image generation provider: {settings.IMAGE_GENERATION_PROVIDER}")
    return _image_generation_service

__all__ = ["get_image_generation_service", "AsyncImageGenerationService"]
