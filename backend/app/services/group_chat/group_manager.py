"""
群组管理器

负责群组创建、成员管理、状态维护
"""
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from ...models.group_chat import (
    GroupChat, GroupMember, MemberType, MemberStatus,
    AIBehaviorConfig, CreateGroupRequest, AddMemberRequest
)
from ...config import settings

logger = logging.getLogger(__name__)


class GroupManager:
    """群组管理器"""
    
    def __init__(self, db: AsyncIOMotorClient):
        self.db = db
        self.collection_groups = db[settings.mongodb_db_name].group_chats
        self.collection_members = db[settings.mongodb_db_name].group_members
        self.collection_messages = db[settings.mongodb_db_name].group_messages
        
        # 内存缓存：group_id -> 在线成员列表
        self._online_members_cache: Dict[str, List[GroupMember]] = {}
    
    async def create_group(
        self,
        owner_id: str,
        request: CreateGroupRequest
    ) -> GroupChat:
        """
        创建群聊
        
        Args:
            owner_id: 创建者的user_id
            request: 创建请求
        
        Returns:
            创建的群聊对象
        """
        group_id = str(uuid.uuid4())
        
        # 创建群聊文档
        group = GroupChat(
            group_id=group_id,
            name=request.name,
            description=request.description,
            avatar=request.avatar,
            owner_id=owner_id,
            member_ids=[owner_id],  # 创建者自动加入
            human_member_ids=[owner_id]
        )
        
        await self.collection_groups.insert_one(group.dict())
        
        logger.info(f"✅ 创建群聊成功: {group_id} | 名称: {request.name}")
        
        # 添加创建者为成员（display_name稍后动态获取），角色为群主
        from ...models.group_chat import MemberRole
        await self._add_member_internal(
            group_id=group_id,
            member_id=owner_id,
            member_type=MemberType.HUMAN,
            display_name=None,
            status=MemberStatus.OFFLINE,  # 初始离线，WebSocket连接后上线
            role=MemberRole.OWNER
        )
        
        # 添加初始AI成员
        for session_id in request.initial_ai_sessions:
            await self.add_ai_member(
                group_id=group_id,
                session_id=session_id,
                user_id=owner_id
            )
        
        return group
    
    async def add_ai_member(
        self,
        group_id: str,
        session_id: str,
        user_id: str,
        behavior_config: Optional[AIBehaviorConfig] = None
    ) -> GroupMember:
        """
        添加AI成员（基于会话）
        
        Args:
            group_id: 群组ID
            session_id: 会话ID
            user_id: 用户ID（用于权限验证）
            behavior_config: AI行为配置（可选）
        
        Returns:
            添加的AI成员
        """
        # 从会话加载配置
        session_data = await self.db[settings.mongodb_db_name].chat_sessions.find_one({
            "_id": session_id,
            "user_id": user_id
        })
        
        if not session_data:
            raise ValueError(f"会话不存在或无权限: {session_id}")
        
        # 提取会话信息
        display_name = session_data.get("name", "AI助手")
        context_count = session_data.get("context_count", 20)
        avatar_url = session_data.get("role_avatar_url")  # 获取会话头像
        
        # 如果未提供行为配置，使用默认配置
        if behavior_config is None:
            behavior_config = AIBehaviorConfig(
                context_window_size=context_count if context_count else 20
            )
        else:
            # 同步上下文窗口大小
            behavior_config.context_window_size = context_count if context_count else 20
        
        # 添加成员
        member_id = f"ai_{session_id}"
        member = await self._add_member_internal(
            group_id=group_id,
            member_id=member_id,
            member_type=MemberType.AI,
            display_name=display_name,
            avatar=avatar_url,  # 传递头像URL
            status=MemberStatus.OFFLINE,  # 初始离线，等待MCP上线
            session_id=session_id,
            behavior_config=behavior_config
        )
        
        # 更新群组的AI成员列表
        await self.collection_groups.update_one(
            {"group_id": group_id},
            {
                "$addToSet": {
                    "member_ids": member_id,
                    "ai_member_ids": member_id
                }
            }
        )
        
        logger.info(f"✅ 添加AI成员: 群组={group_id} | 会话={session_id} | 名称={display_name}")
        
        return member
    
    async def add_human_member(
        self,
        group_id: str,
        user_id: str,
        inviter_id: str
    ) -> GroupMember:
        """
        添加真人成员到群聊
        
        Args:
            group_id: 群组ID
            user_id: 要添加的用户ID
            inviter_id: 邀请者的用户ID（用于权限验证）
        
        Returns:
            添加的成员对象
        """
        # 1. 验证群聊是否存在
        group_doc = await self.collection_groups.find_one({"group_id": group_id})
        if not group_doc:
            raise ValueError(f"群聊不存在: {group_id}")
        
        # 2. 验证邀请者是否是群成员
        if inviter_id not in group_doc.get("member_ids", []):
            raise ValueError(f"邀请者不是群成员: {inviter_id}")
        
        # 3. 查询用户信息（从users集合）
        # 尝试用ObjectId查询，如果失败则用account查询
        from bson import ObjectId
        try:
            user_doc = await self.db[settings.mongodb_db_name].users.find_one({"_id": ObjectId(user_id)})
        except:
            # 如果不是有效的ObjectId，尝试作为account查询
            user_doc = await self.db[settings.mongodb_db_name].users.find_one({"account": user_id})
        
        if not user_doc:
            raise ValueError(f"用户不存在: {user_id}")
        
        # 4. 提取用户信息（统一使用ObjectId作为member_id）
        actual_user_id = str(user_doc["_id"])
        display_name = user_doc.get("full_name") or user_doc.get("account", "未命名用户")  # 优先全名，否则账号
        avatar = user_doc.get("avatar_url")
        
        # 5. 检查用户是否已经在群里
        if actual_user_id in group_doc.get("member_ids", []):
            raise ValueError(f"用户已经在群里: {actual_user_id}")
        
        # 6. 检查群组人数限制
        max_members = group_doc.get("max_members", 100)
        if len(group_doc.get("member_ids", [])) >= max_members:
            raise ValueError(f"群组已达到最大成员数: {max_members}")
        
        # 7. 添加成员（使用统一的ObjectId）
        member = await self._add_member_internal(
            group_id=group_id,
            member_id=actual_user_id,
            member_type=MemberType.HUMAN,
            display_name=display_name,
            avatar=avatar,
            status=MemberStatus.OFFLINE  # 初始离线，WebSocket连接后上线
        )
        
        # 8. 更新群组的成员列表
        await self.collection_groups.update_one(
            {"group_id": group_id},
            {
                "$addToSet": {
                    "member_ids": actual_user_id,
                    "human_member_ids": actual_user_id
                }
            }
        )
        
        logger.info(f"✅ 添加真人成员: 群组={group_id} | 用户={actual_user_id} | 名称={display_name} | 邀请者={inviter_id}")
        
        return member
    
    async def _add_member_internal(
        self,
        group_id: str,
        member_id: str,
        member_type: MemberType,
        display_name: Optional[str] = None,
        avatar: Optional[str] = None,
        status: MemberStatus = MemberStatus.OFFLINE,
        session_id: Optional[str] = None,
        behavior_config: Optional[AIBehaviorConfig] = None,
        role: Optional["MemberRole"] = None
    ) -> GroupMember:
        """内部方法：添加成员"""
        from ...models.group_chat import MemberRole
        
        # 如果没有指定角色，默认为普通成员
        if role is None:
            role = MemberRole.MEMBER
        
        # 确保 role 是字符串格式（如果是枚举则转换）
        role_value = role.value if hasattr(role, 'value') else role
        
        member = GroupMember(
            member_id=member_id,
            member_type=member_type,
            status=status,
            role=role_value,
            session_id=session_id,
            display_name=display_name,
            avatar=avatar,
            behavior_config=behavior_config
        )
        
        # 插入成员文档
        await self.collection_members.insert_one({
            "group_id": group_id,
            **member.dict()
        })
        
        return member
    
    async def update_member_status(
        self,
        group_id: str,
        member_id: str,
        status: MemberStatus,
        websocket_id: Optional[str] = None
    ):
        """
        更新成员状态
        
        Args:
            group_id: 群组ID
            member_id: 成员ID
            status: 新状态
            websocket_id: WebSocket连接ID（仅真人）
        """
        update_data = {
            "status": status.value,
            "last_active_time": datetime.now()
        }
        
        if websocket_id:
            update_data["websocket_id"] = websocket_id
        
        result = await self.collection_members.update_one(
            {"group_id": group_id, "member_id": member_id},
            {"$set": update_data}
        )
        
        # 清除缓存
        if group_id in self._online_members_cache:
            del self._online_members_cache[group_id]
        
        logger.info(
            f"🔄 更新成员状态:\n"
            f"  - 群组: {group_id}\n"
            f"  - 成员: {member_id}\n"
            f"  - 状态: {status}\n"
            f"  - WebSocket ID: {websocket_id}\n"
            f"  - 更新结果: 匹配={result.matched_count} | 修改={result.modified_count}"
        )
    
    async def get_online_ai_members(self, group_id: str) -> List[GroupMember]:
        """
        获取群组中所有在线的AI成员
        
        Returns:
            在线AI成员列表
        """
        # 先查缓存
        if group_id in self._online_members_cache:
            return self._online_members_cache[group_id]
        
        # 查询数据库
        cursor = self.collection_members.find({
            "group_id": group_id,
            "member_type": MemberType.AI.value,
            "status": MemberStatus.ONLINE.value
        })
        
        members = []
        async for doc in cursor:
            # 移除MongoDB的_id字段
            doc.pop("_id", None)
            doc.pop("group_id", None)
            
            # 重建behavior_config
            if doc.get("behavior_config"):
                doc["behavior_config"] = AIBehaviorConfig(**doc["behavior_config"])
            
            member = GroupMember(**doc)
            members.append(member)
        
        # 缓存结果
        self._online_members_cache[group_id] = members
        
        logger.debug(f"📊 获取在线AI成员: 群组={group_id} | 数量={len(members)}")
        
        return members
    
    async def get_all_members(self, group_id: str) -> List[GroupMember]:
        """获取群组所有成员"""
        # 先获取群组信息，用于判断群主
        group = await self.get_group(group_id)
        owner_id = group.owner_id if group else None
        
        cursor = self.collection_members.find({"group_id": group_id})
        
        members = []
        async for doc in cursor:
            doc.pop("_id", None)
            doc.pop("group_id", None)
            
            # 🔧 兼容旧数据：如果文档中没有 role 字段，根据 owner_id 设置角色
            if "role" not in doc and owner_id:
                if doc.get("member_id") == owner_id:
                    doc["role"] = "owner"
                    logger.info(f"🔧 修复群主角色: group_id={group_id}, member_id={doc.get('member_id')}")
                else:
                    doc["role"] = "member"
            
            if doc.get("behavior_config"):
                doc["behavior_config"] = AIBehaviorConfig(**doc["behavior_config"])
            
            member = GroupMember(**doc)
            members.append(member)
        
        return members
    
    async def get_member(self, group_id: str, member_id: str) -> Optional[GroupMember]:
        """获取单个成员"""
        doc = await self.collection_members.find_one({
            "group_id": group_id,
            "member_id": member_id
        })
        
        if not doc:
            return None
        
        doc.pop("_id", None)
        doc.pop("group_id", None)
        
        # 🔧 兼容旧数据：如果文档中没有 role 字段，根据 owner_id 设置角色
        if "role" not in doc:
            group = await self.get_group(group_id)
            if group and doc.get("member_id") == group.owner_id:
                doc["role"] = "owner"
            else:
                doc["role"] = "member"
        
        if doc.get("behavior_config"):
            doc["behavior_config"] = AIBehaviorConfig(**doc["behavior_config"])
        
        return GroupMember(**doc)
    
    async def update_member_reply_stats(
        self,
        group_id: str,
        member_id: str,
        increment_consecutive: bool = True
    ):
        """
        更新成员回复统计
        
        Args:
            group_id: 群组ID
            member_id: 成员ID
            increment_consecutive: 是否增加连续回复计数
        """
        update_data = {
            "last_reply_time": datetime.now()
        }
        
        if increment_consecutive:
            await self.collection_members.update_one(
                {"group_id": group_id, "member_id": member_id},
                {
                    "$set": update_data,
                    "$inc": {"consecutive_reply_count": 1}
                }
            )
        else:
            # 重置连续回复计数（其他成员发言了）
            update_data["consecutive_reply_count"] = 0
            await self.collection_members.update_one(
                {"group_id": group_id, "member_id": member_id},
                {"$set": update_data}
            )
        
        # 清除缓存
        if group_id in self._online_members_cache:
            del self._online_members_cache[group_id]
    
    async def reset_consecutive_replies(self, group_id: str, exclude_member_id: str):
        """
        重置所有成员的连续回复计数（新消息发送时调用）
        
        Args:
            group_id: 群组ID
            exclude_member_id: 排除的成员ID（刚发送消息的成员）
        """
        await self.collection_members.update_many(
            {
                "group_id": group_id,
                "member_id": {"$ne": exclude_member_id}
            },
            {"$set": {"consecutive_reply_count": 0}}
        )
        
        # 清除缓存
        if group_id in self._online_members_cache:
            del self._online_members_cache[group_id]
    
    async def get_group(self, group_id: str) -> Optional[GroupChat]:
        """获取群聊信息"""
        doc = await self.collection_groups.find_one({"group_id": group_id})
        
        if not doc:
            return None
        
        doc.pop("_id", None)
        return GroupChat(**doc)
    
    async def update_behavior_config(
        self,
        group_id: str,
        ai_member_id: str,
        behavior_config: AIBehaviorConfig
    ):
        """更新AI行为配置"""
        await self.collection_members.update_one(
            {"group_id": group_id, "member_id": ai_member_id},
            {"$set": {"behavior_config": behavior_config.dict()}}
        )
        
        # 清除缓存
        if group_id in self._online_members_cache:
            del self._online_members_cache[group_id]
        
        logger.info(f"✅ 更新AI行为配置: 群组={group_id} | AI={ai_member_id}")
    
    async def remove_member(self, group_id: str, member_id: str):
        """移除成员"""
        # 删除成员文档
        await self.collection_members.delete_one({
            "group_id": group_id,
            "member_id": member_id
        })
        
        # 更新群组成员列表
        await self.collection_groups.update_one(
            {"group_id": group_id},
            {
                "$pull": {
                    "member_ids": member_id,
                    "ai_member_ids": member_id,
                    "human_member_ids": member_id
                }
            }
        )
        
        # 清除缓存
        if group_id in self._online_members_cache:
            del self._online_members_cache[group_id]
        
        logger.info(f"❌ 移除成员: 群组={group_id} | 成员={member_id}")
    
    async def set_member_role(
        self,
        group_id: str,
        member_id: str,
        role: str
    ) -> bool:
        """
        设置成员角色
        
        Args:
            group_id: 群组ID
            member_id: 成员ID
            role: 角色 (owner/admin/member)
        
        Returns:
            是否设置成功
        """
        from ...models.group_chat import MemberRole
        
        # 验证角色值
        valid_roles = [MemberRole.OWNER, MemberRole.ADMIN, MemberRole.MEMBER]
        if role not in [r.value for r in valid_roles]:
            raise ValueError(f"无效的角色: {role}")
        
        # 更新成员角色
        result = await self.collection_members.update_one(
            {"group_id": group_id, "member_id": member_id},
            {"$set": {"role": role}}
        )
        
        if result.modified_count > 0:
            # 清除缓存
            if group_id in self._online_members_cache:
                del self._online_members_cache[group_id]
            
            logger.info(f"✅ 设置成员角色: 群组={group_id} | 成员={member_id} | 角色={role}")
            return True
        
        return False
    
    async def set_admin(self, group_id: str, member_id: str) -> bool:
        """设置成员为管理员"""
        return await self.set_member_role(group_id, member_id, "admin")
    
    async def remove_admin(self, group_id: str, member_id: str) -> bool:
        """取消成员的管理员身份（降级为普通成员）"""
        return await self.set_member_role(group_id, member_id, "member")
    
    def clear_cache(self, group_id: Optional[str] = None):
        """清除缓存"""
        if group_id:
            self._online_members_cache.pop(group_id, None)
        else:
            self._online_members_cache.clear()

