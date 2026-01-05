import uuid
import base64
from datetime import timedelta, datetime
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

from ..models.user import (
    User,
    UserCreate,
    authenticate_user,
    authenticate_user_by_identifier,  # 添加这个导入
    create_access_token,
    get_password_hash,
    get_current_active_user,
    users_collection,
    get_current_user,
    get_user_by_email
)
from ..models.verification import verify_code
from ..config import Settings, settings
from pydantic import BaseModel
from typing import Dict, Optional
from fastapi import HTTPException
from fastapi.responses import Response
from ..utils.minio_client import minio_client
from ..database import get_database
import logging

logger = logging.getLogger(__name__)

class AvatarUploadRequest(BaseModel):
    avatar: str  # base64编码的图片数据

class RoleAvatarUploadRequest(BaseModel):
    avatar: str  # base64编码的图片数据
    session_id: str  # 会话ID

# 为助手头像上传新增请求模型
class AssistantAvatarUploadRequest(BaseModel):
    avatar: str  # base64编码的图片数据
    assistant_id: str  # 助手ID

# 配置
settings = Settings()

# 创建路由
router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    account: str
    email: Optional[str] = None
    password: str
    full_name: Optional[str] = None

class UserCreateWithVerification(BaseModel):
    """带邮箱验证的用户注册请求"""
    account: str
    email: str
    password: str
    verification_code: str
    full_name: Optional[str] = None

class ModelConfig(BaseModel):
    base_url: str
    api_key: str

class AppSettingsResponse(BaseModel):
    email_verification: bool

@router.post("/register", response_model=User)
async def register(user_data: UserCreate):
    """用户注册（不需要邮箱验证）"""
    # 检查账号是否已存在
    if await users_collection.find_one({"account": user_data.account}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="账号已存在"
        )

    # 如果提供了邮箱，检查邮箱是否已被使用
    if user_data.email:
        existing_email_user = await get_user_by_email(user_data.email)
        if existing_email_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该邮箱已被注册"
            )

    # 创建新用户
    user_dict = {
        "account": user_data.account,
        "email": user_data.email.strip() if user_data.email else None,  # 保留原格式，仅去除首尾空格
        "full_name": user_data.full_name,
        "hashed_password": get_password_hash(user_data.password),
        "disabled": False
    }

    # 保存到数据库，MongoDB 会自动生成 _id
    result = await users_collection.insert_one(user_dict)
    
    # 将 MongoDB 的 ObjectId 转换为字符串 id 字段
    user_dict["id"] = str(result.inserted_id)

    # 返回用户信息（不包含密码）
    return User(**user_dict)

@router.post("/register-with-email", response_model=User)
async def register_with_email_verification(user_data: UserCreateWithVerification):
    """用户注册（需要邮箱验证）"""
    import re
    from ..config import settings
    
    # 检查邮件验证是否启用
    if not settings.email_verification:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮箱验证服务未启用"
        )
    
    # 验证邮箱格式
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱格式不正确"
        )
    
    # 验证验证码（使用原格式验证）
    is_valid_code = await verify_code(user_data.email.strip(), user_data.verification_code)
    if not is_valid_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期"
        )
    
    # 检查账号是否已存在
    if await users_collection.find_one({"account": user_data.account}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="账号已存在"
        )

    # 检查邮箱是否已被使用
    existing_email_user = await get_user_by_email(user_data.email)
    if existing_email_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已被注册"
        )

    # 创建新用户
    user_dict = {
        "account": user_data.account,
        "email": user_data.email.strip(),  # 保留原格式，仅去除首尾空格
        "full_name": user_data.full_name,
        "hashed_password": get_password_hash(user_data.password),
        "disabled": False,
        "email_verified": True  # 标记邮箱已验证
    }

    # 保存到数据库，MongoDB 会自动生成 _id
    result = await users_collection.insert_one(user_dict)
    
    # 将 MongoDB 的 ObjectId 转换为字符串 id 字段
    user_dict["id"] = str(result.inserted_id)

    # 返回用户信息（不包含密码）
    return User(**user_dict)

@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """用户登录 - 支持邮箱或账号登录"""
    import re
    
    # 判断是邮箱还是账号
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    is_email = re.match(email_pattern, form_data.username)
    
    if is_email:
        # 邮箱登录
        user = await authenticate_user_by_identifier(form_data.username, form_data.password)
    else:
        # 账号登录
        user = await authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号/邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.account},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """获取当前用户信息"""
    return current_user

@router.put("/me", response_model=User)
async def update_user_me(
    user_data: UserCreate,
    current_user: User = Depends(get_current_active_user)
):
    """更新当前用户信息"""
    # 检查新账号是否与其他用户冲突
    if user_data.account != current_user.account:
        if await users_collection.find_one({"account": user_data.account}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="账号已存在"
            )

    # 更新用户信息
    update_data = {
        "account": user_data.account,
        "email": user_data.email,
        "full_name": user_data.full_name
    }

    # 如果提供了新密码，更新密码
    if user_data.password:
        update_data["hashed_password"] = get_password_hash(user_data.password)

    # 更新数据库 - 使用 _id (ObjectId) 进行查询
    from bson import ObjectId
    await users_collection.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": update_data}
    )

    # 获取更新后的用户信息
    updated_user = await users_collection.find_one({"_id": ObjectId(current_user.id)})
    if updated_user and "_id" in updated_user:
        updated_user["id"] = str(updated_user["_id"])
    return User(**updated_user)

@router.get("/model-config/{model_service}", response_model=ModelConfig)
async def get_model_config(
    model_service: str,
    current_user: User = Depends(get_current_active_user)
):
    """获取指定模型服务的配置"""
    # 安全日志：不打印敏感信息
    logger.info(f"请求获取 {model_service} 的配置")
    
    config_map = {
        "doubao": {
            "base_url": settings.doubao_base_url,
            "api_key": settings.doubao_api_key
        },
        "deepseek": {
            "base_url": settings.deepseek_base_url,
            "api_key": settings.deepseek_api_key
        },
        "bailian": {
            "base_url": settings.bailian_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": settings.bailian_api_key
        },
        "ollama": {
            "base_url": "http://localhost:11434",
            "api_key": ""
        },
        "local": {
            "base_url": "http://localhost:8000",
            "api_key": ""
        }
    }
    
    if model_service not in config_map:
        logger.warning(f"不支持的模型服务: {model_service}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的模型服务"
        )
    
    config = config_map[model_service]
    # 安全日志：只记录是否有密钥，不打印密钥内容
    has_api_key = bool(config.get("api_key"))
    logger.info(f"返回 {model_service} 配置 (base_url={config.get('base_url')}, has_api_key={has_api_key})")
    return ModelConfig(**config)

@router.post("/upload-avatar")
async def upload_avatar(
    avatar_data: AvatarUploadRequest,
    current_user: User = Depends(get_current_active_user)
):
    """上传用户头像"""
    try:
        # 上传到MinIO - 使用正确的参数顺序
        # upload_image(image_base64, session_id, message_id, user_id)
        minio_url = minio_client.upload_image(
            avatar_data.avatar,
            "user_profile",  # session_id: 用于用户头像的虚拟session
            "avatar",        # message_id: 标识为头像
            current_user.id # user_id: 用户ID字符串
        )
        
        if not minio_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="头像上传失败"
            )
        
        # 更新用户信息中的头像URL - 使用 _id (ObjectId)
        from bson import ObjectId
        await users_collection.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {"avatar_url": minio_url}}
        )
        
        return {"avatar_url": minio_url}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"头像上传失败: {str(e)}"
        )

@router.post("/upload-role-avatar")
async def upload_role_avatar(
    avatar_data: RoleAvatarUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """上传角色头像"""
    try:
        logger.info(
            f"🖼️ 准备上传角色头像 session_id={avatar_data.session_id} user_id={current_user.id}"
        )
        
        # 上传到MinIO - 使用正确的参数顺序
        # upload_image(image_base64, session_id, message_id, user_id)
        minio_url = minio_client.upload_image(
            avatar_data.avatar,
            f"sessions/{avatar_data.session_id}",  # session_id: 会话路径
            "role_avatar",           # message_id: 标识为角色头像
            current_user.id         # user_id: 用户ID字符串
        )

        logger.info(f"🖼️ 角色头像已上传到MinIO url={minio_url}")
        
        if not minio_url:
            logger.error("❌ 角色头像上传失败，minio_url 为空")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="角色头像上传失败"
            )
        
        
        return {"avatar_url": minio_url}
        
    except Exception as e:
        logger.error(f"❌ 角色头像上传/写库失败: {str(e)}")
@router.post("/upload-group-background")
async def upload_group_background(
    avatar: str = Body(..., embed=True, description="Base64背景图"),
    group_id: str = Body(..., embed=True, description="群聊ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """上传群聊背景（路径和处理方式与群聊头像完全一致）"""
    try:
        logger.info(f"🖼️ 准备上传群聊背景 user_id={current_user.id} group_id={group_id}")
        
        # 验证群聊是否存在
        group_chat = await db[settings.mongodb_db_name].group_chats.find_one({"group_id": group_id})
        if not group_chat:
            raise HTTPException(status_code=404, detail="未找到群聊")
        
        # 权限检查：只有群主可以修改群聊背景
        if group_chat.get("owner_id") != current_user.id:
            raise HTTPException(status_code=403, detail="只有群主可以修改群聊背景")
        
        # 删除旧背景（如果存在）
        old_background = group_chat.get("role_background_url")
        if old_background and old_background.startswith("minio://"):
            try:
                minio_client.delete_image(old_background)
                logger.info(f"🗑️ 已删除旧群聊背景: {old_background}")
            except Exception as e:
                logger.warning(f"⚠️ 删除旧群聊背景失败: {e}")
        
        # 解析 Base64 数据并上传（与群聊头像处理方式完全一致）
        import base64
        import uuid
        import io
        
        # 处理 Base64 数据
        if "," in avatar:
            # 格式: data:image/png;base64,xxxxx
            header, encoded = avatar.split(",", 1)
            if "image/" in header:
                file_ext = header.split("image/")[1].split(";")[0]
            else:
                file_ext = "png"
        else:
            encoded = avatar
            file_ext = "png"
        
        # 解码 Base64
        file_data = base64.b64decode(encoded)
        
        # 生成文件名（使用 background_ 前缀区分）
        file_id = str(uuid.uuid4())
        filename = f"background_{file_id}.{file_ext}"
        
        # 上传到 MinIO，路径: group-chats/{group_id}/{filename}（与群聊头像在同一目录）
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
        
        logger.info(f"✅ 群聊背景上传成功: {minio_url}")
        
        # 更新数据库（存储 minio:// 格式）
        result = await db[settings.mongodb_db_name].group_chats.update_one(
            {"group_id": group_id},
            {"$set": {"role_background_url": minio_url}}
        )
        
        if result.modified_count == 0:
            logger.warning(f"⚠️ 群聊背景URL未更新到数据库")
        
        return {"background_url": minio_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 群聊背景上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"群聊背景上传失败: {str(e)}")

@router.get("/avatar/{user_id}/{filename}")
async def get_avatar(user_id: str, filename: str):
    """获取用户头像"""
    try:
        # 构建MinIO对象路径
        object_name = f"users/{user_id}/user_profile/avatar/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        
        # 从MinIO获取图片
        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            raise HTTPException(status_code=404, detail="头像不存在")
        
        # 转换为二进制数据
        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        
        return Response(content=image_data, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取用户头像失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户头像失败: {str(e)}")

@router.get("/group-avatar/{group_id}/{filename}")
async def get_group_avatar(group_id: str, filename: str):
    """获取群聊头像"""
    try:
        # 构建MinIO对象路径
        object_name = f"group-chats/{group_id}/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        
        # 从MinIO获取图片
        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            raise HTTPException(status_code=404, detail="群聊头像不存在")
        
        # 转换为二进制数据
        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        
        return Response(content=image_data, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取群聊头像失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取群聊头像失败")

@router.get("/role-avatar/{user_id}/{session_id}/{filename}")
async def get_role_avatar(user_id: str, session_id: str, filename: str):
    """获取角色头像"""
    try:
        # 构建MinIO对象路径
        object_name = f"users/{user_id}/sessions/{session_id}/role_avatar/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        
        # 从MinIO获取图片
        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            raise HTTPException(status_code=404, detail="角色头像不存在")
        
        # 转换为二进制数据
        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        
        return Response(content=image_data, media_type="image/png")
        
    except Exception as e:
        print(f"❌ 获取角色头像失败: {e}")
        raise HTTPException(status_code=500, detail="获取角色头像失败")

# 新增：获取助手头像
@router.get("/assistant-avatar/{user_id}/{assistant_id}/{filename}")
async def get_assistant_avatar(user_id: str, assistant_id: str, filename: str):
    """获取助手头像"""
    try:
        object_name = f"users/{user_id}/assistants/{assistant_id}/avatar/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        logger.info(f"🖼️ 读取助手头像 assistant_id={assistant_id} object_name={object_name} url={minio_url}")

        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            logger.warning(f"⚠️ 助手头像不存在 assistant_id={assistant_id} object_name={object_name}")
            raise HTTPException(status_code=404, detail="助手头像不存在")

        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)

        logger.info(f"✅ 返回助手头像 assistant_id={assistant_id} size={len(image_data)} bytes")
        return Response(content=image_data, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取助手头像失败: {e}")
        raise HTTPException(status_code=500, detail="获取助手头像失败")

# 新增：获取助手会话头像
@router.get("/assistant-role-avatar/{user_id}/{assistant_id}/{session_id}/{filename}")
async def get_assistant_role_avatar(user_id: str, assistant_id: str, session_id: str, filename: str):
    """获取助手会话头像（助手会话的角色头像）"""
    try:
        object_name = f"users/{user_id}/assistants/{assistant_id}/sessions/{session_id}/role_avatar/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        logger.info(
            f"🖼️ 读取助手会话头像 user_id={user_id} assistant_id={assistant_id} session_id={session_id} url={minio_url}"
        )
        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            raise HTTPException(status_code=404, detail="助手会话头像不存在")
        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        return Response(content=image_data, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 获取助手会话头像失败: {e}")
        raise HTTPException(status_code=500, detail="获取助手会话头像失败")

@router.get("/message-image/{user_id}/{session_id}/{filename}")
async def get_message_image(user_id: str, session_id: str, filename: str):
    """获取传统会话消息图片（新路径结构，完全用户隔离）"""
    try:
        # 构建MinIO对象路径
        object_name = f"users/{user_id}/sessions/{session_id}/message_image/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        
        logger.info(f"📸 获取传统会话消息图片: {object_name}")
        
        # 从MinIO获取图片
        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            raise HTTPException(status_code=404, detail="图片不存在")
        
        # 转换为二进制数据
        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        
        return Response(content=image_data, media_type="image/png")
        
    except Exception as e:
        logger.error(f"❌ 获取传统会话消息图片失败: {e}")
        raise HTTPException(status_code=500, detail="获取传统会话消息图片失败")

@router.get("/new-message-image/{user_id}/{session_id}/{message_id}/{filename}")
async def get_new_message_image(user_id: str, session_id: str, message_id: str, filename: str):
    """获取新格式会话消息图片（完全用户隔离）"""
    try:
        # 构建MinIO对象路径
        object_name = f"users/{user_id}/{session_id}/{message_id}/{filename}"
        minio_url = f"minio://{settings.minio_bucket_name}/{object_name}"
        
        logger.info(f"📸 获取新格式会话消息图片: {object_name}")
        
        # 从MinIO获取图片
        image_base64 = minio_client.get_image_base64(minio_url)
        if not image_base64:
            raise HTTPException(status_code=404, detail="图片不存在")
        
        # 转换为二进制数据
        if image_base64.startswith("data:image"):
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        
        return Response(content=image_data, media_type="image/png")
        
    except Exception as e:
        logger.error(f"❌ 获取新格式会话消息图片失败: {e}")
        raise HTTPException(status_code=500, detail="获取新格式会话消息图片失败")

@router.get("/settings", response_model=AppSettingsResponse)
async def get_app_settings():
    """返回应用可供前端使用的配置开关"""
    return AppSettingsResponse(email_verification=settings.email_verification)

@router.delete("/account")
async def delete_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """注销当前账号：
    - 删除当前用户的传统会话
    - 删除当前用户的智能助手会话（仅会话，不删除助手本体）
    - 删除当前用户在MinIO下的所有图片前缀（直接删除 users/{user_id}/ 根目录）
    - 删除用户账号本身
    """
    try:
        logger = logging.getLogger(__name__)
        # 使用 _id 字符串作为用户ID
        user_id = str(current_user.id)
        logger.info(f"开始注销账号 user_id={user_id} account={current_user.account}")

        # 构造 user_id 过滤器 - 只使用 _id
        from bson import ObjectId
        user_filter_or = [{"user_id": user_id}]

        # 1) 删除本地数据库中的传统会话（兼容多种 user_id 字段类型与历史字段名）
        deleted_chat_count = 0
        try:
            result_chat = await db[settings.mongodb_db_name].chat_sessions.delete_many({
                "$or": user_filter_or
            })
            deleted_chat_count = result_chat.deleted_count
            logger.info(f"本地传统会话删除: {deleted_chat_count}")
        except Exception as e_db_chat:
            logger.error(f"删除本地传统会话失败: {e_db_chat}")

        # 若以上两类会话均删除为0，进行兜底遍历删除（严格匹配创建时标识，且兼容历史字段名）
        try:
            def _normalize(v: Any) -> str:
                return str(v).strip()

            # 使用同一套 id 变体字符串，便于与任意文档字段进行对比
            compare_variants: set[str] = set()
            for item in [user_id]:
                compare_variants.add(_normalize(item))
            # 添加来自 current_user 的 ID 变体
            try:
                if current_user.id:
                    compare_variants.add(_normalize(current_user.id))
                if current_user.account:
                    compare_variants.add(_normalize(current_user.account))
            except Exception:
                pass

            async def _bruteforce_purge(collection_name: str) -> int:
                col = db[settings.mongodb_db_name][collection_name]
                candidates = await col.find({}, {"_id": 1, "user_id": 1, "userId": 1, "uid": 1}).to_list(length=None)
                to_delete_ids = []
                for doc in candidates:
                    for key in ("user_id", "userId", "uid"):
                        if key in doc and _normalize(doc[key]) in compare_variants:
                            to_delete_ids.append(doc["_id"]) 
                            break
        except Exception as e_bf:
            logger.error(f"兜底遍历删除会话失败: {e_bf}")

        # 4) 删除 MinIO 中该用户根目录
        try:
            from ..utils.minio_client import minio_client
            user_root_prefix = f"users/{user_id}/"
            logger.info(f"开始删除用户MinIO根前缀: {user_root_prefix}")
            minio_client.delete_prefix(user_root_prefix)
            logger.info(f"✅ 用户MinIO根前缀删除完成: {user_root_prefix}")
        except Exception as e_minio:
            logger.error(f"删除MinIO用户根前缀失败: {e_minio}")

        # 5) 删除用户账号记录 - 使用 _id (ObjectId)
        try:
            users_collection = db[settings.mongodb_db_name].users
            await users_collection.delete_one({"_id": ObjectId(user_id)})
            logger.info(f"✅ 用户账号已删除: {user_id}")
        except Exception as e_user:
            logger.error(f"删除用户账号失败: {e_user}")

        return {"message": "账号已注销"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注销账号失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"注销失败: {str(e)}") 

@router.get("/group-background/{group_id}")
async def get_group_background(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取群聊背景（base64）- 与普通会话背景处理方式一致"""
    try:
        # 从 group_chats 集合查询（统一使用一个集合）
        group_chat = await db[settings.mongodb_db_name].group_chats.find_one({"group_id": group_id})
        if not group_chat:
            raise HTTPException(status_code=404, detail="未找到群聊")
        
        # 验证用户是否是群成员
        if str(current_user.id) not in group_chat.get("member_ids", []):
            raise HTTPException(status_code=403, detail="您不是该群成员")
        
        url = group_chat.get("role_background_url")
        if not url:
            raise HTTPException(status_code=404, detail="该群聊未设置背景")
        
        # 从 MinIO 获取 base64 图片
        data_url = minio_client.get_image_base64(url)
        if not data_url:
            raise HTTPException(status_code=500, detail="从存储获取背景失败")
        
        return {"data_url": data_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取群聊背景失败: {e}")
        raise HTTPException(status_code=500, detail="获取群聊背景失败")

class VerifyPasswordRequest(BaseModel):
    """密码验证请求"""
    password: str

class VerifyPasswordResponse(BaseModel):
    """密码验证响应"""
    verified: bool

class UserProfileUpdate(BaseModel):
    """用户个性化信息更新请求"""
    full_name: Optional[str] = None
    gender: Optional[str] = None  # '男', '女', '其他' 或 None
    birth_date: Optional[str] = None  # 出生日期，格式：YYYY-MM-DD
    signature: Optional[str] = None

@router.post("/verify-password", response_model=VerifyPasswordResponse)
async def verify_password_endpoint(
    request: VerifyPasswordRequest,
    current_user: User = Depends(get_current_active_user)
):
    """验证当前用户的密码"""
    try:
        # 使用统一的密码哈希系统
        from ..utils.auth import verify_password
        
        # 验证密码
        is_valid = verify_password(request.password, current_user.hashed_password)
        
        return VerifyPasswordResponse(verified=is_valid)
        
    except Exception as e:
        logger.error(f"密码验证失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="密码验证失败"
        )

@router.put("/profile", response_model=User)
async def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_active_user)
):
    """更新用户个性化信息（姓名、性别、年龄、签名）"""
    try:
        from bson import ObjectId
        
        # 构建更新数据，只更新提供的字段
        update_data = {}
        
        if profile_data.full_name is not None:
            update_data["full_name"] = profile_data.full_name
        
        if profile_data.gender is not None:
            # 验证性别值
            valid_genders = ["男", "女", "其他", ""]
            if profile_data.gender not in valid_genders:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="性别值无效，必须是 男、女、其他 或空字符串"
                )
            update_data["gender"] = profile_data.gender if profile_data.gender else None
        
        if profile_data.birth_date is not None:
            # 验证出生日期格式和合理性
            if profile_data.birth_date:
                try:
                    from datetime import datetime
                    birth_date_obj = datetime.strptime(profile_data.birth_date, "%Y-%m-%d")
                    # 检查日期是否在合理范围内（不能是未来日期，不能早于150年前）
                    today = datetime.now()
                    if birth_date_obj > today:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="出生日期不能是未来日期"
                        )
                    min_date = datetime(today.year - 150, today.month, today.day)
                    if birth_date_obj < min_date:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="出生日期不合理"
                        )
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="出生日期格式无效，必须是 YYYY-MM-DD 格式"
                    )
            update_data["birth_date"] = profile_data.birth_date if profile_data.birth_date else None
        
        if profile_data.signature is not None:
            # 限制签名长度
            if len(profile_data.signature) > 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="个性签名不能超过200个字符"
                )
            update_data["signature"] = profile_data.signature
        
        # 更新数据库
        if update_data:
            await users_collection.update_one(
                {"_id": ObjectId(current_user.id)},
                {"$set": update_data}
            )
        
        # 获取更新后的用户信息
        updated_user = await users_collection.find_one({"_id": ObjectId(current_user.id)})
        if updated_user and "_id" in updated_user:
            updated_user["id"] = str(updated_user["_id"])
        
        logger.info(f"用户 {current_user.id} 更新了个性化信息")
        return User(**updated_user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新用户个性化信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新失败"
        )

@router.post("/upload-role-background")
async def upload_role_background(
    avatar_data: RoleAvatarUploadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """上传会话背景图"""
    try:
        logger.info(
            f"🖼️ 准备上传会话背景 session_id={avatar_data.session_id} user_id={current_user.id}"
        )
        minio_url = minio_client.upload_image(
            avatar_data.avatar,
            f"sessions/{avatar_data.session_id}",
            "role_background",
            current_user.id
        )
        logger.info(f"🖼️ 会话背景已上传到MinIO url={minio_url}")

        if not minio_url:
            logger.error("❌ 会话背景上传失败，minio_url 为空")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="会话背景上传失败"
            )

        update_doc = {"$set": {"role_background_url": minio_url, "updated_at": datetime.now().isoformat()}}

        # 更新 chat_sessions
        result = await db[settings.mongodb_db_name].chat_sessions.update_one({"_id": avatar_data.session_id, "user_id": str(current_user.id)}, update_doc, upsert=False)
        logger.info(f"🗄️ 更新会话背景 matched={result.matched_count} modified={result.modified_count}")

        return {"background_url": minio_url}

    except Exception as e:
        logger.error(f"❌ 会话背景上传/写库失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"会话背景上传失败: {str(e)}"
        )

@router.get("/role-background/{session_id}")
async def get_role_background(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncIOMotorClient = Depends(get_database)
):
    """获取会话背景（base64），从 chat_sessions 查找"""
    try:
        doc = await db[settings.mongodb_db_name].chat_sessions.find_one({"_id": session_id, "user_id": str(current_user.id)})
        if not doc:
            raise HTTPException(status_code=404, detail="未找到会话")
        url = doc.get("role_background_url")
        if not url:
            raise HTTPException(status_code=404, detail="该会话未设置背景")
        data_url = minio_client.get_image_base64(url)
        if not data_url:
            raise HTTPException(status_code=500, detail="从存储获取背景失败")
        return {"data_url": data_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话背景失败: {e}")
        raise HTTPException(status_code=500, detail="获取会话背景失败") 