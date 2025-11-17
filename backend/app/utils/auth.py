from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from ..config import settings
from ..models.user import UserResponse, User
from ..database import get_database
import logging

# 导入模块化密码哈希系统
from .password_hasher import (
    get_password_hash,
    verify_password,
    needs_password_rehash,
    HASH_ALGORITHM
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"密码哈希算法: {HASH_ALGORITHM}")

# 密钥配置
SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, 
        SECRET_KEY, 
        algorithm=ALGORITHM
    )
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_database)) -> User:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        logger.info("开始验证token")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        account: str = payload.get("sub")
        if account is None:
            logger.error("Token payload中没有账号")
            raise credentials_exception
            
        logger.info(f"Token中的账号: {account}")
    except JWTError as e:
        logger.error(f"Token解析失败: {str(e)}")
        raise credentials_exception
        
    try:
        user = await db[settings.mongodb_db_name].users.find_one({"account": account})
        if user is None:
            logger.error("数据库中未找到用户")
            raise credentials_exception
            
        # 将 MongoDB 的 ObjectId 转换为字符串 id 字段
        if "_id" in user and isinstance(user["_id"], ObjectId):
            user["id"] = str(user["_id"])
        
        logger.info(f"找到用户: {user['account']}, id: {user.get('id', 'N/A')}")
        return User(**user)
    except Exception as e:
        logger.error(f"查询用户时出错: {str(e)}")
        raise credentials_exception

async def get_current_user_ws(websocket: WebSocket, db = Depends(get_database)) -> Optional[User]:
    try:
        # 从WebSocket请求头中获取token
        auth_header = websocket.headers.get('authorization')
        logger.info(f"WebSocket认证头: {auth_header}")
        
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.error("WebSocket请求缺少Bearer token")
            return None
            
        token = auth_header.split(' ')[1]
        logger.info("开始验证WebSocket token")
        
        # 验证token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        account: str = payload.get("sub")
        if account is None:
            logger.error("WebSocket token payload中没有账号")
            return None
            
        logger.info(f"WebSocket token中的账号: {account}")
        
        # 获取用户信息
        user = await db[settings.mongodb_db_name].users.find_one({"account": account})
        if user is None:
            logger.error("数据库中未找到WebSocket用户")
            return None
            
        # 将 MongoDB 的 ObjectId 转换为字符串，并使用 id 字段
        if "_id" in user and isinstance(user["_id"], ObjectId):
            user["id"] = str(user["_id"])
        
        logger.info(f"找到WebSocket用户: {user['account']}, id: {user.get('id', 'N/A')}")
        return User(**user)
        
    except JWTError as e:
        logger.error(f"WebSocket token验证失败: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"WebSocket获取用户失败: {str(e)}")
        return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt 