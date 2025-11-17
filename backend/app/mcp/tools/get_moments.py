"""
获取朋友圈（Get Moments）工具

AI 可以使用此工具查看自己发布的朋友圈，包括点赞和评论信息
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
import logging

from ..base import BaseTool, ToolMetadata, ToolContext
from ...config import settings

logger = logging.getLogger(__name__)


class GetMyMomentsTool(BaseTool):
    """获取我的朋友圈工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """
        获取工具元数据
        
        Args:
            context: 工具上下文（不需要）
        """
        return ToolMetadata(
            name="get_my_moments",
            description="""使用该工具可以查看你自己发送的朋友圈，如果有人评论了你，你一般会选择回复评论""".strip(),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "获取最近多少条朋友圈（默认 10 条，最多 50 条）"
                    },
                    "include_details": {
                        "type": "boolean",
                        "description": "是否包含详细的点赞和评论信息（默认 true）"
                    }
                },
                "required": []
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行获取朋友圈操作
        
        Args:
            arguments: {
                "limit": 10,  # 可选，默认 10
                "include_details": true  # 可选，默认 true
            }
            context: 执行上下文（需要 db 和 session_id）
        
        Returns:
            str: JSON 格式的朋友圈列表
        """
        import json
        
        # 从上下文获取必要信息
        db_name = context.extra.get("db_name", settings.mongodb_db_name)
        db = context.db[db_name]
        session_id = context.session_id
        
        if not session_id:
            logger.error("❌ 缺少 session_id，无法获取朋友圈")
            return json.dumps({
                "success": False,
                "error": "系统错误：缺少会话信息"
            }, ensure_ascii=False)
        
        try:
            # 1. 获取当前会话的 user_id
            session = await db.chat_sessions.find_one({"_id": session_id})
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "会话不存在"
                }, ensure_ascii=False)
            
            user_id = session.get("user_id")
            if not user_id:
                return json.dumps({
                    "success": False,
                    "error": "会话信息不完整"
                }, ensure_ascii=False)
            
            # 2. 解析参数
            limit = arguments.get("limit", 10)
            limit = min(max(1, limit), 50)  # 限制在 1-50 之间
            include_details = arguments.get("include_details", True)
            
            # 3. 从会话文档中查询朋友圈（朋友圈存储在 chat_sessions.moments 数组中）
            # 获取当前会话的朋友圈
            session_with_moments = await db.chat_sessions.find_one(
                {"_id": session_id},
                {"moments": 1}
            )
            
            if not session_with_moments or not session_with_moments.get("moments"):
                moments_list = []
            else:
                # 获取所有朋友圈并按创建时间倒序排序
                all_moments = session_with_moments.get("moments", [])
                # 按 created_at 降序排序
                moments_list = sorted(
                    all_moments,
                    key=lambda x: x.get("created_at", ""),
                    reverse=True
                )[:limit]
            
            if not moments_list:
                return json.dumps({
                    "success": True,
                    "count": 0,
                    "moments": [],
                    "message": "当前会话中还没有发布过朋友圈"
                }, ensure_ascii=False)
            
            # 4. 格式化朋友圈数据
            formatted_moments = []
            for moment in moments_list:
                moment_data = {
                    "id": str(moment["_id"]),
                    "content": moment.get("content", ""),
                    "created_at": moment.get("created_at", ""),
                    "images": moment.get("images", []),
                }
                
                if include_details:
                    from bson import ObjectId
                    
                    # 收集所有需要查询的用户 ID（点赞 + 评论）
                    like_user_ids = moment.get("likes", [])
                    comments = moment.get("comments", [])
                    
                    # 收集所有真实用户 ID
                    all_user_ids = set()
                    for uid in like_user_ids:
                        if uid != "ai":
                            all_user_ids.add(uid)
                    for comment in comments:
                        uid = comment.get("user_id")
                        if uid and uid != "ai":
                            all_user_ids.add(str(uid))
                    
                    # 一次性查询所有用户信息
                    user_map = {}
                    if all_user_ids:
                        user_object_ids = []
                        for uid in all_user_ids:
                            try:
                                user_object_ids.append(ObjectId(uid))
                            except Exception:
                                logger.warning(f"无效的用户ID: {uid}")
                        
                        if user_object_ids:
                            users_cursor = db.users.find({"_id": {"$in": user_object_ids}})
                            users_list = await users_cursor.to_list(length=None)
                            user_map = {str(u["_id"]): u.get("full_name") or u.get("account", "未知用户") for u in users_list}
                    
                    # 构建点赞列表
                    like_users = []
                    for user_id in like_user_ids:
                        if user_id == "ai":
                            like_users.append({
                                "user_id": "ai",
                                "user_name": "AI"
                            })
                        else:
                            like_users.append({
                                "user_id": user_id,
                                "user_name": user_map.get(user_id, "未知用户")
                            })
                    
                    moment_data["likes"] = {
                        "count": len(like_user_ids),
                        "users": like_users
                    }
                    
                    # 构建评论列表（使用最新的用户名）
                    comment_list = []
                    for comment in comments:
                        user_id = str(comment.get("user_id", ""))
                        if user_id == "ai":
                            user_name = "AI"
                        else:
                            # 使用动态查询的最新用户名
                            user_name = user_map.get(user_id, comment.get("user_name", "未知用户"))
                        
                        comment_list.append({
                            "user_id": user_id,
                            "user_name": user_name,
                            "content": comment.get("content"),
                            "created_at": comment.get("created_at")
                        })
                    
                    moment_data["comments"] = {
                        "count": len(comments),
                        "list": comment_list
                    }
                else:
                    # 只返回数量
                    moment_data["likes_count"] = len(moment.get("likes", []))
                    moment_data["comments_count"] = len(moment.get("comments", []))
                
                formatted_moments.append(moment_data)
            
            # 5. 统计总体信息
            total_likes = sum(len(m.get("likes", [])) for m in moments_list)
            total_comments = sum(len(m.get("comments", [])) for m in moments_list)
            
            result = {
                "success": True,
                "count": len(formatted_moments),
                "total_likes": total_likes,
                "total_comments": total_comments,
                "moments": formatted_moments
            }
            
            logger.info(f"✅ 成功获取 {len(formatted_moments)} 条朋友圈")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 获取朋友圈失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"获取失败: {str(e)}"
            }, ensure_ascii=False)


class GetMomentDetailTool(BaseTool):
    """获取单条朋友圈详情工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """获取工具元数据"""
        return ToolMetadata(
            name="get_moment_detail",
            description="""使用该工具可以获取指定朋友圈的详细信息，包括所有点赞和评论。""".strip(),
            input_schema={
                "type": "object",
                "properties": {
                    "moment_id": {
                        "type": "string",
                        "description": "朋友圈 ID"
                    }
                },
                "required": ["moment_id"]
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """执行获取朋友圈详情操作"""
        import json
        
        moment_id = arguments.get("moment_id")
        if not moment_id:
            return json.dumps({
                "success": False,
                "error": "缺少 moment_id 参数"
            }, ensure_ascii=False)
        
        try:
            db_name = context.extra.get("db_name", settings.mongodb_db_name)
            db = context.db[db_name]
            session_id = context.session_id
            
            if not session_id:
                return json.dumps({
                    "success": False,
                    "error": "系统错误：缺少会话信息"
                }, ensure_ascii=False)
            
            # 获取当前用户 ID
            session = await db.chat_sessions.find_one({"_id": session_id})
            if not session:
                return json.dumps({
                    "success": False,
                    "error": "会话不存在"
                }, ensure_ascii=False)
            
            user_id = session.get("user_id")
            
            # 从会话文档的 moments 数组中查询朋友圈
            session_with_moment = await db.chat_sessions.find_one(
                {"_id": session_id, "moments._id": moment_id},
                {"moments.$": 1}
            )
            
            if not session_with_moment or not session_with_moment.get("moments"):
                moment = None
            else:
                moment = session_with_moment["moments"][0]
            
            if not moment:
                return json.dumps({
                    "success": False,
                    "error": "朋友圈不存在"
                }, ensure_ascii=False)
            
            # 因为是从当前会话查询的，所以这个朋友圈一定是属于当前会话的AI的
            from bson import ObjectId
            
            # 收集所有需要查询的用户 ID（点赞 + 评论）
            like_user_ids = moment.get("likes", [])
            comments = moment.get("comments", [])
            
            # 收集所有真实用户 ID
            all_user_ids = set()
            for uid in like_user_ids:
                if uid != "ai":
                    all_user_ids.add(str(uid))
            for comment in comments:
                uid = comment.get("user_id")
                if uid and uid != "ai":
                    all_user_ids.add(str(uid))
            
            # 一次性查询所有用户信息
            user_map = {}
            if all_user_ids:
                user_object_ids = []
                for uid in all_user_ids:
                    try:
                        user_object_ids.append(ObjectId(uid))
                    except Exception:
                        logger.warning(f"无效的用户ID: {uid}")
                
                if user_object_ids:
                    users_cursor = db.users.find({"_id": {"$in": user_object_ids}})
                    users_list = await users_cursor.to_list(length=None)
                    user_map = {str(u["_id"]): u.get("full_name") or u.get("account", "未知用户") for u in users_list}
            
            # 构建点赞列表
            like_users = []
            for user_id in like_user_ids:
                if user_id == "ai":
                    like_users.append({
                        "user_id": "ai",
                        "user_name": "AI"
                    })
                else:
                    like_users.append({
                        "user_id": str(user_id),
                        "user_name": user_map.get(str(user_id), "未知用户")
                    })
            
            # 构建评论列表（使用最新的用户名）
            comment_list = []
            for comment in comments:
                user_id = str(comment.get("user_id", ""))
                if user_id == "ai":
                    user_name = "AI"
                else:
                    # 使用动态查询的最新用户名
                    user_name = user_map.get(user_id, comment.get("user_name", "未知用户"))
                
                comment_list.append({
                    "id": comment.get("_id"),
                    "user_id": user_id,
                    "user_name": user_name,
                    "content": comment.get("content"),
                    "created_at": comment.get("created_at")
                })
            
            # 格式化返回数据
            result = {
                "success": True,
                "moment": {
                    "id": str(moment["_id"]),
                    "content": moment.get("content", ""),
                    "created_at": moment.get("created_at", ""),
                    "images": moment.get("images", []),
                    "likes": like_users,
                    "comments": comment_list
                }
            }
            
            logger.info(f"✅ 成功获取朋友圈详情: {moment_id}")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 获取朋友圈详情失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"获取失败: {str(e)}"
            }, ensure_ascii=False)

