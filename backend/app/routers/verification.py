"""
邮箱验证相关API路由
"""
import re
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, EmailStr, validator
from typing import Optional

from ..services.email_service import email_service
from ..models.verification import (
    VerificationCodeCreate, 
    VerificationCodeVerify,
    create_verification_code,
    verify_code,
    get_verification_status,
    cleanup_expired_codes
)
from ..models.user import get_user_by_email
from ..config import settings

router = APIRouter(prefix="/api/verification", tags=["邮箱验证"])

class SendVerificationResponse(BaseModel):
    """发送验证码响应"""
    success: bool
    message: str
    remaining_seconds: Optional[int] = None

class VerifyCodeResponse(BaseModel):
    """验证验证码响应"""
    success: bool
    message: str

@router.post("/send-code", response_model=SendVerificationResponse)
async def send_verification_code(
    request: VerificationCodeCreate,
    background_tasks: BackgroundTasks
):
    """发送邮箱验证码"""
    
    # 检查邮件服务是否启用
    if not email_service.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="邮箱验证服务暂时不可用"
        )
    
    email = request.email.lower()
    
    # 验证邮箱格式
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise HTTPException(
            status_code=400,
            detail="邮箱格式不正确"
        )
    
    # 检查邮箱是否已被注册
    existing_user = await get_user_by_email(email)
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="该邮箱已被注册"
        )
    
    # 检查是否存在未过期的验证码
    status = await get_verification_status(email)
    if status and not status["is_expired"]:
        # 如果剩余时间超过3分钟，不允许重新发送
        if status["remaining_seconds"] > 180:
            return SendVerificationResponse(
                success=False,
                message=f"验证码已发送，请等待 {status['remaining_seconds']} 秒后再试",
                remaining_seconds=status["remaining_seconds"]
            )
    
    try:
        # 发送验证码
        code = await email_service.send_verification_email(email)
        
        if code:
            # 将验证码存储到数据库
            await create_verification_code(email, code)
            
            # 后台清理过期验证码
            background_tasks.add_task(cleanup_expired_codes)
            
            return SendVerificationResponse(
                success=True,
                message="验证码已发送，请查收邮件"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="验证码发送失败，请稍后重试"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"发送验证码时发生错误: {str(e)}"
        )

@router.post("/verify-code", response_model=VerifyCodeResponse)
async def verify_verification_code(request: VerificationCodeVerify):
    """验证邮箱验证码"""
    
    email = request.email.lower()
    code = request.code.strip()
    
    # 验证输入
    if not code or len(code) != settings.verification_code_length:
        raise HTTPException(
            status_code=400,
            detail=f"验证码必须是{settings.verification_code_length}位数字"
        )
    
    if not code.isdigit():
        raise HTTPException(
            status_code=400,
            detail="验证码只能包含数字"
        )
    
    try:
        # 验证验证码
        is_valid = await verify_code(email, code)
        
        if is_valid:
            return VerifyCodeResponse(
                success=True,
                message="验证码验证成功"
            )
        else:
            # 检查验证码状态以提供更详细的错误信息
            status = await get_verification_status(email)
            if not status:
                error_message = "验证码不存在或已过期"
            elif status["is_expired"]:
                error_message = "验证码已过期，请重新获取"
            elif status["attempts"] >= 5:
                error_message = "验证失败次数过多，请重新获取验证码"
            else:
                error_message = "验证码错误"
            
            raise HTTPException(
                status_code=400,
                detail=error_message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"验证过程中发生错误: {str(e)}"
        )

@router.get("/status/{email}")
async def get_verification_code_status(email: str):
    """获取验证码状态"""
    
    # 验证邮箱格式
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        raise HTTPException(
            status_code=400,
            detail="邮箱格式不正确"
        )
    
    try:
        status = await get_verification_status(email.lower())
        
        if not status:
            return {
                "exists": False,
                "message": "未找到验证码"
            }
        
        return {
            "exists": True,
            "is_expired": status["is_expired"],
            "remaining_seconds": status["remaining_seconds"],
            "attempts": status["attempts"],
            "can_resend": status["remaining_seconds"] <= 180  # 3分钟后可重发
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取状态时发生错误: {str(e)}"
        )

@router.delete("/cleanup")
async def cleanup_expired_verification_codes():
    """清理过期的验证码（管理员接口）"""
    try:
        await cleanup_expired_codes()
        return {"message": "清理完成"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"清理过程中发生错误: {str(e)}"
        ) 