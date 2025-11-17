"""
MCP 工具：skip_reply

当 AI 判断不需要回复当前群聊消息时调用此工具
"""
import logging
from typing import Optional, Dict, Any
from ..base import BaseTool, ToolMetadata, ToolContext

logger = logging.getLogger(__name__)


class SkipReplyTool(BaseTool):
    """
    跳过回复工具
    
    当 AI 在群聊中判断不需要回复当前消息时调用。
    调用后，群聊服务将不会保存和广播该 AI 的回复。
    """
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """获取工具元数据"""
        return ToolMetadata(
            name="skip_reply",
            description=(
                "⚠️ 谨慎使用！当你真的确定不需要回复时才调用此工具。"
                "适用场景（必须满足至少一条）："
                "1. 消息完全为空或无任何实际内容"
                "2. 话题完全与你无关，且你没有任何想法或评论"
                "3. 其他人已经完整回答，且你完全没有新见解可以补充"
                "4. 明显的刷屏或垃圾消息"
                ""
                "⛔ 不要在以下情况使用："
                "- 你被 @ 提及（被@必须回复！）"
                "- 话题稍微相关或有趣（应该参与讨论）"
                "- 你有任何想法、评论、表情可以分享"
                "- 只是因为不确定说什么（可以说点轻松的话）"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "不回复的理由（必须提供，说明为什么不回复）"
                    }
                },
                "required": ["reason"]
            }
        )
    
    async def execute(
        self,
        arguments: Dict[str, Any],
        context: ToolContext
    ) -> Dict[str, Any]:
        """
        执行跳过回复
        
        Args:
            arguments: 工具参数 {"reason": "不回复的理由"}
            context: 工具上下文
        
        Returns:
            执行结果，包含 action: "skip_reply" 标记
        """
        reason = arguments.get("reason", "AI选择不发言")
        
        logger.info(f"🤐 AI决定跳过回复 | 理由: {reason}")
        
        return {
            "success": True,
            "action": "skip_reply",  # 关键标记！群聊服务会检测这个字段
            "message": "已跳过本次回复",
            "reason": reason
        }

