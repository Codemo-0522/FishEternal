"""
群聊 HTTP API 路由

提供群聊管理的RESTful接口
"""
import logging
import io
import asyncio
import traceback
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from ..database import get_database
from ..utils.auth import get_current_user
from ..models.user import User
from ..models.group_chat import (
    CreateGroupRequest, AddMemberRequest, SendMessageRequest,
    UpdateBehaviorRequest, GroupChat, GroupMember, GroupMessage,
    AIBehaviorConfig, GroupChatWithMembers, GroupMemberResponse,
    GroupStrategyConfig, UpdateGroupStrategyRequest
)
from ..services.group_chat import GroupChatService
from ..utils.minio_client import minio_client
from ..config import settings
import uuid
from datetime import datetime
import base64

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/group-chat", tags=["群聊"])


def convert_minio_url_to_http(minio_url: str) -> str:
    """
    将 MinIO URL 转换为 HTTP URL
    例如: minio://bucket/group-chats/{group_id}/avatar.png -> http://host/api/auth/group-avatar/{group_id}/avatar.png
    """
    if not minio_url or not minio_url.startswith("minio://"):
        return minio_url
    
    try:
        # 解析 minio://bucket/path
        path = minio_url.replace("minio://", "").split("/", 1)[1]  # 去掉 bucket 名称
        
        # 群聊头像: group-chats/{group_id}/avatar.{ext}
        if path.startswith("group-chats/"):
            parts = path.split("/")
            if len(parts) >= 3:  # group-chats/{group_id}/{filename}
                group_id = parts[1]
                filename = parts[2]
                return f"/api/auth/group-avatar/{group_id}/{filename}"
        
        return minio_url
    except Exception as e:
        logger.warning(f"转换 MinIO URL 失败: {minio_url}, 错误: {e}")
        return minio_url


async def convert_member_to_response(
    member: GroupMember, 
    owner_id: str, 
    db: AsyncIOMotorClient = None
) -> GroupMemberResponse:
    """
    将内部 GroupMember 模型转换为前端格式的 GroupMemberResponse
    
    Args:
        member: 内部成员模型
        owner_id: 群主ID
        db: 数据库连接（用于动态获取AI名称和真人头像）
    
    Returns:
        前端格式的成员响应
    """
    # 转换 member_type: "human" -> "user", "ai" -> "ai"
    member_type = "user" if member.member_type == "human" else "ai"
    
    # 使用成员的实际角色
    role = member.role
    
    # 获取昵称
    nickname = member.display_name or member.member_id
    
    # 初始化头像（默认使用成员存储的头像）
    avatar = member.avatar
    
    # 🔥 动态获取AI会话的最新名称（确保与消息中的名称一致）
    if member.member_type == "ai" and member.session_id and db:
        try:
            from ..config import settings
            # 先查询 chat_sessions
            session_doc = await db[settings.mongodb_db_name].chat_sessions.find_one(
                {"_id": member.session_id}
            )
            # 如果找不到，再查询 ragflow_sessions
            if not session_doc:
                session_doc = await db[settings.mongodb_db_name].ragflow_sessions.find_one(
                    {"_id": member.session_id}
                )
            # 使用最新的会话名称
            if session_doc and session_doc.get("name"):
                nickname = session_doc["name"]
        except Exception as e:
            logger.warning(f"动态获取AI名称失败: session_id={member.session_id}, 错误={e}")
    
    # 🔥 真人成员：从 users 集合实时获取头像（避免使用过时头像）
    if member.member_type == "human" and db:
        try:
            from bson import ObjectId
            from ..config import settings
            
            # 将字符串格式的 member_id 转换为 ObjectId
            user_doc = await db[settings.mongodb_db_name].users.find_one(
                {"_id": ObjectId(member.member_id)}
            )
            
            # 使用最新的用户头像
            if user_doc and user_doc.get("avatar_url"):
                avatar = user_doc["avatar_url"]
            
            # 使用最新的用户昵称
            if user_doc and user_doc.get("nickname"):
                nickname = user_doc["nickname"]
                
        except Exception as e:
            logger.warning(f"动态获取真人头像失败: member_id={member.member_id}, 错误={e}")
    
    # 转换状态
    status_map = {
        "online": "online",
        "offline": "offline",
        "idle": "offline"  # idle 视为 offline
    }
    status = status_map.get(member.status, "offline")
    
    return GroupMemberResponse(
        member_id=member.member_id,
        member_type=member_type,
        nickname=nickname,
        avatar=avatar,
        status=status,
        role=role,
        joined_at=member.joined_at
    )


# ============ 群组管理接口 ============

@router.post("/groups", response_model=GroupChatWithMembers)
async def create_group(
    request: CreateGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    创建群聊
    
    - **name**: 群聊名称
    - **description**: 群聊描述（可选）
    - **initial_ai_sessions**: 初始AI成员的会话ID列表
    """
    try:
        service = GroupChatService(db)
        group = await service.create_group(str(current_user.id), request)
        
        # 获取成员列表
        members = await service.get_group_members(group.group_id)
        
        # 转换成员格式（使用 asyncio.gather 并行处理）
        members_response = await asyncio.gather(*[
            convert_member_to_response(member, group.owner_id, db)
            for member in members
        ])
        
        # 构造包含成员的响应
        return GroupChatWithMembers(
            group_id=group.group_id,
            name=group.name,
            description=group.description,
            avatar=group.avatar,
            owner_id=group.owner_id,
            members=members_response,
            created_at=group.created_at,
            updated_at=group.updated_at,
            is_active=group.is_active
        )
    except Exception as e:
        logger.error(f"创建群聊失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups", response_model=List[GroupChatWithMembers])
async def list_my_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    获取我的群聊列表
    """
    try:
        # 查询我创建的或我加入的群聊
        from ..config import settings
        service = GroupChatService(db)
        
        cursor = db[settings.mongodb_db_name].group_chats.find({
            "$or": [
                {"owner_id": str(current_user.id)},
                {"member_ids": str(current_user.id)}
            ],
            "is_active": True
        }).sort("created_at", -1)
        
        groups_with_members = []
        async for doc in cursor:
            doc.pop("_id", None)
            group = GroupChat(**doc)
            
            # 获取成员列表
            members = await service.get_group_members(group.group_id)
            
            # 转换成员格式（使用 asyncio.gather 并行处理）
            members_response = await asyncio.gather(*[
                convert_member_to_response(member, group.owner_id, db)
                for member in members
            ])
            
            # 转换头像 URL
            avatar_url = convert_minio_url_to_http(group.avatar) if group.avatar else None
            
            # 构造包含成员的响应
            groups_with_members.append(GroupChatWithMembers(
                group_id=group.group_id,
                name=group.name,
                description=group.description,
                avatar=avatar_url,
                owner_id=group.owner_id,
                members=members_response,
                created_at=group.created_at,
                updated_at=group.updated_at,
                is_active=group.is_active
            ))
        
        return groups_with_members
    except Exception as e:
        logger.error(f"获取群聊列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups/{group_id}", response_model=GroupChatWithMembers)
async def get_group(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取群聊详情"""
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 权限检查：是否是成员
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问该群聊")
        
        # 获取成员列表
        members = await service.get_group_members(group.group_id)
        
        # 转换成员格式（使用 asyncio.gather 并行处理）
        members_response = await asyncio.gather(*[
            convert_member_to_response(member, group.owner_id, db)
            for member in members
        ])
        
        # 构造包含成员的响应
        return GroupChatWithMembers(
            group_id=group.group_id,
            name=group.name,
            description=group.description,
            avatar=group.avatar,
            owner_id=group.owner_id,
            members=members_response,
            created_at=group.created_at,
            updated_at=group.updated_at,
            is_active=group.is_active
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取群聊详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/groups/{group_id}")
async def update_group(
    group_id: str,
    updates: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """更新群组基本信息（名称、简介、头像）"""
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 权限检查：仅群主可修改
        if str(current_user.id) != group.owner_id:
            raise HTTPException(status_code=403, detail="仅群主可修改群组信息")
        
        # 只允许更新特定字段
        allowed_fields = {'name', 'description', 'avatar'}
        update_data = {k: v for k, v in updates.items() if k in allowed_fields}
        
        # ⚠️ 重要：avatar 字段只能通过专门的上传API更新，不能通过这个API更新
        # 如果前端传了 avatar 字段且不是 minio:// 格式，则忽略它
        if 'avatar' in update_data:
            avatar_value = update_data.get('avatar', '')
            if not avatar_value or not avatar_value.startswith('minio://'):
                logger.warning(f"⚠️ 忽略非 minio:// 格式的 avatar 字段: {avatar_value}")
                del update_data['avatar']
        
        if not update_data:
            raise HTTPException(status_code=400, detail="没有可更新的字段")
        
        # 验证名称长度
        if 'name' in update_data:
            name = update_data['name'].strip()
            if not name:
                raise HTTPException(status_code=400, detail="群组名称不能为空")
            if len(name) < 2 or len(name) > 50:
                raise HTTPException(status_code=400, detail="群组名称长度为 2-50 个字符")
            update_data['name'] = name
        
        # 验证简介长度
        if 'description' in update_data and update_data['description']:
            if len(update_data['description']) > 200:
                raise HTTPException(status_code=400, detail="群组简介不能超过 200 个字符")
        
        # 更新数据库
        from ..config import settings
        from datetime import datetime
        update_data['updated_at'] = datetime.utcnow()
        
        result = await db[settings.mongodb_db_name].group_chats.update_one(
            {"group_id": group_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0 and result.matched_count == 0:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        logger.info(f"群组信息更新成功: {group_id}, 更新字段: {list(update_data.keys())}")
        
        return {"success": True, "message": "群组信息更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新群组信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/groups/{group_id}/system-prompt")
async def update_group_system_prompt(
    group_id: str,
    request: dict,  # {"system_prompt": "..."}
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    更新群聊的自定义系统提示词
    
    系统提示词构成：
    1. AI原本的系统提示词（来自会话配置）
    2. 群聊自定义系统提示词（本API设置）
    3. 动态群聊信息（成员列表等，自动生成）
    """
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 权限检查：仅群主可修改
        if str(current_user.id) != group.owner_id:
            raise HTTPException(status_code=403, detail="仅群主可修改群聊系统提示词")
        
        # 获取系统提示词
        system_prompt = request.get("system_prompt", "")
        
        # 验证长度（可选，但建议限制）
        if system_prompt and len(system_prompt) > 2000:
            raise HTTPException(status_code=400, detail="系统提示词不能超过 2000 个字符")
        
        # 更新数据库
        result = await db[settings.mongodb_db_name].group_chats.update_one(
            {"group_id": group_id},
            {
                "$set": {
                    "group_system_prompt": system_prompt,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        logger.info(f"✅ 群聊系统提示词已更新: {group_id}")
        
        return {
            "success": True,
            "message": "系统提示词更新成功",
            "group_id": group_id,
            "system_prompt": system_prompt
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新群聊系统提示词失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups/{group_id}/system-prompt")
async def get_group_system_prompt(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取群聊的自定义系统提示词"""
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 权限检查：是否是成员
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问该群聊")
        
        # 获取系统提示词
        group_doc = await db[settings.mongodb_db_name].group_chats.find_one(
            {"group_id": group_id},
            {"group_system_prompt": 1}
        )
        
        system_prompt = group_doc.get("group_system_prompt", "") if group_doc else ""
        
        return {
            "group_id": group_id,
            "system_prompt": system_prompt
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取群聊系统提示词失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/avatar")
async def upload_group_avatar(
    group_id: str,
    avatar_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    上传群聊头像
    
    请求体: { "avatar_data": "base64编码的图片数据" }
    
    文件将存储在 MinIO 的 group-chats/{group_id}/avatar 路径下
    """
    # 从请求体中提取avatar_data
    avatar_data_str = avatar_data.get("avatar_data", "")
    
    if not avatar_data_str:
        raise HTTPException(status_code=400, detail="缺少avatar_data参数")
    
    try:
        # 验证群聊是否存在且用户是群主
        group = await db[settings.mongodb_db_name].group_chats.find_one({"group_id": group_id})
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        logger.info(f"🔍 群聊信息: group_id={group_id}, group={group}")
        
        if group.get("owner_id") != current_user.id:
            raise HTTPException(status_code=403, detail="只有群主可以修改群聊头像")
        
        # 删除旧头像（如果存在）
        old_avatar = group.get("avatar")
        logger.info(f"🔍 检查旧头像: old_avatar={old_avatar}, type={type(old_avatar)}")
        if old_avatar and old_avatar.startswith("minio://"):
            try:
                minio_client.delete_image(old_avatar)
                logger.info(f"✅ 已删除旧头像: {old_avatar}")
            except Exception as e:
                logger.warning(f"❌ 删除旧头像失败: {e}")
        else:
            logger.info(f"ℹ️ 无需删除旧头像（不存在或格式不对）")
        
        # 解析 Base64 数据并上传
        import base64
        import uuid
        
        # 处理 Base64 数据
        if "," in avatar_data_str:
            # 格式: data:image/png;base64,xxxxx
            header, encoded = avatar_data_str.split(",", 1)
            if "image/" in header:
                file_ext = header.split("image/")[1].split(";")[0]
            else:
                file_ext = "png"
        else:
            encoded = avatar_data_str
            file_ext = "png"
        
        # 解码 Base64
        file_data = base64.b64decode(encoded)
        
        # 生成文件名
        file_id = str(uuid.uuid4())
        filename = f"{file_id}.{file_ext}"
        
        # 上传到 MinIO，路径: group-chats/{group_id}/{filename}
        # 这样前端转换规则才能匹配: group-chats/{groupId}/{filename}
        object_name = f"group-chats/{group_id}/{filename}"
        
        minio_client.client.put_object(
            settings.minio_bucket_name,
            object_name,
            io.BytesIO(file_data),
            len(file_data),
            content_type=f"image/{file_ext}"
        )
        
        # 构造 minio:// URL
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        
        logger.info(f"✅ 群聊头像上传成功: {minio_url}")
        
        # 更新数据库（存储 minio:// 格式）
        await db[settings.mongodb_db_name].group_chats.update_one(
            {"group_id": group_id},
            {"$set": {"avatar": minio_url, "updated_at": datetime.utcnow()}}
        )
        
        logger.info(f"群聊头像已更新到数据库: {group_id}, MinIO URL: {minio_url}")
        
        # 转换为 HTTP URL 返回给前端
        http_avatar_url = convert_minio_url_to_http(minio_url)
        
        return {
            "success": True,
            "message": "头像上传成功",
            "avatar_url": http_avatar_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传群聊头像失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传头像失败: {str(e)}")


@router.post("/groups/{group_id}/members")
async def add_member(
    group_id: str,
    request: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    添加成员到群聊（统一接口）
    
    - **member_type**: 成员类型（"human" 或 "ai"）
    - **member_id**: 成员ID（user_id 或 session_id）
    - **display_name**: 显示名称（可选）
    - **behavior_config**: AI行为配置（仅AI成员需要，可选）
    """
    try:
        service = GroupChatService(db)
        
        # 权限检查：是否是群主或成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权操作")
        
        # 根据成员类型添加成员
        if request.member_type == "ai":
            member = await service.add_ai_to_group(
                group_id,
                request.member_id,  # session_id
                str(current_user.id)
            )
        else:  # human
            member = await service.add_human_to_group(
                group_id,
                request.member_id,  # user_id
                str(current_user.id)  # inviter_id
            )
        
        return {"success": True, "member": member.model_dump(mode='json')}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加成员失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/groups/{group_id}/members/{member_id}")
async def remove_member(
    group_id: str,
    member_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    从群聊中移除成员
    
    - **group_id**: 群聊ID
    - **member_id**: 成员ID（user_id 或 session_id）
    
    权限：群主和管理员都可以移除普通成员，但只有群主可以移除管理员
    """
    try:
        service = GroupChatService(db)
        
        # 获取群聊信息
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 检查成员是否存在
        if member_id not in group.member_ids:
            raise HTTPException(status_code=404, detail="成员不存在")
        
        # 不能移除群主自己
        if member_id == group.owner_id:
            raise HTTPException(status_code=400, detail="不能移除群主")
        
        # 获取当前用户的角色
        current_user_id = str(current_user.id)
        collection_members = db[settings.mongodb_db_name].group_members
        
        current_user_member = await collection_members.find_one({
            "group_id": group_id,
            "member_id": current_user_id
        })
        
        if not current_user_member:
            raise HTTPException(status_code=403, detail="您不是群成员")
        
        current_role = current_user_member.get("role", "member")
        
        # 获取被移除成员的角色
        target_member = await collection_members.find_one({
            "group_id": group_id,
            "member_id": member_id
        })
        
        if not target_member:
            raise HTTPException(status_code=404, detail="成员不存在")
        
        target_role = target_member.get("role", "member")
        
        # 权限检查
        if current_role == "owner":
            # 群主可以移除任何人（除了自己）
            pass
        elif current_role == "admin":
            # 管理员只能移除普通成员
            if target_role in ["owner", "admin"]:
                raise HTTPException(status_code=403, detail="管理员无法移除群主或其他管理员")
        else:
            # 普通成员无权移除任何人
            raise HTTPException(status_code=403, detail="您没有权限移除成员")
        
        # 移除成员
        await service.remove_member(group_id, member_id)
        
        return {"success": True, "message": "成员已移除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移除成员失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/groups/{group_id}/members/{member_id}/role")
async def set_member_role(
    group_id: str,
    member_id: str,
    role: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    设置成员角色（设置/取消管理员）
    
    - **group_id**: 群聊ID
    - **member_id**: 成员ID
    - **role**: 角色 (admin/member)
    
    权限：只有群主可以设置管理员
    """
    try:
        service = GroupChatService(db)
        
        # 获取群聊信息
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 只有群主可以设置管理员
        if str(current_user.id) != group.owner_id:
            raise HTTPException(status_code=403, detail="只有群主可以设置管理员")
        
        # 检查成员是否存在
        if member_id not in group.member_ids:
            raise HTTPException(status_code=404, detail="成员不存在")
        
        # 不能修改群主自己的角色
        if member_id == group.owner_id:
            raise HTTPException(status_code=400, detail="不能修改群主角色")
        
        # 验证角色值
        if role not in ["admin", "member"]:
            raise HTTPException(status_code=400, detail="无效的角色，只能设置为 admin 或 member")
        
        # 设置角色
        if role == "admin":
            success = await service.set_admin(group_id, member_id)
        else:
            success = await service.remove_admin(group_id, member_id)
        
        if not success:
            raise HTTPException(status_code=400, detail="设置角色失败")
        
        return {"success": True, "message": f"已将成员设置为{role}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置成员角色失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/members/ai")
async def add_ai_member(
    group_id: str,
    request: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    添加AI成员到群聊（兼容旧接口）
    
    - **member_id**: 会话ID（session_id）
    - **behavior_config**: AI行为配置（可选）
    """
    try:
        service = GroupChatService(db)
        
        # 权限检查：是否是群主或成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权操作")
        
        # 添加AI成员
        member = await service.add_ai_to_group(
            group_id,
            request.member_id,  # session_id
            str(current_user.id)
        )
        
        return {"success": True, "member": member.model_dump(mode='json')}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加AI成员失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups/{group_id}/members", response_model=List[GroupMember])
async def get_group_members(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取群聊成员列表"""
    try:
        service = GroupChatService(db)
        
        # 权限检查
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问")
        
        members = await service.get_group_members(group_id)
        return members
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取成员列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/groups/{group_id}/members/ai/behavior")
async def update_ai_behavior(
    group_id: str,
    request: UpdateBehaviorRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    更新AI行为配置
    
    可以调整AI的回复概率、延迟、关键词等参数
    """
    try:
        service = GroupChatService(db)
        
        # 权限检查
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) != group.owner_id:
            raise HTTPException(status_code=403, detail="仅群主可修改AI配置")
        
        await service.update_ai_behavior(group_id, request)
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新AI行为失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups/{group_id}/strategy", response_model=GroupStrategyConfig)
async def get_group_strategy(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    获取群聊策略配置
    
    - **group_id**: 群聊ID
    
    权限：群聊成员可查看
    """
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 检查成员权限
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="你不是该群聊的成员")
        
        # 返回策略配置（如果不存在则返回默认配置）
        return group.strategy_config or GroupStrategyConfig()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取群聊策略配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/groups/{group_id}/strategy")
async def update_group_strategy(
    group_id: str,
    request: UpdateGroupStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    更新群聊策略配置
    
    - **group_id**: 群聊ID
    - **request**: 策略配置
    
    权限：只有群主可以修改策略配置
    """
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 权限检查：仅群主可修改
        if str(current_user.id) != group.owner_id:
            raise HTTPException(status_code=403, detail="只有群主可以修改策略配置")
        
        # 更新策略配置
        update_data = {
            "strategy_config": request.strategy_config.model_dump(),
            "updated_at": datetime.utcnow()
        }
        
        result = await db[settings.mongodb_db_name].group_chats.update_one(
            {"group_id": group_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0 and result.matched_count == 0:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        logger.info(f"✅ 群聊策略配置更新成功: group_id={group_id}, owner_id={current_user.id}")
        
        return {
            "success": True,
            "message": "策略配置更新成功",
            "strategy_config": request.strategy_config.model_dump()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新群聊策略配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/strategy/reset")
async def reset_group_strategy(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    重置群聊策略配置为默认值
    
    - **group_id**: 群聊ID
    
    权限：只有群主可以重置策略配置
    """
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 权限检查：仅群主可重置
        if str(current_user.id) != group.owner_id:
            raise HTTPException(status_code=403, detail="只有群主可以重置策略配置")
        
        # 重置为默认配置
        default_config = GroupStrategyConfig()
        update_data = {
            "strategy_config": default_config.model_dump(),
            "updated_at": datetime.utcnow()
        }
        
        result = await db[settings.mongodb_db_name].group_chats.update_one(
            {"group_id": group_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0 and result.matched_count == 0:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        logger.info(f"✅ 群聊策略配置已重置为默认值: group_id={group_id}")
        
        return {
            "success": True,
            "message": "策略配置已重置为默认值",
            "strategy_config": default_config.model_dump()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置群聊策略配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/ai/{ai_member_id}/online")
async def set_ai_online(
    group_id: str,
    ai_member_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    设置AI成员上线
    
    **参数：**
    
    - **group_id**: 群聊ID
    - **ai_member_id**: AI成员ID
    """
    try:
        service = GroupChatService(db)
        
        # 验证用户是否是群成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问该群聊")
        
        # 设置AI上线
        await service.set_ai_status(group_id, ai_member_id, "online")
        
        return {"success": True, "status": "online"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置AI上线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/ai/{ai_member_id}/offline")
async def set_ai_offline(
    group_id: str,
    ai_member_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    设置AI成员下线
    
    **参数：**
    
    - **group_id**: 群聊ID
    - **ai_member_id**: AI成员ID
    """
    try:
        service = GroupChatService(db)
        
        # 验证用户是否是群成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问该群聊")
        
        # 设置AI下线
        await service.set_ai_status(group_id, ai_member_id, "offline")
        
        return {"success": True, "status": "offline"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置AI下线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/ai/batch-online")
async def set_all_ai_online(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    批量设置所有AI成员上线
    
    **参数：**
    
    - **group_id**: 群聊ID
    """
    try:
        service = GroupChatService(db)
        
        # 验证用户是否是群成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问该群聊")
        
        # 获取所有成员
        members = await service.get_group_members(group_id)
        
        # 筛选AI成员
        ai_members = [m for m in members if m.member_type == "ai"]
        
        # 批量设置上线
        success_count = 0
        for member in ai_members:
            try:
                await service.set_ai_status(group_id, member.member_id, "online")
                success_count += 1
            except Exception as e:
                logger.warning(f"设置AI {member.member_id} 上线失败: {e}")
        
        return {
            "success": True, 
            "total": len(ai_members),
            "success_count": success_count,
            "message": f"成功上线 {success_count}/{len(ai_members)} 个AI"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量设置AI上线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/ai/batch-offline")
async def set_all_ai_offline(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    批量设置所有AI成员下线
    
    **参数：**
    
    - **group_id**: 群聊ID
    """
    try:
        service = GroupChatService(db)
        
        # 验证用户是否是群成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问该群聊")
        
        # 获取所有成员
        members = await service.get_group_members(group_id)
        
        # 筛选AI成员
        ai_members = [m for m in members if m.member_type == "ai"]
        
        # 批量设置下线
        success_count = 0
        for member in ai_members:
            try:
                await service.set_ai_status(group_id, member.member_id, "offline")
                success_count += 1
            except Exception as e:
                logger.warning(f"设置AI {member.member_id} 下线失败: {e}")
        
        return {
            "success": True, 
            "total": len(ai_members),
            "success_count": success_count,
            "message": f"成功下线 {success_count}/{len(ai_members)} 个AI"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量设置AI下线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _expand_group_history_references(messages: List[Dict[str, Any]], group_id: str, db: AsyncIOMotorClient) -> List[Dict[str, Any]]:
    """
    将群聊历史消息中的精简引用（document_id, chunk_id, score）展开为富引用。
    完全复制普通会话的引用展开逻辑，确保100%一致性。
    """
    logger.info(f"📝 群聊历史引用展开: 开始处理，消息数={len(messages) if messages else 0}")
    if not messages:
        logger.info("📝 群聊历史引用展开: 无消息需要处理")
        return messages
    
    # 获取群聊信息，检查是否启用了知识库
    try:
        service = GroupChatService(db)
        group = await service.get_group_info(group_id)
        if not group:
            logger.warning(f"📝 群聊历史引用展开: 群聊 {group_id} 不存在")
            return messages
        
        # 检查群聊中是否有AI成员且启用了知识库
        # 从group_members集合查询AI成员
        kb_settings = None
        logger.info(f"📝 群聊历史引用展开: 群组 {group_id} 有 {len(group.ai_member_ids)} 个AI成员")
        
        # 查询AI成员信息
        ai_members_cursor = db[settings.mongodb_db_name].group_members.find({
            "group_id": group_id,
            "member_type": "ai"
        })
        ai_members = await ai_members_cursor.to_list(length=None)
        logger.info(f"📝 群聊历史引用展开: 查询到 {len(ai_members)} 个AI成员记录")
        
        for member_doc in ai_members:
            session_id = member_doc.get("session_id")
            logger.info(f"📝 群聊历史引用展开: 检查AI成员 {member_doc.get('member_id')}, session_id={session_id}")
            if session_id:
                # 查询chat_sessions
                session_doc = await db[settings.mongodb_db_name].chat_sessions.find_one(
                    {"_id": session_id}
                )
                logger.info(f"📝 群聊历史引用展开: 会话 {session_id} 的 session_doc={'存在' if session_doc else '不存在'}")
                if session_doc:
                    kb_enabled = session_doc.get("kb_settings", {}).get("enabled")
                    logger.info(f"📝 群聊历史引用展开: 会话 {session_id} 的 kb_enabled={kb_enabled}")
                if session_doc and session_doc.get("kb_settings", {}).get("enabled"):
                    kb_settings = session_doc.get("kb_settings")
                    logger.info(f"📝 群聊历史引用展开: 从会话 {session_id} 获取到知识库配置: {kb_settings}")
                    break
        
        if not kb_settings or not kb_settings.get("enabled"):
            logger.info(f"📝 群聊历史引用展开: 知识库未启用 (kb_settings={'存在' if kb_settings else '不存在'})")
            return messages
        
        # 收集所有 chunk_id
        chunk_to_ref = {}  # chunk_id -> 引用数据
        for i, msg in enumerate(messages):
            msg_id = msg.get("message_id", "未知")
            ref_field = msg.get("reference")
            logger.info(f"📝 群聊历史引用展开: 消息#{i} (id={msg_id}), reference字段={ref_field}")
            refs = msg.get("reference") or []
            if isinstance(refs, dict):
                refs = [refs]
            for r in refs:
                if r and r.get("chunk_id"):
                    chunk_to_ref[r["chunk_id"]] = r
                    logger.info(f"📝 群聊历史引用展开: 收集到 chunk_id={r.get('chunk_id')}")
        
        chunk_ids = list(chunk_to_ref.keys())
        logger.info(f"📝 群聊历史引用展开: 收集到 {len(chunk_ids)} 个唯一 chunk_id")
        logger.info(f"📝 群聊历史引用展开: chunk_to_ref 示例: {list(chunk_to_ref.items())[:2]}")
        
        if not chunk_ids:
            logger.info("📝 群聊历史引用展开: 没有需要展开的引用")
            return messages
        
        # 从多知识库检索
        from ..services.vectorstore_manager import get_vectorstore_manager
        from ..services.embedding_manager import get_embedding_manager
        from ..utils.embedding.path_utils import build_chroma_persist_dir, get_chroma_collection_name
        
        vectorstore_manager = get_vectorstore_manager()
        embedding_manager = get_embedding_manager()
        
        kb_ids = kb_settings.get("kb_ids", [])
        logger.info(f"📝 群聊历史引用展开: kb_settings={kb_settings}")
        logger.info(f"📝 群聊历史引用展开: kb_ids={kb_ids}")
        if not kb_ids:
            logger.warning("📝 群聊历史引用展开: kb_settings中未配置kb_ids")
            return messages
        
        # 获取Embedding配置
        emb_cfg = kb_settings.get("embeddings", {})
        provider = emb_cfg.get("provider", "local")
        model = emb_cfg.get("model", "all-MiniLM-L6-v2")
        base_url = emb_cfg.get("base_url")
        api_key = emb_cfg.get("api_key")
        local_model_path = emb_cfg.get("local_model_path", "checkpoints/embeddings/all-MiniLM-L6-v2")
        
        # 获取embedding function
        embedding_function = embedding_manager.get_or_create(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            local_model_path=local_model_path
        )
        
        # 按document_id分组查询
        docs_by_kb = {}
        for kb_id in kb_ids:
            logger.info(f"📝 群聊历史引用展开: 正在处理知识库 kb_id={kb_id}")
            kb_doc = await db[settings.mongodb_db_name].knowledge_bases.find_one({"_id": ObjectId(kb_id)})
            if not kb_doc:
                logger.warning(f"📝 群聊历史引用展开: 知识库 {kb_id} 不存在")
                continue
            
            collection_name_raw = kb_doc.get("collection_name")
            if not collection_name_raw:
                logger.warning(f"📝 群聊历史引用展开: 知识库 {kb_id} 没有 collection_name")
                continue
            
            logger.info(f"📝 群聊历史引用展开: 知识库 {kb_id} 的 collection_name={collection_name_raw}")
            
            # 获取Chroma的collection_name和persist_dir
            collection_name = get_chroma_collection_name(collection_name_raw)
            persist_dir = build_chroma_persist_dir(collection_name_raw)
            
            # 获取该知识库的向量存储
            try:
                vs = vectorstore_manager.get_or_create(
                    collection_name=collection_name,
                    persist_dir=persist_dir,
                    embedding_function=embedding_function,
                    vector_db_type="chroma"
                )
                logger.info(f"📝 群聊历史引用展开: 获取到 VectorStore，类型={type(vs).__name__}, has_get_by_ids={hasattr(vs, 'get_by_ids')}")
                
                # 查询该库中的chunk（document_id可能是原始知识库名称或Chroma collection_name）
                kb_chunks = [
                    cid for cid in chunk_ids 
                    if chunk_to_ref[cid].get("document_id") in [collection_name_raw, collection_name]
                ]
                logger.info(f"📝 群聊历史引用展开: 按 document_id 匹配到 {len(kb_chunks)} 个 chunk")
                logger.info(f"📝 群聊历史引用展开: collection_name_raw={collection_name_raw}, collection_name={collection_name}")
                if chunk_ids:
                    logger.info(f"📝 群聊历史引用展开: 第一个引用的document_id={chunk_to_ref[chunk_ids[0]].get('document_id')}")
                
                if not kb_chunks:
                    # 如果没有按document_id匹配的，尝试查询所有chunk（回退机制）
                    kb_chunks = chunk_ids
                    logger.info(f"📝 群聊历史引用展开: 未匹配到，使用所有 chunk_ids作为回退，共 {len(kb_chunks)} 个")
                
                if kb_chunks and hasattr(vs, "get_by_ids"):
                    logger.info(f"📝 群聊历史引用展开: 准备调用 get_by_ids 查询 {len(kb_chunks)} 个文档")
                    docs = await vs.get_by_ids(kb_chunks)
                    logger.info(f"📝 群聊历史引用展开: get_by_ids 返回了 {len(docs)} 个文档")
                    for doc in docs:
                        cid = doc.metadata.get("chunk_id")
                        if cid:
                            docs_by_kb[cid] = doc
                    logger.info(f"📝 群聊历史引用展开: 从知识库 {collection_name} 查询到 {len(docs)} 个文档")
                else:
                    logger.warning(f"📝 群聊历史引用展开: kb_chunks={len(kb_chunks) if kb_chunks else 0}, has_get_by_ids={hasattr(vs, 'get_by_ids')}")
            except Exception as e:
                logger.error(f"📝 群聊历史引用展开: 查询知识库 {collection_name} 失败: {e}", exc_info=True)
                continue
        
        logger.info(f"📝 群聊历史引用展开: 总共查询到 {len(docs_by_kb)} 个文档")
        
        # 展开引用
        for msg in messages:
            refs = msg.get("reference") or []
            if isinstance(refs, dict):
                refs = [refs]
            rich_refs = []
            for r in refs:
                cid = r.get("chunk_id") if isinstance(r, dict) else None
                if not cid:
                    continue
                
                doc = docs_by_kb.get(cid)
                if not doc:
                    logger.warning(f"📝 群聊历史引用展开: chunk_id={cid} 在所有知识库中未找到")
                    continue
                
                meta = doc.metadata or {}
                rich_refs.append({
                    "ref_marker": r.get("ref_marker"),
                    "document_id": meta.get("source") or r.get("document_id"),
                    "chunk_id": cid,
                    "score": r.get("score"),
                    "document_name": meta.get("source"),
                    "content": doc.page_content,
                    "metadata": meta,
                    # 添加用于查看原文的必要字段
                    "doc_id": meta.get("doc_id") or r.get("doc_id"),
                    "kb_id": meta.get("kb_id") or r.get("kb_id"),
                    "filename": meta.get("filename") or r.get("filename"),
                })
            
            logger.info(f"📝 群聊历史引用展开: 消息展开了 {len(rich_refs)} 个引用")
            msg["reference"] = rich_refs
        
        return messages
    except Exception as e:
        logger.error(f"📝 群聊历史引用展开失败: {str(e)}")
        logger.error(traceback.format_exc())
        return messages


async def _update_message_sender_names(
    messages: List[GroupMessage],
    db: AsyncIOMotorClient
) -> List[dict]:
    """
    动态更新消息的sender_name（从chat_sessions获取最新名称）
    
    Args:
        messages: 消息列表
        db: 数据库连接
    
    Returns:
        更新后的消息字典列表
    """
    if not messages:
        return []
    
    # 收集所有需要查询的ID（真人用户ID和AI会话ID）
    user_ids = set()
    session_ids = set()
    
    for msg in messages:
        if msg.sender_id.startswith("ai_"):
            # AI消息：提取session_id
            session_id = msg.sender_id.replace("ai_", "")
            session_ids.add(session_id)
        else:
            # 真人消息：user_id
            user_ids.add(msg.sender_id)
    
    # 批量查询真人用户信息
    user_name_map = {}
    if user_ids:
        users_cursor = db[settings.mongodb_db_name].users.find(
            {"_id": {"$in": list(user_ids)}}
        )
        async for user_doc in users_cursor:
            user_id = str(user_doc["_id"])
            user_name_map[user_id] = user_doc.get("username", "未知用户")
    
    # 批量查询AI会话信息（只查询chat_sessions）
    session_name_map = {}
    if session_ids:
        session_list = list(session_ids)
        
        # 查询chat_sessions
        chat_sessions_cursor = db[settings.mongodb_db_name].chat_sessions.find(
            {"_id": {"$in": session_list}}
        )
        async for session_doc in chat_sessions_cursor:
            session_id = str(session_doc["_id"])
            session_name_map[session_id] = session_doc.get("name", "AI助手")
    
    # 更新消息的sender_name
    result = []
    for msg in messages:
        msg_dict = msg.model_dump(mode='json')
        
        # 动态获取最新的sender_name
        if msg.sender_id.startswith("ai_"):
            session_id = msg.sender_id.replace("ai_", "")
            msg_dict["sender_name"] = session_name_map.get(session_id, msg.sender_name)
        else:
            msg_dict["sender_name"] = user_name_map.get(msg.sender_id, msg.sender_name)
        
        # ✅ 确保 reference 字段存在且格式正确（与普通会话字段名一致）
        if not msg_dict.get("reference"):
            msg_dict["reference"] = []
        
        result.append(msg_dict)
    
    return result


@router.get("/groups/{group_id}/messages")
async def get_group_messages(
    group_id: str,
    limit: Optional[int] = None,
    before_timestamp: Optional[float] = None,  # 使用时间戳游标代替offset
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    获取群聊消息历史（支持懒加载分页）
    
    参数：
    - limit: 每次加载的消息数量（默认返回所有）
    - before_timestamp: 获取此时间戳之前的消息（用于懒加载）
    
    返回：
    - 如果不指定limit，返回所有消息列表（向后兼容）
    - 如果指定limit，返回分页数据：{messages, total, has_more, oldest_timestamp}
    """
    try:
        service = GroupChatService(db)
        
        # 权限检查
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权访问")
        
        # 如果没有指定limit，返回所有消息（向后兼容）
        if limit is None:
            all_messages = await service.get_recent_messages(group_id, limit=1000)
            # 🔥 动态更新sender_name
            updated_messages = await _update_message_sender_names(all_messages, db)
            # 🔥 展开知识库引用（与普通会话100%一致）
            expanded_messages = await _expand_group_history_references(updated_messages, group_id, db)
            logger.info(f"获取群聊消息（全部） - 群组ID: {group_id}, 消息数量: {len(expanded_messages)}")
            return expanded_messages
        
        # 懒加载模式：使用时间戳游标
        # 获取总消息数（用于判断是否还有更多）
        collection = db.group_messages
        total_count = await collection.count_documents({"group_id": group_id})
        
        # 构建查询条件
        query = {"group_id": group_id}
        if before_timestamp is not None:
            query["timestamp"] = {"$lt": before_timestamp}
        
        # 按时间倒序查询（最新的在前）
        cursor = collection.find(query).sort("timestamp", -1).limit(limit)
        
        message_objects = []
        oldest_timestamp = None
        async for doc in cursor:
            doc.pop("_id", None)
            message = GroupMessage(**doc)
            message_objects.append(message)
            # 记录最旧的时间戳
            if oldest_timestamp is None or message.timestamp < oldest_timestamp:
                oldest_timestamp = message.timestamp
        
        # 🔥 动态更新sender_name
        updated_messages = await _update_message_sender_names(message_objects, db)
        # 🔥 展开知识库引用（与普通会话100%一致）
        expanded_messages = await _expand_group_history_references(updated_messages, group_id, db)
        
        # 判断是否还有更多消息
        has_more = False
        if oldest_timestamp is not None:
            older_count = await collection.count_documents({
                "group_id": group_id,
                "timestamp": {"$lt": oldest_timestamp}
            })
            has_more = older_count > 0
        
        logger.info(f"获取群聊消息（懒加载） - 群组ID: {group_id}, 返回: {len(expanded_messages)}条, 总数: {total_count}, 还有更多: {has_more}")
        
        return {
            "messages": expanded_messages,
            "total": total_count,
            "has_more": has_more,
            "oldest_timestamp": oldest_timestamp  # 返回最旧消息的时间戳，用于下次查询
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/messages")
async def send_message(
    group_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    发送群聊消息
    
    **参数：**
    
    - **group_id**: 群聊ID
    - **content**: 消息内容
    """
    try:
        service = GroupChatService(db)
        
        # 验证用户是否是群成员
        group = await service.get_group_info(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        if str(current_user.id) not in group.member_ids:
            raise HTTPException(status_code=403, detail="无权在该群聊发送消息")
        
        # 发送消息
        message = await service.send_message(
            group_id=group_id,
            sender_id=str(current_user.id),
            content=request.content
        )
        
        return {"success": True, "message": message}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_scheduler_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取调度器统计信息（调试用）"""
    service = GroupChatService(db)
    stats = await service.get_scheduler_stats()
    return stats


@router.get("/search/users")
async def search_users(
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    搜索用户（用于添加真人成员到群聊）
    
    **参数：**
    
    - **query**: 搜索关键词（匹配用户名或昵称）
    - **limit**: 返回结果数量限制（默认10）
    
    **返回：**
    
    ```json
    [
        {
            "user_id": "用户ID",
            "username": "用户名",
            "nickname": "昵称",
            "avatar": "头像URL"
        }
    ]
    ```
    """
    try:
        from ..config import settings
        
        # 构建搜索条件（模糊匹配账号或全名）
        search_filter = {
            "$or": [
                {"account": {"$regex": query, "$options": "i"}},  # 不区分大小写
                {"full_name": {"$regex": query, "$options": "i"}}
            ]
        }
        
        # 排除当前用户自己
        search_filter["account"] = {"$ne": current_user.account}
        
        # 查询用户
        cursor = db[settings.mongodb_db_name].users.find(
            search_filter,
            {"_id": 1, "account": 1, "full_name": 1, "avatar_url": 1}
        ).limit(limit)
        
        users = []
        async for user_doc in cursor:
            users.append({
                "user_id": str(user_doc["_id"]),  # 转换ObjectId为字符串
                "username": user_doc.get("account", ""),  # 账号
                "nickname": user_doc.get("full_name") or user_doc.get("account", "未命名用户"),  # 显示名称（优先全名，否则账号）
                "avatar": user_doc.get("avatar_url")
            })
        
        logger.info(f"🔍 搜索用户: 关键词={query} | 结果数={len(users)}")
        return users
        
    except Exception as e:
        logger.error(f"搜索用户失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============ WebSocket 接口 ============

@router.websocket("/ws/{group_id}")
async def websocket_group_chat(
    websocket: WebSocket,
    group_id: str,
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    群聊 WebSocket 连接
    
    功能：
    - 长连接支持：保持连接直到客户端主动断开
    - 心跳机制：支持ping/pong保活
    - 超时检测：90秒无活动自动断开
    - 自动清理：连接断开后自动清理资源
    
    消息格式：
    ```json
    {
        "type": "auth|message|ping",
        "data": {...}
    }
    ```
    """
    import asyncio
    from datetime import datetime, timedelta
    
    await websocket.accept()
    logger.info(f"🔌 WebSocket连接请求: 群组={group_id}")
    
    service = GroupChatService(db)
    user_id = None
    websocket_id = str(uuid.uuid4())
    last_activity = datetime.now()
    TIMEOUT_SECONDS = 90  # 90秒超时（前端30秒心跳，留足余量）
    
    async def check_timeout():
        """定期检查连接超时"""
        nonlocal last_activity
        while True:
            await asyncio.sleep(30)  # 每30秒检查一次
            
            if datetime.now() - last_activity > timedelta(seconds=TIMEOUT_SECONDS):
                logger.warning(f"⏰ WebSocket超时: 群组={group_id} | 用户={user_id} | 最后活动={last_activity}")
                raise Exception("连接超时")
    
    timeout_task = asyncio.create_task(check_timeout())
    
    try:
        # 1. 等待认证消息（10秒超时）
        try:
            auth_data = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(f"⏰ 认证超时: 群组={group_id}")
            await websocket.send_json({
                "type": "error",
                "data": {"message": "认证超时"}
            })
            await websocket.close()
            return
        
        last_activity = datetime.now()
        
        if auth_data.get("type") != "auth":
            await websocket.send_json({
                "type": "error",
                "data": {"message": "请先发送认证消息"}
            })
            await websocket.close()
            return
        
        # 2. 验证Token（简化处理，生产环境需完整验证）
        token = auth_data.get("data", {}).get("token")
        if not token:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "缺少token"}
            })
            await websocket.close()
            return
        
        # TODO: 完整的JWT验证
        # 这里简化处理，直接从data中获取user_id
        user_id = auth_data.get("data", {}).get("user_id")
        
        if not user_id:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "认证失败"}
            })
            await websocket.close()
            return
        
        # 3. 验证群组权限
        group = await service.get_group_info(group_id)
        if not group:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "群聊不存在"}
            })
            await websocket.close()
            return
        
        if user_id not in group.member_ids:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "无权访问该群聊"}
            })
            await websocket.close()
            return
        
        # 4. 连接成功
        await service.human_connect(group_id, user_id, websocket_id, websocket)
        logger.info(f"✅ WebSocket认证成功: 群组={group_id} | 用户={user_id} | WS_ID={websocket_id}")
        
        await websocket.send_json({
            "type": "auth_success",
            "data": {"message": "认证成功"}
        })
        
        # 5. 发送历史消息（懒加载优化：只发送最近20条）
        INITIAL_LOAD_LIMIT = 20
        all_messages = await service.get_recent_messages(group_id, limit=1000)  # 获取足够多的消息用于统计
        total_messages = len(all_messages)
        
        # 只发送最近的消息
        recent_messages = all_messages[-INITIAL_LOAD_LIMIT:] if len(all_messages) > INITIAL_LOAD_LIMIT else all_messages
        has_more = len(all_messages) > INITIAL_LOAD_LIMIT
        
        # 🔥 动态更新sender_name
        updated_recent_messages = await _update_message_sender_names(recent_messages, db)
        # 🔥 展开知识库引用（与普通会话100%一致）
        expanded_recent_messages = await _expand_group_history_references(updated_recent_messages, group_id, db)
        
        logger.info(f"📤 发送历史消息（懒加载），显示最近{len(expanded_recent_messages)}条，总共{total_messages}条，还有更多: {has_more}")
        
        await websocket.send_json({
            "type": "history",
            "data": {
                "messages": expanded_recent_messages,
                "total": total_messages,
                "loaded": len(expanded_recent_messages),
                "has_more": has_more
            }
        })
        
        # 6. 消息循环
        while True:
            data = await websocket.receive_json()
            last_activity = datetime.now()  # 更新活动时间
            msg_type = data.get("type")
            
            if msg_type == "message":
                # 发送消息
                content = data.get("data", {}).get("content")
                images = data.get("data", {}).get("images", [])
                mentions = data.get("data", {}).get("mentions", [])
                reply_to = data.get("data", {}).get("reply_to")
                
                request = SendMessageRequest(
                    content=content,
                    images=images,
                    mentions=mentions,
                    reply_to=reply_to
                )
                
                message = await service.send_human_message(group_id, user_id, request)
                
                # 发送确认（需要序列化 datetime）
                await websocket.send_json({
                    "type": "message_sent",
                    "data": message.model_dump(mode='json')
                })
            
            elif msg_type == "ping":
                # 心跳
                logger.debug(f"💓 收到心跳ping: 群组={group_id} | 用户={user_id}")
                await websocket.send_json({"type": "pong"})
            
            else:
                logger.warning(f"未知消息类型: {msg_type}")
    
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket正常断开: 群组={group_id} | 用户={user_id}")
    
    except asyncio.CancelledError:
        logger.info(f"🔌 WebSocket连接被取消: 群组={group_id} | 用户={user_id}")
    
    except Exception as e:
        logger.error(f"❌ WebSocket错误: {e} | 群组={group_id} | 用户={user_id}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    
    finally:
        # 取消超时检测任务
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass
        
        # 清理连接
        if user_id:
            try:
                await service.human_disconnect(group_id, user_id)
                logger.info(f"🧹 WebSocket资源清理完成: 群组={group_id} | 用户={user_id}")
            except Exception as e:
                logger.error(f"❌ 清理连接失败: {e}")


@router.delete("/groups/{group_id}/messages")
async def clear_all_messages(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    清空群聊所有历史消息
    
    只有群主可以清空历史消息。清空后将删除：
    - MongoDB中的所有群聊消息 (group_messages)
    - MinIO中所有消息相关的文件（图片、语音等）
    
    注意：不会删除群聊本身和成员信息
    """
    try:
        # 验证群聊是否存在
        group = await db[settings.mongodb_db_name].group_chats.find_one({"group_id": group_id})
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 验证是否是群主
        if group.get("owner_id") != current_user.id:
            raise HTTPException(status_code=403, detail="只有群主可以清空历史消息")
        
        logger.info(f"开始清空群聊历史消息: {group_id}, 群主: {current_user.id}")
        
        # 1. 删除 MinIO 中的所有消息文件（图片、语音等）
        total_deleted_files = 0
        try:
            # 群聊消息文件存储在 group-chats/{group_id}/messages/ 路径下
            folder_prefix = f"group-chats/{group_id}/messages/"
            deleted_count = minio_client.delete_folder(folder_prefix)
            total_deleted_files += deleted_count
            logger.info(f"已删除MinIO消息文件夹: {folder_prefix}, 文件数: {deleted_count}")
        except Exception as e:
            logger.warning(f"删除MinIO消息文件夹失败: {e}")
            # 继续执行，不因为MinIO删除失败而中断
        
        # 2. 删除 MongoDB 中的所有群聊消息
        messages_result = await db[settings.mongodb_db_name].group_messages.delete_many(
            {"group_id": group_id}
        )
        logger.info(f"已删除群聊消息: {messages_result.deleted_count} 条")
        
        # 3. 通知所有在线成员消息已被清空（通过WebSocket）
        try:
            service = GroupChatService.get_instance()
            connections = service.get_group_connections(group_id)
            
            clear_notification = {
                "type": "messages_cleared",
                "data": {
                    "group_id": group_id,
                    "cleared_by": current_user.username,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            
            logger.info(f"📢 通知 {len(connections)} 个在线连接: 历史消息已清空")
            
            for conn in connections:
                try:
                    await conn.send_json(clear_notification)
                    logger.debug(f"✅ 已通知连接清空消息")
                except Exception as e:
                    logger.warning(f"发送清空通知失败: {e}")
        except Exception as e:
            logger.warning(f"通知在线成员失败: {e}")
        
        logger.info(f"✅ 群聊历史消息清空成功: {group_id}")
        
        return {
            "success": True,
            "message": "历史消息已清空",
            "deleted": {
                "messages": messages_result.deleted_count,
                "files": total_deleted_files
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清空历史消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清空历史消息失败: {str(e)}")


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """
    解散群聊
    
    只有群主可以解散群聊。解散后将删除：
    - MongoDB中的群聊文档 (group_chats)
    - MongoDB中的群聊背景图记录 (groups)
    - MongoDB中的群聊消息 (group_messages)
    - MongoDB中的群聊成员记录 (group_members)
    - MinIO中的群聊文件夹及所有文件 (group-chats/{group_id}/)
    - MinIO中的群聊背景图 (groups/{group_id}/)
    
    注意：不会删除AI会话实例，因为它们是独立的会话
    """
    try:
        # 验证群聊是否存在
        group = await db[settings.mongodb_db_name].group_chats.find_one({"group_id": group_id})
        if not group:
            raise HTTPException(status_code=404, detail="群聊不存在")
        
        # 验证是否是群主
        if group.get("owner_id") != current_user.id:
            raise HTTPException(status_code=403, detail="只有群主可以解散群聊")
        
        logger.info(f"开始解散群聊: {group_id}, 群主: {current_user.id}")
        
        # 1. 删除 MinIO 中的群聊文件夹及所有文件
        total_deleted_files = 0
        try:
            folder_prefix = f"group-chats/{group_id}/"
            deleted_count = minio_client.delete_folder(folder_prefix)
            total_deleted_files += deleted_count
            logger.info(f"已删除MinIO文件夹: {folder_prefix}, 文件数: {deleted_count}")
        except Exception as e:
            logger.warning(f"删除MinIO群聊文件夹失败: {e}")
            # 继续执行，不因为MinIO删除失败而中断
        
        # 1.5. 删除 MinIO 中的群聊背景图（存储在 groups/{group_id}/ 路径下）
        try:
            background_prefix = f"groups/{group_id}/"
            deleted_bg_count = minio_client.delete_folder(background_prefix)
            total_deleted_files += deleted_bg_count
            logger.info(f"已删除MinIO背景图文件夹: {background_prefix}, 文件数: {deleted_bg_count}")
        except Exception as e:
            logger.warning(f"删除MinIO背景图文件夹失败: {e}")
            # 继续执行，不因为MinIO删除失败而中断
        
        # 2. 删除 MongoDB 中的群聊消息
        messages_result = await db[settings.mongodb_db_name].group_messages.delete_many(
            {"group_id": group_id}
        )
        logger.info(f"已删除群聊消息: {messages_result.deleted_count} 条")
        
        # 3. 删除 MongoDB 中的群聊成员记录（如果有单独的集合）
        # 注意：当前成员信息存储在 group_chats 文档中，所以这一步可能不需要
        # 如果将来有独立的 group_members 集合，取消注释以下代码：
        # members_result = await db[settings.mongodb_db_name].group_members.delete_many(
        #     {"group_id": group_id}
        # )
        # logger.info(f"已删除群聊成员记录: {members_result.deleted_count} 条")
        
        # 4. 删除 MongoDB 中的群聊文档
        group_result = await db[settings.mongodb_db_name].group_chats.delete_one(
            {"group_id": group_id}
        )
        
        if group_result.deleted_count == 0:
            raise HTTPException(status_code=500, detail="删除群聊失败")
        
        # 5. 删除 MongoDB 中的 groups 集合记录（存储背景图信息）
        try:
            groups_result = await db[settings.mongodb_db_name].groups.delete_one(
                {"group_id": group_id}
            )
            if groups_result.deleted_count > 0:
                logger.info(f"已删除groups集合记录: {groups_result.deleted_count} 条")
        except Exception as e:
            logger.warning(f"删除groups集合记录失败: {e}")
            # 继续执行，不因为删除失败而中断
        
        logger.info(f"✅ 群聊解散成功: {group_id}")
        
        return {
            "success": True,
            "message": "群聊已解散",
            "deleted": {
                "group": 1,
                "messages": messages_result.deleted_count,
                "files": total_deleted_files
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解散群聊失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"解散群聊失败: {str(e)}")

