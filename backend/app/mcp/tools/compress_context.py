"""
通用上下文压缩工具

允许 LLM 主动压缩之前工具调用的返回结果，释放上下文空间
适用于所有 MCP 工具的返回结果
"""
from typing import Dict, Any, List, Optional
import json
import logging
from ..base import BaseTool, ToolMetadata, ToolContext, ToolExecutionError

logger = logging.getLogger(__name__)


class ContextCompressionManager:
    """
    上下文压缩管理器（按会话隔离）
    
    负责记录哪些 ref_marker 已被压缩，以及对应的工具名称
    """
    _instance = None
    _compressed_markers: Dict[str, Dict[int, Dict[str, Any]]] = {}  # {session_id: {ref_marker: compression_info}}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def compress_markers(
        self,
        session_id: str,
        ref_markers: List[int],
        action: str,
        summary: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        标记指定的 ref_marker 为已压缩
        
        Args:
            session_id: 会话 ID
            ref_markers: 要压缩的引用序号列表
            action: 压缩动作类型
            summary: 压缩后的摘要（可选）
            reason: 压缩原因（可选）
        
        Returns:
            压缩统计信息
        """
        if session_id not in self._compressed_markers:
            self._compressed_markers[session_id] = {}
        
        compression_info = {
            "action": action,
            "summary": summary,
            "reason": reason
        }
        
        compressed_count = 0
        for marker in ref_markers:
            if marker not in self._compressed_markers[session_id]:
                self._compressed_markers[session_id][marker] = compression_info
                compressed_count += 1
        
        logger.info(
            f"🗜️ 会话 {session_id} 压缩了 {compressed_count} 个结果 "
            f"(序号: {min(ref_markers)}-{max(ref_markers)}), 动作: {action}"
        )
        
        return {
            "compressed_count": compressed_count,
            "total_markers": len(ref_markers),
            "already_compressed": len(ref_markers) - compressed_count
        }
    
    def is_compressed(self, session_id: str, ref_marker: int) -> bool:
        """检查指定序号是否已被压缩"""
        return (
            session_id in self._compressed_markers and
            ref_marker in self._compressed_markers[session_id]
        )
    
    def get_compression_info(self, session_id: str, ref_marker: int) -> Optional[Dict[str, Any]]:
        """获取指定序号的压缩信息"""
        if self.is_compressed(session_id, ref_marker):
            return self._compressed_markers[session_id][ref_marker]
        return None
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """获取会话的压缩统计"""
        if session_id not in self._compressed_markers:
            return {"total_compressed": 0}
        
        compressed = self._compressed_markers[session_id]
        return {
            "total_compressed": len(compressed),
            "markers": sorted(compressed.keys())
        }
    
    def reset_session(self, session_id: str):
        """重置会话的压缩记录"""
        if session_id in self._compressed_markers:
            del self._compressed_markers[session_id]
            logger.info(f"🔄 已重置会话 {session_id} 的上下文压缩记录")


# 全局单例
_compression_manager = ContextCompressionManager()


class CompressContextTool(BaseTool):
    """
    通用上下文压缩工具
    
    允许 LLM 主动压缩任何工具的返回结果，释放上下文空间
    """
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> Optional[ToolMetadata]:
        """返回工具元数据"""
        return ToolMetadata(
            name="compress_context",
            description=(
                "压缩之前工具调用的返回结果，释放上下文空间。"
                "当检索到无关信息或已提取关键信息后，可以使用此工具压缩原始数据。"
                "⚠️ 重要：压缩是不可逆的，压缩后原始数据无法恢复（需要重新调用工具获取）。"
                "\n\n使用场景："
                "\n1. mark_irrelevant - 检索到的内容完全不相关，需要重新检索"
                "\n2. compress_to_summary - 已提取关键信息，可以用摘要替代详细内容"
                "\n3. partial_compress - 部分内容有用已提取，其余可以压缩"
                "\n\n⚠️ 使用建议："
                "\n- 在确认内容无关或已充分利用后再压缩"
                "\n- 保留摘要信息，避免后续重复检索"
                "\n- 批量压缩多个结果时注意不要误删有用信息"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ref_markers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "要压缩的结果序号列表（来自之前工具返回的 ref_marker 字段）。"
                            "可以是单个序号如 [5]，也可以是批量序号如 [10, 11, 12, 13, 14]。"
                            "⚠️ 确保这些序号对应的内容确实需要压缩。"
                        )
                    },
                    "action": {
                        "type": "string",
                        "enum": ["mark_irrelevant", "compress_to_summary", "partial_compress"],
                        "description": (
                            "压缩动作类型：\n"
                            "- mark_irrelevant: 标记为完全无关，用于清理误检索的内容\n"
                            "- compress_to_summary: 压缩为摘要，用于已提取关键信息的内容\n"
                            "- partial_compress: 部分压缩，用于混合场景"
                        )
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "压缩后的简短摘要（1-3句话）。"
                            "应该包含："
                            "\n- 原内容的核心主题"
                            "\n- 为什么要压缩（无关/已提取）"
                            "\n- 关键信息（如果有）"
                            "\n\n示例："
                            "\n- '检索到50篇医学论文，与当前计算机视觉主题无关'"
                            "\n- '已从3篇文档提取量子计算核心原理：量子叠加、纠缠、比特概念'"
                            "\n- '论文列表中前20篇为NLP领域，已排除；后30篇为CV领域需保留'"
                        )
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "压缩原因说明（可选，用于调试和日志）。"
                            "建议说明："
                            "\n- 为什么这些内容不再需要"
                            "\n- 已经如何利用这些内容"
                            "\n- 下一步计划（如需要重新检索其他内容）"
                        )
                    }
                },
                "required": ["ref_markers", "action", "summary"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行上下文压缩
        
        Args:
            arguments: {
                "ref_markers": [1, 2, 3],
                "action": "mark_irrelevant" | "compress_to_summary" | "partial_compress",
                "summary": "压缩摘要",
                "reason": "压缩原因（可选）"
            }
            context: 工具上下文
        
        Returns:
            压缩结果的 JSON 字符串
        """
        try:
            # 提取参数
            ref_markers = arguments.get("ref_markers", [])
            action = arguments.get("action")
            summary = arguments.get("summary")
            reason = arguments.get("reason")
            
            # 参数验证
            if not ref_markers:
                return json.dumps({
                    "success": False,
                    "error": "ref_markers 不能为空，请指定要压缩的结果序号"
                }, ensure_ascii=False, indent=2)
            
            if not isinstance(ref_markers, list):
                ref_markers = [ref_markers]
            
            if not all(isinstance(m, int) for m in ref_markers):
                return json.dumps({
                    "success": False,
                    "error": "ref_markers 必须是整数列表"
                }, ensure_ascii=False, indent=2)
            
            if action not in ["mark_irrelevant", "compress_to_summary", "partial_compress"]:
                return json.dumps({
                    "success": False,
                    "error": f"不支持的 action: {action}"
                }, ensure_ascii=False, indent=2)
            
            if not summary:
                return json.dumps({
                    "success": False,
                    "error": "summary 不能为空，请提供压缩后的摘要"
                }, ensure_ascii=False, indent=2)
            
            # 获取会话 ID
            session_id = context.session_id
            if not session_id:
                return json.dumps({
                    "success": False,
                    "error": "缺少会话 ID"
                }, ensure_ascii=False, indent=2)
            
            # 执行压缩
            stats = _compression_manager.compress_markers(
                session_id=session_id,
                ref_markers=ref_markers,
                action=action,
                summary=summary,
                reason=reason
            )
            
            # 构建友好的返回消息
            action_desc = {
                "mark_irrelevant": "标记为无关",
                "compress_to_summary": "压缩为摘要",
                "partial_compress": "部分压缩"
            }
            
            marker_range = f"{min(ref_markers)}-{max(ref_markers)}" if len(ref_markers) > 1 else str(ref_markers[0])
            
            # 🎯 关键：返回简洁的压缩确认消息（替代原来的大量数据）
            result_message = (
                f"✅ 已压缩序号 {marker_range} 的检索结果\n"
                f"📊 动作: {action_desc[action]}\n"
                f"📝 摘要: {summary}"
            )
            
            if stats["already_compressed"] > 0:
                result_message += f"\n⚠️ 其中 {stats['already_compressed']} 个序号已被压缩过"
            
            # 获取会话统计
            session_stats = _compression_manager.get_session_stats(session_id)
            
            logger.info(
                f"✅ 上下文压缩成功: 会话={session_id}, "
                f"压缩序号={marker_range}, 动作={action}, "
                f"本次={stats['compressed_count']}, 累计={session_stats['total_compressed']}"
            )
            
            return json.dumps({
                "success": True,
                "message": result_message,
                "stats": {
                    "compressed_this_time": stats["compressed_count"],
                    "total_markers_requested": stats["total_markers"],
                    "already_compressed": stats["already_compressed"],
                    "session_total_compressed": session_stats["total_compressed"]
                },
                "compression_info": {
                    "ref_markers": ref_markers,
                    "action": action,
                    "summary": summary,
                    "reason": reason
                }
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 上下文压缩失败: {str(e)}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"执行压缩失败: {str(e)}"
            }, ensure_ascii=False, indent=2)


# 导出单例和工具类
__all__ = [
    "CompressContextTool",
    "ContextCompressionManager",
    "_compression_manager"
]

