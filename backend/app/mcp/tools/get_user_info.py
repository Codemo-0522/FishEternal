"""
获取用户信息（Get User Info）工具

AI 可以使用此工具获取当前会话中用户的个人信息，包括姓名、性别、年龄、个性签名等
"""

from datetime import datetime, date
from typing import Dict, Any, Optional
import json
import logging
from bson import ObjectId

from ..base import BaseTool, ToolMetadata, ToolContext
from ...config import settings

logger = logging.getLogger(__name__)


class GetUserInfoTool(BaseTool):
    """获取用户信息工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> ToolMetadata:
        """
        获取工具元数据
        
        Args:
            context: 工具上下文（不需要）
        """
        return ToolMetadata(
            name="get_user_info",
            description="""使用该工具可以查看当前用户的个人信息，以便于你了解用户""".strip(),
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行获取用户信息操作
        
        Args:
            arguments: {} （此工具不需要参数）
            context: 执行上下文（需要 db 和 user_id）
        
        Returns:
            str: JSON 格式的用户信息
        """
        # 从上下文获取必要信息
        db_name = context.extra.get("db_name", settings.mongodb_db_name)
        db = context.db[db_name]
        user_id = context.user_id
        
        if not user_id:
            logger.error("❌ 缺少 user_id，无法获取用户信息")
            return json.dumps({
                "success": False,
                "error": "系统错误：缺少用户信息"
            }, ensure_ascii=False)
        
        try:
            # 从数据库获取用户信息
            from ...database import users_collection
            
            user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
            
            if not user_doc:
                logger.error(f"❌ 未找到用户: {user_id}")
                return json.dumps({
                    "success": False,
                    "error": "用户不存在"
                }, ensure_ascii=False)
            
            # 计算年龄（如果有出生日期）
            age = None
            birth_date = user_doc.get("birth_date")
            
            if birth_date:
                try:
                    # 解析出生日期
                    birth = datetime.strptime(birth_date, "%Y-%m-%d").date()
                    today = date.today()
                    # 计算年龄
                    age = today.year - birth.year
                    # 如果今年的生日还没到，年龄减1
                    if today.month < birth.month or (today.month == birth.month and today.day < birth.day):
                        age -= 1
                except (ValueError, AttributeError) as e:
                    logger.warning(f"⚠️ 解析出生日期失败: {birth_date}, 错误: {e}")
                    age = None
            
            # 构建返回的用户信息
            user_info = {
                "success": True,
                "user": {
                    "account": user_doc.get("account"),
                    "full_name": user_doc.get("full_name"),
                    "gender": user_doc.get("gender"),
                    "birth_date": birth_date,
                    "age": age,
                    "signature": user_doc.get("signature"),
                    "email": user_doc.get("email"),
                    "avatar_url": user_doc.get("avatar_url")
                }
            }
            
            logger.info(f"✅ 成功获取用户信息: {user_doc.get('account')}")
            return json.dumps(user_info, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 获取用户信息失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"获取用户信息失败: {str(e)}"
            }, ensure_ascii=False)

