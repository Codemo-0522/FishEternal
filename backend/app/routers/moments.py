"""
朋友圈 API 路由

提供朋友圈查询、点赞、评论等功能
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional, List
from datetime import datetime
from bson import ObjectId
import logging

from ..models.user import User
from ..utils.auth import get_current_user
from ..database import get_database
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/moments",
    tags=["moments"]
)


@router.get("/sessions/{session_id}")
async def get_session_moments(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    since: Optional[str] = Query(default=None, description="只获取此时间之后的朋友圈（ISO格式）")
):
    """
    获取会话的朋友圈列表
    
    Args:
        session_id: 会话 ID
        limit: 返回数量（默认 20，最多 100）
        offset: 偏移量（用于分页）
        since: 只获取此时间之后的朋友圈（用于增量更新）
    
    Returns:
        {
            "moments": [...],
            "total": 总数,
            "has_more": 是否还有更多,
            "has_updates": 是否有更新（仅当使用 since 参数时）
        }
    """
    try:
        # 验证会话所属权限
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        # 获取朋友圈列表
        moments = session.get("moments", [])
        
        # 如果指定了 since 参数，只返回该时间之后的朋友圈
        if since:
            moments = [m for m in moments if m.get("created_at", "") > since]
            # 倒序排列
            moments_sorted = sorted(moments, key=lambda x: x.get("created_at", ""), reverse=True)
            
            # 为每条朋友圈添加点赞用户详情和更新评论用户名
            for moment in moments_sorted:
                # 统一转换 likes 为字符串数组
                like_user_ids = [str(like) for like in moment.get("likes", [])]
                moment["likes"] = like_user_ids  # 更新为统一格式
                like_users = []
                
                # 收集所有需要查询的用户 ID（点赞 + 评论）
                all_user_ids = set(uid for uid in like_user_ids if uid != "ai")
                
                # 从评论中也收集用户 ID
                comments = moment.get("comments", [])
                for comment in comments:
                    user_id = str(comment.get("user_id", ""))
                    if user_id and user_id != "ai":
                        all_user_ids.add(user_id)
                
                # 一次性查询所有用户信息
                user_map = {}
                if all_user_ids:
                    # 将字符串 ID 转换为 ObjectId
                    user_object_ids = []
                    for uid in all_user_ids:
                        try:
                            user_object_ids.append(ObjectId(uid))
                        except Exception:
                            logger.warning(f"无效的用户ID: {uid}")
                    
                    if user_object_ids:
                        users_cursor = db[settings.mongodb_db_name].users.find({"_id": {"$in": user_object_ids}})
                        users_list = await users_cursor.to_list(length=None)
                        user_map = {str(u["_id"]): u.get("full_name") or u.get("account", "未知用户") for u in users_list}
                
                # 构建点赞用户列表
                if like_user_ids:
                    for user_id in like_user_ids:
                        if user_id == "ai":
                            # AI 用户使用会话的 AI 名称
                            ai_name = session.get("model_settings", {}).get("character_name", "AI")
                            like_users.append({
                                "user_id": "ai",
                                "user_name": ai_name
                            })
                        else:
                            like_users.append({
                                "user_id": user_id,
                                "user_name": user_map.get(user_id, "未知用户")
                            })
                
                moment["like_users"] = like_users
                
                # 更新评论中的用户名
                for comment in comments:
                    user_id = str(comment.get("user_id", ""))
                    if user_id == "ai":
                        # AI 评论保持原名称（已包含在评论数据中）
                        pass
                    elif user_id in user_map:
                        # 更新为最新的用户名
                        comment["user_name"] = user_map[user_id]
            
            return {
                "moments": moments_sorted,
                "total": len(moments_sorted),
                "has_more": False,
                "has_updates": len(moments_sorted) > 0
            }
        
        # 正常分页查询
        total = len(moments)
        
        # 倒序并分页
        moments_sorted = sorted(moments, key=lambda x: x.get("created_at", ""), reverse=True)
        moments_page = moments_sorted[offset:offset + limit]
        
        # 为每条朋友圈添加点赞用户详情和更新评论用户名
        for moment in moments_page:
            # 统一转换 likes 为字符串数组
            like_user_ids = [str(like) for like in moment.get("likes", [])]
            moment["likes"] = like_user_ids  # 更新为统一格式
            like_users = []
            
            # 收集所有需要查询的用户 ID（点赞 + 评论）
            all_user_ids = set(uid for uid in like_user_ids if uid != "ai")
            
            # 从评论中也收集用户 ID
            comments = moment.get("comments", [])
            for comment in comments:
                user_id = str(comment.get("user_id", ""))
                if user_id and user_id != "ai":
                    all_user_ids.add(user_id)
            
            # 一次性查询所有用户信息
            user_map = {}
            if all_user_ids:
                # 将字符串 ID 转换为 ObjectId
                user_object_ids = []
                for uid in all_user_ids:
                    try:
                        user_object_ids.append(ObjectId(uid))
                    except Exception:
                        logger.warning(f"无效的用户ID: {uid}")
                
                if user_object_ids:
                    users_cursor = db[settings.mongodb_db_name].users.find({"_id": {"$in": user_object_ids}})
                    users_list = await users_cursor.to_list(length=None)
                    user_map = {str(u["_id"]): u.get("full_name") or u.get("account", u.get("username", "未知用户")) for u in users_list}
            
            # 构建点赞用户列表
            if like_user_ids:
                for user_id in like_user_ids:
                    if user_id == "ai":
                        # AI 用户使用会话的 AI 名称
                        ai_name = session.get("model_settings", {}).get("character_name", "AI")
                        like_users.append({
                            "user_id": "ai",
                            "user_name": ai_name
                        })
                    else:
                        like_users.append({
                            "user_id": user_id,
                            "user_name": user_map.get(user_id, "未知用户")
                        })
            
            moment["like_users"] = like_users
            
            # 更新评论中的用户名
            for comment in comments:
                user_id = str(comment.get("user_id", ""))
                if user_id == "ai":
                    # AI 评论保持原名称（已包含在评论数据中）
                    pass
                elif user_id in user_map:
                    # 更新为最新的用户名
                    comment["user_name"] = user_map[user_id]
        
        return {
            "moments": moments_page,
            "total": total,
            "has_more": offset + limit < total,
            "has_updates": None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取朋友圈失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取朋友圈失败")


@router.get("/sessions/{session_id}/queue")
async def get_session_moment_queue(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database),
    since: Optional[str] = Query(default=None, description="只获取此时间之后更新的队列项")
):
    """
    获取会话的朋友圈队列（待发布、发布中、已发布）
    
    Args:
        session_id: 会话 ID
        since: 只获取此时间之后更新的队列项（ISO格式）
    
    Returns:
        {
            "pending": [...],  # 待发布
            "published": [...],  # 已发布
            "error": [...],  # 发布失败
            "cancelled": [...],  # 已取消
            "has_updates": 是否有更新（仅当使用 since 参数时）
        }
    """
    try:
        # 验证会话所属权限
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        # 获取队列
        queue = session.get("moment_queue", [])
        
        # 如果指定了 since 参数，只返回该时间之后更新的项
        if since:
            queue = [
                item for item in queue 
                if item.get("updated_at", item.get("created_at", "")) > since
            ]
        
        # 按状态分组
        result = {
            "pending": [],
            "published": [],
            "error": [],
            "cancelled": []
        }
        
        for item in queue:
            status = item.get("status", "pending")
            if status in result:
                result[status].append(item)
        
        # 排序（最新的在前）
        for status in result:
            result[status] = sorted(result[status], key=lambda x: x.get("created_at", ""), reverse=True)
        
        # 如果使用 since 参数，添加 has_updates 标识
        if since:
            result["has_updates"] = len(queue) > 0
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取朋友圈队列失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取朋友圈队列失败")


@router.post("/sessions/{session_id}/moments/{moment_id}/like")
async def like_moment(
    session_id: str,
    moment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    给朋友圈点赞
    
    Args:
        session_id: 会话 ID
        moment_id: 朋友圈 ID
    
    Returns:
        {"success": true, "message": "点赞成功"}
    """
    try:
        user_id = str(current_user.id)
        
        # 检查是否已点赞
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "moments._id": moment_id
        })
        
        if not session:
            raise HTTPException(status_code=404, detail="朋友圈不存在")
        
        # 找到对应的朋友圈
        moment = next((m for m in session.get("moments", []) if m["_id"] == moment_id), None)
        
        if not moment:
            raise HTTPException(status_code=404, detail="朋友圈不存在")
        
        # 检查是否已点赞（统一转换为字符串比较）
        likes = moment.get("likes", [])
        likes_str = [str(like) for like in likes]
        
        logger.info(f"🔍 点赞检查 - user_id: {user_id}, likes原始: {likes}, likes转换: {likes_str}, 是否已点赞: {user_id in likes_str}")
        
        if user_id in likes_str:
            # 取消点赞
            await db[settings.mongodb_db_name].chat_sessions.update_one(
                {"_id": session_id, "moments._id": moment_id},
                {"$pull": {"moments.$.likes": user_id}}
            )
            return {"success": True, "message": "取消点赞成功"}
        else:
            # 添加点赞
            await db[settings.mongodb_db_name].chat_sessions.update_one(
                {"_id": session_id, "moments._id": moment_id},
                {"$addToSet": {"moments.$.likes": user_id}}
            )
            return {"success": True, "message": "点赞成功"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"点赞失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="点赞失败")


@router.post("/sessions/{session_id}/moments/{moment_id}/comment")
async def comment_moment(
    session_id: str,
    moment_id: str,
    content: str = Query(..., description="评论内容"),
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    评论朋友圈
    
    Args:
        session_id: 会话 ID
        moment_id: 朋友圈 ID
        content: 评论内容
    
    Returns:
        {"success": true, "comment": {...}}
    """
    try:
        import uuid
        
        user_id = str(current_user.id)
        
        # 从数据库获取最新的用户信息（确保获取到最新的 full_name）
        user_doc = await db[settings.mongodb_db_name].users.find_one({"_id": ObjectId(user_id)})
        user_name = user_doc.get("full_name") or user_doc.get("account", "未知用户") if user_doc else current_user.account
        
        # 创建评论
        current_time = datetime.now().isoformat()
        comment = {
            "_id": str(uuid.uuid4()),
            "user_id": user_id,
            "user_name": user_name,
            "content": content,
            "created_at": current_time
        }
        
        # 添加评论到朋友圈
        result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {"_id": session_id, "moments._id": moment_id},
            {"$push": {"moments.$.comments": comment}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="朋友圈不存在")
        
        return {"success": True, "comment": comment}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"评论失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="评论失败")


@router.delete("/sessions/{session_id}/moments/{moment_id}/comments/{comment_id}")
async def delete_comment(
    session_id: str,
    moment_id: str,
    comment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    删除评论
    
    Args:
        session_id: 会话 ID
        moment_id: 朋友圈 ID
        comment_id: 评论 ID
    
    Returns:
        {"success": true, "message": "删除成功"}
    """
    try:
        user_id = str(current_user.id)
        
        # 查找朋友圈和评论
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "moments._id": moment_id
        })
        
        if not session:
            raise HTTPException(status_code=404, detail="朋友圈不存在")
        
        # 找到对应的朋友圈
        moment = next((m for m in session.get("moments", []) if m["_id"] == moment_id), None)
        
        if not moment:
            raise HTTPException(status_code=404, detail="朋友圈不存在")
        
        # 找到对应的评论
        comment = next((c for c in moment.get("comments", []) if c.get("_id") == comment_id), None)
        
        if not comment:
            raise HTTPException(status_code=404, detail="评论不存在")
        
        # 权限检查：只能删除自己的评论
        comment_user_id = str(comment.get("user_id", ""))
        if comment_user_id != user_id:
            # 禁止删除其他用户或 AI 的评论
            raise HTTPException(status_code=403, detail="无权删除此评论")
        
        # 删除评论
        result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {"_id": session_id, "moments._id": moment_id},
            {"$pull": {"moments.$.comments": {"_id": comment_id}}}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=500, detail="删除评论失败")
        
        logger.info(f"✅ 评论已删除: comment_id={comment_id}, user_id={user_id}")
        
        return {"success": True, "message": "删除成功"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除评论失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除失败")


@router.delete("/sessions/{session_id}/moments/{moment_id}")
async def delete_moment(
    session_id: str,
    moment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    删除朋友圈
    
    Args:
        session_id: 会话 ID
        moment_id: 朋友圈 ID
    
    Returns:
        {"success": true, "message": "删除成功"}
    """
    try:
        # 验证会话所属权限
        session = await db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": str(current_user.id)
        })
        
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        
        # 删除朋友圈
        result = await db[settings.mongodb_db_name].chat_sessions.update_one(
            {"_id": session_id},
            {"$pull": {"moments": {"_id": moment_id}}}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="朋友圈不存在")
        
        logger.info(f"✅ 朋友圈已删除: {moment_id}")
        
        return {"success": True, "message": "删除成功"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除朋友圈失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除朋友圈失败")
