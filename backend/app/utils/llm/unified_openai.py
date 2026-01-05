from openai import OpenAI, AsyncOpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError
from .base import ModelService
from .common import BaseModelService
import json
import logging
from typing import Dict, List, AsyncGenerator, Optional, Any
import httpx
import asyncio
from functools import wraps

# 配置日志
logger = logging.getLogger(__name__)


def async_retry_on_connection_error(max_retries: int = None, delay: float = None, backoff: float = 2.0):
    """
    装饰器：在遇到网络连接错误时自动重试
    
    Args:
        max_retries: 最大重试次数（None时使用全局配置）
        delay: 初始重试延迟（秒，None时使用全局配置）
        backoff: 延迟倍增因子
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            from .tool_config import tool_config
            
            # 使用全局配置或传入参数
            actual_max_retries = max_retries if max_retries is not None else tool_config.max_retries
            actual_delay = delay if delay is not None else tool_config.retry_delay
            
            last_exception = None
            current_delay = actual_delay
            
            for attempt in range(actual_max_retries + 1):  # +1 因为第一次不算重试
                try:
                    # 尝试执行函数
                    async for item in func(*args, **kwargs):
                        yield item
                    return  # 成功完成，退出
                    
                except (APIConnectionError, APITimeoutError, httpx.ConnectError, httpx.TimeoutException) as e:
                    last_exception = e
                    
                    if attempt < actual_max_retries:
                        logger.warning(
                            f"⚠️ 网络连接失败 (尝试 {attempt + 1}/{actual_max_retries + 1}): {e}"
                        )
                        logger.info(f"⏳ {current_delay:.1f}秒后重试...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff  # 指数退避
                    else:
                        logger.error(
                            f"❌ 重试 {actual_max_retries} 次后仍然失败: {e}"
                        )
                        raise
                        
                except Exception as e:
                    # 其他异常不重试，直接抛出
                    raise
        
        return wrapper
    return decorator


class UnifiedOpenAIService(ModelService, BaseModelService):
    """
    统一的 OpenAI 兼容服务
    
    支持所有兼容 OpenAI API 格式的模型厂商，通过配置区分不同厂商的特性。
    只需提供 provider 配置即可自动适配不同厂商。
    
    ✨ 个性化参数支持：
    - 使用 OpenAI SDK 的 extra_body 机制传递模型特定参数
    - 标准参数（temperature, top_p 等）直接传递
    - 非标准参数（top_k, repetition_penalty 等）通过 extra_body 传递
    - 完美支持各厂商的个性化配置，无需修改 SDK
    """
    
    # 🔒 OpenAI SDK 支持的标准参数列表
    # 注意：OpenAI Python SDK 在客户端会严格验证参数，只接受标准参数。
    # 但 SDK 提供了 extra_body 参数，可以传递模型特定的个性化参数到服务端。
    # 
    # 工作原理：
    # - 标准参数（如 temperature, top_p）直接传递给 SDK
    # - 非标准参数（如 top_k, repetition_penalty）通过 extra_body 传递到服务端
    # - 这样既满足 SDK 验证，又保留了模型的个性化配置能力
    # 
    # 参考: https://platform.openai.com/docs/api-reference/chat/create
    OPENAI_SDK_SUPPORTED_PARAMS = {
        'model', 'messages', 'stream', 'temperature', 'top_p', 'max_tokens',
        'presence_penalty', 'frequency_penalty', 'logit_bias', 'logprobs',
        'top_logprobs', 'n', 'stop', 'seed', 'user', 'response_format',
        'tools', 'tool_choice', 'parallel_tool_calls'
    }
    
    # 🎯 预定义各厂商的特殊配置
    PROVIDER_CONFIGS = {
        "deepseek": {
            "url_suffix": "",  # API URL 后缀
            "api_key_override": None,  # 是否覆盖 API Key（None表示使用传入的）
            "default_headers": {},  # 自定义请求头
            "supports_vision": False,  # 是否支持图片理解
            "save_images_to_minio": False,  # 是否保存图片到 MinIO
            "fallback_to_non_stream": False,  # 流式失败时是否回退到非流式
            "default_params": {  # 模型特定的默认参数
                # ✨ OpenAI SDK 支持通过 extra_body 传递额外参数
                # 标准参数直接传递，非标准参数通过 extra_body 传递到服务端
                "top_k": 30,  # 🎯 通过 extra_body 传递（DeepSeek 特有）
                "presence_penalty": 0.3,  # ✅ 标准参数，直接传递
                "frequency_penalty": 0.2,  # ✅ 标准参数，直接传递
                "repetition_penalty": 1.2,  # 🎯 通过 extra_body 传递（DeepSeek 特有）
            }
        },
        "ollama": {
            "url_suffix": "/v1",  # Ollama 需要 /v1 后缀
            "api_key_override": "ollama",  # Ollama 不验证 API Key，随意填
            "default_headers": {},
            "supports_vision": True,  # Ollama 支持 LLaVA 等多模态模型
            "save_images_to_minio": False,
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.7,
                "max_tokens": 1024,
            }
        },
        "doubao": {
            "url_suffix": "",
            "api_key_override": None,
            "default_headers": {
                "User-Agent": "fish-chat/1.0"
            },
            "supports_vision": True,  # 豆包支持多模态
            "save_images_to_minio": True,  # 豆包需要保存图片到 MinIO
            "fallback_to_non_stream": True,  # 豆包流式失败时重试非流式
            "default_params": {
                # 豆包不支持某些参数，使用空字典
            }
        },
        "bailian": {
            "url_suffix": "",  # 已包含在 base_url 中
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # 通义千问支持多模态
            "save_images_to_minio": False,  # 直接支持 base64 图片
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.8,  # 通义千问推荐的温度值
                "top_p": 0.8,
            }
        },
        "siliconflow": {
            "url_suffix": "",  # 已包含在 base_url 中
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # 硅基流动支持多模态
            "save_images_to_minio": False,  # 直接支持 base64 图片
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.8,  # 硅基流动推荐的温度值
                "top_p": 0.8,
            }
        },
        "zhipu": {
            "url_suffix": "",  # 已包含在 base_url 中
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # 智谱AI支持多模态
            "save_images_to_minio": False,  # 直接支持 base64 图片
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.7,
                "top_p": 0.7,
            }
        },
        "hunyuan": {
            "url_suffix": "",  # 已包含在 base_url 中
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # 腾讯混元支持多模态
            "save_images_to_minio": False,  # 直接支持 base64 图片
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.7,
                "top_p": 0.7,
            }
        },
        "moonshot": {
            "url_suffix": "",  # 已包含在 base_url 中
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # Moonshot Kimi支持多模态
            "save_images_to_minio": False,  # 直接支持 base64 图片
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.3,
                "top_p": 0.7,
            }
        },
        "modelscope": {
            "url_suffix": "",
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # Qwen-VL模型支持图片
            "save_images_to_minio": True,
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.7,
                "top_p": 0.8
            }
        },
        "stepfun": {
            "url_suffix": "",  # 已包含在 base_url 中
            "api_key_override": None,
            "default_headers": {},
            "supports_vision": True,  # 阶跃星辰支持多模态
            "save_images_to_minio": False,  # 直接支持 base64 图片
            "fallback_to_non_stream": False,
            "default_params": {
                "temperature": 0.7,
                "top_p": 0.7,
            }
        },
    }
    
    def __init__(self, base_url: str, api_key: str, model_name: str, provider: str = "openai"):
        """
        初始化统一的 OpenAI 兼容服务
        
        Args:
            base_url: API 基础 URL
            api_key: API 密钥
            model_name: 模型名称
            provider: 厂商标识 (deepseek/ollama/doubao 等)
        """
        BaseModelService.__init__(self, base_url, api_key, model_name)
        
        self.provider = provider
        self.config = self.PROVIDER_CONFIGS.get(provider, {})
        self.last_saved_images = []  # 保存的图片 URL 列表
        
        # 根据配置处理 URL
        url_suffix = self.config.get('url_suffix', '')
        final_url = f"{self.base_url}{url_suffix}"
        
        # 根据配置处理 API Key
        api_key_override = self.config.get('api_key_override')
        final_key = api_key_override if api_key_override is not None else api_key
        
        # 根据配置处理 Headers
        headers = self.config.get('default_headers', {})
        
        # 配置超时：connect=10秒，read=120秒，write=120秒，pool=10秒
        # 这样可以防止网络问题导致的无限等待，同时给流式响应足够时间
        timeout = httpx.Timeout(
            connect=10.0,  # 连接超时
            read=120.0,    # 读取超时（流式响应需要较长时间）
            write=120.0,   # 写入超时
            pool=10.0      # 连接池超时
        )
        
        # 初始化 OpenAI 客户端（同步）
        self.client = OpenAI(
            base_url=final_url,
            api_key=final_key,
            default_headers=headers if headers else None,
            timeout=timeout,  # 添加超时配置
            max_retries=0  # 禁用自动重试，避免长时间阻塞
        )
        
        # 初始化 OpenAI 异步客户端（用于真流式）
        self.async_client = AsyncOpenAI(
            base_url=final_url,
            api_key=final_key,
            default_headers=headers if headers else None,
            timeout=timeout,
            max_retries=0
        )
        
        logger.info(f"🎯 初始化 {provider} 服务")
        logger.info(f"📡 API URL: {final_url}")
        logger.info(f"🏷️ 模型: {model_name}")
    
    def get_model_specific_params(self) -> Dict[str, Any]:
        """获取厂商特定的默认参数"""
        return self.config.get('default_params', {})
    
    def _process_request_data(self, data: Dict[str, Any], images_base64: Optional[List[str]] = None, **kwargs) -> Dict[str, Any]:
        """
        处理请求数据，统一处理图片格式
        
        将图片转换为 OpenAI Vision API 标准格式
        
        逻辑简化：只要有图片就处理，不管配置如何
        这样可以让 API 自己决定是否支持图片，而不是在客户端判断
        """
        # 🐛 调试：记录接收到的images_base64
        logger.info(f"🖼️ [UnifiedOpenAIService._process_request_data] 接收到images_base64参数: {len(images_base64) if images_base64 else 0}张图片")
        logger.info(f"🖼️ [UnifiedOpenAIService._process_request_data] images_base64类型: {type(images_base64)}")
        if images_base64:
            logger.info(f"🖼️ [UnifiedOpenAIService._process_request_data] 第一张图片Base64前缀: {images_base64[0][:50] if images_base64[0] else 'None'}")
        
        messages = data.get("messages", [])
        
        # 🖼️ 第一步：处理历史消息中的图片（MinIO URL -> Base64）
        from ...utils.minio_client import minio_client
        
        for i, msg in enumerate(messages):
            if msg.get("role") == "user" and msg.get("images"):
                user_content = msg.get("content", "")
                image_urls = msg.get("images", [])
                
                # 构建包含图片的消息内容（OpenAI 标准格式）
                message_content = []
                
                # 将 MinIO URL 转换为 base64
                for image_url in image_urls:
                    if image_url.startswith("minio://"):
                        try:
                            # get_image_base64 返回的已经是完整的 data URL (data:image/png;base64,...)
                            data_url = minio_client.get_image_base64(image_url)
                            if data_url:
                                message_content.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": data_url
                                    }
                                })
                                logger.info(f"📸 历史消息图片已转换: {image_url[:60]}... -> base64")
                            else:
                                logger.warning(f"⚠️ 无法从MinIO获取图片: {image_url}")
                        except Exception as e:
                            logger.error(f"❌ 转换历史消息图片失败: {str(e)}")
                
                # 添加文本内容
                if user_content.strip():
                    message_content.append({
                        "type": "text",
                        "text": user_content
                    })
                
                # 更新消息格式（只有有图片时才改为多模态格式）
                if message_content and any(item.get("type") == "image_url" for item in message_content):
                    messages[i]["content"] = message_content
                    logger.info(f"📸 历史消息已转换为多模态格式: {len(image_urls)}张图片")
                
                # 移除 images 字段，因为已经转换到 content 中
                if "images" in messages[i]:
                    del messages[i]["images"]
        
        # 🖼️ 第二步：处理当前消息的图片（Base64）
        if images_base64 and len(images_base64) > 0:
            # 找到最后一条用户消息并添加图片
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    user_content = messages[i].get("content", "")
                    
                    # 如果已经是多模态格式（从历史消息处理来的），追加图片
                    if isinstance(user_content, list):
                        message_content = user_content
                    else:
                        # 构建新的多模态消息内容
                        message_content = []
                        # 先添加文本
                        if user_content.strip():
                            message_content.append({
                                "type": "text",
                                "text": user_content
                            })
                    
                    # 添加所有当前消息的图片
                    for image_base64 in images_base64:
                        image_format = self._detect_image_format(image_base64)
                        image_url = f"data:image/{image_format};base64,{image_base64}"
                        
                        message_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        })
                        
                        logger.info(f"检测到图片格式: {image_format}")
                    
                    # 更新消息格式
                    messages[i]["content"] = message_content
                    logger.info(f"为 {self.provider} API 转换图片消息格式: {len(images_base64)}张图片")
                    break
        
        data["messages"] = messages
        return data
    
    def _OLD_COMPLEX_process_request_data(self, data: Dict[str, Any], images_base64: Optional[List[str]] = None, **kwargs) -> Dict[str, Any]:
        """
        【废弃】旧的复杂逻辑，包含 supports_vision 检查
        保留以备参考
        """
        messages = data.get("messages", [])
        supports_vision = self.config.get('supports_vision', False)
        
        # 🚫 如果当前模型不支持图片，移除所有图片相关字段
        if not supports_vision:
            logger.warning(f"⚠️ 当前模型 {self.model_name} 不支持图片，将忽略历史消息和当前消息中的所有图片")
            
            # 清理历史消息中的图片字段
            for i, msg in enumerate(messages):
                if msg.get("role") == "user" and msg.get("images"):
                    logger.info(f"📸 移除历史消息中的图片字段: {len(msg.get('images', []))}张图片")
                    # 移除 images 字段
                    if "images" in messages[i]:
                        del messages[i]["images"]
                    # 确保 content 是纯文本格式
                    if isinstance(messages[i].get("content"), list):
                        # 如果是多模态格式，提取文本部分
                        text_parts = [item.get("text", "") for item in messages[i]["content"] if item.get("type") == "text"]
                        messages[i]["content"] = " ".join(text_parts).strip()
            
            # 忽略当前消息中的图片(不处理 images_base64)
            if images_base64 and len(images_base64) > 0:
                logger.warning(f"⚠️ 忽略当前消息中的 {len(images_base64)} 张图片，因为当前模型不支持图片")
            
            data["messages"] = messages
            return data
        
        # ✅ 如果当前模型支持图片，处理图片数据
        logger.info(f"✅ 当前模型 {self.model_name} 支持图片，将处理历史消息和当前消息中的图片")
        
        # 🖼️ 第一步：处理历史消息中的图片（MinIO URL -> Base64）
        from ...utils.minio_client import minio_client
        
        for i, msg in enumerate(messages):
            if msg.get("role") == "user" and msg.get("images"):
                user_content = msg.get("content", "")
                image_urls = msg.get("images", [])
                
                # 构建包含图片的消息内容（OpenAI 标准格式）
                message_content = []
                
                # 将 MinIO URL 转换为 base64
                for image_url in image_urls:
                    if image_url.startswith("minio://"):
                        try:
                            # get_image_base64 返回的已经是完整的 data URL (data:image/png;base64,...)
                            data_url = minio_client.get_image_base64(image_url)
                            if data_url:
                                message_content.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": data_url
                                    }
                                })
                                logger.info(f"📸 历史消息图片已转换: {image_url[:60]}... -> base64")
                            else:
                                logger.warning(f"⚠️ 无法从MinIO获取图片: {image_url}")
                        except Exception as e:
                            logger.error(f"❌ 转换历史消息图片失败: {str(e)}")
                
                # 添加文本内容
                if user_content.strip():
                    message_content.append({
                        "type": "text",
                        "text": user_content
                    })
                
                # 更新消息格式（只有有图片时才改为多模态格式）
                if any(item.get("type") == "image_url" for item in message_content):
                    messages[i]["content"] = message_content
                    # 移除 images 字段，避免传递给 API
                    if "images" in messages[i]:
                        del messages[i]["images"]
        
        # 🖼️ 第二步：处理当前消息的图片（Base64）
        if images_base64:
            # 找到最后一条用户消息并添加图片
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    user_content = messages[i].get("content", "")
                    
                    # 如果已经是多模态格式，追加图片
                    if isinstance(user_content, list):
                        message_content = user_content
                    else:
                        message_content = []
                    
                    # 添加所有图片
                    for image_base64 in images_base64:
                        image_format = self._detect_image_format(image_base64)
                        image_url = f"data:image/{image_format};base64,{image_base64}"
                        
                        message_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        })
                        
                        logger.info(f"检测到图片格式: {image_format}")
                    
                    # 添加文本内容（如果还没有）
                    if not isinstance(user_content, list) and user_content.strip():
                        message_content.append({
                            "type": "text",
                            "text": user_content
                        })
                    
                    # 更新消息格式
                    messages[i]["content"] = message_content
                    logger.info(f"为 {self.provider} API 转换当前消息图片格式: {len(images_base64)}张图片")
                    break
        
        data["messages"] = messages
        return data
    
    def _detect_image_format(self, image_base64: str) -> str:
        """
        自动检测图片格式
        
        根据 Base64 编码的开头字符判断图片格式
        """
        if image_base64.startswith('/9j/') or image_base64.startswith('/9j'):
            return "jpeg"
        elif image_base64.startswith('iVBORw0KGgo'):
            return "png"
        elif image_base64.startswith('R0lGODlh') or image_base64.startswith('R0lGODdh'):
            return "gif"
        elif image_base64.startswith('UklGR'):  # WEBP
            return "webp"
        else:
            return "jpeg"  # 默认
    
    async def generate_stream(self, prompt: str, system_prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """实现抽象方法 - 使用模板方法"""
        async for chunk in self.generate_stream_template(prompt, system_prompt, **kwargs):
            yield chunk
    
    def _filter_params(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分离标准参数和额外参数
        
        OpenAI SDK 会在客户端侧严格验证参数，只接受标准参数
        但可以通过 extra_body 参数传递模型特定的个性化参数
        
        Args:
            data: 请求数据字典
        
        Returns:
            dict: 过滤后的数据（标准参数 + extra_body）
        """
        filtered_data = {}
        extra_params = {}
        
        for key, value in data.items():
            if key in self.OPENAI_SDK_SUPPORTED_PARAMS:
                filtered_data[key] = value
            else:
                extra_params[key] = value
        
        # 记录参数分离情况
        if extra_params:
            logger.info(f"✨ 通过 extra_body 传递模型个性化参数: {list(extra_params.keys())}")
            logger.info(f"   个性化参数详情: {json.dumps(extra_params, ensure_ascii=False)}")
            # 将额外参数添加到 extra_body
            filtered_data['extra_body'] = extra_params
        
        return filtered_data
    
    async def _call_api(self, data: Dict[str, Any], **kwargs) -> AsyncGenerator[str, None]:
        """
        统一的 API 调用实现
        
        所有兼容 OpenAI 格式的厂商都使用相同的调用逻辑
        """
        try:
            logger.info(f"📡 调用 {self.provider} API")
            logger.info(f"🏷️ 模型: {data.get('model')}")
            
            # 提取参数用于后续处理
            images_base64 = kwargs.get("images_base64")
            session_id = kwargs.get("session_id")
            message_id = kwargs.get("message_id")
            user_id = kwargs.get("user_id")
            
            try:
                # 🔒 分离标准参数和额外参数
                filtered_data = self._filter_params(data)
                
                logger.info(f"🔍 传递给 OpenAI SDK 的标准参数:")
                for key, value in filtered_data.items():
                    if key == 'extra_body':
                        logger.info(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
                    elif key != 'messages':
                        logger.info(f"  {key}: {type(value).__name__} = {value}")
                    else:
                        logger.info(f"  {key}: [{len(value)} messages]")
                
                # ✅ 使用 extra_body 传递额外参数的 OpenAI SDK 流式请求
                stream = self.client.chat.completions.create(**filtered_data)
                
                # 处理流式响应
                from ...config import settings
                full_response = ""
                MAX_RESPONSE_LENGTH = settings.max_response_length  # 从配置读取最大响应长度
                MAX_CHUNK_LENGTH = settings.max_chunk_length  # 从配置读取单个chunk最大长度
                chunk_count = 0
                
                for chunk in stream:
                    # 增加安全检查，确保 choices 列表不为空
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        chunk_count += 1
                        
                        # 🛡️ 防护1：检查单个chunk长度（异常数据注入）
                        if len(content) > MAX_CHUNK_LENGTH:
                            error_msg = f"🚨 检测到异常数据注入！单个chunk长度={len(content)}，超过限制{MAX_CHUNK_LENGTH}。chunk序号={chunk_count}"
                            logger.error(error_msg)
                            logger.error(f"异常chunk前1000字符预览: {content[:1000]}")
                            # 抛出异常，拒绝此次请求
                            raise ValueError(f"检测到异常数据：单个响应片段过长（{len(content)}字符），可能是异常注入，已拒绝请求")
                        
                        # 🛡️ 防护2：检查累积响应长度（异常数据注入）
                        if len(full_response) + len(content) > MAX_RESPONSE_LENGTH:
                            error_msg = f"🚨 检测到异常数据注入！响应总长度={len(full_response) + len(content)}，超过限制{MAX_RESPONSE_LENGTH}"
                            logger.error(error_msg)
                            logger.error(f"完整响应前2000字符: {full_response[:2000]}")
                            logger.error(f"完整响应后2000字符: {full_response[-2000:]}")
                            # 抛出异常，拒绝此次请求
                            raise ValueError(f"检测到异常数据：响应总长度过长（{len(full_response) + len(content)}字符），可能是异常注入，已拒绝请求")
                        
                        full_response += content
                        yield content
                        
                logger.info(f"✅ 流式响应完成。总chunk数={chunk_count}，总长度={len(full_response)}")
                
                # 🖼️ 如果配置了保存图片到 MinIO，在响应完成后保存
                if self.config.get('save_images_to_minio'):
                    await self._save_images_after_response(images_base64, session_id, message_id, user_id)
                
            except Exception as e:
                # 检查是否是超时异常
                is_timeout = isinstance(e, (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout))
                
                if is_timeout:
                    logger.error(f"⏱️ {self.provider} 请求超时: {str(e)}")
                else:
                    logger.error(f"{self.provider} 流式请求失败: {str(e)}")
                
                # 如果配置了 fallback，尝试非流式请求（但超时异常不重试）
                if self.config.get('fallback_to_non_stream') and not is_timeout:
                    logger.info(f"尝试 {self.provider} 非流式请求...")
                    request_data = filtered_data.copy()  # 使用已过滤的数据
                    request_data["stream"] = False
                    
                    response = self.client.chat.completions.create(**request_data)
                    
                    if response.choices[0].message.content:
                        full_response = response.choices[0].message.content
                        yield full_response
                        
                        # 🖼️ 非流式响应完成后也保存图片
                        if self.config.get('save_images_to_minio'):
                            await self._save_images_after_response(images_base64, session_id, message_id, user_id)
                else:
                    # 不支持 fallback 或超时异常，直接抛出
                    if is_timeout:
                        raise Exception(f"API请求超时，请检查网络连接或稍后重试")
                    raise e
        
        except Exception as e:
            logger.error(f"{self.provider} API Error: {str(e)}")
            raise self.error_handler.handle_api_error(e)
    
    async def _save_images_after_response(self, 
                                         images_base64: Optional[List[str]], 
                                         session_id: Optional[str], 
                                         message_id: Optional[str], 
                                         user_id: Optional[str] = None):
        """
        响应完成后保存图片到 MinIO
        
        只有配置了 save_images_to_minio 的厂商才会执行此操作
        """
        logger.info(f"=== 检查是否需要保存图片到 MinIO ({self.provider}) ===")
        logger.info(f"images_base64存在: {images_base64 is not None}")
        logger.info(f"user_id: {user_id}")
        logger.info(f"session_id存在: {session_id is not None}")
        logger.info(f"message_id存在: {message_id is not None}")
        
        if images_base64 and session_id and message_id:
            logger.info(f"✅ 开始保存 {len(images_base64)} 张图片到 MinIO...")
            saved_images = await self._save_images_to_minio(images_base64, session_id, message_id, user_id)
            logger.info(f"✅ 图片保存结果: {saved_images}")
            
            # 将保存的图片 URL 存储到实例变量中，供外部访问
            self.last_saved_images = saved_images
        else:
            logger.warning(f"❌ 缺少必要参数，跳过图片保存 ({self.provider})")
            if not images_base64:
                logger.warning("  - images_base64为空")
            if not session_id:
                logger.warning("  - session_id为空")
            if not message_id:
                logger.warning("  - message_id为空")
    
    async def _save_images_to_minio(self, 
                                   images_base64: List[str], 
                                   session_id: str, 
                                   message_id: str, 
                                   user_id: Optional[str] = None):
        """
        保存图片到 MinIO
        
        Args:
            images_base64: Base64 编码的图片列表
            session_id: 会话 ID
            message_id: 消息 ID
            user_id: 用户 ID（用于路径隔离）
            
        Returns:
            保存成功的图片 URL 列表
        """
        logger.info(f"=== 开始保存图片到 MinIO ({self.provider}) ===")
        logger.info(f"user_id: {user_id}")
        logger.info(f"session_id: {session_id}")
        logger.info(f"message_id: {message_id}")
        logger.info(f"图片数量: {len(images_base64)}")
        
        try:
            from ..minio_client import minio_client
            
            saved_images = []
            for i, image_base64 in enumerate(images_base64):
                logger.info(f"正在保存第 {i+1} 张图片...")
                minio_url = minio_client.upload_image(image_base64, session_id, message_id, user_id)
                if minio_url:
                    saved_images.append(minio_url)
                    logger.info(f"✅ 图片已保存到 MinIO: {minio_url}")
                else:
                    logger.error(f"❌ 第 {i+1} 张图片保存失败")
            
            if saved_images:
                logger.info(f"✅ 共保存了 {len(saved_images)} 张图片到 MinIO")
                return saved_images
            else:
                logger.error("❌ 没有图片保存成功")
                return []
        except Exception as e:
            logger.error(f"❌ 保存图片到 MinIO 失败: {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return []
    
    def _call_llm_with_tools_sync(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], model_params: Optional[Dict[str, Any]] = None, images_base64: Optional[List[str]] = None, use_streaming: bool = False, **kwargs) -> Dict[str, Any]:
        """
        同步调用 LLM（带工具支持）
        
        支持流式和非流式两种模式：
        - 非流式（默认）：直接返回完整响应
        - 流式：累积流式响应片段后返回完整响应
        
        Args:
            messages: 消息列表
            tools: 工具列表（OpenAI 格式）
            model_params: 用户自定义模型参数（优先级最高）
            images_base64: 图片base64列表（用于vision模型）
            use_streaming: 是否使用流式模式（默认False）
            **kwargs: 其他参数（包括 session_id, message_id, user_id）
        
        Returns:
            dict: {
                "content": "回复内容",
                "tool_calls": [...]  # 如果需要调用工具
            }
        
        Raises:
            NotImplementedError: 当模型不支持工具调用时
        """
        try:
            # 🖼️ 保存图片相关参数到实例变量（用于后续保存到MinIO）
            if images_base64:
                session_id = kwargs.get('session_id')
                message_id = kwargs.get('message_id')
                user_id = kwargs.get('user_id')
                
                self._pending_images = {
                    'images_base64': images_base64,
                    'session_id': session_id,
                    'message_id': message_id,
                    'user_id': user_id
                }
                logger.info(f"🖼️ 工具调用模式：已缓存 {len(images_base64)} 张图片数据（session_id={session_id}, message_id={message_id}, user_id={user_id}）")
            
            # 构建请求数据
            request_data = {
                "model": self.model_name,
                "messages": messages,
                "tools": tools,
                "stream": use_streaming,  # 🎯 支持流式/非流式切换
                **self.get_default_request_params(),
                **self.get_model_specific_params()
            }
            
            # 🎯 合并用户自定义模型参数（优先级最高）
            if isinstance(model_params, dict) and model_params:
                request_data.update(model_params)
                logger.info(f"✅ 工具调用应用自定义模型参数: {json.dumps(model_params, ensure_ascii=False)}")
            
            # 🖼️ 【关键修复】始终调用 _process_request_data 来处理图片
            # 即使当前消息没有图片，历史消息中也可能包含图片需要转换
            if images_base64:
                logger.info(f"🖼️ 工具调用中包含 {len(images_base64)} 张当前消息图片，调用_process_request_data处理")
            else:
                logger.info(f"🖼️ 当前消息无图片，但检查历史消息是否包含图片...")
            
            request_data = self._process_request_data(request_data, images_base64, **kwargs)
            
            # 分离标准参数和额外参数
            filtered_data = self._filter_params(request_data)
            
            logger.info(f"🔧 调用 {self.provider} LLM（带工具支持，{'✅ 流式' if use_streaming else '⚠️ 非流式'}模式）")
            logger.info(f"🛠️ 工具数量: {len(tools)}")
            
            # 打印实际发送的请求体（用于调试）
            self.log_request_data(filtered_data, f"{self.provider} (工具调用)")
            
            # 调用 API
            response = self.client.chat.completions.create(**filtered_data)
            
            # 🎯 自动检测返回类型（兼容强制流式模型）
            # 检查 response 是否为 Stream 对象
            is_stream_response = hasattr(response, '__iter__') and not hasattr(response, 'choices')
            
            if is_stream_response:
                # 🔄 流式模式：累积chunks
                logger.info("🔄 使用流式模式处理工具调用响应")
                result = {
                    "content": "",
                    "tool_calls": []
                }
                
                # 用于累积工具调用信息
                tool_calls_accumulator = {}  # {index: {id, name, arguments}}
                finish_reason = None
                
                for chunk in response:
                    # 检查 finish_reason（流式结束标志）
                    if chunk.choices and chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                        logger.info(f"🏁 流式输出结束标志: {finish_reason}")
                    
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue
                    
                    # 累积内容
                    if hasattr(delta, 'content') and delta.content:
                        result["content"] += delta.content
                    
                    # 累积工具调用
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            
                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": ""
                                }
                            
                            if hasattr(tc_delta, 'id') and tc_delta.id:
                                tool_calls_accumulator[idx]["id"] = tc_delta.id
                            
                            if hasattr(tc_delta, 'function'):
                                if hasattr(tc_delta.function, 'name') and tc_delta.function.name:
                                    tool_calls_accumulator[idx]["name"] = tc_delta.function.name
                                if hasattr(tc_delta.function, 'arguments') and tc_delta.function.arguments:
                                    tool_calls_accumulator[idx]["arguments"] += tc_delta.function.arguments
                
                # 🎯 流式输出完成后的日志
                logger.info(f"✅ 流式输出完成，finish_reason={finish_reason}，累积了 {len(tool_calls_accumulator)} 个工具调用")
                
                # 转换累积的工具调用为标准格式
                for idx in sorted(tool_calls_accumulator.keys()):
                    tc = tool_calls_accumulator[idx]
                    result["tool_calls"].append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"]
                        }
                    })
                
                if result["tool_calls"]:
                    logger.info(f"🔧 LLM 请求调用 {len(result['tool_calls'])} 个工具（流式累积）")
                else:
                    logger.info("✅ LLM 返回最终回复（无工具调用，流式）")
            else:
                # 📦 非流式模式：直接解析
                message = response.choices[0].message
                result = {
                    "content": message.content or "",
                    "tool_calls": []
                }
                
                # 🔍 调试：打印原始响应结构
                logger.debug(f"🔍 API 返回的 message 对象: {message}")
                logger.debug(f"🔍 message 是否有 tool_calls 属性: {hasattr(message, 'tool_calls')}")
                logger.debug(f"🔍 message.tool_calls 的值: {getattr(message, 'tool_calls', None)}")
                
                # 检查是否有工具调用
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tc in message.tool_calls:
                        result["tool_calls"].append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        })
                    
                    logger.info(f"🔧 LLM 请求调用 {len(result['tool_calls'])} 个工具")
                else:
                    logger.info("✅ LLM 返回最终回复（无工具调用）")
            
            return result
        
        except Exception as e:
            # 🎯 检查是否为"模型不支持工具调用"的错误
            # 策略：通过错误对象的 code/type 属性判断（比字符串匹配更可靠）
            
            error_msg = str(e).lower()
            
            # 1️⃣ 优先检查异常对象的 code 属性（OpenAI SDK 标准）
            error_code = getattr(e, 'code', None)
            error_type_attr = getattr(e, 'type', None)
            
            # 2️⃣ 明确的"不支持工具"错误码（各API提供商可能使用的标准码）
            # - feature_not_supported: 功能不支持
            # - invalid_request_error + tools/functions 关键词: 工具请求无效
            if error_code in ['feature_not_supported', 'unsupported_feature']:
                logger.warning(f"⚠️ 模型 {self.model_name} 不支持此功能（错误码: {error_code}）")
                raise NotImplementedError(f"Model {self.model_name} does not support function calling") from e
            
            # 3️⃣ invalid_request_error 且错误信息明确提到工具/函数不支持
            if error_code == 'invalid_request_error' or error_type_attr == 'invalid_request_error':
                # 只有同时包含"不支持"+"工具/函数"才认定为MCP不支持
                has_unsupported = any(kw in error_msg for kw in [
                    "not supported", "unsupported", "does not support", "不支持"
                ])
                has_tool_ref = any(kw in error_msg for kw in [
                    "tool", "function", "function_call", "function calling"
                ])
                
                if has_unsupported and has_tool_ref:
                    logger.warning(f"⚠️ 模型 {self.model_name} 不支持工具调用")
                    logger.debug(f"🔍 错误详情: code={error_code}, type={error_type_attr}, msg={error_msg[:150]}")
                    raise NotImplementedError(f"Model {self.model_name} does not support function calling") from e
            
            # ⚠️ 其他错误直接抛出，不标记为"不支持工具"
            # 包括：认证错误、网络错误、参数错误、服务不可用等
            logger.error(f"❌ 调用 LLM 失败 ({type(e).__name__}): {e}", exc_info=True)
            raise
    
    @async_retry_on_connection_error()  # 使用全局配置
    async def _call_llm_with_tools_streaming(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        model_params: Optional[Dict[str, Any]] = None,
        images_base64: Optional[List[str]] = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        异步流式调用 LLM（带工具支持）
        
        与 _call_llm_with_tools_sync 的区别：
        - 返回异步生成器，逐块yield事件
        - 工具调用：累积后yield完整的tool_calls
        - 内容输出：直接透传每个chunk，不累积
        
        Yields:
            dict: 事件对象
                - {"type": "content_delta", "content": "..."}  # 内容片段
                - {"type": "tool_calls", "tool_calls": [...]}  # 工具调用（累积完成）
                - {"type": "done", "finish_reason": "stop"}    # 完成标志
        """
        try:
            # 🖼️ 保存图片相关参数
            if images_base64:
                session_id = kwargs.get('session_id')
                message_id = kwargs.get('message_id')
                user_id = kwargs.get('user_id')
                
                self._pending_images = {
                    'images_base64': images_base64,
                    'session_id': session_id,
                    'message_id': message_id,
                    'user_id': user_id
                }
                logger.info(f"🖼️ 流式工具调用：已缓存 {len(images_base64)} 张图片数据")
            
            # 构建请求数据
            request_data = {
                "model": self.model_name,
                "messages": messages,
                "tools": tools,
                "stream": True,  # 🎯 强制流式
                **self.get_default_request_params(),
                **self.get_model_specific_params()
            }
            
            # 合并用户自定义参数
            if isinstance(model_params, dict) and model_params:
                request_data.update(model_params)
                logger.info(f"✅ 应用自定义模型参数: {json.dumps(model_params, ensure_ascii=False)}")
            
            # 处理图片
            request_data = self._process_request_data(request_data, images_base64, **kwargs)
            filtered_data = self._filter_params(request_data)
            
            logger.info(f"🔧 调用 {self.provider} LLM（真流式工具调用模式）")
            logger.info(f"🛠️ 工具数量: {len(tools)}")
            self.log_request_data(filtered_data, f"{self.provider} (真流式)")
            
            # 🚀 调用 API（异步）
            response = await self.async_client.chat.completions.create(**filtered_data)
            
            # 🎯 流式处理
            tool_calls_accumulator = {}  # 工具调用需要累积
            finish_reason = None
            
            async for chunk in response:
                # 检查完成标志
                if chunk.choices and chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue
                
                # 🎯 内容直接透传（不累积）
                if hasattr(delta, 'content') and delta.content:
                    yield {
                        "type": "content_delta",
                        "content": delta.content
                    }
                
                # 🎯 工具调用累积（必须等待完整）
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        
                        if idx not in tool_calls_accumulator:
                            tool_calls_accumulator[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": ""
                            }
                        
                        if hasattr(tc_delta, 'id') and tc_delta.id:
                            tool_calls_accumulator[idx]["id"] = tc_delta.id
                        
                        if hasattr(tc_delta, 'function'):
                            if hasattr(tc_delta.function, 'name') and tc_delta.function.name:
                                tool_calls_accumulator[idx]["name"] = tc_delta.function.name
                            if hasattr(tc_delta.function, 'arguments') and tc_delta.function.arguments:
                                tool_calls_accumulator[idx]["arguments"] += tc_delta.function.arguments
            
            # 🏁 流式结束
            logger.info(f"✅ 真流式完成，finish_reason={finish_reason}，累积了 {len(tool_calls_accumulator)} 个工具调用")
            
            # 🎯 如果有工具调用，yield工具调用事件
            if tool_calls_accumulator:
                tool_calls = []
                for idx in sorted(tool_calls_accumulator.keys()):
                    tc = tool_calls_accumulator[idx]
                    tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"]
                        }
                    })
                
                logger.info(f"🔧 LLM 请求调用 {len(tool_calls)} 个工具（真流式累积）")
                yield {
                    "type": "tool_calls",
                    "tool_calls": tool_calls
                }
            
            # 🎯 最后yield完成事件
            yield {
                "type": "done",
                "finish_reason": finish_reason
            }
        
        except Exception as e:
            # 错误处理（与同步版本相同）
            error_msg = str(e).lower()
            error_code = getattr(e, 'code', None)
            error_type_attr = getattr(e, 'type', None)
            
            if error_code in ['feature_not_supported', 'unsupported_feature']:
                logger.warning(f"⚠️ 模型 {self.model_name} 不支持此功能（错误码: {error_code}）")
                raise NotImplementedError(f"Model {self.model_name} does not support function calling") from e
            
            if error_code == 'invalid_request_error' or error_type_attr == 'invalid_request_error':
                has_unsupported = any(kw in error_msg for kw in [
                    "not supported", "unsupported", "does not support", "不支持"
                ])
                has_tool_ref = any(kw in error_msg for kw in [
                    "tool", "function", "function_call", "function calling"
                ])
                
                if has_unsupported and has_tool_ref:
                    logger.warning(f"⚠️ 模型 {self.model_name} 不支持工具调用")
                    raise NotImplementedError(f"Model {self.model_name} does not support function calling") from e
            
            logger.error(f"❌ 真流式调用失败 ({type(e).__name__}): {e}", exc_info=True)
            raise

