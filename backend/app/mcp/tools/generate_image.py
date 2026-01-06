"""
图片生成MCP工具
支持调用用户配置的图片生成服务，自动下载并上传到MinIO
"""

import logging
import httpx
import asyncio
import time
import json
import base64
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from bson import ObjectId

from ..base import BaseTool, ToolMetadata, ToolContext, ToolExecutionError
from ...config import settings
from ...utils.minio_client import minio_client
from ...utils.image_generation.modelscope import ModelScopeImageGenerationService

logger = logging.getLogger(__name__)


async def get_user_image_generation_providers(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    """
    获取用户已配置并启用的图片生成服务商

    Returns:
        Dict[provider_id, provider_config]
        例如: {
            "modelscope": {
                "id": "modelscope",
                "api_key": "xxx",
                "enabled": True,
                "default_model": "wanx-v1",
                "models": ["wanx-v1", "wanx-sketch-to-image-v1"]
            }
        }
    """
    try:
        # 查询用户文档 - 转换 user_id 为 ObjectId
        logger.info(f"🔍 [get_user_image_generation_providers] 开始查询: user_id={user_id}, type={type(user_id)}")
        user_object_id = ObjectId(user_id)
        logger.info(f"🔍 [get_user_image_generation_providers] 转换后 ObjectId: {user_object_id}")

        user_doc = await db[settings.mongodb_db_name].users.find_one({
            "_id": user_object_id
        })
        logger.info(f"🔍 [get_user_image_generation_providers] 查询结果: user_doc存在={user_doc is not None}")

        if not user_doc or not user_doc.get("image_generation_configs"):
            logger.warning(f"⚠️ [get_user_image_generation_providers] 用户无配置: user_doc存在={user_doc is not None}, has_configs={user_doc.get('image_generation_configs') if user_doc else None}")
            return {}

        # 只返回启用的服务商
        configs = user_doc.get("image_generation_configs", {})
        logger.info(f"🔍 [get_user_image_generation_providers] 原始配置: {list(configs.keys())}")

        enabled_configs = {
            provider_id: config
            for provider_id, config in configs.items()
            if config.get("enabled", False)
        }
        logger.info(f"✅ [get_user_image_generation_providers] 启用的配置: {list(enabled_configs.keys())}")

        return enabled_configs

    except Exception as e:
        logger.error(f"❌ [get_user_image_generation_providers] 获取用户图片生成配置失败: {str(e)}", exc_info=True)
        return {}


async def download_image(image_url: str, timeout: int = 600) -> bytes:
    """
    从URL下载图片

    Args:
        image_url: 图片URL
        timeout: 超时时间（秒）

    Returns:
        图片二进制数据
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=timeout)
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.error(f"下载图片失败: {image_url}, 错误: {str(e)}")
        raise ToolExecutionError(f"下载图片失败: {str(e)}")


async def upload_generated_image_to_minio(
    image_bytes: bytes,
    session_id: str,
    user_id: str,
    image_index: int = 0
) -> str:
    """
    上传生成的图片到MinIO

    Args:
        image_bytes: 图片二进制数据
        session_id: 会话ID
        user_id: 用户ID
        image_index: 图片索引（如果生成多张）

    Returns:
        MinIO URL (minio://{bucket}/{path})
    """
    try:
        # 转换为base64编码
        base64_image = base64.b64encode(image_bytes).decode('utf-8')

        # 使用message_id标识这是AI生成的图片
        message_id = f"ai_generated_image_{image_index}"

        # 上传到MinIO（路径: users/{user_id}/{session_id}/ai_generated_image_{index}/{file_id}.jpg）
        minio_url = minio_client.upload_image(
            image_base64=base64_image,
            session_id=session_id,
            message_id=message_id,
            user_id=user_id
        )

        return minio_url

    except Exception as e:
        logger.error(f"上传图片到MinIO失败: {str(e)}")
        raise ToolExecutionError(f"上传图片到MinIO失败: {str(e)}")


class GenerateImageTool(BaseTool):
    """
    图片生成工具

    支持调用用户配置的图片生成服务商（如ModelScope），
    自动下载生成的图片并上传到MinIO，
    返回MinIO链接供后续使用
    """

    def get_metadata(self, context: Optional[ToolContext] = None) -> Optional[ToolMetadata]:
        """
        动态生成工具元数据

        从 context.extra 中读取用户的图片生成配置,并将可用的服务商和模型列表
        注入到工具描述中,让模型知道用户有哪些选项可用。

        如果用户没有配置任何图片生成服务,返回 None (工具不显示)。
        """
        # 从 context.extra 中获取图片生成配置
        image_configs = None
        default_provider = None

        if context and context.extra:
            image_configs = context.extra.get("image_generation_configs")
            default_provider = context.extra.get("default_image_provider")

        # 如果用户没有配置任何图片生成服务,不显示此工具
        if not image_configs:
            logger.info("🚫 图片生成工具不可用 - 用户未配置任何服务商")
            return None

        # 构建可用服务商和模型的描述
        providers_info = []
        for provider_id, config in image_configs.items():
            provider_name = provider_id
            default_model = config.get("default_model", "未设置")
            models = config.get("models", [])

            if models:
                models_str = ", ".join(models)
            else:
                models_str = default_model

            is_default = " (默认)" if provider_id == default_provider else ""
            providers_info.append(f"  - {provider_name}{is_default}: 模型 [{models_str}]")

        providers_desc = "\n".join(providers_info)

        # 构建使用示例（动态生成）
        example_provider = list(image_configs.keys())[0] if image_configs else "your_provider"
        example_model = ""
        if image_configs and example_provider in image_configs:
            models = image_configs[example_provider].get("models", [])
            example_model = models[0] if models else image_configs[example_provider].get("default_model", "your_model")

        # 构建完整描述
        description_parts = [
            "【图片生成工具】根据文字描述生成AI图片。",
            "\n\n🎨 您当前已配置的图片生成服务：",
            f"\n{providers_desc}",
            "\n\n📝 参数说明：",
            "\n- **prompt** (必填): 正向提示词,描述想要生成的内容",
            "\n- **provider** (可选): 指定服务商,留空使用默认",
            "\n- **model** (可选): 指定模型,留空使用服务商默认模型",
            "\n- **negative_prompt** (可选): 反向提示词,描述不想出现的内容",
            "\n- **size** (可选): 图片尺寸,如 '1024*1024'",
            "\n- **n** (可选): 生成数量,默认1",
            "\n- **steps** (可选): 生成步数,影响质量,默认50",
            "\n\n✨ 使用示例：",
            "\n1. 使用默认配置: generate_image(prompt='一只可爱的猫咪')",
            f"\n2. 指定模型: generate_image(prompt='...', model='{example_model}')",
            f"\n3. 指定服务商: generate_image(prompt='...', provider='{example_provider}')"
        ]

        # provider参数的描述(包含可用选项)
        provider_options = list(image_configs.keys())
        provider_desc = f"图片生成服务商ID。可选值: {', '.join(provider_options)}。留空使用默认服务商"
        if default_provider:
            provider_desc += f" ({default_provider})"
        provider_desc += "。"

        # model参数的描述(包含所有可用模型)
        all_models = []
        for config in image_configs.values():
            models = config.get("models", [])
            all_models.extend(models)

        if all_models:
            model_desc = f"模型名称。可选值: {', '.join(all_models)}。留空使用服务商的默认模型。不同模型适用于不同场景,请根据需求选择。"
        else:
            model_desc = "模型名称。留空使用服务商的默认模型。"

        return ToolMetadata(
            name="generate_image",
            description="".join(description_parts),
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "正向提示词,描述想要生成的图片内容。建议使用详细、具体的描述,包含主体、风格、细节等。",
                    },
                    "provider": {
                        "type": "string",
                        "description": provider_desc,
                    },
                    "model": {
                        "type": "string",
                        "description": model_desc,
                    },
                    "negative_prompt": {
                        "type": "string",
                        "description": "反向提示词,描述不想在图片中出现的内容,如'模糊、低质量、变形'等。",
                    },
                    "size": {
                        "type": "string",
                        "description": "图片尺寸,格式为 '宽*高',常用: '1024*1024'(正方形)、'1024*768'(横版)、'768*1024'(竖版)。默认 '1024*1024'。",
                        "default": "1024*1024"
                    },
                    "n": {
                        "type": "integer",
                        "description": "生成图片的数量。默认 1,范围 1-4。生成多张可用于对比选择。",
                        "default": 1,
                        "minimum": 1,
                        "maximum": 4
                    },
                    "steps": {
                        "type": "integer",
                        "description": "生成步数,影响图片质量和细节。默认 50,范围 20-100。步数越高质量越好但耗时越长。",
                        "default": 50,
                        "minimum": 20,
                        "maximum": 100
                    },
                    "seed": {
                        "type": "integer",
                        "description": "随机种子,用于复现相同的生成结果。相同的seed和prompt会生成相同的图片。",
                    }
                },
                "required": ["prompt"]
            }
        )

    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行图片生成

        流程:
        1. 获取用户的图片生成配置
        2. 提交图片生成任务
        3. 轮询任务状态直到完成
        4. 下载生成的图片
        5. 上传到MinIO
        6. 保存MinIO链接到消息记录
        7. 返回结果
        """
        try:
            db = context.db
            user_id = context.user_id
            session_id = context.session_id

            # 1. 获取用户配置
            user_providers = await get_user_image_generation_providers(db, user_id)

            if not user_providers:
                return json.dumps({
                    "success": False,
                    "error": "您还没有配置任何图片生成服务。请先在模型配置页面配置图片生成服务商。"
                }, ensure_ascii=False)

            # 2. 确定使用的服务商
            provider_id = arguments.get("provider", "").strip()

            # 如果没有指定provider，使用用户的默认服务商
            if not provider_id:
                user_object_id = ObjectId(user_id)
                user_doc = await db[settings.mongodb_db_name].users.find_one({"_id": user_object_id})
                provider_id = user_doc.get("default_image_generation_provider") if user_doc else None

                # 如果没有设置默认，使用第一个启用的服务商
                if not provider_id:
                    provider_id = list(user_providers.keys())[0]

            # 验证服务商是否已配置
            if provider_id not in user_providers:
                available_providers = ", ".join(user_providers.keys())
                return json.dumps({
                    "success": False,
                    "error": f"服务商 '{provider_id}' 未配置或未启用。可用的服务商: {available_providers}"
                }, ensure_ascii=False)

            provider_config = user_providers[provider_id]

            # 3. 确定使用的模型
            model = arguments.get("model", "").strip()
            if not model:
                model = provider_config.get("default_model")

            if not model:
                return json.dumps({
                    "success": False,
                    "error": f"服务商 '{provider_id}' 没有配置默认模型，请指定 model 参数。"
                }, ensure_ascii=False)

            # 4. 获取生成参数
            prompt = arguments.get("prompt", "").strip()
            if not prompt:
                return json.dumps({
                    "success": False,
                    "error": "必须提供 prompt 参数（正向提示词）。"
                }, ensure_ascii=False)

            negative_prompt = arguments.get("negative_prompt", "").strip() or None
            size = arguments.get("size", "1024*1024")
            n = arguments.get("n", 1)
            steps = arguments.get("steps", 50)
            seed = arguments.get("seed")

            logger.info(
                f"开始生成图片: provider={provider_id}, model={model}, "
                f"prompt={prompt[:50]}..., size={size}, n={n}"
            )

            # 5. 调用对应的图片生成服务
            if provider_id == "modelscope":
                service = ModelScopeImageGenerationService(
                    api_key=provider_config["api_key"]
                )

                # 提交任务
                task_id = await service.submit_task(
                    prompt=prompt,
                    model=model,
                    negative_prompt=negative_prompt,
                    size=size,
                    n=n,
                    steps=steps,
                    seed=seed
                )

                if not task_id:
                    return json.dumps({
                        "success": False,
                        "error": "图片生成任务提交失败，请检查配置是否正确。"
                    }, ensure_ascii=False)

                logger.info(f"任务已提交: task_id={task_id}")

                # 6. 轮询任务状态
                start_time = time.time()
                timeout = 600  # 10分钟超时

                while time.time() - start_time < timeout:
                    result = await service.get_task_result(task_id)
                    task_status = result.get("task_status")

                    if task_status == "SUCCEED":
                        # 任务成功
                        output_images = result.get("output_images", [])

                        if not output_images:
                            return json.dumps({
                                "success": False,
                                "error": "任务完成但没有返回图片URL。"
                            }, ensure_ascii=False)

                        logger.info(f"任务成功，获得 {len(output_images)} 张图片")

                        # 7. 下载并上传图片到MinIO
                        minio_urls = []

                        for idx, image_url in enumerate(output_images):
                            try:
                                # 下载图片
                                image_bytes = await download_image(image_url)

                                # 上传到MinIO
                                minio_url = await upload_generated_image_to_minio(
                                    image_bytes=image_bytes,
                                    session_id=session_id,
                                    user_id=user_id,
                                    image_index=idx
                                )

                                minio_urls.append(minio_url)
                                logger.info(f"图片 {idx+1} 已上传到MinIO: {minio_url}")

                            except Exception as e:
                                logger.error(f"处理图片 {idx+1} 失败: {str(e)}")
                                # 继续处理其他图片
                                continue

                        if not minio_urls:
                            return json.dumps({
                                "success": False,
                                "error": "所有图片下载或上传都失败了。"
                            }, ensure_ascii=False)

                        # 8. 返回成功结果
                        # 图片URL会被streaming_manager自动缓存并添加到assistant消息
                        # 无需在这里直接操作数据库
                        return json.dumps({
                            "success": True,
                            "message": f"成功生成 {len(minio_urls)} 张图片",
                            "images": minio_urls,
                            "details": {
                                "provider": provider_id,
                                "model": model,
                                "prompt": prompt,
                                "size": size,
                                "count": len(minio_urls)
                            }
                        }, ensure_ascii=False)

                    elif task_status == "FAILED":
                        error_message = result.get("output", {}).get("message", "未知错误")
                        logger.error(f"图片生成任务失败: {error_message}")
                        return json.dumps({
                            "success": False,
                            "error": f"图片生成失败: {error_message}"
                        }, ensure_ascii=False)

                    elif task_status in ["PENDING", "RUNNING", "PROCESSING"]:
                        # 任务进行中，等待
                        await asyncio.sleep(5)

                    else:
                        logger.warning(f"未知任务状态: {task_status}")
                        await asyncio.sleep(5)

                # 超时
                return json.dumps({
                    "success": False,
                    "error": "图片生成超时（超过3分钟）。任务可能仍在处理中，请稍后重试。"
                }, ensure_ascii=False)

            else:
                return json.dumps({
                    "success": False,
                    "error": f"不支持的服务商: {provider_id}"
                }, ensure_ascii=False)

        except ToolExecutionError as e:
            logger.error(f"图片生成工具执行错误: {str(e)}")
            return json.dumps({
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"图片生成工具执行异常: {str(e)}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"图片生成过程中发生错误: {str(e)}"
            }, ensure_ascii=False)
