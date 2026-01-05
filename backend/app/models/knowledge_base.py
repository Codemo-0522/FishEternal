"""
知识库相关数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from bson import ObjectId


class PyObjectId(ObjectId):
    """自定义 ObjectId 类型"""
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


class EmbeddingConfig(BaseModel):
    """Embedding配置"""
    provider: str
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    local_model_path: Optional[str] = None


class SplitParams(BaseModel):
    """文本分割参数"""
    chunk_size: int = 500
    chunk_overlap: int = 100
    separators: Optional[List[str]] = None
    # 智能分片策略配置
    chunking_strategy: Optional[str] = "document_aware"  # simple, semantic, document_aware, hierarchical
    use_sentence_boundary: Optional[bool] = True
    semantic_threshold: Optional[float] = 0.5
    preserve_structure: Optional[bool] = True
    ast_parsing: Optional[bool] = True
    enable_hierarchy: Optional[bool] = False
    parent_chunk_size: Optional[int] = 4096
    max_workers: Optional[int] = 4
    batch_size: Optional[int] = 100


class VectorSearchParams(BaseModel):
    """向量检索参数"""
    distance_metric: str = Field(
        default="cosine",
        description="距离度量方式: cosine(余弦距离-文本语义) | l2(欧氏距离-精确匹配) | ip(内积-推荐系统)"
    )
    similarity_threshold: float = Field(
        default=0.3,
        description="相似度分数阈值(0-1，1=最相似): 统一转换后的相似度分数，推荐0.3-0.7，宽松场景用0.3"
    )
    top_k: int = Field(default=3, ge=1, le=20, description="返回结果数量")


class KnowledgeBaseCreateRequest(BaseModel):
    """创建知识库请求（前端格式）"""
    name: str
    description: Optional[str] = None
    collection_name: Optional[str] = None
    vector_db: str = "chroma"
    embedding_config: EmbeddingConfig
    split_params: SplitParams
    search_params: Optional[VectorSearchParams] = None  # 新增：向量检索参数
    # 兼容旧版字段
    similarity_threshold: Optional[float] = 10.0
    top_k: Optional[int] = 3


class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求"""
    name: str = Field(..., description="知识库名称")
    description: Optional[str] = Field(None, description="知识库描述")
    embedding_config_id: Optional[str] = Field(None, description="Embedding配置ID")
    kb_settings: Dict[str, Any] = Field(..., description="知识库配置")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "我的知识库",
                "description": "用于存储技术文档",
                "kb_settings": {
                    "enabled": True,
                    "vector_db": "chroma",
                    "collection_name": "my_kb",
                    "embeddings": {
                        "provider": "ollama",
                        "model": "nomic-embed-text:v1.5",
                        "base_url": "http://localhost:11434"
                    },
                    "split_params": {
                        "chunk_size": 500,
                        "chunk_overlap": 100
                    }
                }
            }
        }


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求
    
    注意：distance_metric 不可修改，因为向量索引结构依赖此配置
    其他配置（chunk_size、chunk_overlap等）可以修改，新配置将应用于后续上传的文档
    """
    name: Optional[str] = None
    description: Optional[str] = None
    kb_settings: Optional[Dict[str, Any]] = None


class KnowledgeBaseResponse(BaseModel):
    """知识库响应"""
    id: str
    name: str
    description: Optional[str] = None
    user_id: str
    embedding_config_id: Optional[str] = None
    kb_settings: Dict[str, Any]
    document_count: int = 0
    chunk_count: int = 0
    total_size: int = 0
    created_at: str
    updated_at: str
    # 前端需要的额外字段
    collection_name: Optional[str] = None
    vector_db: Optional[str] = None
    embedding_config: Optional[Dict[str, Any]] = None
    split_params: Optional[Dict[str, Any]] = None
    search_params: Optional[Dict[str, Any]] = None  # 新增：向量检索参数
    # 兼容旧版字段
    similarity_threshold: Optional[float] = None
    top_k: Optional[int] = None
    sharing_info: Optional[Dict[str, Any]] = None  # 共享信息
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "name": "我的知识库",
                "description": "用于存储技术文档",
                "user_id": "507f1f77bcf86cd799439012",
                "kb_settings": {},
                "document_count": 5,
                "chunk_count": 150,
                "total_size": 1024000,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        }


class DocumentCreate(BaseModel):
    """创建文档请求（元数据）"""
    filename: str
    file_size: int
    file_type: str
    metadata: Optional[Dict[str, Any]] = None


class DocumentResponse(BaseModel):
    """文档响应"""
    id: str
    kb_id: str
    filename: str
    file_size: int
    file_type: str
    chunk_count: int = 0
    status: str = "pending"  # pending, uploaded, processing, completed, failed
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None
    file_url: Optional[str] = None  # MinIO 存储路径
    upload_time: str
    update_time: str
    # 任务进度信息
    progress: float = 0.0  # 进度百分比 (0.0-1.0)
    progress_msg: str = ""  # 进度描述信息
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439013",
                "kb_id": "507f1f77bcf86cd799439011",
                "filename": "document.pdf",
                "file_size": 102400,
                "file_type": "pdf",
                "chunk_count": 30,
                "status": "completed",
                "file_url": "kb-documents/user_123/kb_001/doc_001/document.pdf",
                "upload_time": "2024-01-01T00:00:00",
                "update_time": "2024-01-01T00:00:00"
            }
        }


class KBStatistics(BaseModel):
    """知识库统计信息"""
    total_kbs: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    total_size: int = 0
    
    class Config:
        json_schema_extra = {
            "example": {
                "total_kbs": 3,
                "total_documents": 15,
                "total_chunks": 450,
                "total_size": 5120000
            }
        }


class KBSearchRequest(BaseModel):
    """知识库检索请求"""
    query: str = Field(..., description="检索查询文本")
    top_k: int = Field(default=5, ge=1, le=20, description="返回结果数量")
    similarity_threshold: Optional[float] = Field(default=None, description="相似度阈值(距离阈值)，只返回distance≤此值的结果")
    distance_metric: Optional[str] = Field(default=None, description="距离度量方式: cosine/l2/ip")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "如何使用知识库？",
                "top_k": 5,
                "similarity_threshold": 0.7,
                "distance_metric": "cosine"
            }
        }


class KBSearchResult(BaseModel):
    """检索结果项"""
    content: str
    score: float  # 相似度分数 (0-1)
    distance: Optional[float] = None  # L2距离
    metadata: Dict[str, Any]
    chunk_id: Optional[str] = None  # chunk ID
    doc_id: Optional[str] = None  # 文档ID
    document_name: Optional[str] = None  # 文档名称（前端显示用）
    
    class Config:
        json_schema_extra = {
            "example": {
                "content": "知识库使用指南...",
                "score": 0.85,
                "metadata": {
                    "source": "guide.pdf",
                    "chunk_index": 0,
                    "document_id": "doc123"
                },
                "chunk_id": "chunk_123",
                "doc_id": "doc_456",
                "document_name": "guide.pdf"
            }
        }


class KBSearchResponse(BaseModel):
    """知识库检索响应"""
    success: bool
    results: List[KBSearchResult]
    total: Optional[int] = None  # 结果总数
    error: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "results": [
                    {
                        "content": "知识库使用指南...",
                        "score": 0.85,
                        "metadata": {"source": "guide.pdf"}
                    }
                ],
                "total": 1
            }
        }


# ==================== 多知识库检索模型 ====================

class MultiKBSearchRequest(BaseModel):
    """多知识库检索请求"""
    query: str = Field(..., description="检索查询文本")
    kb_ids: List[str] = Field(..., description="要检索的知识库ID列表", min_items=1)
    top_k_per_kb: int = Field(default=3, ge=1, le=10, description="每个知识库返回的结果数")
    final_top_k: int = Field(default=10, ge=1, le=50, description="最终返回的结果总数")
    merge_strategy: str = Field(
        default="weighted_score",
        description="合并策略: weighted_score(加权分数) | simple_concat(简单拼接) | interleave(交错)"
    )
    similarity_threshold: Optional[float] = Field(
        default=None,
        description="相似度阈值(L2距离),默认使用知识库配置"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "如何使用知识库？",
                "kb_ids": ["kb_001", "kb_002"],
                "top_k_per_kb": 3,
                "final_top_k": 10,
                "merge_strategy": "weighted_score"
            }
        }


class MultiKBSearchResult(BaseModel):
    """多知识库检索结果项 (扩展了来源信息)"""
    content: str
    score: float
    distance: float
    metadata: Dict[str, Any]
    kb_id: str = Field(..., description="来源知识库ID")
    kb_name: str = Field(..., description="来源知识库名称")
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "content": "知识库使用指南...",
                "score": 0.85,
                "distance": 0.15,
                "metadata": {"source": "guide.pdf"},
                "kb_id": "kb_001",
                "kb_name": "技术文档库",
                "chunk_id": "chunk_123",
                "doc_id": "doc_456"
            }
        }


class MultiKBSearchResponse(BaseModel):
    """多知识库检索响应"""
    success: bool
    results: List[MultiKBSearchResult]
    total_results: int = Field(..., description="返回的结果总数")
    kb_count: int = Field(..., description="检索的知识库数量")
    merge_strategy: str = Field(..., description="使用的合并策略")
    error: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "results": [
                    {
                        "content": "知识库使用指南...",
                        "score": 0.85,
                        "distance": 0.15,
                        "metadata": {"source": "guide.pdf"},
                        "kb_id": "kb_001",
                        "kb_name": "技术文档库"
                    }
                ],
                "total_results": 5,
                "kb_count": 2,
                "merge_strategy": "weighted_score"
            }
        }
