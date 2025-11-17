from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import logging
import httpx

from ..models.user import User, get_current_active_user
from ..database import get_database
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/embedding-config",
    tags=["embedding-config"]
)

class EmbeddingProviderConfig(BaseModel):
    """Embedding 服务商配置"""
    id: str
    name: str
    base_url: Optional[str] = ""
    api_key: Optional[str] = ""
    default_model: str
    enabled: bool
    models: List[str] = []

# 本地模型基础路径
LOCAL_EMBEDDING_BASE_PATH = "checkpoints/embeddings"

class EmbeddingConfigRequest(BaseModel):
    """Embedding 配置请求"""
    provider_id: str
    config: EmbeddingProviderConfig

class EmbeddingConfigResponse(BaseModel):
    """Embedding 配置响应"""
    success: bool
    message: str
    config: Optional[EmbeddingProviderConfig] = None

@router.get("/providers")
async def get_available_embedding_providers(
    current_user: User = Depends(get_current_active_user)
):
    """获取可用的 Embedding 服务商列表（已废弃，前端使用本地默认配置）"""
    # 这个接口已废弃，前端直接使用 defaultEmbeddingProviders
    # 保留接口是为了向后兼容
    return {"providers": []}

@router.get("/user/{provider_id}")
async def get_user_embedding_provider_config(
    provider_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户特定 Embedding 服务商的配置"""
    try:
        # 从用户文档中获取 embedding 配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if user_doc and user_doc.get("embedding_configs") and provider_id in user_doc["embedding_configs"]:
            return EmbeddingConfigResponse(
                success=True,
                message="配置获取成功",
                config=EmbeddingProviderConfig(**user_doc["embedding_configs"][provider_id])
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该服务商的配置"
            )
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户 Embedding 配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/user/{provider_id}")
async def save_user_embedding_provider_config(
    provider_id: str,
    config: EmbeddingProviderConfig,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """保存用户特定 Embedding 服务商的配置"""
    try:
        # 验证配置
        if provider_id == "ark":
            if not config.api_key.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="火山引擎需要 API Key"
                )
            if not config.base_url.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="火山引擎需要 API 地址"
                )
        elif provider_id == "ollama":
            if not config.base_url.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ollama 需要服务地址"
                )
        
        # 保存到用户文档的 embedding_configs 字段中
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    f"embedding_configs.{provider_id}": config.dict(),
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 保存了 {provider_id} 的 Embedding 配置")
        
        return EmbeddingConfigResponse(
            success=True,
            message="配置保存成功",
            config=config
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存用户 Embedding 配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存配置失败"
        )

@router.get("/user")
async def get_all_user_embedding_configs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户所有 Embedding 配置"""
    try:
        # 从用户文档中获取所有 embedding 配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        result = {}
        if user_doc and user_doc.get("embedding_configs"):
            for provider_id, config_data in user_doc["embedding_configs"].items():
                result[provider_id] = EmbeddingProviderConfig(**config_data)
        
        return {
            "success": True,
            "message": "配置获取成功",
            "configs": result
        }
        
    except Exception as e:
        logger.error(f"获取用户所有 Embedding 配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/test/{provider_id}")
async def test_embedding_provider_config(
    provider_id: str,
    config: EmbeddingProviderConfig,
    current_user: User = Depends(get_current_active_user)
):
    """测试 Embedding 服务商配置"""
    try:
        if provider_id == "ark":
            # 测试火山引擎 Embedding
            from ..utils.embedding.volcengine_embedding import ArkEmbeddings
            try:
                embeddings = ArkEmbeddings(
                    api_key=config.api_key,
                    model=config.default_model
                )
                # 测试嵌入一个简单文本
                test_result = embeddings.embed_query("测试")
                if test_result and len(test_result) > 0:
                    return {
                        "success": True,
                        "message": f"{config.name} 配置测试成功"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"{config.name} 配置测试失败: 返回结果为空"
                    }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"{config.name} 配置测试失败: {str(e)}"
                }
                
        elif provider_id == "ollama":
            # 测试 Ollama Embedding
            from ..utils.embedding.ollama_embedding import OllamaEmbeddings
            try:
                embeddings = OllamaEmbeddings(
                    model=config.default_model,
                    base_url=config.base_url
                )
                # 测试嵌入一个简单文本
                test_result = embeddings.embed_query("测试")
                if test_result and len(test_result) > 0:
                    return {
                        "success": True,
                        "message": f"{config.name} 配置测试成功"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"{config.name} 配置测试失败: 返回结果为空"
                    }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"{config.name} 配置测试失败: {str(e)}"
                }
                
        elif provider_id == "local":
            # 测试本地模型
            from ..utils.embedding.all_mini_embedding import MiniLMEmbeddings
            import os
            try:
                # 构建完整的模型路径
                model_path = os.path.join(LOCAL_EMBEDDING_BASE_PATH, config.default_model)
                
                if not os.path.exists(model_path):
                    return {
                        "success": False,
                        "message": f"{config.name} 配置测试失败: 模型路径不存在 ({model_path})"
                    }
                
                embeddings = MiniLMEmbeddings(
                    model_name_or_path=model_path,
                    max_length=512,
                    batch_size=8,
                    normalize=True
                )
                # 测试嵌入一个简单文本
                test_result = embeddings.embed_query("测试")
                if test_result and len(test_result) > 0:
                    return {
                        "success": True,
                        "message": f"{config.name} 配置测试成功（模型路径：{model_path}）"
                    }
                else:
                    return {
                        "success": False,
                        "message": f"{config.name} 配置测试失败: 返回结果为空"
                    }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"{config.name} 配置测试失败: {str(e)}"
                }
        else:
            return {
                "success": False,
                "message": f"不支持的 Embedding 提供商: {provider_id}"
            }
                    
    except Exception as e:
        logger.error(f"测试 Embedding 配置失败: {str(e)}")
        return {
            "success": False,
            "message": f"{config.name} 配置测试失败: {type(e).__name__} - {str(e)}"
        }

@router.post("/default")
async def set_default_embedding(
    provider_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: User = Depends(get_current_active_user)
):
    """设置默认 Embedding 模型"""
    try:
        users = db[settings.mongodb_db_name]["users"]
        
        # 更新用户文档，设置默认 embedding
        result = await users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    "default_embedding_provider": provider_id,
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        return {
            "success": True,
            "message": "默认 Embedding 模型设置成功",
            "provider_id": provider_id
        }
        
    except Exception as e:
        logger.error(f"设置默认 Embedding 模型失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="设置默认 Embedding 模型失败"
        )

@router.get("/default")
async def get_default_embedding(
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: User = Depends(get_current_active_user)
):
    """获取默认 Embedding 模型配置"""
    try:
        users = db[settings.mongodb_db_name]["users"]
        
        user_doc = await users.find_one({
            "account": current_user.account
        })
        
        if not user_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        # 获取默认 embedding 提供商ID
        default_provider_id = user_doc.get("default_embedding_provider")
        
        if not default_provider_id:
            return {
                "success": False,
                "message": "未设置默认 Embedding 模型"
            }
        
        # 获取该提供商的配置
        embedding_configs = user_doc.get("embedding_configs", {})
        default_config = embedding_configs.get(default_provider_id)
        
        if not default_config:
            return {
                "success": False,
                "message": "默认 Embedding 模型配置不存在"
            }
        
        # 检查该提供商是否已启用
        if not default_config.get("enabled", False):
            provider_name = default_config.get("name", default_provider_id)
            return {
                "success": False,
                "message": f"默认 Embedding 提供商 {provider_name} 已被禁用"
            }
        
        return {
            "success": True,
            "message": "获取默认 Embedding 模型成功",
            "provider_id": default_provider_id,
            "config": EmbeddingProviderConfig(**default_config)
        }
        
    except Exception as e:
        logger.error(f"获取默认 Embedding 模型失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取默认 Embedding 模型失败"
        )

