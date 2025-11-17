"""
文档上传服务模块
提供解耦的文档上传、解析、嵌入功能
支持异步处理、进度跟踪、错误重试
"""
import logging
import uuid
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class DocumentUploadResult:
    """文档上传结果"""
    def __init__(
        self,
        success: bool,
        task_id: Optional[str] = None,
        chunks: Optional[int] = None,
        message: str = "",
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.success = success
        self.task_id = task_id
        self.chunks = chunks
        self.message = message
        self.error = error
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.success,
            "task_id": self.task_id,
            "chunks": self.chunks,
            "status": "processing" if self.task_id else ("success" if self.success else "error"),
            "message": self.message,
            "error": self.error,
            "metadata": self.metadata
        }


class DocumentUploadService:
    """
    文档上传服务
    
    职责：
    1. 接收文件上传
    2. 文档格式验证
    3. 文档解析（文本提取）
    4. 提交嵌入任务到队列（异步）
    5. 更新会话配置
    """
    
    def __init__(self):
        self.supported_extensions = {
            '.txt', '.md', '.pdf', '.doc', '.docx',
            '.html', '.htm', '.json', '.csv',
            '.xlsx', '.xls', '.pptx', '.ppt'
        }
    
    def validate_file(self, filename: str, max_size_mb: int = 50) -> tuple[bool, Optional[str]]:
        """
        验证文件
        
        Args:
            filename: 文件名
            max_size_mb: 最大文件大小（MB）
            
        Returns:
            (是否有效, 错误信息)
        """
        if not filename:
            return False, "文件名不能为空"
        
        # 检查扩展名
        ext = Path(filename).suffix.lower()
        if ext not in self.supported_extensions:
            return False, f"不支持的文件格式: {ext}。支持的格式: {', '.join(self.supported_extensions)}"
        
        return True, None
    
    async def parse_document(
        self,
        content: bytes,
        filename: str
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        解析文档，提取文本
        
        Args:
            content: 文件内容（字节）
            filename: 文件名
            
        Returns:
            (是否成功, 提取的文本, 错误信息)
        """
        try:
            from app.utils.document_parsers import DocumentParserFactory
            
            # 初始化解析器（如果尚未初始化）
            if not hasattr(DocumentParserFactory, '_initialized'):
                DocumentParserFactory.initialize_default_parsers()
                DocumentParserFactory._initialized = True
            
            # 使用文档解析器解析文件
            parse_result = await DocumentParserFactory.parse_document(
                content, 
                filename
            )
            
            if not parse_result.success:
                return False, None, parse_result.error_message
            
            # 记录解析信息
            logger.info(f"文档解析成功: {filename}")
            logger.info(f"解析器: {parse_result.metadata.get('parser_name', 'unknown')}")
            logger.info(f"文本长度: {len(parse_result.text)}")
            
            return True, parse_result.text, None
            
        except Exception as e:
            error_msg = f"文档解析失败: {str(e)}"
            logger.error(f"{error_msg} - 文件: {filename}")
            return False, None, error_msg
    
    async def upload_and_process_async(
        self,
        content: bytes,
        filename: str,
        kb_settings: Dict[str, Any],
        session_id: Optional[str],
        user_id: str,
        priority: str = "NORMAL",
        timeout: float = 600.0,
        max_retries: int = 3
    ) -> DocumentUploadResult:
        """
        上传并异步处理文档
        
        Args:
            content: 文件内容
            filename: 文件名
            kb_settings: 知识库配置
            session_id: 会话ID
            user_id: 用户ID
            priority: 任务优先级 (LOW/NORMAL/HIGH)
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            
        Returns:
            DocumentUploadResult 对象
        """
        # 1. 验证文件
        is_valid, error_msg = self.validate_file(filename)
        if not is_valid:
            return DocumentUploadResult(
                success=False,
                error=error_msg
            )
        
        # 2. 解析文档
        success, text, error_msg = await self.parse_document(content, filename)
        if not success:
            return DocumentUploadResult(
                success=False,
                error=error_msg
            )
        
        # 3. 创建文档记录
        try:
            from app.database import get_database
            from app.config import settings
            from app.services.knowledge_base_service import KnowledgeBaseService
            
            # 获取数据库连接
            db = await get_database()
            kb_service = KnowledgeBaseService(db[settings.mongodb_db_name])
            
            # 从kb_settings中获取必要信息
            collection_name = kb_settings.get('collection_name')
            user_id_from_settings = kb_settings.get('user_id', user_id)
            
            if collection_name and user_id_from_settings:
                # 根据collection_name查找真正的知识库ID
                kb_list = await kb_service.get_knowledge_bases(user_id_from_settings)
                kb_record = None
                for kb in kb_list:
                    if kb.collection_name == collection_name:
                        kb_record = kb
                        break
                
                if not kb_record:
                    logger.warning(f"未找到集合名为 '{collection_name}' 的知识库")
                    return None
                
                kb_id = str(kb_record.id)
                # 计算文件大小
                file_size = len(content)
                file_type = filename.split('.')[-1] if '.' in filename else 'txt'
                
                # 创建文档记录
                doc_response = await kb_service.create_document(
                    kb_id=kb_id,
                    user_id=user_id_from_settings,
                    filename=filename,
                    file_size=file_size,
                    file_type=file_type,
                    metadata={"text_length": len(text)}
                )
                
                logger.info(f"已创建文档记录: {filename}, ID: {doc_response.id}")
                
                # 将文档ID添加到kb_settings中
                kb_settings['document_id'] = str(doc_response.id)
                
        except Exception as e:
            logger.warning(f"创建文档记录失败: {str(e)}")
            # 不影响主要处理流程
        
        # 4. 提交到任务队列
        try:
            from app.utils.embedding.task_queue import (
                get_task_queue, 
                EmbeddingTask, 
                TaskPriority
            )
            
            # 创建嵌入任务
            task_data = EmbeddingTask(
                text=text,
                filename=filename,
                kb_settings=kb_settings,
                session_id=session_id,
                user_id=user_id
            )
            
            # 映射优先级
            priority_map = {
                "LOW": TaskPriority.LOW,
                "NORMAL": TaskPriority.NORMAL,
                "HIGH": TaskPriority.HIGH
            }
            task_priority = priority_map.get(priority.upper(), TaskPriority.NORMAL)
            
            # 提交任务
            task_queue = await get_task_queue()
            task_id = await task_queue.submit_task(
                task_type="embedding",
                task_data=task_data,
                priority=task_priority,
                timeout=timeout,
                max_retries=max_retries,
                metadata={
                    "user_id": user_id,
                    "session_id": session_id,
                    "filename": filename,
                    "submitted_at": datetime.utcnow().isoformat()
                }
            )
            
            return DocumentUploadResult(
                success=True,
                task_id=task_id,
                message="文档正在后台处理中，请使用task_id查询进度",
                metadata={
                    "filename": filename,
                    "text_length": len(text),
                    "kb_collection": kb_settings.get("collection_name")
                }
            )
            
        except Exception as e:
            error_msg = f"提交处理任务失败: {str(e)}"
            logger.error(error_msg)
            return DocumentUploadResult(
                success=False,
                error=error_msg
            )
    
    async def update_session_kb_config(
        self,
        db,
        session_id: str,
        user_id: str,
        kb_settings: Dict[str, Any],
        kb_parsed: bool = False
    ) -> tuple[bool, Optional[str]]:
        """
        更新会话的知识库配置
        
        Args:
            db: 数据库连接
            session_id: 会话ID
            user_id: 用户ID
            kb_settings: 知识库配置
            kb_parsed: 是否已解析
            
        Returns:
            (是否成功, 错误信息)
        """
        try:
            from app.config import settings
            
            update_data = {"kb_settings": kb_settings}
            if kb_parsed:
                update_data["kb_parsed"] = True
            
            result = await db[settings.mongodb_db_name].chat_sessions.update_one(
                {"_id": session_id, "user_id": user_id},
                {"$set": update_data}
            )
            
            if result.matched_count == 0:
                return False, "未找到会话或无权限"
            
            return True, None
            
        except Exception as e:
            error_msg = f"更新会话配置失败: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def get_supported_formats(self) -> List[str]:
        """获取支持的文件格式列表"""
        return sorted(list(self.supported_extensions))


# 全局单例
_document_upload_service: Optional[DocumentUploadService] = None


def get_document_upload_service() -> DocumentUploadService:
    """获取文档上传服务单例"""
    global _document_upload_service
    if _document_upload_service is None:
        _document_upload_service = DocumentUploadService()
    return _document_upload_service

