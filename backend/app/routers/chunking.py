"""
智能分片API路由
提供分片策略配置、测试、质量评估等功能
"""

from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
import logging

from ..models.user import User
from ..utils.auth import get_current_user
from ..database import get_database
from ..services.chunking import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkerFactory,
    ChunkerRegistry
)
from ..services.chunking.async_processor import (
    AsyncChunkingProcessor,
    ChunkingTask,
    ExecutorType
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["智能分片"])


# ==================== 请求/响应模型 ====================

class ChunkingConfigRequest(BaseModel):
    """分片配置请求"""
    strategy: ChunkingStrategy = Field(ChunkingStrategy.DOCUMENT_AWARE, description="分片策略")
    chunk_size: int = Field(1024, ge=100, le=8000, description="分片大小")
    chunk_overlap: int = Field(100, ge=0, le=2000, description="分片重叠")
    separators: List[str] = Field(default_factory=lambda: ["\n\n", "\n", "。", "！", "？", "，", " ", ""], description="分隔符列表")
    use_sentence_boundary: bool = Field(True, description="使用句子边界")
    semantic_threshold: float = Field(0.5, ge=0, le=1, description="语义阈值")
    preserve_structure: bool = Field(True, description="保持结构完整性")
    ast_parsing: bool = Field(True, description="使用AST解析（代码文件）")
    enable_hierarchy: bool = Field(False, description="启用层级分片")
    parent_chunk_size: int = Field(4096, ge=1000, le=16000, description="父分片大小")
    max_workers: int = Field(4, ge=1, le=16, description="最大并发数")
    batch_size: int = Field(100, ge=1, le=1000, description="批次大小")


class ChunkingTestRequest(BaseModel):
    """分片测试请求"""
    content: str = Field(..., description="测试内容")
    file_type: str = Field("txt", description="文件类型")
    config: ChunkingConfigRequest = Field(..., description="分片配置")


class ChunkInfo(BaseModel):
    """分片信息"""
    content: str
    chunk_index: int
    metadata: Dict[str, Any]
    quality_score: float
    completeness: bool
    char_count: int
    word_count: int


class ChunkingTestResponse(BaseModel):
    """分片测试响应"""
    success: bool
    chunks: List[ChunkInfo]
    total_chunks: int
    total_chars: int
    avg_chunk_size: float
    avg_quality_score: float
    processing_time: float
    chunker_type: str
    error: Optional[str] = None


class ChunkerInfo(BaseModel):
    """分片器信息"""
    name: str
    priority: int
    can_handle: bool


class ChunkersListResponse(BaseModel):
    """分片器列表响应"""
    chunkers: List[str]
    total: int


class ChunkQualityReport(BaseModel):
    """分片质量报告"""
    total_chunks: int
    avg_size: float
    min_size: int
    max_size: int
    avg_quality_score: float
    completeness_rate: float
    oversized_chunks: int
    undersized_chunks: int


# ==================== API端点 ====================

@router.post("/chunking/test", response_model=ChunkingTestResponse)
async def test_chunking(
    request: ChunkingTestRequest,
    current_user: User = Depends(get_current_user)
):
    """
    测试分片效果
    
    用于在实际使用前测试不同的分片配置
    """
    try:
        import time
        
        # 转换配置
        config = ChunkingConfig(
            strategy=request.config.strategy,
            chunk_size=request.config.chunk_size,
            chunk_overlap=request.config.chunk_overlap,
            separators=request.config.separators,
            use_sentence_boundary=request.config.use_sentence_boundary,
            semantic_threshold=request.config.semantic_threshold,
            preserve_structure=request.config.preserve_structure,
            ast_parsing=request.config.ast_parsing,
            enable_hierarchy=request.config.enable_hierarchy,
            parent_chunk_size=request.config.parent_chunk_size,
            max_workers=request.config.max_workers,
            batch_size=request.config.batch_size
        )
        
        # 创建分片器
        start_time = time.time()
        chunker = ChunkerFactory.create_chunker(
            file_type=request.file_type,
            content=request.content,
            config=config
        )
        
        # 执行分片
        chunks = chunker.chunk(request.content)
        processing_time = time.time() - start_time
        
        # 计算统计信息
        total_chars = sum(len(chunk.content) for chunk in chunks)
        avg_chunk_size = total_chars / len(chunks) if chunks else 0
        avg_quality_score = sum(chunk.quality_score for chunk in chunks) / len(chunks) if chunks else 0
        
        # 转换为响应格式
        chunk_infos = [
            ChunkInfo(
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                metadata=chunk.metadata,
                quality_score=chunk.quality_score,
                completeness=chunk.completeness,
                char_count=chunk.metadata.get('char_count', len(chunk.content)),
                word_count=chunk.metadata.get('word_count', len(chunk.content.split()))
            )
            for chunk in chunks
        ]
        
        return ChunkingTestResponse(
            success=True,
            chunks=chunk_infos,
            total_chunks=len(chunks),
            total_chars=total_chars,
            avg_chunk_size=avg_chunk_size,
            avg_quality_score=avg_quality_score,
            processing_time=processing_time,
            chunker_type=chunker.__class__.__name__
        )
        
    except Exception as e:
        logger.error(f"分片测试失败: {e}", exc_info=True)
        return ChunkingTestResponse(
            success=False,
            chunks=[],
            total_chunks=0,
            total_chars=0,
            avg_chunk_size=0,
            avg_quality_score=0,
            processing_time=0,
            chunker_type="unknown",
            error=str(e)
        )


@router.get("/chunking/chunkers", response_model=ChunkersListResponse)
async def list_chunkers(
    current_user: User = Depends(get_current_user)
):
    """
    列出所有可用的分片器
    """
    try:
        chunkers = ChunkerRegistry.list_chunkers()
        
        return ChunkersListResponse(
            chunkers=chunkers,
            total=len(chunkers)
        )
        
    except Exception as e:
        logger.error(f"获取分片器列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取分片器列表失败: {str(e)}")


@router.post("/chunking/detect-chunker")
async def detect_best_chunker(
    file_type: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user)
):
    """
    检测最适合的分片器
    """
    try:
        config = ChunkingConfig()
        chunker = ChunkerRegistry.get_best_chunker(file_type, content, config)
        
        return {
            "success": True,
            "chunker_type": chunker.__class__.__name__,
            "priority": chunker.get_priority(),
            "can_handle": chunker.can_handle(file_type, content)
        }
        
    except Exception as e:
        logger.error(f"检测分片器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检测分片器失败: {str(e)}")


@router.post("/chunking/quality-report", response_model=ChunkQualityReport)
async def generate_quality_report(
    request: ChunkingTestRequest,
    current_user: User = Depends(get_current_user)
):
    """
    生成分片质量报告
    """
    try:
        # 转换配置
        config = ChunkingConfig(
            strategy=request.config.strategy,
            chunk_size=request.config.chunk_size,
            chunk_overlap=request.config.chunk_overlap,
            separators=request.config.separators,
            use_sentence_boundary=request.config.use_sentence_boundary,
            semantic_threshold=request.config.semantic_threshold,
            preserve_structure=request.config.preserve_structure,
            ast_parsing=request.config.ast_parsing,
            enable_hierarchy=request.config.enable_hierarchy,
            parent_chunk_size=request.config.parent_chunk_size
        )
        
        # 创建分片器并执行分片
        chunker = ChunkerFactory.create_chunker(
            file_type=request.file_type,
            content=request.content,
            config=config
        )
        chunks = chunker.chunk(request.content)
        
        if not chunks:
            return ChunkQualityReport(
                total_chunks=0,
                avg_size=0,
                min_size=0,
                max_size=0,
                avg_quality_score=0,
                completeness_rate=0,
                oversized_chunks=0,
                undersized_chunks=0
            )
        
        # 计算统计信息
        sizes = [len(chunk.content) for chunk in chunks]
        quality_scores = [chunk.quality_score for chunk in chunks]
        complete_chunks = sum(1 for chunk in chunks if chunk.completeness)
        
        # 定义过大/过小的阈值
        ideal_size = config.chunk_size
        oversized_threshold = ideal_size * 1.5
        undersized_threshold = ideal_size * 0.3
        
        oversized = sum(1 for size in sizes if size > oversized_threshold)
        undersized = sum(1 for size in sizes if size < undersized_threshold)
        
        return ChunkQualityReport(
            total_chunks=len(chunks),
            avg_size=sum(sizes) / len(sizes),
            min_size=min(sizes),
            max_size=max(sizes),
            avg_quality_score=sum(quality_scores) / len(quality_scores),
            completeness_rate=complete_chunks / len(chunks),
            oversized_chunks=oversized,
            undersized_chunks=undersized
        )
        
    except Exception as e:
        logger.error(f"生成质量报告失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成质量报告失败: {str(e)}")


@router.get("/chunking/strategies")
async def list_strategies(
    current_user: User = Depends(get_current_user)
):
    """
    列出所有可用的分片策略
    """
    return {
        "strategies": [
            {
                "value": ChunkingStrategy.SIMPLE,
                "label": "简单分片",
                "description": "基于分隔符的传统分片方法，适合简单文本"
            },
            {
                "value": ChunkingStrategy.SEMANTIC,
                "label": "语义分片",
                "description": "基于句子边界和语义相似度，保持语义连贯性"
            },
            {
                "value": ChunkingStrategy.DOCUMENT_AWARE,
                "label": "文档感知分片（推荐）",
                "description": "自动识别文档类型，使用专用分片器保持结构完整性"
            },
            {
                "value": ChunkingStrategy.HIERARCHICAL,
                "label": "层级分片",
                "description": "创建父子分片关系，提供多层次上下文"
            }
        ]
    }

