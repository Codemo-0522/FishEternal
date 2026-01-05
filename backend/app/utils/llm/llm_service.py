
import logging
from typing import Dict, Any, Optional, List, AsyncGenerator
from datetime import datetime, timezone, timedelta
# 移除向量相关导入
# import numpy as np
# from numpy.typing import NDArray
# from langchain_core.embeddings import Embeddings
# from sklearn.feature_extraction.text import TfidfVectorizer
# from ..vector_store.vector_store import VectorStore
# from ..content_filter import prepare_content_for_vector_storage, should_store_in_vector_db, prepare_content_for_context
from .deepseek import DeepSeekService
from .ollama import OllamaService
from .doubao import DouBaoService
from .bailian import BaiLianService
from .siliconflow import SiliconFlowService
from .zhipu import ZhipuService
from .hunyuan import HunyuanService
from .moonshot import MoonshotService
from .stepfun import StepfunService
from .modelscope import ModelScopeService
from ...mcp.manager import mcp_manager
from .streaming_manager import streaming_manager, StreamingState
from .tool_config import tool_config  # 👈 导入全局配置

# 配置日志
logger = logging.getLogger(__name__)

# 移除SimpleEmbeddings类和simple_tokenizer函数

class LLMService:
    """LLM服务管理类"""
    def __init__(self):
        # 移除向量存储初始化
        # self.vector_store = VectorStore()
        self.last_response = None
        self.last_saved_images = []  # 添加保存图片的属性
        # 移除 current_service 的缓存

    # 移除 _get_relevant_history 方法

    async def generate_stream_universal(self,
                                      user_message: str,
                                      history: List[Dict[str, Any]],
                                      model_settings: Dict[str, Any],
                                      system_prompt: Optional[str] = None,
                                      session_id: Optional[str] = None,
                                      user_id: Optional[str] = None,
                                      enable_tools: bool = True,
                                      **kwargs) -> AsyncGenerator[str, None]:
        """
        通用流式生成方法
        
        使用新的流式管理器，支持所有模型，解决并发和工具调用问题
        """
        
        if not session_id:
            # 如果没有session_id，生成一个临时的
            import uuid
            session_id = f"temp_{uuid.uuid4().hex[:8]}"
        
        # 注册会话到流式管理器（如果还没注册）
        if session_id not in streaming_manager.active_sessions:
            # 创建一个虚拟websocket对象用于状态管理
            class MockWebSocket:
                async def send_json(self, data):
                    logger.debug(f"状态更新: {data}")
            
            await streaming_manager.register_session(
                session_id=session_id,
                user_id=user_id or "unknown",
                websocket=MockWebSocket()
            )
        
        try:
            # 使用通用流式管理器
            async for chunk in streaming_manager.generate_stream_universal(
                session_id=session_id,
                llm_service=self,
                user_message=user_message,
                history=history,
                model_settings=model_settings,
                system_prompt=system_prompt,
                enable_tools=enable_tools,
                user_id=user_id,
                **kwargs
            ):
                yield chunk
        finally:
            # 清理会话
            await streaming_manager.unregister_session(session_id)

    async def generate_stream(self, 
                             user_message: str, 
                             history: List[Dict[str, Any]], 
                             model_settings: Dict[str, Any],
                             system_prompt: Optional[str] = None,
                             session_id: Optional[str] = None,
                             **kwargs) -> AsyncGenerator[str, None]:
        """
        生成流式回复
        
        Args:
            user_message: 用户消息
            history: 历史对话记录
            model_settings: 模型配置
            system_prompt: 系统提示
            session_id: 会话ID
            **kwargs: 其他参数
            
        Yields:
            str: 生成的文本片段
        """
        
        try:
            # 解析模型配置
            model_service = model_settings.get("modelService", "deepseek")
            base_url = model_settings.get("baseUrl", "")
            api_key = model_settings.get("apiKey", "")
            model_name = model_settings.get("modelName", "")
            model_params = model_settings.get("modelParams") if isinstance(model_settings, dict) else None
            
            logger.info(f"生成流式回复")
            logger.info(f"用户消息: {user_message}")
            logger.info(f"会话ID: {session_id}")
            logger.info(f"使用模型服务: {model_service}")
            # 🐛 调试：检查kwargs中是否包含images_base64
            logger.info(f"🖼️ [llm_service.generate_stream] kwargs包含: {list(kwargs.keys())}")
            if 'images_base64' in kwargs:
                images_data = kwargs.get('images_base64', [])
                logger.info(f"🖼️ [llm_service.generate_stream] 接收到images_base64: {len(images_data) if images_data else 0}张图片")
            else:
                logger.warning(f"⚠️ [llm_service.generate_stream] kwargs中没有images_base64！")
            
            # 每次都创建新的服务实例，确保使用最新配置
            current_service = None
            if model_service == "deepseek":
                current_service = DeepSeekService(base_url, api_key, model_name)
            elif model_service == "ollama":
                current_service = OllamaService(base_url, api_key, model_name)
            elif model_service == "doubao":
                current_service = DouBaoService(base_url, api_key, model_name)
            elif model_service == "bailian":
                current_service = BaiLianService(base_url, api_key, model_name)
            elif model_service == "siliconflow":
                current_service = SiliconFlowService(base_url, api_key, model_name)
            elif model_service == "zhipu":
                current_service = ZhipuService(base_url, api_key, model_name)
            elif model_service == "hunyuan":
                current_service = HunyuanService(base_url, api_key, model_name)
            elif model_service == "moonshot":
                current_service = MoonshotService(base_url, api_key, model_name)
            elif model_service == "stepfun":
                current_service = StepfunService(base_url, api_key, model_name)
            elif model_service == "modelscope":
                current_service = ModelScopeService(base_url, api_key, model_name)
            else:
                raise ValueError(f"不支持的模型服务: {model_service}")
            
            # 生成回复，同时传递历史消息
            response_text = ""
            error_occurred = False
            saved_images = []
            
            try:
                # 传递历史消息
                extra_kwargs = {"history": history}
                
                # 如果有图片，传递多张图片base64数据
                if hasattr(current_service, 'generate_stream') and 'images_base64' in kwargs:
                    extra_kwargs["images_base64"] = kwargs.get("images_base64")
                    logger.info(f"传递图片数据: {len(kwargs.get('images_base64', []))}张图片")
                
                # 传递session_id和message_id参数
                if session_id:
                    extra_kwargs["session_id"] = session_id
                    logger.info(f"传递session_id: {session_id}")
                elif 'session_id' in kwargs:
                    extra_kwargs["session_id"] = kwargs.get("session_id")
                    logger.info(f"传递session_id: {kwargs.get('session_id')}")
                
                if 'message_id' in kwargs:
                    extra_kwargs["message_id"] = kwargs.get("message_id")
                    logger.info(f"传递message_id: {kwargs.get('message_id')}")
                
                # 传递user_id参数（用于MinIO路径隔离）
                if 'user_id' in kwargs:
                    extra_kwargs["user_id"] = kwargs.get("user_id")
                    logger.info(f"传递user_id: {kwargs.get('user_id')}")
                
                # 透传模型参数
                if model_params and isinstance(model_params, dict):
                    extra_kwargs["model_params"] = model_params
                    logger.info(f"透传模型参数: {list(model_params.keys())}")
                
                logger.info(f"最终传递给模型服务的参数: {list(extra_kwargs.keys())}")

                async for chunk in current_service.generate_stream(
                    user_message,  # 直接使用原始用户消息
                    system_prompt or "",
                    **extra_kwargs
                ):
                    if isinstance(chunk, str):
                        response_text += chunk
                        yield chunk
                    else:
                        logger.warning(f"收到非字符串的chunk: {type(chunk)}")
                
                self.last_response = {
                    "text": response_text,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # 获取具体服务实例的保存图片信息
                if hasattr(current_service, 'last_saved_images'):
                    self.last_saved_images = current_service.last_saved_images
                    logger.info(f"✅ 从具体服务实例获取到保存的图片: {self.last_saved_images}")
                else:
                    self.last_saved_images = []
                    logger.info("具体服务实例没有last_saved_images属性")
                    
            except Exception as e:
                error_occurred = True
                logger.error(f"生成回复时发生错误: {str(e)}", exc_info=True)
                raise
            
        except Exception as e:
            logger.error(f"LLMService.generate_stream 发生错误: {str(e)}", exc_info=True)
            raise

    def get_last_response(self) -> Optional[str]:
        """获取最后一次的回复"""
        return self.last_response
    
    async def generate_with_tools(
        self,
        user_message: str,
        history: List[Dict[str, Any]],
        model_settings: Dict[str, Any],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        max_tool_iterations: Optional[int] = None,  # 👈 改为可选，自动读取全局配置
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        带工具调用的流式生成（支持 MCP 工具）
        
        Args:
            user_message: 用户消息
            history: 历史对话记录
            model_settings: 模型配置
            system_prompt: 系统提示
            session_id: 会话ID（工具调用需要）
            user_id: 用户ID
            max_tool_iterations: 最大工具调用迭代次数，None时使用全局配置 (tool_config.max_iterations)
            **kwargs: 其他参数
        
        Yields:
            str: 生成的文本片段
        """
        # 👇 使用全局配置或传入参数
        max_iter = max_tool_iterations if max_tool_iterations is not None else tool_config.max_iterations
        logger.info(f"🔧 [generate_with_tools] 最大迭代次数: {max_iter} (全局配置: {tool_config.max_iterations})")
        # 检查 MCP 是否可用
        mcp_client = mcp_manager.get_client()
        if not mcp_client:
            logger.warning("⚠️ MCP Client 未初始化，回退到普通对话模式")
            async for chunk in self.generate_stream(
                user_message, history, model_settings, system_prompt, session_id, **kwargs
            ):
                yield chunk
            return
        
        # 获取工具列表（传递 session_id 以支持动态参数）
        try:
            tools = await mcp_client.list_tools(
                session_id=session_id,
                user_id=user_id
            )
            if not tools:
                logger.info("ℹ️ 无可用工具，使用普通对话模式")
                async for chunk in self.generate_stream(
                    user_message, history, model_settings, system_prompt, session_id, **kwargs
                ):
                    yield chunk
                return
            
            logger.info(f"🔧 已加载 {len(tools)} 个 MCP 工具")
            # 打印工具描述（用于调试）
            for tool in tools:
                logger.debug(f"  - {tool['function']['name']}: {tool['function']['description'][:100]}...")
        except Exception as e:
            logger.error(f"❌ 获取工具列表失败: {e}")
            async for chunk in self.generate_stream(
                user_message, history, model_settings, system_prompt, session_id, **kwargs
            ):
                yield chunk
            return
        
        # 解析模型配置
        model_service = model_settings.get("modelService", "deepseek")
        base_url = model_settings.get("baseUrl", "")
        api_key = model_settings.get("apiKey", "")
        model_name = model_settings.get("modelName", "")
        
        # 创建服务实例
        current_service = self._create_service_instance(model_service, base_url, api_key, model_name)
        if not current_service:
            raise ValueError(f"不支持的模型服务: {model_service}")
        
        # 检查服务是否支持工具调用 - 如果不支持，直接使用普通模式
        if not hasattr(current_service, '_call_llm_with_tools_sync'):
            logger.warning(f"⚠️ {model_service} 服务不支持工具调用，使用普通对话模式")
            async for chunk in self.generate_stream(
                user_message, history, model_settings, system_prompt, session_id, **kwargs
            ):
                yield chunk
            return
        
        # 执行工具调用循环
        iteration = 0
        messages = self._build_messages(system_prompt, history, user_message)
        
        while iteration < max_iter:  # 👈 使用全局配置
            iteration += 1
            logger.info(f"🔄 工具调用迭代 {iteration}/{max_iter}")
            
            # 打印当前消息列表（用于调试）
            logger.info(f"📝 当前消息列表（共 {len(messages)} 条）:")
            for i, msg in enumerate(messages):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "tool":
                    tool_name = msg.get("name", "unknown")
                    logger.info(f"   [{i+1}] {role} ({tool_name}): {content[:100]}...")
                elif role == "assistant" and "tool_calls" in msg:
                    tool_calls_info = msg.get("tool_calls", [])
                    logger.info(f"   [{i+1}] {role} (请求工具): {len(tool_calls_info)} 个工具")
                else:
                    logger.info(f"   [{i+1}] {role}: {content[:100]}...")
            
            # 调用 LLM（带工具）
            try:
                # 🎯 提取用户自定义模型参数
                model_params = model_settings.get("modelParams", {})
                # 🖼️ 传递图片数据及其他参数（session_id, message_id, user_id等）
                # 注意：使用get而不是pop,因为kwargs可能还需要用于其他地方
                images_base64 = kwargs.get('images_base64')
                # 创建不包含images_base64的kwargs副本,避免重复传递
                other_kwargs = {k: v for k, v in kwargs.items() if k != 'images_base64'}
                if images_base64:
                    response = current_service._call_llm_with_tools_sync(messages, tools, model_params, images_base64, **other_kwargs)
                else:
                    # ⚠️ 即使没有图片，也要传递 other_kwargs（包含 session_id, message_id, user_id）
                    response = current_service._call_llm_with_tools_sync(messages, tools, model_params, **other_kwargs)
            except NotImplementedError as e:
                # 模型不支持工具调用，直接使用普通对话模式
                # 注意：history 中已经包含了之前所有的对话上下文（包括工具调用结果）
                logger.warning(f"⚠️ 模型不支持工具调用，切换到普通对话模式: {e}")
                async for chunk in self.generate_stream(
                    user_message, history, model_settings, system_prompt, session_id, **kwargs
                ):
                    yield chunk
                return
            except Exception as e:
                logger.error(f"❌ LLM 调用失败: {e}")
                yield f"\n[错误] LLM 调用失败: {str(e)}\n"
                break
            
            # 检查是否需要调用工具
            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                # 无工具调用，返回最终回复
                final_content = response.get("content", "")
                logger.info("✅ LLM 返回最终回复（无工具调用）")
                
                # 流式输出
                for char in final_content:
                    yield char
                break
            
            # 有工具调用
            logger.info(f"🔧 LLM 请求调用 {len(tool_calls)} 个工具")
            
            # 🎯 获取模型在调用工具时输出的描述（如"🔍 正在检索..."）
            tool_call_description = response.get("content") or ""
            
            # 📤 如果模型输出了描述，流式输出到前端的 <think> 标签中
            if tool_call_description and tool_call_description.strip():
                logger.info(f"💬 模型工具调用描述: {tool_call_description[:100]}")
                # 🎯 关键：先发送开始标签，然后流式发送内容，最后发送结束标签
                # 这样前端会累积成一个完整的 <think>...</think>，只渲染一个折叠栏
                yield "<think>"  # 开始标签
                # 流式输出描述内容
                for char in tool_call_description:
                    yield char
                yield "</think>"  # 结束标签
            
            # 添加 assistant 消息到历史
            messages.append({
                "role": "assistant",
                "content": response.get("content") or None,
                "tool_calls": tool_calls
            })
            
            # 执行工具调用
            for tool_call in tool_calls:
                import json
                tool_name = tool_call.get("function", {}).get("name")
                tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                tool_call_id = tool_call.get("id", "")
                
                try:
                    tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                except json.JSONDecodeError:
                    tool_args = {}
                
                logger.info(f"  🔧 调用工具: {tool_name}")
                logger.info(f"     参数: {json.dumps(tool_args, ensure_ascii=False)}")
                
                # 🎯 不发送工具状态到前端（避免显示多余气泡）
                import json as json_lib
                # yield f"__TOOL_STATUS__{json_lib.dumps({'tool': tool_name, 'status': 'calling', 'args': tool_args}, ensure_ascii=False)}__END__"
                
                # 执行工具
                try:
                    result = await mcp_client.call_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        session_id=session_id,
                        user_id=user_id
                    )
                    
                    logger.info(f"  ✅ 工具执行成功: {tool_name}")
                    logger.info(f"     结果: {result[:200]}...")
                    
                    # 🎯 特殊处理：拦截 search_knowledge_base 的结果，提取引用信息
                    if tool_name == "search_knowledge_base":
                        try:
                            result_data = json.loads(result) if isinstance(result, str) else result
                            if result_data.get("success") and result_data.get("results"):
                                # 提取引用（与旧 RAG 模式格式保持一致）
                                rich_refs = []
                                lean_refs = []
                                
                                for item in result_data["results"]:
                                    metadata = item.get("metadata", {})
                                    # 精简引用（用于保存到数据库）
                                    # 🆕 添加查看原文所需的字段
                                    lean = {
                                        "document_id": metadata.get("document_id") or metadata.get("source"),
                                        "chunk_id": metadata.get("chunk_id"),
                                        "score": item.get("score", 0.0),
                                        "doc_id": metadata.get("doc_id", ""),
                                        "kb_id": metadata.get("kb_id", ""),
                                        "filename": metadata.get("filename", "")
                                    }
                                    lean_refs.append(lean)
                                    
                                    # 完整引用（用于前端显示）
                                    rich = {
                                        "document_id": lean["document_id"],
                                        "chunk_id": lean["chunk_id"],
                                        "score": lean["score"],
                                        "document_name": metadata.get("source"),
                                        "content": item.get("content", ""),
                                        "metadata": metadata,
                                        # 🆕 添加查看原文所需的字段到顶层
                                        "doc_id": metadata.get("doc_id", ""),
                                        "kb_id": metadata.get("kb_id", ""),
                                        "filename": metadata.get("filename", "")
                                    }
                                    rich_refs.append(rich)
                                
                                # ❌ 不在这里发送引用数据！因为还没去重排序！
                                # 引用数据会在 streaming_manager 的去重排序后统一发送
                                if rich_refs:
                                    logger.info(f"  📚 提取到 {len(rich_refs)} 条知识库引用（等待去重排序后发送）")
                                    # yield f"__REFERENCES__{json_lib.dumps({'rich': rich_refs, 'lean': lean_refs}, ensure_ascii=False)}__END__"
                        except Exception as ref_err:
                            logger.warning(f"  ⚠️ 提取引用信息失败: {ref_err}")
                    
                    # 🎯 不发送工具执行成功状态到前端（避免显示多余气泡）
                    # yield f"__TOOL_STATUS__{json_lib.dumps({'tool': tool_name, 'status': 'success'}, ensure_ascii=False)}__END__"
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": result
                    })
                
                except Exception as e:
                    logger.error(f"  ❌ 工具执行失败: {tool_name}, 错误: {e}")
                    
                    # 🎯 不发送工具执行失败状态到前端（避免显示多余气泡）
                    # yield f"__TOOL_STATUS__{json_lib.dumps({'tool': tool_name, 'status': 'error', 'error': str(e)}, ensure_ascii=False)}__END__"
                    
                    import json
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps({"error": str(e)}, ensure_ascii=False)
                    })
        
        if iteration >= max_iter:  # 👈 使用全局配置
            logger.warning(f"⚠️ 达到最大工具调用次数 ({max_iter})，强制生成最终回复")
            
            # 添加系统消息，提示模型工具调用次数已达上限
            messages.append({
                "role": "system",
                "content": "⚠️ 工具调用次数已达上限，请根据已获取的信息生成最终回复。"
            })
            
            # 强制调用一次 LLM 生成最终回复（不带工具）
            try:
                # 🎯 提取用户自定义模型参数
                model_params = model_settings.get("modelParams", {})
                # 🖼️ 传递图片数据及其他参数（session_id, message_id, user_id等）
                images_base64 = kwargs.get('images_base64')
                # 创建不包含images_base64的kwargs副本,避免重复传递
                other_kwargs = {k: v for k, v in kwargs.items() if k != 'images_base64'}
                if images_base64:
                    response = current_service._call_llm_with_tools_sync(messages, [], model_params, images_base64, **other_kwargs)
                else:
                    # ⚠️ 即使没有图片，也要传递 other_kwargs（包含 session_id, message_id, user_id）
                    response = current_service._call_llm_with_tools_sync(messages, [], model_params, **other_kwargs)
                final_content = response.get("content", "")
                
                if final_content:
                    logger.info(f"✅ 生成最终回复（工具调用上限后）: {final_content[:100]}...")
                    # 流式输出
                    for char in final_content:
                        yield char
                else:
                    # 如果还是没有内容，返回提示信息
                    fallback_msg = "\n\n⚠️ 已达到最大工具调用次数，但我已为您收集了相关信息。如需更多帮助，请尝试简化问题或分批次询问。"
                    for char in fallback_msg:
                        yield char
                        
            except Exception as e:
                logger.error(f"❌ 生成最终回复失败: {e}")
                error_msg = f"\n\n⚠️ 系统错误：工具调用次数达到上限后生成回复失败。错误信息：{str(e)}"
                for char in error_msg:
                    yield char
    
    def _create_service_instance(self, model_service: str, base_url: str, api_key: str, model_name: str):
        """创建服务实例"""
        if model_service == "deepseek":
            return DeepSeekService(base_url, api_key, model_name)
        elif model_service == "ollama":
            return OllamaService(base_url, api_key, model_name)
        elif model_service == "doubao":
            return DouBaoService(base_url, api_key, model_name)
        elif model_service == "bailian":
            return BaiLianService(base_url, api_key, model_name)
        elif model_service == "siliconflow":
            return SiliconFlowService(base_url, api_key, model_name)
        elif model_service == "zhipu":
            return ZhipuService(base_url, api_key, model_name)
        elif model_service == "hunyuan":
            return HunyuanService(base_url, api_key, model_name)
        elif model_service == "moonshot":
            return MoonshotService(base_url, api_key, model_name)
        elif model_service == "stepfun":
            return StepfunService(base_url, api_key, model_name)
        elif model_service == "modelscope":
            return ModelScopeService(base_url, api_key, model_name)
        return None
    
    def _build_messages(self, system_prompt: str, history: List[Dict[str, Any]], user_message: str) -> List[Dict[str, Any]]:
        """构建消息列表"""
        messages = []
        
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        
        if history:
            for msg in history:
                # 🖼️ 【关键修复】保留历史消息中的图片信息
                message = {
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                }
                
                # 如果历史消息包含图片，保留 images 字段（MinIO URL）
                if 'images' in msg and msg['images']:
                    message['images'] = msg['images']
                    logger.info(f"📸 历史消息包含 {len(msg['images'])} 张图片（将由_process_request_data转换为base64）")
                
                messages.append(message)
        
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    async def generate_with_tools_non_streaming(
        self,
        user_message: str,
        history: List[Dict[str, Any]],
        model_settings: Dict[str, Any],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        max_tool_iterations: Optional[int] = None,  # 👈 改为可选，自动读取全局配置
        extra_tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        带工具调用的非流式生成（用于群聊等场景）
        
        Args:
            max_tool_iterations: 最大工具调用迭代次数，None时使用全局配置 (tool_config.max_iterations)
            extra_tools: 额外注入的工具列表（例如群聊专用工具）
        
        Returns:
            dict: {
                "content": "最终回复内容",
                "tool_calls_made": ["tool1", "tool2"],  # 调用过的工具列表
                "skip_reply": bool,  # 是否调用了 skip_reply 工具
                "references": []  # 知识库引用列表（精简格式，已去重排序）
            }
        """
        # 👇 使用全局配置或传入参数
        max_iter = max_tool_iterations if max_tool_iterations is not None else tool_config.max_iterations
        logger.info(f"🔧 [generate_with_tools_non_streaming] 最大迭代次数: {max_iter} (全局配置: {tool_config.max_iterations})")
        from app.mcp.manager import mcp_manager
        
        # 检查 MCP 是否可用
        mcp_client = mcp_manager.get_client()
        if not mcp_client:
            logger.warning("⚠️ MCP Client 未初始化，回退到普通模式")
            # 使用普通模式生成
            full_response = ""
            async for chunk in self.generate_stream(
                user_message, history, model_settings, system_prompt, session_id, **kwargs
            ):
                full_response += chunk
            return {
                "content": full_response,
                "tool_calls_made": [],
                "skip_reply": False,
                "references": []
            }
        
        # 获取工具列表
        try:
            tools = await mcp_client.list_tools(session_id=session_id, user_id=user_id)
            if not tools:
                tools = []
            
            # 合并额外工具
            if extra_tools:
                tools.extend(extra_tools)
                logger.info(f"✨ 注入了 {len(extra_tools)} 个额外工具")
            
            if not tools:
                logger.info("ℹ️ 无可用工具，使用普通模式")
                full_response = ""
                async for chunk in self.generate_stream(
                    user_message, history, model_settings, system_prompt, session_id, **kwargs
                ):
                    full_response += chunk
                return {
                    "content": full_response,
                    "tool_calls_made": [],
                    "skip_reply": False,
                    "references": []
                }
            
            logger.info(f"🔧 已加载 {len(tools)} 个 MCP 工具")
        except Exception as e:
            logger.error(f"❌ 获取工具列表失败: {e}")
            full_response = ""
            async for chunk in self.generate_stream(
                user_message, history, model_settings, system_prompt, session_id, **kwargs
            ):
                full_response += chunk
            return {
                "content": full_response,
                "tool_calls_made": [],
                "skip_reply": False,
                "references": []
            }
        
        # 创建服务实例
        model_service = model_settings.get("modelService", "deepseek")
        base_url = model_settings.get("baseUrl", "")
        api_key = model_settings.get("apiKey", "")
        model_name = model_settings.get("modelName", "")
        
        current_service = self._create_service_instance(model_service, base_url, api_key, model_name)
        if not current_service:
            raise ValueError(f"不支持的模型服务: {model_service}")
        
        # 检查是否支持工具调用
        if not hasattr(current_service, '_call_llm_with_tools_sync'):
            logger.warning(f"⚠️ {model_service} 服务不支持工具调用，使用普通模式")
            full_response = ""
            async for chunk in self.generate_stream(
                user_message, history, model_settings, system_prompt, session_id, **kwargs
            ):
                full_response += chunk
            return {
                "content": full_response,
                "tool_calls_made": [],
                "skip_reply": False,
                "references": []
            }
        
        # 🆕 创建 streaming_manager 实例来处理引用（复用去重排序逻辑）
        from app.utils.llm.streaming_manager import UniversalStreamingManager
        streaming_manager = UniversalStreamingManager()
        
        # 执行工具调用循环
        iteration = 0
        messages = self._build_messages(system_prompt, history, user_message)
        tool_calls_made = []
        skip_reply_called = False
        
        while iteration < max_iter:  # 👈 使用全局配置
            iteration += 1
            logger.info(f"🔄 工具调用迭代 {iteration}/{max_iter}")
            
            # 调用 LLM
            try:
                model_params = model_settings.get("modelParams", {})
                images_base64 = kwargs.get('images_base64')
                other_kwargs = {k: v for k, v in kwargs.items() if k != 'images_base64'}
                
                if images_base64:
                    response = current_service._call_llm_with_tools_sync(
                        messages, tools, model_params, images_base64, **other_kwargs
                    )
                else:
                    response = current_service._call_llm_with_tools_sync(
                        messages, tools, model_params, **other_kwargs
                    )
            except Exception as e:
                logger.error(f"❌ LLM 调用失败: {e}")
                return {
                    "content": f"[错误] LLM 调用失败: {str(e)}",
                    "tool_calls_made": tool_calls_made,
                    "skip_reply": skip_reply_called,
                    "references": []
                }
            
            # 检查工具调用
            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                # 无工具调用，返回最终回复
                final_content = response.get("content", "")
                logger.info("✅ LLM 返回最终回复（无工具调用）")
                
                # 🆕 提取最终的引用数据
                final_references = []
                if hasattr(streaming_manager, '_pending_references') and session_id in streaming_manager._pending_references:
                    refs_data = streaming_manager._pending_references[session_id]
                    final_references = refs_data.get("lean", [])
                    logger.info(f"📚 返回 {len(final_references)} 条知识库引用")
                
                return {
                    "content": final_content,
                    "tool_calls_made": tool_calls_made,
                    "skip_reply": skip_reply_called,
                    "references": final_references
                }
            
            # 有工具调用
            logger.info(f"🔧 LLM 请求调用 {len(tool_calls)} 个工具")
            
            # 添加 assistant 消息
            messages.append({
                "role": "assistant",
                "content": response.get("content") or None,
                "tool_calls": tool_calls
            })
            
            # 执行工具调用
            for tool_call in tool_calls:
                import json
                tool_name = tool_call.get("function", {}).get("name")
                tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                tool_call_id = tool_call.get("id", "")
                
                try:
                    tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                except json.JSONDecodeError:
                    tool_args = {}
                
                logger.info(f"  🔧 调用工具: {tool_name}")
                logger.info(f"     参数: {json.dumps(tool_args, ensure_ascii=False)}")
                
                # 记录工具调用
                tool_calls_made.append(tool_name)
                
                # 🎯 检测 skip_reply 工具
                if tool_name == "skip_reply":
                    skip_reply_called = True
                    logger.info(f"  🤐 检测到 skip_reply 工具调用")
                
                # 执行工具
                try:
                    result = await mcp_client.call_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        session_id=session_id,
                        user_id=user_id
                    )
                    
                    logger.info(f"  ✅ 工具执行成功: {tool_name}")
                    # 🔧 修复：result 可能是字典，不能直接切片
                    result_str = str(result) if result else 'None'
                    logger.info(f"     结果: {result_str[:200]}...")
                    
                    # 🆕 特殊处理：如果是知识库检索工具，收集引用数据（复用 streaming_manager 的逻辑）
                    if tool_name == "search_knowledge_base" and isinstance(result, str):
                        try:
                            result_data = json.loads(result)
                            if result_data.get("success") and result_data.get("results"):
                                # 初始化引用存储
                                if not hasattr(streaming_manager, '_pending_references'):
                                    streaming_manager._pending_references = {}
                                if session_id not in streaming_manager._pending_references:
                                    streaming_manager._pending_references[session_id] = {"rich": [], "lean": []}
                                
                                # 🔥 修复：与streaming_manager._execute_tools_parallel()保持完全一致的引用构建逻辑
                                rich_refs = []
                                lean_refs = []
                                
                                for item in result_data.get("results", []):
                                    meta = item.get("metadata", {})
                                    
                                    # 🆕 使用工具返回的全局序号（已在knowledge_retrieval.py中分配）
                                    global_marker = item.get("ref_marker")
                                    if not global_marker:
                                        logger.warning(f"⚠️ 检索结果缺少ref_marker字段！item: {item.keys()}")
                                        continue
                                    
                                    # 获取chunk_id（可能为空）
                                    chunk_id = meta.get("chunk_id", "")
                                    
                                    # 🎯 【关键修复】生成唯一的ref_id用于去重
                                    # 使用 chunk_id 作为唯一标识（如果没有则用内容哈希）
                                    import hashlib
                                    if chunk_id:
                                        ref_id = chunk_id
                                    else:
                                        # 如果没有chunk_id，用内容哈希作为唯一标识
                                        content = item.get("content", "")
                                        ref_id = hashlib.md5(content.encode('utf-8')).hexdigest()
                                    
                                    # Rich格式：包含完整内容和元数据（发送到前端）
                                    rich_refs.append({
                                        "ref_id": ref_id,  # 🎯 唯一标识（用于去重）
                                        "ref_marker": global_marker,  # 🆕 全局序号（用于##数字$$引用）
                                        "document_id": meta.get("document_id") or meta.get("source"),
                                        "chunk_id": chunk_id,
                                        "score": item.get("score", 0.0),
                                        "document_name": meta.get("source"),
                                        "content": item.get("content", ""),
                                        "metadata": meta,
                                        "doc_id": meta.get("doc_id", ""),
                                        "kb_id": meta.get("kb_id", ""),
                                        "filename": meta.get("filename", "")
                                    })
                                    
                                    # Lean格式：仅保存索引信息（保存到数据库）
                                    lean_refs.append({
                                        "ref_id": ref_id,  # 🎯 唯一标识（用于去重）
                                        "ref_marker": global_marker,  # 🆕 全局序号
                                        "document_id": meta.get("document_id") or meta.get("source"),
                                        "chunk_id": chunk_id,
                                        "score": item.get("score", 0.0),
                                        "doc_id": meta.get("doc_id", ""),
                                        "kb_id": meta.get("kb_id", ""),
                                        "filename": meta.get("filename", "")
                                    })
                                
                                # 追加到待处理引用
                                streaming_manager._pending_references[session_id]["rich"].extend(rich_refs)
                                streaming_manager._pending_references[session_id]["lean"].extend(lean_refs)
                                
                                logger.info(f"  📚 收集到 {len(rich_refs)} 条知识库引用（ref_marker范围: {rich_refs[0].get('ref_marker') if rich_refs else '?'} - {rich_refs[-1].get('ref_marker') if rich_refs else '?'}）")
                        except json.JSONDecodeError:
                            logger.warning(f"  ⚠️ 无法解析知识库检索结果")
                        except Exception as ref_err:
                            logger.error(f"  ❌ 提取引用数据失败: {ref_err}")
                    
                except Exception as tool_err:
                    logger.error(f"  ❌ 工具执行失败: {tool_name} | 错误: {tool_err}")
                    result = f"工具调用失败: {str(tool_err)}"
                
                # 添加工具结果
                # 🔧 确保 content 是字符串（LLM API 要求）
                import json
                content_str = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": content_str
                })
            
            # 🆕 每轮工具调用后进行去重（复用 streaming_manager 的去重逻辑）
            await streaming_manager._deduplicate_knowledge_base_results(
                session_id=session_id,
                tool_calls=tool_calls
            )
        
        # 达到最大迭代次数
        logger.warning(f"⚠️ 达到最大工具调用次数 ({max_iter})")
        
        # 🆕 提取最终的引用数据
        final_references = []
        if hasattr(streaming_manager, '_pending_references') and session_id in streaming_manager._pending_references:
            refs_data = streaming_manager._pending_references[session_id]
            final_references = refs_data.get("lean", [])
        
        return {
            "content": "[提示] 已达到最大工具调用次数，请稍后重试。",
            "tool_calls_made": tool_calls_made,
            "skip_reply": skip_reply_called,
            "references": final_references
        } 