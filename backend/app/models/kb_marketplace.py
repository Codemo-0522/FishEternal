"""
知识库广场数据模型
用于共享知识库的元数据管理
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from bson import ObjectId


class PyObjectId(ObjectId):
    """自定义 ObjectId 类型，用于 Pydantic 校验"""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)
    
    @classmethod
    def __modify_schema__(cls, field_schema):
        field_schema.update(type="string")


class SharedKnowledgeBase(BaseModel):
    """共享知识库模型（广场展示）"""
    id: str
    original_kb_id: str  # 原始知识库ID
    owner_id: str  # 所有者ID
    owner_account: str  # 所有者账号
    name: str
    description: Optional[str] = None
    collection_name: str  # ChromaDB collection名称
    vector_db: str  # 向量数据库类型
    
    # 元数据信息（不包含敏感信息如API Key）
    embedding_provider: str  # 嵌入模型提供商
    embedding_model: str  # 嵌入模型名称
    
    # 分片配置（拉取用户需要参考）
    chunk_size: int
    chunk_overlap: int
    separators: List[str]
    
    # 统计信息
    document_count: int = 0
    chunk_count: int = 0
    pull_count: int = 0  # 被拉取次数
    
    # 时间戳
    shared_at: datetime
    updated_at: datetime
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str}
    }


class PulledKnowledgeBase(BaseModel):
    """用户拉取的知识库（保存到用户账号）"""
    id: str
    user_id: str  # 拉取用户的ID
    shared_kb_id: str  # 共享知识库ID
    original_kb_id: str  # 原始知识库ID
    owner_id: str  # 原作者ID
    owner_account: str  # 原作者账号
    
    # 基本信息
    name: str
    description: Optional[str] = None
    collection_name: str  # 使用原作者的collection（只读）
    vector_db: str
    
    # 用户自己的嵌入模型配置（必须自己配置）
    embedding_config: Dict[str, Any]  # 用户自己的embedding配置
    
    # 分片参数（只读，从原知识库复制）
    split_params: Dict[str, Any]
    
    # 用户可调整的检索参数
    similarity_threshold: float = 0.3  # 统一使用0-1的相似度分数（宽松场景推荐0.3）
    top_k: int = 5
    
    # 时间戳
    pulled_at: datetime
    updated_at: datetime
    
    # 状态
    enabled: bool = True  # 是否启用
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str}
    }


class ShareKBRequest(BaseModel):
    """共享知识库请求"""
    kb_id: str
    description: Optional[str] = None  # 可选的共享描述


class UnshareKBRequest(BaseModel):
    """取消共享请求"""
    kb_id: str


class PullKBRequest(BaseModel):
    """拉取知识库请求"""
    shared_kb_id: str
    embedding_config: Dict[str, Any]  # 用户自己的embedding配置
    distance_metric: Optional[str] = 'cosine'  # 距离度量方式
    similarity_threshold: Optional[float] = 0.3  # 默认值0.3(宽松场景推荐)
    top_k: Optional[int] = 5


class UpdatePulledKBRequest(BaseModel):
    """更新已拉取知识库配置"""
    embedding_config: Optional[Dict[str, Any]] = None
    distance_metric: Optional[str] = None  # 距离度量方式
    similarity_threshold: Optional[float] = None
    top_k: Optional[int] = None
    enabled: Optional[bool] = None


class SharedKBResponse(BaseModel):
    """共享知识库响应"""
    id: str
    original_kb_id: str
    owner_id: str
    owner_account: str
    name: str
    description: Optional[str] = None
    collection_name: str
    vector_db: str
    embedding_provider: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    separators: List[str]
    distance_metric: str = 'cosine'  # 新增：距离度量方式
    similarity_threshold: float
    top_k: int
    document_count: int
    chunk_count: int
    pull_count: int
    shared_at: str
    updated_at: str
    is_owner: bool = False  # 是否是所有者


class PulledKBResponse(BaseModel):
    """拉取的知识库响应"""
    id: str
    user_id: str
    shared_kb_id: str
    original_kb_id: str
    owner_id: str
    owner_account: str
    name: str
    description: Optional[str] = None
    collection_name: str
    vector_db: str
    embedding_config: Dict[str, Any]
    split_params: Dict[str, Any]
    distance_metric: str = 'cosine'  # 新增：距离度量方式
    similarity_threshold: float
    top_k: int
    pulled_at: str
    updated_at: str
    enabled: bool
    
    # 额外信息
    document_count: int = 0
    chunk_count: int = 0

