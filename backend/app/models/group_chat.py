"""
AI群聊数据模型

定义群聊相关的所有数据结构
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class MemberType(str, Enum):
    """成员类型"""
    HUMAN = "human"  # 真人用户
    AI = "ai"        # AI成员


class MemberStatus(str, Enum):
    """成员在线状态"""
    ONLINE = "online"      # 在线
    OFFLINE = "offline"    # 离线
    IDLE = "idle"          # 空闲（在线但不活跃）


class MemberRole(str, Enum):
    """成员角色"""
    OWNER = "owner"        # 群主
    ADMIN = "admin"        # 管理员
    MEMBER = "member"      # 普通成员


class AIBehaviorConfig(BaseModel):
    """AI行为配置"""
    # 基础开关
    auto_reply_enabled: bool = True  # 是否启用自动回复
    
    # 响应概率与延迟
    base_reply_probability: float = Field(0.3, ge=0.0, le=1.0)  # 基础回复概率
    delay_range: tuple[float, float] = (1.0, 5.0)  # 延迟回复范围（秒）
    
    # 关键词与兴趣
    interest_keywords: List[str] = []  # 兴趣关键词（增加回复概率）
    interest_boost: float = Field(0.4, ge=0.0, le=1.0)  # 兴趣加成
    
    # @提及
    mention_reply_probability: float = Field(0.9, ge=0.0, le=1.0)  # 被@时回复概率
    
    # 随机唤醒
    random_wake_enabled: bool = False  # 是否启用随机唤醒
    random_wake_probability: float = Field(0.05, ge=0.0, le=1.0)  # 随机唤醒概率
    random_wake_interval: int = 300  # 随机唤醒检查间隔（秒）
    
    # 抢答控制
    max_consecutive_replies: int = 2  # 最大连续回复次数
    cooldown_after_reply: float = 10.0  # 回复后冷却时间（秒）
    
    # 上下文管理
    context_window_size: int = 20  # 查看的群聊消息数量（继承自会话配置）
    
    # 情绪响应（预留）
    emotion_enabled: bool = False
    emotion_keywords: Dict[str, float] = {}  # 情绪关键词 -> 响应概率调整


class GroupMember(BaseModel):
    """群聊成员"""
    member_id: str  # 成员ID (user_id 或 session_id)
    member_type: MemberType  # 成员类型
    status: MemberStatus = MemberStatus.OFFLINE  # 在线状态
    role: MemberRole = MemberRole.MEMBER  # 成员角色
    
    # AI专属字段
    session_id: Optional[str] = None  # AI对应的会话ID
    display_name: Optional[str] = None  # 显示名称
    avatar: Optional[str] = None  # 头像URL
    behavior_config: Optional[AIBehaviorConfig] = None  # AI行为配置
    
    # 状态跟踪
    last_active_time: Optional[datetime] = None  # 最后活跃时间
    consecutive_reply_count: int = 0  # 连续回复计数
    last_reply_time: Optional[datetime] = None  # 最后回复时间
    
    # WebSocket连接（仅真人）
    websocket_id: Optional[str] = None  # WebSocket连接ID
    
    joined_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        use_enum_values = True


class MessageType(str, Enum):
    """消息类型"""
    TEXT = "text"              # 文本消息
    IMAGE = "image"            # 图片消息
    SYSTEM = "system"          # 系统消息
    AI_THINKING = "ai_thinking"  # AI思考中
    AI_REPLY = "ai_reply"      # AI回复


class GroupMessage(BaseModel):
    """群聊消息"""
    message_id: str
    group_id: str
    sender_id: str  # 发送者ID
    sender_type: MemberType  # 发送者类型
    sender_name: str  # 发送者昵称
    
    message_type: MessageType = MessageType.TEXT
    content: str  # 消息内容
    images: List[str] = []  # 图片URL列表
    
    # @提及
    mentions: List[str] = []  # @的成员ID列表
    
    # 引用回复
    reply_to: Optional[str] = None  # 回复的消息ID
    
    # 元数据
    timestamp: datetime = Field(default_factory=datetime.now)
    read_by: List[str] = []  # 已读成员ID列表
    
    # AI回复专属
    ai_session_id: Optional[str] = None  # AI对应的会话ID
    reference: List[Dict[str, Any]] = []  # 知识库引用（与普通会话字段名一致）
    
    class Config:
        use_enum_values = True


class GroupStrategyConfig(BaseModel):
    """群聊策略配置（所有限流策略）"""
    
    # ========== 模板信息 ==========
    applied_template: Optional[str] = Field(None, description="应用的模板名称（用于标记配置来源）")
    base_template: Optional[str] = Field(None, description="基础模板名称（即使被修改也保留，用于前端显示修改状态）")
    
    # ========== 一键解除限流开关 ==========
    unrestricted_mode: bool = Field(False, description="一键解除限流模式：开启后所有限流策略失效")
    
    # ========== 第1层：对话轮次限流 ==========
    max_ai_consecutive_replies: int = Field(3, ge=1, description="AI最多连续回复次数")
    max_messages_per_round: int = Field(20, ge=1, description="每轮对话最多消息数")
    max_tokens_per_round: int = Field(50000, ge=1000, description="每轮对话最多tokens")
    cooldown_seconds: int = Field(30, ge=0, description="冷却期时长（秒）")
    max_cooldown_recoveries: int = Field(3, ge=0, description="最大冷却期恢复次数")
    enable_ai_to_ai: bool = Field(True, description="是否启用AI互相对话")
    ai_reply_probability: float = Field(0.6, ge=0.0, le=1.0, description="AI对AI消息的基础回复概率")
    
    # ========== 第2层：概率采样限流 ==========
    high_probability_threshold: float = Field(0.7, ge=0.0, le=1.0, description="高概率阈值")
    high_probability_keep_rate: float = Field(0.8, ge=0.0, le=1.0, description="高概率保留率")
    mid_probability_threshold: float = Field(0.3, ge=0.0, le=1.0, description="中概率阈值")
    low_probability_keep_rate: float = Field(0.3, ge=0.0, le=1.0, description="低概率采样率")
    min_ai_sample_count: int = Field(3, ge=1, description="AI数量≤此值时直接放行")
    
    # ========== 第3层：智能并发控制 ==========
    # 根据群组活跃度
    cold_group_max_concurrent: int = Field(1, ge=1, description="冷清群最大并发AI数")
    cold_group_min_delay_gap: float = Field(5.0, ge=0.0, description="冷清群最小延迟间隔（秒）")
    warm_group_max_concurrent: int = Field(2, ge=1, description="温和群最大并发AI数")
    warm_group_min_delay_gap: float = Field(3.0, ge=0.0, description="温和群最小延迟间隔（秒）")
    hot_group_max_concurrent: int = Field(3, ge=1, description="热闹群最大并发AI数")
    hot_group_min_delay_gap: float = Field(2.0, ge=0.0, description="热闹群最小延迟间隔（秒）")
    
    # 根据触发消息类型
    human_message_max_concurrent: int = Field(3, ge=1, description="人类消息最大并发AI数")
    ai_message_max_concurrent: int = Field(2, ge=1, description="AI消息最大并发AI数")
    at_mention_max_concurrent: int = Field(1, ge=1, description="@消息最大并发AI数")
    
    # 根据AI连续回复情况（概率衰减系数）
    ai_consecutive_0_multiplier: float = Field(1.0, ge=0.0, le=1.0, description="无AI连续时的概率倍数")
    ai_consecutive_1_multiplier: float = Field(0.8, ge=0.0, le=1.0, description="1次AI连续时的概率倍数")
    ai_consecutive_2_multiplier: float = Field(0.5, ge=0.0, le=1.0, description="2次AI连续时的概率倍数")
    ai_consecutive_3_multiplier: float = Field(0.2, ge=0.0, le=1.0, description="3次及以上AI连续时的概率倍数")
    
    # 根据AI密度
    dense_ai_multiplier: float = Field(0.5, ge=0.0, le=1.0, description="AI回复密集时的概率倍数")
    
    # ========== 第4层：抢答控制限流 ==========
    max_concurrent_replies_per_message: int = Field(3, ge=1, description="单条消息最大并发回复数")
    
    # ========== 第5层：相似度检测 ==========
    enable_similarity_detection: bool = Field(True, description="是否启用相似度检测")
    similarity_threshold: float = Field(0.6, ge=0.0, le=1.0, description="相似度阈值")
    similarity_lookback: int = Field(3, ge=1, description="相似度检测回溯消息数")
    
    # ========== 延迟控制 ==========
    mention_delay_min: float = Field(0.5, ge=0.0, description="被@时最小延迟（秒）")
    mention_delay_max: float = Field(2.0, ge=0.0, description="被@时最大延迟（秒）")
    high_interest_delay_min: float = Field(1.0, ge=0.0, description="高兴趣最小延迟（秒）")
    high_interest_delay_max: float = Field(3.0, ge=0.0, description="高兴趣最大延迟（秒）")
    normal_delay_min: float = Field(2.0, ge=0.0, description="普通消息最小延迟（秒）")
    normal_delay_max: float = Field(5.0, ge=0.0, description="普通消息最大延迟（秒）")
    ai_to_ai_delay_seconds: float = Field(7.0, ge=0.0, description="AI回复后触发新AI决策的延迟时间（秒）")


class GroupChat(BaseModel):
    """群聊"""
    group_id: str
    name: str
    description: Optional[str] = None
    avatar: Optional[str] = None
    
    # 所有者
    owner_id: str  # 创建者的user_id
    
    # 成员列表（存储引用，详细信息在 group_members 集合）
    member_ids: List[str] = []  # 所有成员ID列表
    ai_member_ids: List[str] = []  # AI成员ID列表（快速查询）
    human_member_ids: List[str] = []  # 真人成员ID列表
    
    # 群聊配置
    max_members: int = 100  # 最大成员数
    allow_ai_invite: bool = True  # 是否允许AI邀请其他AI
    
    # 🔥 群聊策略配置（限流策略）
    strategy_config: GroupStrategyConfig = Field(default_factory=GroupStrategyConfig)
    
    # 🎯 群聊自定义系统提示词（用户定义的群聊场景/规则）
    group_system_prompt: Optional[str] = Field(
        None, 
        description="用户自定义的群聊系统提示词，会插入到AI原本的系统提示词和群聊信息之间"
    )
    
    # 消息管理
    message_count: int = 0  # 消息总数
    last_message_time: Optional[datetime] = None  # 最后一条消息时间
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # 是否活跃
    is_active: bool = True


class AIReplyDecision(BaseModel):
    """AI回复决策结果"""
    ai_member_id: str
    session_id: str
    should_reply: bool  # 是否回复
    
    # 决策依据
    decision_reason: str  # 决策原因
    probability_score: float  # 概率分数
    
    # 延迟控制
    delay_seconds: float = 0.0  # 延迟时间（秒）
    scheduled_time: Optional[datetime] = None  # 预定回复时间
    tier: Optional[int] = None  # 分层级别（1=高优先级，2=中优先级，3=低优先级）
    
    # 过滤器结果
    passed_filters: List[str] = []  # 通过的过滤器
    failed_filters: List[str] = []  # 未通过的过滤器


class GroupChatContext(BaseModel):
    """群聊上下文（用于AI调用LLM）"""
    group_id: str
    group_name: str
    
    # 最近消息
    recent_messages: List[GroupMessage]  # 根据AI的context_window_size截取
    
    # 当前消息
    current_message: GroupMessage
    
    # 成员信息
    online_members: List[GroupMember]  # 在线成员
    ai_members: List[GroupMember]  # 所有AI成员
    
    # 元数据
    total_members: int
    timestamp: datetime = Field(default_factory=datetime.now)


# ============ 请求/响应模型 ============

class CreateGroupRequest(BaseModel):
    """创建群聊请求"""
    name: str
    description: Optional[str] = None
    avatar: Optional[str] = None
    initial_ai_sessions: List[str] = []  # 初始AI成员（会话ID列表）


class AddMemberRequest(BaseModel):
    """添加成员请求"""
    member_type: MemberType
    member_id: str  # user_id 或 session_id
    display_name: Optional[str] = None
    behavior_config: Optional[AIBehaviorConfig] = None  # AI专属


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content: str
    images: List[str] = []  # 图片base64列表
    mentions: List[str] = []  # @的成员ID
    reply_to: Optional[str] = None  # 回复的消息ID


class UpdateBehaviorRequest(BaseModel):
    """更新AI行为配置请求"""
    ai_member_id: str
    behavior_config: AIBehaviorConfig


class UpdateGroupStrategyRequest(BaseModel):
    """更新群聊策略配置请求"""
    strategy_config: GroupStrategyConfig


class GroupChatWebSocketMessage(BaseModel):
    """WebSocket消息格式"""
    type: str  # message/system/ai_status/member_join/member_leave
    data: Dict[str, Any]


class GroupMemberResponse(BaseModel):
    """群聊成员（API响应格式）"""
    member_id: str
    member_type: str  # "user" 或 "ai"（前端格式）
    nickname: str  # 显示名称
    avatar: Optional[str] = None
    status: str  # "online" | "offline" | "busy"
    role: str  # "owner" | "admin" | "member"
    joined_at: datetime


class GroupChatWithMembers(BaseModel):
    """群聊（包含成员信息）- 用于API响应"""
    group_id: str
    name: str
    description: Optional[str] = None
    avatar: Optional[str] = None
    owner_id: str
    members: List[GroupMemberResponse] = []  # 成员列表（前端格式）
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    
    # 额外字段（前端需要）
    last_message: Optional[GroupMessage] = None
    unread_count: int = 0

