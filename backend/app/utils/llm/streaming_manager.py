"""
通用流式输出管理器

解决所有模型的流式输出问题，支持工具调用，确保真正的异步并发处理
"""

import asyncio
import json
import logging
import time
import concurrent.futures
from typing import AsyncGenerator, Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import uuid
from .streaming_config import streaming_config
from .tool_config import tool_config  # 👈 导入全局配置

logger = logging.getLogger(__name__)


class StreamingState(Enum):
    """流式输出状态"""
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    GENERATING = "generating"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class StreamingSession:
    """流式会话信息"""
    session_id: str
    user_id: str
    websocket: Any
    state: StreamingState = StreamingState.IDLE
    current_task: Optional[asyncio.Task] = None
    start_time: float = 0
    last_activity: float = 0
    
    def __post_init__(self):
        self.start_time = time.time()
        self.last_activity = time.time()


class UniversalStreamingManager:
    """
    通用流式输出管理器
    
    特性：
    1. 支持所有模型的真正流式输出
    2. 工具调用期间的实时进度反馈
    3. 真正的异步并发，用户之间不会相互阻塞
    4. 智能的流式输出优化
    5. 完善的错误处理和恢复机制
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, StreamingSession] = {}
        self.session_lock = asyncio.Lock()
        self.thread_pool = None
        self._cleanup_task = None
        
        # 初始化线程池（如果启用）
        if streaming_config.use_thread_pool_for_sync_calls:
            self.thread_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=streaming_config.thread_pool_max_workers
            )
        
        # 延迟启动清理任务（在有事件循环时启动）
        self._cleanup_task = None
        self._cleanup_started = False
        
        # 🆕 并发控制信号量（每个会话独立）
        self._tool_semaphores: Dict[str, asyncio.Semaphore] = {}
        
        # 🆕 工具调用缓存（如果启用）
        self._tool_cache: Dict[str, Any] = {}  # {cache_key: result}
        
        # 🆕 工具调用统计（如果启用）
        self._tool_stats: Dict[str, Dict[str, Any]] = {}  # {session_id: stats}
    
    def _start_cleanup_task(self):
        """启动清理任务（如果有事件循环）"""
        if self._cleanup_started:
            return
            
        try:
            # 检查是否有运行中的事件循环
            loop = asyncio.get_running_loop()
            
            async def cleanup_loop():
                while True:
                    try:
                        await asyncio.sleep(streaming_config.cleanup_interval)
                        await self._cleanup_expired_sessions()
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"清理任务出错: {e}")
            
            self._cleanup_task = asyncio.create_task(cleanup_loop())
            self._cleanup_started = True
            logger.info("✅ 清理任务已启动")
        except RuntimeError:
            # 没有运行中的事件循环，稍后启动
            logger.debug("暂无事件循环，清理任务将在首次使用时启动")
    
    async def _cleanup_expired_sessions(self):
        """清理过期会话"""
        current_time = time.time()
        expired_sessions = []
        
        async with self.session_lock:
            for session_id, session in self.active_sessions.items():
                if current_time - session.last_activity > streaming_config.session_timeout:
                    expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            logger.info(f"清理过期会话: {session_id}")
            await self.unregister_session(session_id)
    
    async def shutdown(self):
        """关闭管理器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
        
        # 清理所有会话
        session_ids = list(self.active_sessions.keys())
        for session_id in session_ids:
            await self.unregister_session(session_id)
        
    async def register_session(self, session_id: str, user_id: str, websocket: Any) -> StreamingSession:
        """注册新的流式会话"""
        # 确保清理任务已启动
        self._start_cleanup_task()
        
        async with self.session_lock:
            session = StreamingSession(
                session_id=session_id,
                user_id=user_id,
                websocket=websocket
            )
            self.active_sessions[session_id] = session
            logger.info(f"🔗 注册流式会话: {session_id} (用户: {user_id})")
            return session
    
    async def unregister_session(self, session_id: str):
        """注销流式会话"""
        async with self.session_lock:
            if session_id in self.active_sessions:
                session = self.active_sessions[session_id]
                if session.current_task and not session.current_task.done():
                    session.current_task.cancel()
                del self.active_sessions[session_id]
                logger.info(f"🔌 注销流式会话: {session_id}")
    
    async def update_session_state(self, session_id: str, state: StreamingState, 
                                 message: Optional[str] = None):
        """更新会话状态并通知前端"""
        if session_id not in self.active_sessions:
            return
            
        session = self.active_sessions[session_id]
        session.state = state
        session.last_activity = time.time()
        
        # 发送状态更新到前端
        try:
            status_data = {
                "type": "status_update",
                "state": state.value,
                "message": message,
                "timestamp": time.time()
            }
            await session.websocket.send_json(status_data)
        except Exception as e:
            logger.warning(f"发送状态更新失败: {e}")
    
    async def send_tool_status(self, session_id: str, tool_name: str, status: str, 
                             args: Optional[Dict] = None, error: Optional[str] = None):
        """发送工具状态到前端（用于状态气泡显示）"""
        if session_id not in self.active_sessions:
            return
            
        session = self.active_sessions[session_id]
        
        try:
            tool_status_data = {
                "type": "tool_status",
                "tool": tool_name,
                "status": status,  # calling, success, error
                "args": args,
                "error": error
            }
            await session.websocket.send_json(tool_status_data)
            logger.debug(f"🔧 发送工具状态: {tool_name} - {status}")
        except Exception as e:
            logger.warning(f"发送工具状态失败: {e}")
    
    async def generate_stream_universal(
        self,
        session_id: str,
        llm_service: Any,
        user_message: str,
        history: List[Dict[str, Any]],
        model_settings: Dict[str, Any],
        system_prompt: Optional[str] = None,
        enable_tools: bool = True,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        通用流式生成方法
        
        支持所有模型，自动处理工具调用，确保真正的流式输出
        """
        
        if session_id not in self.active_sessions:
            raise ValueError(f"会话未注册: {session_id}")
        
        session = self.active_sessions[session_id]
        
        try:
            # ⚠️ 【关键修复】每次新对话开始时清空上次保存的图片URL
            if hasattr(llm_service, 'last_saved_images'):
                llm_service.last_saved_images = []
                logger.debug("🧹 已清空上次保存的图片URL")
            
            # 更新状态为思考中
            await self.update_session_state(session_id, StreamingState.THINKING, "正在分析您的问题...")
            
            # 检查是否需要工具调用（传递model_settings用于模型能力检查）
            should_use_tools = await self._should_use_tools(user_message, llm_service, model_settings)
            
            if enable_tools and should_use_tools:
                # 使用工具调用流式生成
                async for chunk in self._generate_with_tools_streaming(
                    session_id, llm_service, user_message, history, 
                    model_settings, system_prompt, **kwargs
                ):
                    yield chunk
            else:
                # 直接流式生成
                await self.update_session_state(session_id, StreamingState.GENERATING, "正在生成回复...")
                async for chunk in self._generate_direct_streaming(
                    session_id, llm_service, user_message, history,
                    model_settings, system_prompt, **kwargs
                ):
                    yield chunk
            
            # 完成
            await self.update_session_state(session_id, StreamingState.COMPLETED, "回复完成")
            
        except Exception as e:
            logger.error(f"流式生成错误: {e}")
            await self.update_session_state(session_id, StreamingState.ERROR, f"生成失败: {str(e)}")
            yield f"\n[错误] 生成失败: {str(e)}\n"
    
    async def _should_use_tools(
        self, 
        user_message: str, 
        llm_service: Any,
        model_settings: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        判断是否需要使用工具调用
        
        检查顺序：
        1. 检查服务是否支持工具调用方法
        2. 检查模型是否在黑名单中（已知不支持）
        """
        
        # 1. 检查LLM服务是否支持工具调用
        if not hasattr(llm_service, 'generate_with_tools') and \
           not hasattr(llm_service, '_call_llm_with_tools_sync'):
            logger.debug("LLM服务不支持工具调用方法")
            return False
        
        # 2. 检查模型是否已知不支持工具调用
        if model_settings:
            model_name = model_settings.get("modelName", "")
            if model_name:
                try:
                    from .model_capability_manager import model_capability_manager
                    
                    # 查询模型能力（三层缓存：本地 → Redis → MongoDB）
                    supports = await model_capability_manager.check_supports_tools(model_name)
                    
                    if not supports:
                        logger.info(f"🚫 模型 {model_name} 已知不支持工具调用，跳过MCP")
                        return False
                    
                except Exception as e:
                    logger.warning(f"⚠️ 查询模型能力失败，默认允许尝试: {e}")
        
        return True
    
    async def _generate_direct_streaming(
        self,
        session_id: str,
        llm_service: Any,
        user_message: str,
        history: List[Dict[str, Any]],
        model_settings: Dict[str, Any],
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """直接流式生成（无工具调用）"""
        
        # 🐛 调试：检查images_base64是否存在
        images_base64 = kwargs.get('images_base64', [])
        logger.info(f"🖼️ [streaming_manager._generate_direct_streaming] 接收到images_base64: {len(images_base64) if images_base64 else 0}张图片")
        logger.info(f"🖼️ [streaming_manager._generate_direct_streaming] kwargs包含: {list(kwargs.keys())}")
        
        try:
            async for chunk in llm_service.generate_stream(
                user_message=user_message,
                history=history,
                model_settings=model_settings,
                system_prompt=system_prompt,
                session_id=session_id,
                **kwargs
            ):
                # 更新会话活动时间
                if session_id in self.active_sessions:
                    self.active_sessions[session_id].last_activity = time.time()
                yield chunk
                
        except Exception as e:
            logger.error(f"直接流式生成失败: {e}")
            raise
    
    async def _generate_with_tools_streaming(
        self,
        session_id: str,
        llm_service: Any,
        user_message: str,
        history: List[Dict[str, Any]],
        model_settings: Dict[str, Any],
        system_prompt: Optional[str] = None,
        max_iterations: Optional[int] = None,  # 👈 改为可选，自动读取全局配置
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        带工具调用的流式生成
        
        核心优化：
        1. 并行处理工具调用和状态更新
        2. 智能的流式输出缓冲
        3. 实时进度反馈
        
        参数:
            max_iterations: 最大迭代次数，None时使用全局配置 (tool_config.max_iterations)
        """
        
        # 👇 使用全局配置或传入参数
        max_iter = max_iterations if max_iterations is not None else tool_config.max_iterations
        logger.info(f"🔧 工具调用最大迭代次数: {max_iter} (全局配置: {tool_config.max_iterations})")
        
        from ...mcp.manager import mcp_manager
        
        # 获取MCP客户端
        mcp_client = mcp_manager.get_client()
        if not mcp_client:
            logger.warning("MCP客户端未初始化，回退到直接流式生成")
            async for chunk in self._generate_direct_streaming(
                session_id, llm_service, user_message, history, 
                model_settings, system_prompt, **kwargs
            ):
                yield chunk
            return
        
        # 获取用户ID（从已注册的会话中）
        session = self.active_sessions.get(session_id)
        user_id = session.user_id if session else None
        
        # 获取可用工具（传递session_id和user_id以支持用户工具配置过滤）
        tools = await mcp_client.list_tools(session_id=session_id, user_id=user_id)
        if not tools:
            logger.info("无可用工具，使用直接流式生成")
            async for chunk in self._generate_direct_streaming(
                session_id, llm_service, user_message, history,
                model_settings, system_prompt, **kwargs
            ):
                yield chunk
            return
        
        # 构建消息列表
        messages = llm_service._build_messages(system_prompt or "", history, user_message)
        iteration = 0
        has_output_started = False  # 🎯 追踪是否已经开始输出内容
        reached_limit = False  # 🎯 追踪是否真的达到了迭代上限
        last_iteration_had_tool_calls = False  # 🎯 追踪上一次迭代是否同时输出了 content 和 tool_calls
        
        # 🆕 总超时控制
        workflow_start_time = time.time()
        
        while iteration < max_iter:  # 👈 使用全局配置
            iteration += 1
            
            # 🆕 检查总超时
            elapsed_time = time.time() - workflow_start_time
            if elapsed_time > tool_config.total_timeout:
                logger.warning(f"⚠️ 工具调用流程总超时（{elapsed_time:.1f}秒 > {tool_config.total_timeout}秒）")
                if tool_config.force_reply_on_max_iterations:
                    yield "\n\n⚠️ 工具调用超时，正在生成最终回复...\n\n"
                    # 添加系统消息，提示模型超时
                    messages.append({
                        "role": "system",
                        "content": f"⚠️ 工具调用已超时（{elapsed_time:.1f}秒），请根据已获取的信息生成最终回复。"
                    })
                    # 强制生成最终回复
                    async for chunk in self._generate_direct_streaming(
                        session_id, llm_service, "", [], model_settings, None, 
                        messages=messages, **kwargs
                    ):
                        yield chunk
                break
            
            logger.info(f"🔄 工具调用迭代 {iteration}/{max_iter} (已用时: {elapsed_time:.1f}秒/{tool_config.total_timeout}秒)")
            
            # 🎯 累积模型在工具调用前输出的描述文字
            accumulated_content = ""
            is_first_content_in_iteration = True  # 🎯 追踪当前迭代是否是第一次输出内容
            logger.info(f"🔍 迭代 {iteration} 开始，last_iteration_had_tool_calls={last_iteration_had_tool_calls}")
            
            try:
                # 🚀 真流式：直接使用异步流式生成器
                async for event in self._call_llm_streaming_with_tools(
                    llm_service, messages, tools, session_id, model_settings, **kwargs
                ):
                    # 处理不同类型的事件
                    if event["type"] == "content_delta":
                        # 🎯 内容片段直接输出（真流式！）
                        if not has_output_started:
                            await self.update_session_state(
                                session_id,
                                StreamingState.GENERATING,
                                None
                            )
                            has_output_started = True
                            logger.info("✅ 首次输出（真流式内容），已通知前端隐藏状态气泡")
                        
                        # 🎯 如果上一次迭代同时输出了 content 和 tool_calls，且当前是第一次输出内容，插入分隔符
                        # 作用：分隔工具调用时的描述文字（如"🔍 正在检索..."）和最终回复内容
                        if last_iteration_had_tool_calls and is_first_content_in_iteration and event["content"].strip():
                            yield "\n\n---\n\n"
                            is_first_content_in_iteration = False
                            logger.info(f"✅ 第 {iteration} 次迭代，插入分隔线分隔工具调用描述和最终回复")
                        
                        # 🎯 标记当前迭代已经输出过 content
                        if event["content"].strip() and is_first_content_in_iteration:
                            is_first_content_in_iteration = False
                        
                        # 🎯 累积内容（用于保存到消息历史）
                        accumulated_content += event["content"]
                        
                        # 直接透传内容（不累积、不模拟）
                        yield event["content"]
                        if session_id in self.active_sessions:
                            self.active_sessions[session_id].last_activity = time.time()
                    
                    elif event["type"] == "tool_calls":
                        # 🎯 收到工具调用请求
                        tool_calls = event["tool_calls"]
                        logger.info(f"🔧 需要调用 {len(tool_calls)} 个工具（真流式）")
                        
                        # 🎯 如果模型输出了描述文字，记录日志
                        if accumulated_content.strip():
                            logger.info(f"💬 模型工具调用描述: {accumulated_content[:100]}")
                        
                        # 🎯 标记：当前迭代同时输出了 content 和 tool_calls
                        # 只有当 accumulated_content 非空时才标记（如果 content 为 null 则不标记）
                        last_iteration_had_tool_calls = bool(accumulated_content.strip())
                        logger.info(f"🔍 设置 last_iteration_had_tool_calls={last_iteration_had_tool_calls}, accumulated_content={accumulated_content[:50]}")
                        
                        # 添加到消息历史（保留模型输出的描述）
                        messages.append({
                            "role": "assistant",
                            "content": accumulated_content if accumulated_content.strip() else None,
                            "tool_calls": tool_calls
                        })
                        
                        # 跳出事件循环，准备执行工具
                        break
                    
                    elif event["type"] == "done":
                        # 🎯 流式完成（无工具调用）
                        logger.info("✅ 真流式完成，无工具调用")
                        
                        # 🖼️ 保存图片
                        await self._save_pending_images_after_tools(llm_service)
                        
                        # 退出迭代循环（正常完成，不是达到上限）
                        iteration = max_iter  # 👈 使用全局配置
                        reached_limit = False  # 明确标记：这是正常完成
                        break
                
                # 检查是否有工具调用需要执行
                if event.get("type") != "tool_calls":
                    # 没有工具调用，结束
                    break
                
                # 有工具调用，继续执行
                tool_calls = event["tool_calls"]
                
            except NotImplementedError as e:
                # 模型不支持工具调用，标记并降级到直接流式生成
                logger.warning(f"⚠️ 模型不支持工具调用，切换到普通对话模式: {e}")
                
                # ✅ 标记模型不支持工具调用（写入MongoDB + Redis + 本地缓存）
                model_name = model_settings.get("modelName", "")
                if model_name:
                    try:
                        from .model_capability_manager import model_capability_manager
                        await model_capability_manager.mark_unsupported(
                            model_name,
                            error_message=str(e),
                            notes="自动检测：工具调用返回NotImplementedError"
                        )
                    except Exception as mark_error:
                        logger.error(f"标记模型能力失败: {mark_error}")
                
                # 降级到普通流式生成
                async for chunk in self._generate_direct_streaming(
                    session_id, llm_service, user_message, history,
                    model_settings, system_prompt, **kwargs
                ):
                    yield chunk
                return
            except Exception as e:
                logger.error(f"LLM调用失败: {e}")
                yield f"\n[错误] 分析失败: {str(e)}\n"
                break
            
            # 🎯 如果还没开始输出，立即隐藏状态气泡
            if not has_output_started:
                await self.update_session_state(
                    session_id,
                    StreamingState.GENERATING,
                    None
                )
                has_output_started = True
                logger.info("✅ 工具调用开始，已通知前端隐藏状态气泡")
            
            # 🎯 移除了"正在调用X个工具..."的状态气泡
            # 因为工具调用思考过程已经在 <think> 标签中显示
            
            tool_results = await self._execute_tools_parallel(
                tool_calls, mcp_client, session_id, kwargs.get('user_id')
            )
            
            # 🎯 检查是否有待发送的引用数据（增量数据）
            if hasattr(self, '_pending_references') and session_id in self._pending_references:
                refs_data = self._pending_references.get(session_id)
                if refs_data and refs_data.get('rich'):
                    # 🔍 调试：打印即将发送的ref_id和序号
                    sending_info = [(r.get("ref_marker", "?"), r.get("ref_id", "")[:8] + "..." if r.get("ref_id") else "EMPTY") for r in refs_data.get('rich', [])]
                    logger.info(f"📤 准备发送 {len(refs_data.get('rich', []))} 条MCP工具引用数据到chat router（迭代 {iteration}/{max_iter}）")  # 👈 使用全局配置
                    logger.info(f"🔍 发送的序号和ref_id: {sending_info}")
                # 通过特殊标记发送引用数据
                refs_json = json.dumps(refs_data, ensure_ascii=False)
                yield f"__REFERENCES__{refs_json}__END__"
                logger.info(f"✅ 已成功发送 {len(refs_data.get('rich', []))} 条增量引用数据到chat router")
                
                # 🎯 【关键修复】发送后清空 _pending_references（但保留 _sent_ref_ids）
                # _pending_references 只存储待发送的增量数据
                # _sent_ref_ids 记录所有已发送的ref_id，用于去重
                self._pending_references[session_id] = {"rich": [], "lean": []}
                logger.info(f"🧹 已清空待发送缓存（已发送的ref_id仍保留用于去重）")
            
            # 添加工具结果到消息列表
            for result in tool_results:
                messages.append(result)
            
            # 🎯 检查是否真的达到了迭代上限（而不是正常完成）
            if iteration >= max_iter:  # 👈 使用全局配置
                reached_limit = True
        
        # 🆕 如果真的达到最大迭代次数（而不是正常完成）
        if reached_limit:
            if tool_config.force_reply_on_max_iterations:
                logger.warning(f"⚠️ 达到最大工具调用次数 ({max_iter})，强制生成最终回复")
                yield "\n\n⚠️ 已达到最大工具调用次数，正在生成最终回复...\n\n"
                
                # 添加系统消息，提示模型工具调用次数已达上限
                messages.append({
                    "role": "system",
                    "content": "⚠️ 工具调用次数已达上限，请根据已获取的信息生成最终回复。"
                })
                
                # 强制调用一次 LLM 生成最终回复（不带工具）
                try:
                    async for chunk in self._generate_direct_streaming(
                        session_id, llm_service, "", [], model_settings, None,
                        messages=messages, **kwargs
                    ):
                        yield chunk
                except Exception as e:
                    logger.error(f"❌ 强制生成最终回复失败: {e}")
                    yield f"\n\n[错误] 生成最终回复失败: {str(e)}\n"
            else:
                yield "\n[提示] 已达到最大工具调用次数，请尝试重新提问。\n"
        
        # 🎯 【关键】工具调用循环结束后，清理该会话的所有引用相关缓存
        # 无论是正常完成还是达到上限，都应该清理
        if hasattr(self, '_pending_references') and session_id in self._pending_references:
            del self._pending_references[session_id]
        if hasattr(self, '_sent_ref_ids') and session_id in self._sent_ref_ids:
            del self._sent_ref_ids[session_id]
        if hasattr(self, '_last_ref_marker') and session_id in self._last_ref_marker:
            del self._last_ref_marker[session_id]
        
        logger.info(f"🧹 工具调用流程结束，已清理会话 {session_id} 的所有引用数据缓存")
        
        # 🆕 输出工具调用统计（如果启用）
        if tool_config.enable_tool_stats and session_id in self._tool_stats:
            stats = self._tool_stats[session_id]
            logger.info(f"📊 工具调用统计 [会话 {session_id}]:")
            logger.info(f"   总调用: {stats['total_calls']}, 成功: {stats['successful_calls']}, 失败: {stats['failed_calls']}, 缓存: {stats['cached_calls']}")
            logger.info(f"   总耗时: {stats['total_time']:.2f}秒")
            if stats['by_tool']:
                logger.info(f"   按工具统计:")
                for tool_name, tool_stats in stats['by_tool'].items():
                    avg_time = tool_stats['total_time'] / tool_stats['calls'] if tool_stats['calls'] > 0 else 0
                    logger.info(f"     - {tool_name}: {tool_stats['calls']}次 (成功:{tool_stats['success']}, 失败:{tool_stats['failed']}, 缓存:{tool_stats['cached']}, 平均:{avg_time:.2f}秒)")
    
    def get_tool_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取工具调用统计"""
        if tool_config.enable_tool_stats and session_id in self._tool_stats:
            return self._tool_stats[session_id].copy()
        return None
    
    def clear_tool_cache(self):
        """清空工具缓存"""
        if tool_config.enable_tool_cache:
            cache_size = len(self._tool_cache)
            self._tool_cache.clear()
            logger.info(f"🧹 已清空工具缓存 ({cache_size} 条记录)")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "enabled": tool_config.enable_tool_cache,
            "size": len(self._tool_cache) if tool_config.enable_tool_cache else 0
        }
    
    async def _call_llm_async_with_tools(
        self, 
        llm_service: Any, 
        messages: List[Dict], 
        tools: List[Dict],
        session_id: str,
        model_settings: Dict[str, Any],
        **kwargs  # 🖼️ 接收图片等额外参数
    ) -> Dict[str, Any]:
        """
        异步调用LLM（带工具）
        
        关键优化：将同步调用包装为异步，避免阻塞事件循环
        """
        
        def sync_call():
            # 获取具体的模型服务实例
            if hasattr(llm_service, '_create_service_instance'):
                # 对于LLMService，使用_create_service_instance方法
                model_service = model_settings.get("modelService", "deepseek")
                base_url = model_settings.get("baseUrl", "")
                api_key = model_settings.get("apiKey", "")
                model_name = model_settings.get("modelName", "")
                current_service = llm_service._create_service_instance(model_service, base_url, api_key, model_name)
            elif hasattr(llm_service, '_get_service'):
                # 对于其他服务，使用_get_service方法
                current_service = llm_service._get_service(model_settings)
            else:
                # 直接使用传入的服务
                current_service = llm_service
            
            if not current_service:
                raise ValueError("无法创建模型服务实例")
            
            if not hasattr(current_service, '_call_llm_with_tools_sync'):
                raise NotImplementedError(f"模型服务 {current_service.__class__.__name__} 不支持工具调用")
            
            # 🖼️ 保存服务实例引用，供图片保存使用
            llm_service._last_service_instance = current_service
            
            # 🎯 提取用户自定义模型参数
            model_params = model_settings.get("modelParams", {})
            logger.info(f"🔧 工具调用传递用户模型参数: {json.dumps(model_params, ensure_ascii=False) if model_params else '无'}")
            
            # 🖼️ 提取并传递图片数据及其他参数（session_id, message_id, user_id等）
            images_base64 = kwargs.pop('images_base64', None)  # 使用pop移除,避免重复传递
            if images_base64:
                logger.info(f"🖼️ 工具调用传递 {len(images_base64)} 张图片")
            
            # ⚠️ 【关键修复】确保session_id在kwargs中（因为它是显式参数，需要手动加回去）
            if 'session_id' not in kwargs:
                kwargs['session_id'] = session_id
            
            # ⚠️ 【关键修复】始终使用关键字参数传递，避免参数位置错乱
            # 🎯 使用流式工具调用（默认启用，自动兼容所有模型）
            return current_service._call_llm_with_tools_sync(
                messages=messages,
                tools=tools,
                model_params=model_params,
                images_base64=images_base64,  # 即使为None也显式传递
                use_streaming=streaming_config.use_streaming_tool_calls,  # 🎯 流式工具调用（默认True）
                **kwargs
            )
        
        # 使用配置的线程池或默认执行器
        loop = asyncio.get_event_loop()
        executor = self.thread_pool if streaming_config.use_thread_pool_for_sync_calls else None
        
        try:
            # 添加超时控制（使用 tool_config 的 llm_call_timeout）
            return await asyncio.wait_for(
                loop.run_in_executor(executor, sync_call),
                timeout=tool_config.llm_call_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"LLM调用超时 (会话: {session_id}, 超时时间: {tool_config.llm_call_timeout}秒)")
            raise Exception(f"LLM调用超时（超过{tool_config.llm_call_timeout}秒）")
        except NotImplementedError:
            # 重新抛出NotImplementedError，让上层处理模型不支持工具调用的情况
            raise
    
    async def _call_llm_streaming_with_tools(
        self,
        llm_service: Any,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        session_id: str,
        model_settings: Dict[str, Any],
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        真流式调用 LLM（带工具支持）
        
        直接使用底层服务的流式生成器，不累积内容
        
        Yields:
            dict: 事件对象
                - {"type": "content_delta", "content": "..."}
                - {"type": "tool_calls", "tool_calls": [...]}
                - {"type": "done", "finish_reason": "stop"}
        """
        # 🎯 获取模型参数（使用正确的键名 modelParams）
        model_params = model_settings.get("modelParams", {})
        logger.info(f"🔧 真流式工具调用传递用户模型参数: {json.dumps(model_params, ensure_ascii=False) if model_params else '无'}")
        
        # 从 kwargs 中提取 images_base64，避免重复传递
        images_base64 = kwargs.pop('images_base64', None)
        
        # 🔧 获取具体的服务实例（根据 model_settings 动态创建，避免使用过期的缓存）
        if hasattr(llm_service, '_create_service_instance'):
            # 对于LLMService，使用_create_service_instance方法
            model_service = model_settings.get("modelService", "deepseek")
            base_url = model_settings.get("baseUrl", "")
            api_key = model_settings.get("apiKey", "")
            model_name = model_settings.get("modelName", "")
            current_service = llm_service._create_service_instance(model_service, base_url, api_key, model_name)
            
            if not current_service:
                raise ValueError(f"无法创建模型服务实例: {model_service}")
            
            # 保存服务实例引用（供图片保存使用）
            llm_service._last_service_instance = current_service
        elif hasattr(llm_service, '_get_service'):
            # 对于其他服务，使用_get_service方法
            current_service = llm_service._get_service(model_settings)
        else:
            # 直接使用传入的服务
            current_service = llm_service
        
        # 检查服务是否支持真流式
        if not hasattr(current_service, '_call_llm_with_tools_streaming'):
            logger.warning("⚠️ 服务不支持真流式，降级到同步模式")
            # 降级：使用同步方法并模拟流式
            response = await self._call_llm_async_with_tools(
                llm_service, messages, tools, session_id, model_settings, 
                images_base64=images_base64, **kwargs
            )
            
            # 检查工具调用
            if response.get("tool_calls"):
                yield {
                    "type": "tool_calls",
                    "tool_calls": response["tool_calls"]
                }
            else:
                # 模拟流式输出内容
                content = response.get("content", "")
                async for chunk in self._smart_streaming_output(content):
                    yield {
                        "type": "content_delta",
                        "content": chunk
                    }
            
            yield {
                "type": "done",
                "finish_reason": "stop"
            }
            return
        
        # 🚀 使用真流式
        async for event in current_service._call_llm_with_tools_streaming(
            messages=messages,
            tools=tools,
            model_params=model_params,
            images_base64=images_base64,
            **kwargs
        ):
            yield event
    
    async def _save_pending_images_after_tools(self, llm_service: Any):
        """
        在工具调用完成后，保存缓存的图片到MinIO
        
        用于工具调用模式下的图片保存，因为工具调用是同步+非流式的，
        需要在最终回复时才触发图片保存逻辑。
        """
        try:
            # 获取具体的服务实例（处理LLMService包装的情况）
            current_service = llm_service
            if hasattr(llm_service, '_last_service_instance'):
                current_service = llm_service._last_service_instance
            
            # 检查是否有缓存的图片数据
            if not hasattr(current_service, '_pending_images'):
                logger.debug("工具调用模式：无缓存的图片数据")
                return
            
            pending = current_service._pending_images
            images_base64 = pending.get('images_base64')
            session_id = pending.get('session_id')
            message_id = pending.get('message_id')
            user_id = pending.get('user_id')
            
            if not images_base64 or not session_id or not message_id:
                logger.warning(f"⚠️ 缓存的图片数据不完整，跳过保存")
                return
            
            logger.info(f"🖼️ 工具调用模式：开始保存 {len(images_base64)} 张缓存图片到MinIO...")
            
            # 调用具体服务的图片保存方法
            if hasattr(current_service, '_save_images_to_minio'):
                saved_images = await current_service._save_images_to_minio(
                    images_base64=images_base64,
                    session_id=session_id,
                    message_id=message_id,
                    user_id=user_id
                )
                
                # 保存到实例变量供外部访问
                current_service.last_saved_images = saved_images
                # ⚠️ 【关键修复】同时保存到 llm_service，供 chat.py 获取
                if hasattr(llm_service, 'last_saved_images'):
                    llm_service.last_saved_images = saved_images
                    logger.info(f"✅ 工具调用模式：成功保存 {len(saved_images)} 张图片并同步到 llm_service")
                else:
                    logger.info(f"✅ 工具调用模式：成功保存 {len(saved_images)} 张图片")
                
                # 清理缓存
                delattr(current_service, '_pending_images')
            else:
                logger.warning(f"⚠️ 服务 {current_service.__class__.__name__} 不支持图片保存")
                
        except Exception as e:
            logger.error(f"❌ 工具调用模式：保存图片失败: {e}", exc_info=True)
    
    async def _deduplicate_knowledge_base_results(
        self,
        session_id: str,
        tool_calls: List[Dict]
    ):
        """
        对知识库检索结果进行全局去重
        
        场景：
        1. 并行调用：模型一次返回多个 search_knowledge_base
        2. 串行调用：模型多轮迭代，每轮都调用 search_knowledge_base
        3. 混合调用：第一轮并行3次，第二轮又并行2次...
        
        策略：
        - 🎯 【关键】全局去重：跨所有轮次累积的所有数据进行去重
        - 使用内容哈希作为去重键
        - 保留分数最高的结果
        - 去重后重新分配全局序号（从1开始连续编号）
        
        注意：
        - 每轮工具调用后都会追加新数据到 _pending_references
        - 本函数负责对累积的所有数据进行去重（包括历史轮次的数据）
        """
        
        # 检查是否有待处理的引用数据
        if not hasattr(self, '_pending_references') or session_id not in self._pending_references:
            return
        
        # 检查本轮是否有 search_knowledge_base 调用
        has_kb_search = any(
            tc.get("function", {}).get("name") == "search_knowledge_base"
            for tc in tool_calls
        )
        
        if not has_kb_search:
            return
        
        refs_data = self._pending_references[session_id]
        rich_refs = refs_data.get("rich", [])
        lean_refs = refs_data.get("lean", [])
        
        if not rich_refs:
            return
        
        logger.info(f"🔄 开始全局去重知识库检索结果（累积总数: {len(rich_refs)} 条）")
        
        # 🎯 使用内容哈希进行全局去重
        import hashlib
        
        def get_content_hash(content: str) -> str:
            """计算内容哈希"""
            return hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # 构建去重字典：{content_hash: (max_score, best_rich_ref, best_lean_ref)}
        dedup_map = {}
        
        # 确保 rich_refs 和 lean_refs 长度一致
        if len(rich_refs) != len(lean_refs):
            logger.warning(f"⚠️ rich_refs 和 lean_refs 长度不一致: {len(rich_refs)} vs {len(lean_refs)}")
            # 截断到较短的长度
            min_len = min(len(rich_refs), len(lean_refs))
            rich_refs = rich_refs[:min_len]
            lean_refs = lean_refs[:min_len]
        
        # 🎯 遍历所有累积的引用（跨所有轮次）
        for rich_ref, lean_ref in zip(rich_refs, lean_refs):
            content = rich_ref.get("content", "")
            if not content:
                continue
            
            content_hash = get_content_hash(content)
            score = rich_ref.get("score", 0.0)
            
            # 保留分数最高的版本
            if content_hash not in dedup_map or score > dedup_map[content_hash][0]:
                dedup_map[content_hash] = (score, rich_ref, lean_ref)
        
        # 提取去重后的结果（按分数降序）
        deduped_items = sorted(dedup_map.values(), key=lambda x: x[0], reverse=True)
        
        # 🎯 【关键修复】保留已发送的旧数据，只标记新增的数据
        # 策略：
        # 1. 记录上一轮已经去重并发送的数据（通过ref_id）
        # 2. 本轮去重后，标记哪些是新增的
        # 3. 只给新增的数据分配新序号
        
        # 获取已发送的ref_id集合
        if not hasattr(self, '_sent_ref_ids'):
            self._sent_ref_ids = {}
        if session_id not in self._sent_ref_ids:
            self._sent_ref_ids[session_id] = set()
        
        # 获取当前的最大序号
        if not hasattr(self, '_last_ref_marker'):
            self._last_ref_marker = {}
        current_max_marker = self._last_ref_marker.get(session_id, 0)
        
        new_rich_refs = []
        new_lean_refs = []
        
        for score, rich_ref, lean_ref in deduped_items:
            ref_id = rich_ref.get("ref_id", "")
            
            if ref_id in self._sent_ref_ids[session_id]:
                # 这是已发送的旧数据，跳过（不添加到待发送列表）
                continue
            else:
                # 这是新数据，分配新序号
                current_max_marker += 1
                rich_ref["ref_marker"] = current_max_marker
                lean_ref["ref_marker"] = current_max_marker
                
                new_rich_refs.append(rich_ref)
                new_lean_refs.append(lean_ref)
                
                # 标记为已发送
                self._sent_ref_ids[session_id].add(ref_id)
        
        # 更新最大序号
        if current_max_marker > 0:
            self._last_ref_marker[session_id] = current_max_marker
        
        # 🎯 更新为去重后的全局数据
        self._pending_references[session_id]["rich"] = new_rich_refs
        self._pending_references[session_id]["lean"] = new_lean_refs
        
        removed_count = len(rich_refs) - len(new_rich_refs)
        logger.info(f"✅ 全局去重完成（去重前: {len(rich_refs)} 条 → 去重后: {len(new_rich_refs)} 条，去除: {removed_count} 条重复）")
        
        # 打印全局序号范围
        if new_rich_refs:
            markers = [r.get("ref_marker") for r in new_rich_refs]
            logger.info(f"📚 全局序号范围: {markers[0]} - {markers[-1]}")
    
    def _get_tool_semaphore(self, session_id: str) -> asyncio.Semaphore:
        """获取会话的工具并发控制信号量"""
        if session_id not in self._tool_semaphores:
            self._tool_semaphores[session_id] = asyncio.Semaphore(tool_config.max_concurrent_tools)
        return self._tool_semaphores[session_id]
    
    def _get_cache_key(self, tool_name: str, tool_args: Dict) -> str:
        """生成工具调用的缓存键"""
        import hashlib
        args_str = json.dumps(tool_args, sort_keys=True, ensure_ascii=False)
        key = f"{tool_name}:{args_str}"
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    
    def _init_tool_stats(self, session_id: str):
        """初始化工具调用统计"""
        if tool_config.enable_tool_stats and session_id not in self._tool_stats:
            self._tool_stats[session_id] = {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "cached_calls": 0,
                "total_time": 0.0,
                "by_tool": {}
            }
    
    def _record_tool_call(self, session_id: str, tool_name: str, success: bool, duration: float, cached: bool = False):
        """记录工具调用统计"""
        if not tool_config.enable_tool_stats:
            return
        
        self._init_tool_stats(session_id)
        stats = self._tool_stats[session_id]
        
        stats["total_calls"] += 1
        stats["total_time"] += duration
        
        if cached:
            stats["cached_calls"] += 1
        elif success:
            stats["successful_calls"] += 1
        else:
            stats["failed_calls"] += 1
        
        # 按工具统计
        if tool_name not in stats["by_tool"]:
            stats["by_tool"][tool_name] = {
                "calls": 0,
                "success": 0,
                "failed": 0,
                "cached": 0,
                "total_time": 0.0
            }
        
        tool_stats = stats["by_tool"][tool_name]
        tool_stats["calls"] += 1
        tool_stats["total_time"] += duration
        
        if cached:
            tool_stats["cached"] += 1
        elif success:
            tool_stats["success"] += 1
        else:
            tool_stats["failed"] += 1
        
        if tool_config.verbose_logging:
            logger.info(f"📊 工具统计 [{tool_name}]: 总调用={stats['total_calls']}, 成功={stats['successful_calls']}, 失败={stats['failed_calls']}, 缓存={stats['cached_calls']}")
    
    def _truncate_tool_result(self, result: str, tool_name: str) -> str:
        """截断过大的工具返回结果"""
        result_bytes = len(result.encode('utf-8'))
        
        if result_bytes > tool_config.max_tool_result_size:
            if tool_config.verbose_logging:
                logger.warning(
                    f"⚠️ 工具 {tool_name} 返回结果过大 "
                    f"({result_bytes} 字节)，截断到 {tool_config.max_tool_result_size} 字节"
                )
            
            # 截断到指定大小
            truncated = result.encode('utf-8')[:tool_config.max_tool_result_size].decode('utf-8', errors='ignore')
            return truncated + f"\n\n⚠️ [结果过大，已截断。原始大小: {result_bytes} 字节，截断后: {tool_config.max_tool_result_size} 字节]"
        
        return result
    
    async def _execute_tools_parallel(
        self,
        tool_calls: List[Dict],
        mcp_client: Any,
        session_id: str,
        user_id: Optional[str]
    ) -> List[Dict]:
        """
        并行执行工具调用（带并发控制、缓存、统计、超时等功能）
        
        新增功能：
        1. 并发控制（max_concurrent_tools）
        2. 工具结果缓存（enable_tool_cache）
        3. 工具调用统计（enable_tool_stats）
        4. 结果大小截断（max_tool_result_size）
        5. 单个工具执行超时（tool_execution_timeout）
        6. 错误继续控制（allow_continue_on_error）
        7. 详细日志控制（verbose_logging）
        """
        
        # 初始化统计
        self._init_tool_stats(session_id)
        
        # 获取并发控制信号量
        semaphore = self._get_tool_semaphore(session_id)
        
        async def execute_single_tool(tool_call):
            tool_name = tool_call.get("function", {}).get("name")
            tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
            tool_call_id = tool_call.get("id", "")
            
            start_time = time.time()
            
            # 🔒 并发控制：获取信号量
            async with semaphore:
                try:
                    # 解析参数
                    if isinstance(tool_args_str, str):
                        tool_args = json.loads(tool_args_str)
                    else:
                        tool_args = tool_args_str
                    
                    if tool_config.verbose_logging:
                        logger.info(f"🔧 执行工具: {tool_name}, 参数: {tool_args}")
                    else:
                        logger.info(f"🔧 执行工具: {tool_name}")
                    
                    # 🎯 检查缓存
                    cache_key = None
                    if tool_config.enable_tool_cache:
                        cache_key = self._get_cache_key(tool_name, tool_args)
                        if cache_key in self._tool_cache:
                            cached_result = self._tool_cache[cache_key]
                            duration = time.time() - start_time
                            self._record_tool_call(session_id, tool_name, True, duration, cached=True)
                            
                            if tool_config.verbose_logging:
                                logger.info(f"💾 使用缓存结果: {tool_name}")
                            
                            return {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "content": str(cached_result)
                            }
                    
                    # 🎯 发送工具状态到前端状态气泡（不是消息气泡）
                    await self.send_tool_status(
                        session_id=session_id,
                        tool_name=tool_name,
                        status="calling",
                        args=tool_args
                    )
                    
                    # 🕐 执行工具（带超时控制）
                    try:
                        result = await asyncio.wait_for(
                            mcp_client.call_tool(
                                tool_name=tool_name,
                                arguments=tool_args,
                                session_id=session_id,
                                user_id=user_id
                            ),
                            timeout=tool_config.tool_execution_timeout
                        )
                    except asyncio.TimeoutError:
                        raise Exception(f"工具执行超时（超过{tool_config.tool_execution_timeout}秒）")
                    
                    duration = time.time() - start_time
                    
                    if tool_config.verbose_logging:
                        logger.info(f"✅ 工具执行成功: {tool_name} (耗时: {duration:.2f}秒)")
                    else:
                        logger.info(f"✅ 工具执行成功: {tool_name}")
                    
                    # 🎯 截断过大的结果
                    result_str = str(result)
                    result_str = self._truncate_tool_result(result_str, tool_name)
                    
                    # 🎯 缓存结果
                    if tool_config.enable_tool_cache and cache_key:
                        self._tool_cache[cache_key] = result_str
                        if tool_config.verbose_logging:
                            logger.info(f"💾 已缓存工具结果: {tool_name}")
                    
                    # 🎯 记录统计
                    self._record_tool_call(session_id, tool_name, True, duration)
                    
                    # 🎯 特殊处理：如果是知识库检索工具，提取并发送引用数据
                    if tool_name == "search_knowledge_base" and isinstance(result_str, str):
                        try:
                            result_data = json.loads(result_str)
                            if result_data.get("success") and result_data.get("results"):
                                # 初始化引用存储
                                if not hasattr(self, '_pending_references'):
                                    self._pending_references = {}
                                if session_id not in self._pending_references:
                                    self._pending_references[session_id] = {"rich": [], "lean": []}
                                
                                # 构建引用数据（rich和lean格式）
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
                                    
                                    # 🔍 调试：记录全局序号
                                    logger.info(f"✅ 提取全局序号 {global_marker}: ref_id={ref_id[:12]}..., source={meta.get('source', 'Unknown')}")
                                    
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
                                        # 🆕 添加查看原文所需的字段到顶层
                                        "doc_id": meta.get("doc_id", ""),
                                        "kb_id": meta.get("kb_id", ""),
                                        "filename": meta.get("filename", "")
                                    })
                                    
                                    # Lean格式：仅保存索引信息（保存到数据库）
                                    # 🆕 添加查看原文所需的字段
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
                                
                                # 追加新的引用数据
                                self._pending_references[session_id]["rich"].extend(rich_refs)
                                self._pending_references[session_id]["lean"].extend(lean_refs)
                                
                                # 🔍 调试：打印累积的全局序号
                                all_markers = [r.get("ref_marker", "?") for r in self._pending_references[session_id]["rich"]]
                                logger.info(f"📚 已提取 {len(rich_refs)} 条MCP工具引用数据（累计: {len(self._pending_references[session_id]['rich'])} 条），全局序号范围: {all_markers[0] if all_markers else '?'} - {all_markers[-1] if all_markers else '?'}")
                                logger.debug(f"🔍 累积全局序号列表: {all_markers}")
                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ 无法解析工具结果为JSON: {result_str[:100]}")
                        except Exception as e:
                            logger.error(f"❌ 提取引用数据失败: {e}", exc_info=True)
                    
                    # 🆕 特殊标记：如果是图谱检索工具，记录会话ID（稍后从Redis提取可视化数据）
                    if tool_name in ["graph_search_knowledge", "flexible_graph_query"]:
                        # 初始化图谱检索标记存储
                        if not hasattr(self, '_pending_graph_sessions'):
                            self._pending_graph_sessions = set()
                        self._pending_graph_sessions.add(session_id)
                        logger.info(f"🎨 图谱检索工具 [{tool_name}] 已执行，标记会话: {session_id}（可视化数据将从Redis提取）")
                    
                    # 🎯 发送工具成功状态
                    await self.send_tool_status(
                        session_id=session_id,
                        tool_name=tool_name,
                        status="success"
                    )
                    
                    return {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": result_str
                    }
                    
                except Exception as e:
                    duration = time.time() - start_time
                    
                    if tool_config.verbose_logging:
                        logger.error(f"❌ 工具执行失败 {tool_name}: {e} (耗时: {duration:.2f}秒)")
                    else:
                        logger.error(f"❌ 工具执行失败 {tool_name}: {e}")
                    
                    # 🎯 记录失败统计
                    self._record_tool_call(session_id, tool_name, False, duration)
                    
                    # 🎯 发送工具失败状态
                    await self.send_tool_status(
                        session_id=session_id,
                        tool_name=tool_name,
                        status="error",
                        error=str(e)
                    )
                    
                    # 🎯 检查是否允许失败后继续
                    if not tool_config.allow_continue_on_error:
                        raise  # 重新抛出异常，中断整个工具调用流程
                    
                    return {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": f"工具执行失败: {str(e)}"
                    }
        
        # 并行执行所有工具
        tasks = [execute_single_tool(tool_call) for tool_call in tool_calls]
        results = await asyncio.gather(*tasks)
        
        # 🎯 去重：如果本轮有多个 search_knowledge_base 调用，对结果进行去重
        await self._deduplicate_knowledge_base_results(session_id, tool_calls)
        
        # 🎯 【关键修复】去重后，需要更新所有 search_knowledge_base 的 tool 消息内容
        # 策略：每个 tool 消息都返回相同的去重数据（满足 OpenAI API 要求每个 tool_call 都有响应）
        if hasattr(self, '_pending_references') and session_id in self._pending_references:
            refs_data = self._pending_references[session_id]
            rich_refs = refs_data.get("rich", [])
            
            # 检查是否有 search_knowledge_base 调用
            kb_search_indices = [i for i, r in enumerate(results) if r.get("name") == "search_knowledge_base"]
            
            # 🎯 【关键修复】无论有几个调用，都要更新tool消息为去重后的结果！
            if len(kb_search_indices) >= 1 and rich_refs:
                logger.info(f"🔄 检测到 {len(kb_search_indices)} 个 search_knowledge_base 调用，更新tool消息为去重排序后的结果（去重后: {len(rich_refs)} 条）")
                
                # 🎯 构建合并后的去重结果
                deduped_results = []
                all_queries = []
                
                # 🔍 调试：打印去重排序后的序号
                logger.info(f"🔍 去重排序后的ref_marker顺序: {[r.get('ref_marker') for r in rich_refs]}")
                
                for idx, rich_ref in enumerate(rich_refs, start=1):
                    deduped_results.append({
                        "index": idx,
                        "ref_marker": rich_ref.get("ref_marker", idx),
                        "content": rich_ref.get("content", ""),
                        "score": rich_ref.get("score", 0.0),
                        "metadata": {
                            "source": rich_ref.get("source", ""),
                            "chunk_index": rich_ref.get("chunk_index", 0),
                            "chunk_id": rich_ref.get("chunk_id", ""),
                            "document_id": rich_ref.get("doc_id", ""),
                            "doc_id": rich_ref.get("doc_id", ""),
                            "kb_id": rich_ref.get("kb_id", ""),
                            "filename": rich_ref.get("filename", "")
                        }
                    })
                
                # 收集所有查询
                for i in kb_search_indices:
                    try:
                        original_data = json.loads(results[i]["content"])
                        query = original_data.get("query", "")
                        if query:
                            all_queries.append(query)
                    except:
                        pass
                
                # 构建合并后的 tool 消息内容（所有 tool 消息都返回相同的去重数据）
                merged_content = json.dumps({
                    "success": True,
                    "query": " | ".join(all_queries) if all_queries else "多次检索（已合并去重）",
                    "total": len(deduped_results),
                    "results": deduped_results
                }, ensure_ascii=False)
                
                # 🎯 更新所有 search_knowledge_base 消息为去重排序后的内容
                # 注意：不能删除消息，因为 OpenAI API 要求每个 tool_call 都有对应的响应
                # 【关键】这样可以确保模型看到的引用序号和前端收到的一致！
                for i in kb_search_indices:
                    results[i]["content"] = merged_content
                
                logger.info(f"✅ 已更新 {len(kb_search_indices)} 个 search_knowledge_base 工具消息为去重排序后的结果（去重后: {len(deduped_results)} 条，模型看到的序号将与前端一致）")
        
        return results
    
    async def _smart_streaming_output(self, content: str, chunk_size: Optional[int] = None) -> AsyncGenerator[str, None]:
        """
        智能流式输出
        
        按词汇单位输出，而不是逐字符，提升用户体验
        """
        
        if not content:
            return
        
        # 使用配置的分块大小
        if chunk_size is None:
            chunk_size = streaming_config.chunk_size
        
        # 如果禁用智能分块，直接输出
        if not streaming_config.enable_smart_chunking:
            yield content
            return
        
        # 按词汇分割（支持中英文）
        import re
        
        # 分割策略：中文字符、英文单词、标点符号
        tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+|\d+|[^\w\s]|\s+', content)
        
        current_chunk = ""
        for token in tokens:
            current_chunk += token
            
            # 记录分块内容（如果启用调试）
            if streaming_config.log_chunk_content:
                logger.debug(f"分块累积: '{current_chunk}'")
            
            # 当累积到足够的内容时输出
            if len(current_chunk) >= chunk_size or token in ['\n', '。', '！', '？', '.', '!', '?']:
                yield current_chunk
                current_chunk = ""
                # 使用配置的延迟
                if streaming_config.chunk_delay > 0:
                    await asyncio.sleep(streaming_config.chunk_delay)
        
        # 输出剩余内容
        if current_chunk:
            yield current_chunk
    
    async def get_session_stats(self) -> Dict[str, Any]:
        """获取会话统计信息"""
        async with self.session_lock:
            active_count = len(self.active_sessions)
            states = {}
            for session in self.active_sessions.values():
                state = session.state.value
                states[state] = states.get(state, 0) + 1
            
            return {
                "active_sessions": active_count,
                "states": states,
                "timestamp": time.time()
            }


# 全局流式管理器实例
streaming_manager = UniversalStreamingManager()
