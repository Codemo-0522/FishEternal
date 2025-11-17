"""
知识库检索工具

从会话关联的知识库中检索相关文档片段
这是 FishChat 的核心 RAG 工具
"""
from typing import Dict, Any, List, Tuple, Optional
import json
import logging
from ..base import BaseTool, ToolMetadata, ToolContext, ToolExecutionError
from ...config import settings

logger = logging.getLogger(__name__)


# 🆕 全局序号管理器（按会话管理，确保跨工具调用的序号连续且唯一）
class GlobalReferenceMarkerManager:
    """全局引用序号管理器（按会话隔离）"""
    _instance = None
    _session_markers: Dict[str, int] = {}  # session_id -> 当前序号
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_next_marker(self, session_id: str) -> int:
        """获取下一个全局序号（从1开始递增）"""
        if session_id not in self._session_markers:
            self._session_markers[session_id] = 0
        self._session_markers[session_id] += 1
        return self._session_markers[session_id]
    
    def reset_session(self, session_id: str):
        """重置会话的序号计数器（新一轮对话开始时调用）"""
        self._session_markers[session_id] = 0
        logger.info(f"🔄 已重置会话 {session_id} 的全局引用序号")
    
    def get_current_marker(self, session_id: str) -> int:
        """获取当前会话的序号（不递增）"""
        return self._session_markers.get(session_id, 0)


# 全局单例
_marker_manager = GlobalReferenceMarkerManager()


class KnowledgeRetrievalTool(BaseTool):
    """知识库检索工具"""
    
    def get_metadata(self, context: Optional[ToolContext] = None) -> Optional[ToolMetadata]:
        """
        获取工具元数据（动态生成参数）
        
        Args:
            context: 包含 kb_settings 的上下文（从 context.extra 中获取）
        
        Returns:
            ToolMetadata: 工具元数据，参数根据会话配置动态生成
            None: 如果知识库未启用，返回 None（工具不会出现在列表中）
        """
        # 从 context.extra 中获取 kb_settings（如果存在）
        kb_settings = None
        if context and context.extra:
            kb_settings = context.extra.get("kb_settings")
        
        # 如果没有知识库配置或知识库未启用，返回 None（不显示该工具）
        if not kb_settings or not kb_settings.get("enabled"):
            logger.info(f"🚫 知识库工具不可用 - kb_settings存在: {kb_settings is not None}, enabled: {kb_settings.get('enabled') if kb_settings else 'N/A'}")
            return None
        
        # 基础 schema（只包含 query，模型只能控制查询词）
        base_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询，描述需要查找的内容"
                }
            },
            "required": ["query"]
        }
        
        # 构建描述信息（显示当前配置）
        top_k = kb_settings.get("top_k", 3)
        similarity_threshold = kb_settings.get("similarity_threshold", 10)
        
        description_parts = ["""
            "从知识库中检索相关文档片段。",
            "\n\n🌍 多语言检索策略：",
            "\n当搜索技术文档、编程概念、项目配置、API文档等专业内容时，必须同时使用多语言并行检索以提高准确性：",
            "\n- 语言优先级：中文 → 英文 → 其他语言",
            "\n- 技术术语（高并发、数据库优化等）必须中英文并行搜索",
            "\n- 包含同义词和相关概念（如"并发"与"异步"）",
            "\n- 所有并行检索必须在同一轮次调用",
            "\n\n示例：",
            "\n- 用户问"高并发、线程阻塞" → 并行调用:",
            "\n  1. search_knowledge_base(query=\"高并发 线程阻塞 性能优化\")",
            "\n  2. search_knowledge_base(query=\"concurrency thread blocking performance\")",
            "\n  3. search_knowledge_base(query=\"并发编程 异步处理 多线程\")",
            "\n\n仅日常对话（如"你好"、"天气"）可单语言检索。"
            """
        ]
        
        return ToolMetadata(
            name="search_knowledge_base",
            description="".join(description_parts),
            input_schema=base_schema
        )
    
    async def execute(self, arguments: Dict[str, Any], context: ToolContext) -> str:
        """
        执行知识库检索
        
        Args:
            arguments: {"query": str}（只接受查询词，其他参数从 kb_settings 读取）
            context: 必须包含 session_id 和 db
        
        Returns:
            str: JSON 格式的检索结果
        """
        # 验证上下文
        if not context.session_id:
            raise ToolExecutionError("search_knowledge_base", "缺少 session_id")
        if not context.db:
            raise ToolExecutionError("search_knowledge_base", "缺少数据库连接")
        
        query = arguments.get("query", "")
        
        if not query.strip():
            return json.dumps({"success": False, "error": "查询内容不能为空"}, ensure_ascii=False)
        
        try:
            # 获取会话的知识库配置
            db_name = context.extra.get("db_name", settings.mongodb_db_name)
            session_data = await context.db[db_name].chat_sessions.find_one(
                {"_id": context.session_id}
            )
            
            if not session_data:
                return json.dumps({
                    "success": False,
                    "error": "会话不存在",
                    "results": []
                }, ensure_ascii=False)
            
            kb_settings = session_data.get("kb_settings")
            
            # 检查知识库是否启用
            if not kb_settings or not kb_settings.get("enabled"):
                return json.dumps({
                    "success": False,
                    "error": "当前会话未启用知识库功能",
                    "results": []
                }, ensure_ascii=False)
            
            # 从 kb_settings 中读取参数（由用户配置，模型不能修改）
            top_k = kb_settings.get("top_k", 3)
            top_k = max(1, min(12, top_k))  # 限制范围
            
            logger.info(f"📋 使用用户配置: top_k={top_k}, similarity_threshold={kb_settings.get('similarity_threshold', 10)}")
            
            # 🆕 根据 kb_ids 加载知识库配置并检索
            kb_ids = kb_settings.get("kb_ids", [])
            if not kb_ids:
                logger.warning("kb_ids 为空，跳过检索")
                return json.dumps({
                    "success": True,
                    "message": "未配置知识库",
                    "results": []
                }, ensure_ascii=False)
            
            # 判断单库还是多库检索
            from ...services.knowledge_base_service import KnowledgeBaseService
            kb_service = KnowledgeBaseService(context.db[db_name])
            
            if len(kb_ids) == 1:
                # 单知识库检索
                kb = await kb_service.get_knowledge_base(kb_ids[0], context.user_id)
                if not kb:
                    logger.warning(f"知识库不存在: {kb_ids[0]}")
                    return json.dumps({
                        "success": False,
                        "error": f"知识库 {kb_ids[0]} 不存在或无权限",
                        "results": []
                    }, ensure_ascii=False)
                
                # 使用知识库自己的配置构建vectorstore
                vectorstore = await self._build_vectorstore(kb.kb_settings)
                retriever = await self._create_retriever(vectorstore, kb.kb_settings, top_k)
                
                # 执行检索（异步调用）
                search_results = await retriever.search(query, top_k=top_k)
            else:
                # 多知识库并行检索
                from ...services.multi_kb_retriever import get_multi_kb_retriever
                
                kb_configs = []
                for kb_id in kb_ids:
                    kb = await kb_service.get_knowledge_base(kb_id, context.user_id)
                    if kb:
                        kb_configs.append({
                            'kb_id': kb_id,
                            'kb_name': kb.name,
                            'kb_settings': kb.kb_settings
                        })
                
                if not kb_configs:
                    logger.warning("所有知识库都不存在或无权限")
                    return json.dumps({
                        "success": False,
                        "error": "所有知识库都不存在或无权限",
                        "results": []
                    }, ensure_ascii=False)
                
                # 使用多知识库检索器
                retriever_multi = await get_multi_kb_retriever()
                top_k_per_kb = kb_settings.get("top_k_per_kb", 3)
                final_top_k = kb_settings.get("final_top_k", 10)
                merge_strategy = kb_settings.get("merge_strategy", "weighted_score")
                similarity_threshold = kb_settings.get("similarity_threshold", 10)
                
                multi_results = await retriever_multi.retrieve_from_multiple_kbs(
                    query=query,
                    kb_configs=kb_configs,
                    top_k_per_kb=top_k_per_kb,
                    similarity_threshold=similarity_threshold,
                    merge_strategy=merge_strategy,
                    final_top_k=final_top_k
                )
                
                # 将多库结果转换为统一格式
                search_results = [(type('Doc', (), {
                    'page_content': r.content, 
                    'metadata': {
                        'source': r.kb_name, 
                        'chunk_id': r.chunk_id or '', 
                        'chunk_index': r.metadata.get('chunk_index', 0), 
                        'document_id': r.doc_id or '',
                        # 🆕 添加查看原文所需的字段
                        'doc_id': r.metadata.get('doc_id', r.doc_id or ''),
                        'kb_id': r.metadata.get('kb_id', ''),
                        'filename': r.metadata.get('filename', '')
                    }
                })(), r.distance) for r in multi_results]
            
            if not search_results:
                return json.dumps({
                    "success": True,
                    "message": "未找到相关文档片段",
                    "results": []
                }, ensure_ascii=False)
            
            # 🆕 收集需要查询的doc_id，用于批量查询filename
            from bson import ObjectId
            doc_ids_to_query = set()
            for doc, score in search_results:
                doc_id = doc.metadata.get("doc_id")
                filename = doc.metadata.get("filename")
                # 如果filename为空且doc_id存在，记录需要查询
                if doc_id and not filename:
                    doc_ids_to_query.add(doc_id)
            
            # 🆕 批量查询filename
            filename_map = {}
            if doc_ids_to_query:
                try:
                    doc_ids_obj = [ObjectId(doc_id) for doc_id in doc_ids_to_query if ObjectId.is_valid(doc_id)]
                    if doc_ids_obj:
                        cursor = context.db[db_name].kb_documents.find(
                            {"_id": {"$in": doc_ids_obj}},
                            {"_id": 1, "filename": 1}
                        )
                        async for doc_record in cursor:
                            filename_map[str(doc_record["_id"])] = doc_record.get("filename", "")
                        logger.info(f"📝 从数据库补充了 {len(filename_map)} 个文档的filename")
                except Exception as e:
                    logger.warning(f"⚠️ 批量查询filename失败: {e}")
            
            # 🆕 格式化结果并分配全局序号
            formatted_results = []
            for idx, (doc, score) in enumerate(search_results, 1):
                # 分配全局唯一序号（跨多次调用递增）
                global_marker = _marker_manager.get_next_marker(context.session_id)
                
                # 🆕 如果metadata中filename为空，尝试从数据库查询结果中获取
                doc_id = doc.metadata.get("doc_id", "")
                filename = doc.metadata.get("filename") or filename_map.get(doc_id, "")
                
                formatted_results.append({
                    "index": idx,  # 保留原始索引（向后兼容）
                    "ref_marker": global_marker,  # 🆕 全局序号（用于##数字$$引用）
                    "content": doc.page_content,
                    "score": float(score),
                    "metadata": {
                        "source": doc.metadata.get("source", "Unknown"),
                        "chunk_index": doc.metadata.get("chunk_index", 0),
                        "chunk_id": doc.metadata.get("chunk_id", ""),  # 🎯 添加 chunk_id 用于引用
                        "document_id": doc.metadata.get("document_id", ""),
                        # 🆕 添加查看原文所需的字段
                        "doc_id": doc_id,
                        "kb_id": doc.metadata.get("kb_id", ""),
                        "filename": filename
                    }
                })
                
                logger.info(f"📌 分配全局序号 ##{ global_marker}$$: chunk_id={doc.metadata.get('chunk_id', '(空)')}, source={doc.metadata.get('source', 'Unknown')}")
            
            result = {
                "success": True,
                "query": query,
                "total": len(formatted_results),
                "results": formatted_results
            }
            
            logger.info(f"✅ 知识库检索成功: query='{query}', found={len(formatted_results)} chunks")
            
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        except Exception as e:
            logger.error(f"❌ 知识库检索失败: {e}", exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"检索失败: {str(e)}",
                "results": []
            }, ensure_ascii=False)
    
    async def _build_vectorstore(self, kb_settings: dict):
        """构建向量存储（使用全局单例管理器）"""
        # 延迟导入避免启动时加载
        from ...routers.kb import _get_kb_components
        
        _, vectorstore, _ = _get_kb_components(kb_settings)
        return vectorstore
    
    async def _create_retriever(self, vectorstore, kb_settings: dict, top_k: int):
        """创建检索器"""
        from ...utils.embedding.pipeline import Retriever
        
        # 从配置中获取相似度阈值
        similarity_threshold = kb_settings.get("similarity_threshold", 10) if isinstance(kb_settings, dict) else 10
        
        return Retriever(
            vector_store=vectorstore,
            top_k=top_k,
            similarity_threshold=similarity_threshold
        )

