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
    prefix="/model-config",
    tags=["model-config"]
)

class CustomModel(BaseModel):
    """自定义模型配置"""
    id: str
    displayName: str
    supportsImage: bool = False

class ModelProviderConfig(BaseModel):
    """模型服务商配置"""
    id: str
    name: str
    base_url: str
    api_key: str
    default_model: str
    enabled: bool
    models: List[str] = []
    custom_models: Optional[List[CustomModel]] = None
    features: Dict[str, Any] = {}

class ModelConfigRequest(BaseModel):
    """模型配置请求"""
    provider_id: str
    config: ModelProviderConfig

class ModelConfigResponse(BaseModel):
    """模型配置响应"""
    success: bool
    message: str
    config: Optional[ModelProviderConfig] = None

@router.get("/providers")
async def get_available_providers(
    current_user: User = Depends(get_current_active_user)
):
    """获取可用的模型服务商列表"""
    providers = [
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "logo": "/static/logo/deepseek.png",
            "description": "深度求索AI，提供强大的推理能力",
            "base_url": settings.deepseek_base_url,
            "api_key": settings.deepseek_api_key,
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-coder"],
            "features": {
                "supports_image": False,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 4096
            }
        },
        {
            "id": "doubao",
            "name": "豆包",
            "logo": "/static/logo/doubao.png",
            "description": "字节跳动豆包大模型",
            "base_url": settings.doubao_base_url,
            "api_key": settings.doubao_api_key,
            "default_model": "ep-20241220123456-abcde",
            "models": ["ep-20241220123456-abcde", "doubao-pro-4k", "doubao-pro-32k"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 32768
            }
        },
        {
            "id": "bailian",
            "name": "通义千问",
            "logo": "/static/logo/bailian.png",
            "description": "阿里云百炼平台 - 通义千问大模型",
            "base_url": settings.bailian_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": settings.bailian_api_key,
            "default_model": "qwen-plus",
            "models": ["qwen-plus"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 8192
            }
        },
        {
            "id": "zhipu",
            "name": "智谱清言",
            "logo": "/static/logo/zhipu.png",
            "description": "智谱AI - GLM大模型",
            "base_url": settings.zhipu_base_url or "https://open.bigmodel.cn/api/paas/v4/",
            "api_key": settings.zhipu_api_key,
            "default_model": "glm-4-plus",
            "models": ["glm-4-plus"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 8192
            }
        },
        {
            "id": "hunyuan",
            "name": "腾讯混元",
            "logo": "/static/logo/hunyuan.png",
            "description": "腾讯混元大模型",
            "base_url": settings.hunyuan_base_url or "https://api.hunyuan.cloud.tencent.com/v1",
            "api_key": settings.hunyuan_api_key,
            "default_model": "hunyuan-turbos-latest",
            "models": ["hunyuan-turbos-latest"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 8192
            }
        },
        {
            "id": "moonshot",
            "name": "月之暗面",
            "logo": "/static/logo/moonshot.png",
            "description": "Moonshot AI - Kimi大模型",
            "base_url": settings.moonshot_base_url or "https://api.moonshot.cn/v1",
            "api_key": settings.moonshot_api_key,
            "default_model": "kimi-k2-0905-preview",
            "models": ["kimi-k2-0905-preview"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 8192
            }
        },
        {
            "id": "stepfun",
            "name": "阶跃星辰",
            "logo": "/static/logo/stepfun.png",
            "description": "StepFun - Step大模型",
            "base_url": settings.stepfun_base_url or "https://api.stepfun.com/v1",
            "api_key": settings.stepfun_api_key,
            "default_model": "step-1-8k",
            "models": ["step-1-8k"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": True,
                "max_tokens": 8192
            }
        },
        {
            "id": "ollama",
            "name": "Ollama",
            "logo": "/static/logo/ollama.png",
            "description": "本地部署的开源大模型",
            "base_url": "http://localhost:11434",
            "api_key": "ollama",
            "default_model": "llama3.2",
            "models": ["llama3.2", "qwen2.5", "gemma2", "codellama"],
            "features": {
                "supports_image": True,
                "supports_stream": True,
                "supports_function": False,
                "max_tokens": 8192
            }
        },
        {
            "id": "local",
            "name": "本地模型",
            "logo": "/static/logo/localmodel.png",
            "description": "本地部署的其他模型服务",
            "base_url": "http://localhost:8000",
            "api_key": "",
            "default_model": "local-model",
            "models": ["local-model", "custom-model"],
            "features": {
                "supports_image": False,
                "supports_stream": True,
                "supports_function": False,
                "max_tokens": 2048
            }
        }
    ]
    
    return {"providers": providers}

@router.get("/user/{provider_id}")
async def get_user_provider_config(
    provider_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户特定服务商的配置"""
    try:
        # 从用户文档中获取模型配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        if user_doc and user_doc.get("model_configs") and provider_id in user_doc["model_configs"]:
            return ModelConfigResponse(
                success=True,
                message="配置获取成功",
                config=ModelProviderConfig(**user_doc["model_configs"][provider_id])
            )
        else:
            # 返回默认配置
            default_configs = {
                "deepseek": {
                    "id": "deepseek",
                    "name": "DeepSeek",
                    "base_url": settings.deepseek_base_url,
                    "api_key": settings.deepseek_api_key,
                    "default_model": "deepseek-chat",
                    "enabled": bool(settings.deepseek_base_url and settings.deepseek_api_key),
                    "models": ["deepseek-chat", "deepseek-coder"],
                    "features": {
                        "supports_image": False,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 4096
                    }
                },
                "doubao": {
                    "id": "doubao",
                    "name": "豆包",
                    "base_url": settings.doubao_base_url,
                    "api_key": settings.doubao_api_key,
                    "default_model": "ep-20241220123456-abcde",
                    "enabled": bool(settings.doubao_base_url and settings.doubao_api_key),
                    "models": ["ep-20241220123456-abcde", "doubao-pro-4k", "doubao-pro-32k"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 32768
                    }
                },
                "bailian": {
                    "id": "bailian",
                    "name": "通义千问",
                    "base_url": settings.bailian_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": settings.bailian_api_key,
                    "default_model": "qwen-plus",
                    "enabled": bool(settings.bailian_base_url and settings.bailian_api_key),
                    "models": ["qwen-plus"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 8192
                    }
                },
                "zhipu": {
                    "id": "zhipu",
                    "name": "智谱清言",
                    "base_url": settings.zhipu_base_url or "https://open.bigmodel.cn/api/paas/v4/",
                    "api_key": settings.zhipu_api_key,
                    "default_model": "glm-4-plus",
                    "enabled": bool(settings.zhipu_base_url and settings.zhipu_api_key),
                    "models": ["glm-4-plus"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 8192
                    }
                },
                "hunyuan": {
                    "id": "hunyuan",
                    "name": "腾讯混元",
                    "base_url": settings.hunyuan_base_url or "https://api.hunyuan.cloud.tencent.com/v1",
                    "api_key": settings.hunyuan_api_key,
                    "default_model": "hunyuan-turbos-latest",
                    "enabled": bool(settings.hunyuan_base_url and settings.hunyuan_api_key),
                    "models": ["hunyuan-turbos-latest"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 8192
                    }
                },
                "moonshot": {
                    "id": "moonshot",
                    "name": "月之暗面",
                    "base_url": settings.moonshot_base_url or "https://api.moonshot.cn/v1",
                    "api_key": settings.moonshot_api_key,
                    "default_model": "kimi-k2-0905-preview",
                    "enabled": bool(settings.moonshot_base_url and settings.moonshot_api_key),
                    "models": ["kimi-k2-0905-preview"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 8192
                    }
                },
                "stepfun": {
                    "id": "stepfun",
                    "name": "阶跃星辰",
                    "base_url": settings.stepfun_base_url or "https://api.stepfun.com/v1",
                    "api_key": settings.stepfun_api_key,
                    "default_model": "step-1-8k",
                    "enabled": bool(settings.stepfun_base_url and settings.stepfun_api_key),
                    "models": ["step-1-8k"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": True,
                        "max_tokens": 8192
                    }
                },
                "ollama": {
                    "id": "ollama",
                    "name": "Ollama",
                    "base_url": "http://localhost:11434",
                    "api_key": "ollama",
                    "default_model": "llama3.2",
                    "enabled": False,
                    "models": ["llama3.2", "qwen2.5", "gemma2", "codellama"],
                    "features": {
                        "supports_image": True,
                        "supports_stream": True,
                        "supports_function": False,
                        "max_tokens": 8192
                    }
                },
                "local": {
                    "id": "local",
                    "name": "本地模型",
                    "base_url": "http://localhost:8000",
                    "api_key": "",
                    "default_model": "local-model",
                    "enabled": False,
                    "models": ["local-model", "custom-model"],
                    "features": {
                        "supports_image": False,
                        "supports_stream": True,
                        "supports_function": False,
                        "max_tokens": 2048
                    }
                }
            }
            
            default_config = default_configs.get(provider_id)
            if default_config:
                return ModelConfigResponse(
                    success=True,
                    message="使用默认配置",
                    config=ModelProviderConfig(**default_config)
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="不支持的模型服务商"
                )
                
    except Exception as e:
        logger.error(f"获取用户配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/user/{provider_id}")
async def save_user_provider_config(
    provider_id: str,
    config: ModelProviderConfig,
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """保存用户特定服务商的配置"""
    try:
        # 验证配置
        if not config.base_url.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="服务地址不能为空"
            )
        
        if not config.api_key.strip() and provider_id != "ollama":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API密钥不能为空"
            )
        
        # 保存到用户文档的 model_configs 字段中
        from datetime import datetime
        
        await db[settings.mongodb_db_name].users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    f"model_configs.{provider_id}": config.dict(),
                    "updated_at": datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"用户 {current_user.id} 保存了 {provider_id} 的配置")
        
        return ModelConfigResponse(
            success=True,
            message="配置保存成功",
            config=config
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存用户配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存配置失败"
        )

@router.get("")
async def get_all_user_configs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户所有模型配置 - 主端点"""
    try:
        # 从用户文档中获取所有模型配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        # 返回 model_configs 字段以保持与前端的兼容性
        model_configs = user_doc.get("model_configs", {}) if user_doc else {}
        
        return {
            "model_configs": model_configs
        }
        
    except Exception as e:
        logger.error(f"获取用户所有配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.get("/user")
async def get_all_user_configs_detailed(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取用户所有模型配置 - 详细格式"""
    try:
        # 从用户文档中获取所有模型配置
        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "account": current_user.account
        })
        
        result = {}
        if user_doc and user_doc.get("model_configs"):
            for provider_id, config_data in user_doc["model_configs"].items():
                result[provider_id] = ModelProviderConfig(**config_data)
        
        return {
            "success": True,
            "message": "配置获取成功",
            "configs": result
        }
        
    except Exception as e:
        logger.error(f"获取用户所有配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置失败"
        )

@router.post("/test/{provider_id}")
async def test_provider_config(
    provider_id: str,
    config: ModelProviderConfig,
    current_user: User = Depends(get_current_active_user)
):
    """测试模型服务商配置"""
    try:
        if provider_id == "ollama":
            # Ollama特殊处理
            from ..routers.chat import test_ollama_config
            result = await test_ollama_config(
                config.base_url,
                config.default_model,
                current_user
            )
            return result
        else:
            # 其他服务商测试
            headers = {
                "Content-Type": "application/json"
            }
            
            if config.api_key and config.api_key != "ollama":
                headers["Authorization"] = f"Bearer {config.api_key}"
            
            test_data = {
                "model": config.default_model,
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1
            }
            
            test_url = config.base_url
            if provider_id == "deepseek":
                test_url += "/v1/models"
                method = "GET"
                test_data = None
            elif provider_id in ["bailian", "zhipu", "hunyuan", "moonshot", "stepfun", "siliconflow"]:
                # 标准 OpenAI 兼容接口
                test_url += "/chat/completions"
                method = "POST"
            else:
                test_url += "/chat/completions"
                method = "POST"
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                if method == "GET":
                    response = await client.get(test_url, headers=headers)
                else:
                    response = await client.post(test_url, headers=headers, json=test_data)
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": f"{config.name}配置测试成功"
                    }
                else:
                    # 尝试解析错误响应体
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('error', {}).get('message', error_data.get('message', str(error_data)))
                    except:
                        error_msg = response.text or f"HTTP {response.status_code}"
                    
                    return {
                        "success": False,
                        "message": f"{config.name} 配置测试失败: Error code: {response.status_code} - {error_msg}"
                    }
                    
    except httpx.ConnectError as e:
        logger.error(f"测试配置失败 - 连接错误: {str(e)}")
        return {
            "success": False,
            "message": f"{config.name} 配置测试失败: 无法连接到服务器，请检查 API 地址是否正确。详细信息: {str(e)}"
        }
    except httpx.TimeoutException as e:
        logger.error(f"测试配置失败 - 超时: {str(e)}")
        return {
            "success": False,
            "message": f"{config.name} 配置测试失败: 连接超时，请检查网络连接和服务器状态。详细信息: {str(e)}"
        }
    except Exception as e:
        logger.error(f"测试配置失败: {str(e)}")
        return {
            "success": False,
            "message": f"{config.name} 配置测试失败: {type(e).__name__} - {str(e)}"
        }

@router.post("/default")
async def set_default_model(
    provider_id: str,
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: User = Depends(get_current_active_user)
):
    """设置默认模型"""
    try:
        users = db[settings.mongodb_db_name]["users"]
        
        # 更新用户文档，设置默认模型
        result = await users.update_one(
            {"account": current_user.account},
            {
                "$set": {
                    "default_model_provider": provider_id,
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
            "message": "默认模型设置成功",
            "provider_id": provider_id
        }
        
    except Exception as e:
        logger.error(f"设置默认模型失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="设置默认模型失败"
        )

@router.get("/default")
async def get_default_model(
    db: AsyncIOMotorClient = Depends(get_database),
    current_user: User = Depends(get_current_active_user)
):
    """获取默认模型配置"""
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
        
        # 获取默认模型提供商ID
        default_provider_id = user_doc.get("default_model_provider")
        
        if not default_provider_id:
            return {
                "success": False,
                "message": "未设置默认模型"
            }
        
        # 获取该提供商的配置
        model_configs = user_doc.get("model_configs", {})
        default_config = model_configs.get(default_provider_id)
        
        if not default_config:
            return {
                "success": False,
                "message": "默认模型配置不存在"
            }
        
        # 检查该提供商是否已启用
        if not default_config.get("enabled", False):
            # 获取提供商名称
            provider_name = default_config.get("name", default_provider_id)
            return {
                "success": False,
                "message": f"默认模型提供商 {provider_name} 已被禁用，请在模型配置页面重新设置默认模型"
            }
        
        return {
            "success": True,
            "message": "获取默认模型成功",
            "provider_id": default_provider_id,
            "config": ModelProviderConfig(**default_config)
        }
        
    except Exception as e:
        logger.error(f"获取默认模型失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取默认模型失败"
        )
