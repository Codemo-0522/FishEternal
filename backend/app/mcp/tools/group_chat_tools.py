"""
MCP 工具：群聊AI生命周期管理

提供AI上线、下线的工具接口（标准 BaseTool 实现）
"""
import logging
import json
from typing import Dict, Any, Optional
from ..base import BaseTool, ToolMetadata, ToolContext

logger = logging.getLogger(__name__)


class AIGoOnlineTool(BaseTool):
    """AI上线工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        return ToolMetadata(
            name="ai_go_online",
            description="AI上线到群聊。当你决定参与群聊时调用此工具。",
            input_schema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "description": "群组ID"
                    },
                    "reason": {
                        "type": "string",
                        "description": "上线理由（可选，如：对话题感兴趣、被@等）"
                    }
                },
                "required": ["group_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """执行AI上线"""
        group_id = arguments.get("group_id")
        reason = arguments.get("reason")
        
        # 从 context.extra 获取 AI 成员 ID（群聊服务会注入）
        ai_member_id = context.extra.get("ai_member_id")
        
        if not group_id or not ai_member_id:
            return json.dumps({
                "success": False,
                "error": "缺少必要参数"
            }, ensure_ascii=False)
        
        try:
            from ...services.group_chat import GroupChatService
            
            service = GroupChatService(context.db)
            await service.ai_go_online(group_id, ai_member_id)
            
            logger.info(
                f"✅ AI上线成功: 群组={group_id} | AI={ai_member_id} | "
                f"理由={reason or '无'}"
            )
            
            return json.dumps({
                "success": True,
                "message": f"已成功上线到群聊「{group_id}」",
                "ai_member_id": ai_member_id,
                "group_id": group_id
            }, ensure_ascii=False)
        
        except Exception as e:
            logger.error(f"❌ AI上线失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)


class AIGoOfflineTool(BaseTool):
    """AI下线工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        return ToolMetadata(
            name="ai_go_offline",
            description="AI从群聊下线。当你决定暂时退出群聊时调用此工具。下线后你将不再收到群聊消息。",
            input_schema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "description": "群组ID"
                    },
                    "reason": {
                        "type": "string",
                        "description": "下线理由（可选，如：无兴趣话题、需要休息等）"
                    }
                },
                "required": ["group_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """执行AI下线"""
        group_id = arguments.get("group_id")
        reason = arguments.get("reason")
        
        # 从 context.extra 获取 AI 成员 ID
        ai_member_id = context.extra.get("ai_member_id")
        
        if not group_id or not ai_member_id:
            return json.dumps({
                "success": False,
                "error": "缺少必要参数"
            }, ensure_ascii=False)
        
        try:
            from ...services.group_chat import GroupChatService
            
            service = GroupChatService(context.db)
            await service.ai_go_offline(group_id, ai_member_id)
            
            logger.info(
                f"✅ AI下线成功: 群组={group_id} | AI={ai_member_id} | "
                f"理由={reason or '无'}"
            )
            
            return json.dumps({
                "success": True,
                "message": f"已从群聊「{group_id}」下线",
                "ai_member_id": ai_member_id,
                "group_id": group_id
            }, ensure_ascii=False)
        
        except Exception as e:
            logger.error(f"❌ AI下线失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)


class CheckOnlineStatusTool(BaseTool):
    """查询在线状态工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        return ToolMetadata(
            name="check_online_status",
            description="查询自己在群聊中的在线状态",
            input_schema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "description": "群组ID"
                    }
                },
                "required": ["group_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """执行查询在线状态"""
        group_id = arguments.get("group_id")
        
        # 从 context.extra 获取 AI 成员 ID
        ai_member_id = context.extra.get("ai_member_id")
        
        if not group_id or not ai_member_id:
            return json.dumps({
                "success": False,
                "error": "缺少必要参数"
            }, ensure_ascii=False)
        
        try:
            from ...services.group_chat import GroupChatService
            from ...models.group_chat import MemberStatus
            
            service = GroupChatService(context.db)
            member = await service.group_manager.get_member(group_id, ai_member_id)
            
            if not member:
                return json.dumps({
                    "success": False,
                    "error": "AI成员不存在"
                }, ensure_ascii=False)
            
            return json.dumps({
                "success": True,
                "ai_member_id": ai_member_id,
                "status": member.status.value,
                "is_online": member.status == MemberStatus.ONLINE,
                "last_active_time": member.last_active_time.isoformat() if member.last_active_time else None
            }, ensure_ascii=False)
        
        except Exception as e:
            logger.error(f"❌ 查询在线状态失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)


class GetGroupInfoTool(BaseTool):
    """获取群聊信息工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        return ToolMetadata(
            name="get_group_info",
            description="获取群聊的当前信息，包括成员数量、最近消息等，用于决策是否上线",
            input_schema={
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "description": "群组ID"
                    }
                },
                "required": ["group_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """执行获取群聊信息"""
        group_id = arguments.get("group_id")
        
        if not group_id:
            return json.dumps({
                "success": False,
                "error": "缺少 group_id 参数"
            }, ensure_ascii=False)
        
        try:
            from ...services.group_chat import GroupChatService
            
            service = GroupChatService(context.db)
            
            # 获取群组基本信息
            group = await service.get_group_info(group_id)
            if not group:
                return json.dumps({
                    "success": False,
                    "error": "群聊不存在"
                }, ensure_ascii=False)
            
            # 获取成员列表
            members = await service.get_group_members(group_id)
            
            # 获取最近消息
            recent_messages = await service.get_recent_messages(group_id, limit=10)
            
            return json.dumps({
                "success": True,
                "group_name": group.name,
                "group_id": group_id,
                "total_members": len(members),
                "online_members": len([m for m in members if m.status.value == "online"]),
                "ai_members": len([m for m in members if m.member_type.value == "ai"]),
                "recent_message_count": len(recent_messages),
                "last_message_time": group.last_message_time.isoformat() if group.last_message_time else None,
                "recent_messages": [
                    {
                        "sender_name": msg.sender_name,
                        "content": msg.content[:100],
                        "timestamp": msg.timestamp.isoformat()
                    }
                    for msg in recent_messages[-5:]  # 最近5条
                ]
            }, ensure_ascii=False)
        
        except Exception as e:
            logger.error(f"❌ 获取群聊信息失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": str(e)
            }, ensure_ascii=False)
