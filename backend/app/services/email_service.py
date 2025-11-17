"""
邮件服务模块
支持多种邮件服务商的模块化实现
"""
import smtplib
import ssl
import random
import string
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
import logging

from ..config import settings

logger = logging.getLogger(__name__)

class EmailProvider(ABC):
    """邮件服务商抽象基类"""
    
    @abstractmethod
    async def send_email(self, to_email: str, subject: str, html_content: str, text_content: str = "") -> bool:
        """发送邮件"""
        pass
    
    @abstractmethod
    def validate_config(self) -> bool:
        """验证配置是否正确"""
        pass

class SMTPEmailProvider(EmailProvider):
    """SMTP邮件服务商实现"""
    
    def __init__(self, smtp_server: str, smtp_port: int, username: str, password: str, use_ssl: bool = True):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
    
    def validate_config(self) -> bool:
        """验证SMTP配置"""
        required_fields = [self.smtp_server, self.username, self.password]
        return all(field.strip() for field in required_fields)
    
    async def send_email(self, to_email: str, subject: str, html_content: str, text_content: str = "") -> bool:
        """发送SMTP邮件"""
        try:
            # 创建邮件消息
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.username
            message["To"] = to_email
            
            # 添加文本内容
            if text_content:
                text_part = MIMEText(text_content, "plain", "utf-8")
                message.attach(text_part)
            
            # 添加HTML内容
            html_part = MIMEText(html_content, "html", "utf-8")
            message.attach(html_part)
            
            # 创建SMTP连接
            if self.use_ssl:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            
            # 登录并发送邮件
            server.login(self.username, self.password)
            server.sendmail(self.username, to_email, message.as_string())
            server.quit()
            
            logger.info(f"邮件发送成功: {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"邮件发送失败 {to_email}: {str(e)}")
            return False

class NetEase163Provider(SMTPEmailProvider):
    """网易163邮箱服务商"""
    
    def __init__(self, username: str, password: str):
        super().__init__(
            smtp_server="smtp.163.com",
            smtp_port=465,
            username=username,
            password=password,
            use_ssl=True
        )

class QQEmailProvider(SMTPEmailProvider):
    """QQ邮箱服务商"""
    
    def __init__(self, username: str, password: str):
        super().__init__(
            smtp_server="smtp.qq.com",
            smtp_port=587,
            username=username,
            password=password,
            use_ssl=False
        )

class GmailProvider(SMTPEmailProvider):
    """Gmail邮箱服务商"""
    
    def __init__(self, username: str, password: str):
        super().__init__(
            smtp_server="smtp.gmail.com",
            smtp_port=587,
            username=username,
            password=password,
            use_ssl=False
        )

class EmailService:
    """邮件服务主类"""
    
    def __init__(self):
        self.provider: Optional[EmailProvider] = None
        self.verification_codes: Dict[str, Dict[str, Any]] = {}
        self._init_provider()
    
    def _init_provider(self):
        """初始化邮件服务商"""
        if not settings.email_verification:
            logger.info("邮箱验证功能已关闭")
            return
        
        # 根据SMTP服务器自动选择服务商
        if "163.com" in settings.smtp_server:
            self.provider = NetEase163Provider(settings.smtp_user, settings.smtp_pass)
        elif "qq.com" in settings.smtp_server:
            self.provider = QQEmailProvider(settings.smtp_user, settings.smtp_pass)
        elif "gmail.com" in settings.smtp_server:
            self.provider = GmailProvider(settings.smtp_user, settings.smtp_pass)
        else:
            # 使用通用SMTP配置
            self.provider = SMTPEmailProvider(
                settings.smtp_server,
                settings.smtp_port,
                settings.smtp_user,
                settings.smtp_pass,
                settings.smtp_use_ssl
            )
        
        if self.provider and not self.provider.validate_config():
            logger.error("邮件服务配置无效")
            self.provider = None
    
    def generate_verification_code(self) -> str:
        """生成验证码"""
        return ''.join(random.choices(string.digits, k=settings.verification_code_length))
    
    def store_verification_code(self, email: str, code: str):
        """存储验证码"""
        expire_time = datetime.now() + timedelta(minutes=settings.verification_code_expire_minutes)
        self.verification_codes[email] = {
            "code": code,
            "expire_time": expire_time,
            "attempts": 0
        }
        
        # 清理过期的验证码
        self._cleanup_expired_codes()
    
    def verify_code(self, email: str, code: str) -> bool:
        """验证验证码"""
        if email not in self.verification_codes:
            return False
        
        stored_data = self.verification_codes[email]
        
        # 检查是否过期
        if datetime.now() > stored_data["expire_time"]:
            del self.verification_codes[email]
            return False
        
        # 检查尝试次数（防止暴力破解）
        if stored_data["attempts"] >= 5:
            del self.verification_codes[email]
            return False
        
        # 验证码错误时增加尝试次数
        if stored_data["code"] != code:
            stored_data["attempts"] += 1
            return False
        
        # 验证成功，删除验证码
        del self.verification_codes[email]
        return True
    
    def _cleanup_expired_codes(self):
        """清理过期的验证码"""
        current_time = datetime.now()
        expired_emails = [
            email for email, data in self.verification_codes.items()
            if current_time > data["expire_time"]
        ]
        for email in expired_emails:
            del self.verification_codes[email]
    
    async def send_verification_email(self, to_email: str) -> Optional[str]:
        """发送验证邮件"""
        if not self.provider:
            logger.error("邮件服务未配置")
            return None
        
        # 生成验证码
        code = self.generate_verification_code()
        
        # 构建邮件内容
        subject = f"{settings.app_name} - 邮箱验证码"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    font-family: Arial, sans-serif;
                    background-color: #f9f9f9;
                    padding: 20px;
                }}
                .card {{
                    background: white;
                    border-radius: 8px;
                    padding: 30px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                .header {{
                    text-align: center;
                    color: #333;
                    margin-bottom: 30px;
                }}
                .code {{
                    background: #007bff;
                    color: white;
                    font-size: 32px;
                    font-weight: bold;
                    text-align: center;
                    padding: 20px;
                    border-radius: 8px;
                    letter-spacing: 8px;
                    margin: 20px 0;
                }}
                .info {{
                    color: #666;
                    line-height: 1.6;
                    margin: 15px 0;
                }}
                .warning {{
                    background: #fff3cd;
                    border: 1px solid #ffeaa7;
                    color: #856404;
                    padding: 15px;
                    border-radius: 4px;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    color: #999;
                    margin-top: 30px;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="header">
                        <h1>{settings.app_name}</h1>
                        <h2>邮箱验证码</h2>
                    </div>
                    
                    <p class="info">您好！</p>
                    <p class="info">您正在注册 {settings.app_name} 账户，您的邮箱验证码是：</p>
                    
                    <div class="code">{code}</div>
                    
                    <div class="warning">
                        <strong>重要提醒：</strong>
                        <ul>
                            <li>此验证码有效期为 {settings.verification_code_expire_minutes} 分钟</li>
                            <li>请勿将验证码告诉他人</li>
                            <li>如果您没有进行此操作，请忽略此邮件</li>
                        </ul>
                    </div>
                    
                    <p class="info">感谢您使用 {settings.app_name}！</p>
                    
                    <div class="footer">
                        <p>此邮件由系统自动发送，请勿回复</p>
                        <p>{settings.app_name} 团队</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        {settings.app_name} - 邮箱验证码
        
        您好！
        
        您正在注册 {settings.app_name} 账户，您的邮箱验证码是：{code}
        
        重要提醒：
        - 此验证码有效期为 {settings.verification_code_expire_minutes} 分钟
        - 请勿将验证码告诉他人
        - 如果您没有进行此操作，请忽略此邮件
        
        感谢您使用 {settings.app_name}！
        
        此邮件由系统自动发送，请勿回复
        {settings.app_name} 团队
        """
        
        # 发送邮件
        success = await self.provider.send_email(to_email, subject, html_content, text_content)
        
        if success:
            # 存储验证码
            self.store_verification_code(to_email, code)
            logger.info(f"验证码已发送到: {to_email}")
            return code  # 仅在开发环境返回验证码用于调试
        
        return None
    
    def is_enabled(self) -> bool:
        """检查邮件服务是否启用"""
        return settings.email_verification and self.provider is not None

# 创建全局邮件服务实例
email_service = EmailService() 