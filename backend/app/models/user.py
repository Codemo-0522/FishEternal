import os
from jose import jwt, JWTError
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field, computed_field
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

from ..config import Settings
from ..database import users_collection

# 导入模块化密码哈希系统
from ..utils.password_hasher import (
    get_password_hash,
    verify_password,
    needs_password_rehash
)

# 配置
settings = Settings()

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

class UserCreate(BaseModel):
    account: str = Field(..., min_length=3, max_length=20)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=50)

class UserResponse(BaseModel):
    id: str
    account: str
    email: str

class User(BaseModel):
    id: str  # MongoDB ObjectId 的字符串形式
    account: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None
    avatar_url: Optional[str] = None
    model_configs: Optional[Dict[str, Dict[str, Any]]] = None  # 模型配置 {provider_id: config}
    tts_configs: Optional[Dict[str, Dict[str, Any]]] = None  # TTS配置 {provider_id: config}
    default_tts_provider: Optional[str] = None  # 默认TTS服务商
    # 个性化字段
    gender: Optional[str] = None  # 性别：男/女/其他
    birth_date: Optional[str] = None  # 出生日期，格式：YYYY-MM-DD
    signature: Optional[str] = None  # 个性签名
    
    @computed_field
    @property
    def age(self) -> Optional[int]:
        """根据出生日期动态计算年龄"""
        if not self.birth_date:
            return None
        try:
            # 解析出生日期
            birth = datetime.strptime(self.birth_date, "%Y-%m-%d").date()
            today = date.today()
            # 计算年龄
            age = today.year - birth.year
            # 如果今年的生日还没到，年龄减1
            if today.month < birth.month or (today.month == birth.month and today.day < birth.day):
                age -= 1
            return age
        except (ValueError, AttributeError):
            return None
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True
    }

class UserInDB(User):
    hashed_password: str

def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt

async def get_user(account: str) -> Optional[UserInDB]:
    """获取用户信息"""
    if user_dict := await users_collection.find_one({"account": account}):
        # 将 MongoDB 的 ObjectId 转换为字符串 id 字段
        if "_id" in user_dict and isinstance(user_dict["_id"], ObjectId):
            user_dict["id"] = str(user_dict["_id"])
        return UserInDB(**user_dict)
    return None

async def get_user_by_email(email: str) -> Optional[UserInDB]:
    """通过邮箱获取用户信息（不区分大小写）"""
    # 使用正则表达式实现大小写不敏感查询，保留数据库中的原始格式
    import re
    email_pattern = re.compile(f"^{re.escape(email.strip())}$", re.IGNORECASE)
    if user_dict := await users_collection.find_one({"email": {"$regex": email_pattern}}):
        # 将 ObjectId 转换为字符串，并使用 id 字段
        if "_id" in user_dict and isinstance(user_dict["_id"], ObjectId):
            user_dict["id"] = str(user_dict["_id"])
        return UserInDB(**user_dict)
    return None

async def get_user_by_identifier(identifier: str) -> Optional[UserInDB]:
    """通过账号或邮箱获取用户信息"""
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if re.match(email_pattern, identifier):
        # 是邮箱
        return await get_user_by_email(identifier)
    else:
        # 是账号
        return await get_user(identifier)

async def authenticate_user(account: str, password: str) -> Optional[User]:
    """认证用户"""
    user = await get_user(account)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

async def authenticate_user_by_identifier(identifier: str, password: str) -> Optional[User]:
    """通过账号或邮箱认证用户"""
    user = await get_user_by_identifier(identifier)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        account: str = payload.get("sub")
        if account is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = await get_user(account)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """获取当前活跃用户"""
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="用户已禁用")
    return current_user 