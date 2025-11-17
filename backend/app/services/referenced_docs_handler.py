"""
引用文档智能处理器

根据文档大小自动选择最佳策略：
1. 小文档 (< 8000 tokens): 直接全文注入到用户消息
2. 大文档 (>= 8000 tokens): 使用 RAG 检索相关片段
"""
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import tiktoken

logger = logging.getLogger(__name__)

# Token 阈值配置
SMALL_DOC_TOKEN_THRESHOLD = 8000  # 小于此值直接全文注入
MAX_TOTAL_TOKENS = 32000  # 所有引用文档总 token 上限


def clean_referenced_content(text: str) -> str:
    """
    清洗文本中的引用文档注入内容（移除 <referenced_documents>...</referenced_documents> 标签及其内容）
    
    Args:
        text: 包含引用文档注入的文本
    
    Returns:
        清洗后的文本（移除了所有引用文档注入内容）
    """
    # 移除 <referenced_documents>...</referenced_documents> 及其内部所有内容
    # 使用 DOTALL 标志让 . 匹配换行符
    cleaned = re.sub(
        r'<referenced_documents>.*?</referenced_documents>\s*',
        '',
        text,
        flags=re.DOTALL
    )
    return cleaned.strip()


class ReferencedDocsHandler:
    """引用文档智能处理器"""
    
    def __init__(self, db: AsyncIOMotorClient, db_name: str):
        self.db = db
        self.db_name = db_name
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")  # GPT-4 编码
        except Exception as e:
            logger.warning(f"tiktoken初始化失败: {e}，使用简单估算")
            self.tokenizer = None
    
    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数量"""
        if self.tokenizer:
            try:
                return len(self.tokenizer.encode(text))
            except:
                pass
        # 简单估算：中文约 1.5 字符/token，英文约 4 字符/token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)
    
    async def get_document_content(self, doc_id: str, user_id: str) -> Optional[str]:
        """
        获取文档的完整文本内容
        
        流程：
        1. 从 MongoDB 查询文档记录，获取 file_url (MinIO路径)
        2. 从 MinIO 下载原始文件
        3. 解析文件提取文本内容
        """
        try:
            from ..utils.minio_client import minio_client
            from app.utils.document_parsers import DocumentParserFactory
            
            # 将字符串 doc_id 转换为 ObjectId
            try:
                doc_object_id = ObjectId(doc_id)
            except Exception as e:
                logger.error(f"无效的 doc_id 格式: {doc_id}, 错误: {e}")
                return None
            
            # 从 knowledge_base_documents 集合中获取文档记录
            doc = await self.db[self.db_name].kb_documents.find_one({
                "_id": doc_object_id
            })
            
            if not doc:
                logger.warning(f"文档不存在: doc_id={doc_id}")
                return None
            
            # 获取 MinIO 文件路径
            file_url = doc.get("file_url")
            if not file_url:
                logger.warning(f"文档没有关联的文件: doc_id={doc_id}")
                return None
            
            # 从 MinIO 下载文档
            logger.info(f"从 MinIO 下载文档: {file_url}")
            file_content = minio_client.download_kb_document(file_url)
            
            # 解析文档内容（提取文本）
            if not hasattr(DocumentParserFactory, '_initialized'):
                DocumentParserFactory.initialize_default_parsers()
                DocumentParserFactory._initialized = True
            
            filename = doc.get("filename", "unknown.txt")
            parse_result = await DocumentParserFactory.parse_document(
                file_content,
                filename
            )
            
            if not parse_result.success:
                logger.error(f"文档解析失败: {parse_result.error_message}")
                return None
            
            logger.info(f"✅ 成功获取文档内容: {filename}, 长度: {len(parse_result.text)} 字符")
            return parse_result.text
        
        except Exception as e:
            logger.error(f"获取文档内容失败: {e}", exc_info=True)
            return None
    
    async def process_referenced_docs(
        self,
        referenced_docs: List[Dict[str, Any]],
        user_id: str,
        query: Optional[str] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """
        智能处理引用文档
        
        策略：
        1. 小文档 (< 8000 tokens): 直接全文注入到用户消息
        2. 大文档 (>= 8000 tokens): 提示用户文档太大，建议使用知识库问答
        
        Args:
            referenced_docs: 引用文档列表 [{"doc_id": "xxx", "filename": "xxx"}]
            user_id: 用户 ID
            query: 用户问题（用于 RAG 检索）
        
        Returns:
            (user_message_content, system_prompt_addition):
                - user_message_content: 注入到用户消息的内容（@文档）
                - system_prompt_addition: 注入到系统提示词的内容（@知识库）
        """
        if not referenced_docs:
            return None, None
        
        logger.info(f"📄 开始处理 {len(referenced_docs)} 个引用文档")
        
        small_docs = []  # 小文档：直接注入
        large_docs = []  # 大文档：提示信息
        total_tokens = 0
        kb_mentioned = False  # 标记是否@了知识库
        
        for doc_info in referenced_docs:
            doc_id = doc_info.get("doc_id")
            filename = doc_info.get("filename", "未知文档")
            
            # 🆕 特殊处理：@知识库标记
            if filename == "知识库" and doc_id == "knowledge-base":
                kb_mentioned = True
                logger.info(f"📚 检测到 @知识库 标记，将注入知识库提示词")
                continue
            
            # 获取文档内容
            content = await self.get_document_content(doc_id, user_id)
            if not content:
                logger.warning(f"跳过无内容的文档: {filename}")
                continue
            
            # 计算 token 数
            token_count = self.count_tokens(content)
            logger.info(f"📊 文档 '{filename}' 的 token 数: {token_count}")
            
            # 判断策略
            if token_count < SMALL_DOC_TOKEN_THRESHOLD and (total_tokens + token_count) < MAX_TOTAL_TOKENS:
                # 小文档：直接注入
                small_docs.append({
                    "filename": filename,
                    "content": content,
                    "tokens": token_count
                })
                total_tokens += token_count
                logger.info(f"✅ '{filename}' 归类为小文档，将直接注入 (tokens: {token_count})")
            else:
                # 大文档：记录信息，稍后提示
                large_docs.append({
                    "filename": filename,
                    "tokens": token_count
                })
                logger.info(f"⚠️ '{filename}' 归类为大文档，无法直接注入 (tokens: {token_count})")
        
        # 🆕 分离系统提示词和用户文档内容
        system_prompt_addition = None
        user_message_parts = []
        
        # 🆕 如果用户@了知识库，生成系统提示词（注入到 system prompt）
        if kb_mentioned:
            system_prompt_addition = (
                "\n\n【知识库模式】\n"
                "用户希望使用知识库中的信息回答问题。请优先基于知识库检索到的内容进行回答。"
            )
            logger.info(f"📚 生成知识库系统提示词，长度: {len(system_prompt_addition)}")
        
        # 添加小文档的完整内容（每个文档用单独的 XML 标签）
        if small_docs:
            for doc in small_docs:
                user_message_parts.append(
                    f"<document filename=\"{doc['filename']}\" tokens=\"{doc['tokens']}\">\n"
                    f"{doc['content']}\n"
                    f"</document>\n\n"
                )
        
        # 添加大文档的提示
        if large_docs:
            user_message_parts.append("<large_documents>\n")
            for doc in large_docs:
                user_message_parts.append(
                    f"<large_doc filename=\"{doc['filename']}\" tokens=\"{doc['tokens']}\">\n"
                    f"此文档因内容过多无法完整加载（约 {doc['tokens']} tokens，超过阈值）。\n"
                    f"建议：请建议用户在知识库中检索此文档的相关内容，或缩小问题范围。\n"
                    f"</large_doc>\n"
                )
            user_message_parts.append("</large_documents>\n\n")
        
        # 构建用户消息注入内容
        user_message_content = None
        if user_message_parts:
            # 用最外层的 XML 标签包裹所有引用文档内容
            user_message_content = (
                "<referenced_documents>\n"
                + ''.join(user_message_parts) +
                "</referenced_documents>"
            )
        
        logger.info(f"✅ 处理完成 - 小文档: {len(small_docs)} (总 {total_tokens} tokens), 大文档: {len(large_docs)}")
        if system_prompt_addition:
            logger.info(f"✅ 生成系统提示词注入内容")
        if user_message_content:
            logger.info(f"✅ 生成用户消息注入内容")
        
        return user_message_content, system_prompt_addition

