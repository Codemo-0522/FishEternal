"""
邮箱验证码数据模型
"""
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, EmailStr
from motor.motor_asyncio import AsyncIOMotorClient
from ..config import settings

# 数据库连接
client = AsyncIOMotorClient(settings.mongodb_url)
db = client[settings.mongodb_db_name]
verification_codes_collection = db.verification_codes

class VerificationCode(BaseModel):
    """验证码模型"""
    email: EmailStr
    code: str
    created_at: datetime
    expire_at: datetime
    attempts: int = 0
    is_used: bool = False

class VerificationCodeCreate(BaseModel):
    """创建验证码请求"""
    email: EmailStr

class VerificationCodeVerify(BaseModel):
    """验证验证码请求"""
    email: EmailStr
    code: str

async def create_verification_code(email: str, code: str) -> bool:
    """创建验证码记录"""
    try:
        now = datetime.utcnow()
        expire_at = now + timedelta(minutes=settings.verification_code_expire_minutes)
        
        verification_code = {
            "email": email,
            "code": code,
            "created_at": now,
            "expire_at": expire_at,
            "attempts": 0,
            "is_used": False
        }
        
        # 删除该邮箱的旧验证码
        await verification_codes_collection.delete_many({"email": email})
        
        # 插入新验证码
        await verification_codes_collection.insert_one(verification_code)
        return True
        
    except Exception as e:
        print(f"创建验证码失败: {e}")
        return False

async def verify_code(email: str, code: str) -> bool:
    """验证验证码"""
    try:
        now = datetime.utcnow()
        
        # 查找验证码
        verification_doc = await verification_codes_collection.find_one({
            "email": email,
            "code": code,
            "is_used": False,
            "expire_at": {"$gt": now}
        })
        
        if not verification_doc:
            # 尝试更新失败次数
            await verification_codes_collection.update_one(
                {"email": email, "is_used": False},
                {"$inc": {"attempts": 1}}
            )
            return False
        
        # 检查尝试次数
        if verification_doc.get("attempts", 0) >= 5:
            return False
        
        # 标记为已使用
        await verification_codes_collection.update_one(
            {"_id": verification_doc["_id"]},
            {"$set": {"is_used": True}}
        )
        
        return True
        
    except Exception as e:
        print(f"验证码验证失败: {e}")
        return False

async def cleanup_expired_codes():
    """清理过期的验证码"""
    try:
        now = datetime.utcnow()
        result = await verification_codes_collection.delete_many({
            "expire_at": {"$lt": now}
        })
        if result.deleted_count > 0:
            print(f"清理了 {result.deleted_count} 个过期验证码")
    except Exception as e:
        print(f"清理过期验证码失败: {e}")

async def get_verification_status(email: str) -> Optional[dict]:
    """获取验证码状态"""
    try:
        now = datetime.utcnow()
        verification_doc = await verification_codes_collection.find_one(
            {"email": email, "is_used": False},
            sort=[("created_at", -1)]
        )
        
        if not verification_doc:
            return None
        
        is_expired = verification_doc["expire_at"] < now
        remaining_time = max(0, (verification_doc["expire_at"] - now).total_seconds())
        
        return {
            "exists": True,
            "is_expired": is_expired,
            "remaining_seconds": int(remaining_time),
            "attempts": verification_doc.get("attempts", 0)
        }
        
    except Exception as e:
        print(f"获取验证码状态失败: {e}")
        return None 