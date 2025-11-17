"""
工具调用支持模块

为 LLM 服务提供工具调用（Function Calling）能力
集成 MCP 工具系统
"""
import json
import logging
from typing import List, Dict, Any, AsyncGenerator, Optional
from ...mcp.manager import mcp_manager
from .tool_config import tool_config

logger = logging.getLogger(__name__)


class ToolCallingMixin:
    """
    工具调用混入类
    
    为 LLM 服务提供工具调用能力
    任何需要支持工具调用的服务都可以继承此类
    """
    
    async def generate_with_tools(
        self,
        prompt: str,
        system_prompt: str,
        history: List[Dict[str, str]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        max_tool_iterations: Optional[int] = None,  # 👈 改为可选，自动读取全局配置
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        带工具调用的流式生成
        
        工作流程：
        1. 调用 LLM，检查是否需要使用工具
        2. 如果需要，执行工具调用
        3. 将工具结果添加到上下文
        4. 继续调用 LLM 直到得到最终答案
        
        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            history: 历史消息
            session_id: 会话 ID（工具调用时需要）
            user_id: 用户 ID
            max_tool_iterations: 最大工具调用迭代次数，None时使用全局配置 (tool_config.max_iterations)
            **kwargs: 其他参数
        
        Yields:
            str: 流式响应片段
        """
        history = history or []
        iteration = 0
        
        # 👇 使用全局配置或传入参数
        max_iter = max_tool_iterations if max_tool_iterations is not None else tool_config.max_iterations
        logger.info(f"🔧 [tool_calling] 最大迭代次数: {max_iter} (全局配置: {tool_config.max_iterations})")
        
        # 获取 MCP 工具列表
        mcp_client = mcp_manager.get_client()
        if not mcp_client:
            logger.warning("⚠️ MCP Client 未初始化，回退到无工具模式")
            async for chunk in self.generate_stream(prompt, system_prompt, history=history, **kwargs):
                yield chunk
            return
        
        try:
            tools = await mcp_client.list_tools()
            if not tools:
                logger.info("ℹ️ 无可用工具，使用普通对话模式")
                async for chunk in self.generate_stream(prompt, system_prompt, history=history, **kwargs):
                    yield chunk
                return
            
            logger.info(f"🔧 已加载 {len(tools)} 个工具")
        except Exception as e:
            logger.error(f"❌ 获取工具列表失败: {e}")
            async for chunk in self.generate_stream(prompt, system_prompt, history=history, **kwargs):
                yield chunk
            return
        
        # 构建消息历史
        messages = self._build_messages_with_history(system_prompt, history, prompt)
        
        # 开始工具调用循环
        while iteration < max_iter:  # 👈 使用全局配置
            iteration += 1
            logger.info(f"🔄 工具调用迭代 {iteration}/{max_iter}")
            
            # 调用 LLM（带工具列表）
            response = await self._call_llm_with_tools(messages, tools, **kwargs)
            
            # 检查是否需要调用工具
            if not response.get("tool_calls"):
                # 无工具调用，返回最终回复
                logger.info("✅ LLM 返回最终回复（无工具调用）")
                final_content = response.get("content", "")
                
                # 流式输出（模拟）
                if final_content:
                    for char in final_content:
                        yield char
                
                break
            
            # 处理工具调用
            tool_calls = response["tool_calls"]
            logger.info(f"🔧 LLM 请求调用 {len(tool_calls)} 个工具")
            
            # 将 assistant 消息（包含工具调用请求）添加到历史
            messages.append({
                "role": "assistant",
                "content": response.get("content", ""),
                "tool_calls": tool_calls
            })
            
            # 执行所有工具调用
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call.get("function", {}).get("name")
                tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                tool_call_id = tool_call.get("id", "")
                
                try:
                    tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                except json.JSONDecodeError:
                    tool_args = {}
                
                logger.info(f"  🔧 调用工具: {tool_name}, 参数: {tool_args}")
                
                # 执行工具
                try:
                    result = await mcp_client.call_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        session_id=session_id,
                        user_id=user_id
                    )
                    
                    logger.info(f"  ✅ 工具执行成功: {tool_name}")
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": result
                    })
                
                except Exception as e:
                    logger.error(f"  ❌ 工具执行失败: {tool_name}, 错误: {e}")
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps({"error": str(e)}, ensure_ascii=False)
                    })
            
            # 将工具结果添加到消息历史
            messages.extend(tool_results)
            
            # 提示用户工具调用进度（可选）
            yield f"\n[工具调用] 已执行 {len(tool_calls)} 个工具，正在生成回复...\n\n"
        
        if iteration >= max_iter:  # 👈 使用全局配置
            logger.warning(f"⚠️ 达到最大工具调用次数 ({max_iter})，强制结束")
            yield "\n[系统提示] 已达到最大工具调用次数，停止迭代。\n"
    
    def _build_messages_with_history(
        self,
        system_prompt: str,
        history: List[Dict[str, str]],
        user_message: str
    ) -> List[Dict[str, Any]]:
        """构建包含历史的消息列表"""
        messages = []
        
        # 系统提示词
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        
        # 历史消息
        if history:
            for msg in history:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        
        # 当前用户消息
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    async def _call_llm_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用 LLM（带工具列表）
        
        子类应该实现此方法来调用具体的 LLM API
        
        Returns:
            dict: {
                "content": "回复内容",
                "tool_calls": [...]  # 如果需要调用工具
            }
        """
        raise NotImplementedError("子类必须实现 _call_llm_with_tools 方法")


class ToolCallingHelper:
    """工具调用辅助函数"""
    
    @staticmethod
    def convert_mcp_tools_to_openai_format(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 MCP 工具格式转换为 OpenAI Function Calling 格式
        
        MCP 格式已经是 OpenAI 格式，直接返回
        """
        return tools
    
    @staticmethod
    def parse_tool_calls_from_response(response) -> Optional[List[Dict[str, Any]]]:
        """
        从 LLM 响应中解析工具调用
        
        Args:
            response: OpenAI API 响应对象
        
        Returns:
            List[Dict] | None: 工具调用列表
        """
        if not hasattr(response, "choices") or not response.choices:
            return None
        
        message = response.choices[0].message
        
        if not hasattr(message, "tool_calls") or not message.tool_calls:
            return None
        
        tool_calls = []
        for tc in message.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })
        
        return tool_calls


__all__ = ["ToolCallingMixin", "ToolCallingHelper"]

