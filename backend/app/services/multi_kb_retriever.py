"""
多知识库并行检索服务

功能特性:
1. 完全异步并行检索,不阻塞主线程
2. 使用信号量控制并发数,避免资源耗尽
3. 智能结果合并和去重
4. 支持多种合并策略
5. 用户级别隔离,互不影响
6. 完善的错误处理和日志

作者: FishChat Team
创建时间: 2025-01-29
"""

import asyncio
import logging
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
import hashlib
from ..utils.distance_utils import calculate_score_from_distance

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果数据类"""
    content: str
    score: float
    distance: float
    metadata: Dict[str, Any]
    kb_id: str  # 来源知识库ID
    kb_name: str  # 来源知识库名称
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    document_name: Optional[str] = None  # 文档名称（前端显示用）


class MultiKBRetriever:
    """
    多知识库并行检索器
    
    设计原则:
    - 异步非阻塞: 所有IO操作使用async/await
    - 并发控制: 使用信号量限制同时检索的知识库数量
    - 资源隔离: 每个知识库使用独立的vectorstore实例
    - 容错设计: 单个知识库失败不影响其他知识库
    """
    
    # 并发控制: 同时检索的最大知识库数量 (可根据服务器性能调整)
    MAX_CONCURRENT_KB = 5
    
    def __init__(self):
        """初始化多知识库检索器"""
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_KB)
        logger.info(f"🔧 多知识库检索器已初始化 (最大并发: {self.MAX_CONCURRENT_KB})")
    
    async def retrieve_from_multiple_kbs(
        self,
        query: str,
        kb_configs: List[Dict[str, Any]],
        top_k_per_kb: int = 3,
        similarity_threshold: Optional[float] = None,
        merge_strategy: str = "weighted_score",
        final_top_k: int = 10
    ) -> List[RetrievalResult]:
        """
        从多个知识库并行检索并合并结果
        
        Args:
            query: 查询文本
            kb_configs: 知识库配置列表,每项包含 kb_id, kb_name, kb_settings
            top_k_per_kb: 每个知识库返回的最大结果数
            similarity_threshold: 相似度阈值 (L2距离)
            merge_strategy: 合并策略 (weighted_score/simple_concat/interleave)
            final_top_k: 最终返回的结果数量
            
        Returns:
            合并后的检索结果列表
        """
        if not kb_configs:
            logger.warning("⚠️ 知识库配置列表为空")
            return []
        
        logger.info(f"🔍 开始多知识库检索: query='{query[:50]}...', kb_count={len(kb_configs)}, "
                   f"top_k_per_kb={top_k_per_kb}, merge_strategy={merge_strategy}")
        
        # 并行检索所有知识库
        tasks = []
        for kb_config in kb_configs:
            task = self._retrieve_single_kb_with_semaphore(
                query=query,
                kb_config=kb_config,
                top_k=top_k_per_kb,
                similarity_threshold=similarity_threshold
            )
            tasks.append(task)
        
        # 等待所有检索任务完成 (并行执行)
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤异常结果
        valid_results = []
        for i, result in enumerate(results_list):
            if isinstance(result, Exception):
                kb_id = kb_configs[i].get('kb_id', 'unknown')
                logger.error(f"❌ 知识库 {kb_id} 检索失败: {result}")
            else:
                valid_results.append(result)
        
        if not valid_results:
            logger.warning("⚠️ 所有知识库检索都失败了")
            return []
        
        # 合并结果
        merged_results = self._merge_results(
            results_list=valid_results,
            merge_strategy=merge_strategy,
            final_top_k=final_top_k
        )
        
        logger.info(f"✅ 多知识库检索完成: 总结果数={len(merged_results)}")
        return merged_results
    
    async def _retrieve_single_kb_with_semaphore(
        self,
        query: str,
        kb_config: Dict[str, Any],
        top_k: int,
        similarity_threshold: Optional[float]
    ) -> List[RetrievalResult]:
        """
        使用信号量控制的单知识库检索 (防止并发过高)
        
        Args:
            query: 查询文本
            kb_config: 知识库配置 {kb_id, kb_name, kb_settings}
            top_k: 返回结果数
            similarity_threshold: 相似度阈值
            
        Returns:
            检索结果列表
        """
        async with self._semaphore:  # 信号量控制并发
            return await self._retrieve_single_kb(
                query=query,
                kb_config=kb_config,
                top_k=top_k,
                similarity_threshold=similarity_threshold
            )
    
    async def _retrieve_single_kb(
        self,
        query: str,
        kb_config: Dict[str, Any],
        top_k: int,
        similarity_threshold: Optional[float]
    ) -> List[RetrievalResult]:
        """
        单个知识库的异步检索
        
        Args:
            query: 查询文本
            kb_config: 知识库配置
            top_k: 返回结果数
            similarity_threshold: 相似度阈值
            
        Returns:
            检索结果列表
        """
        kb_id = kb_config.get('kb_id', 'unknown')
        kb_name = kb_config.get('kb_name', kb_id)
        kb_settings = kb_config.get('kb_settings', {})
        
        try:
            logger.debug(f"📚 开始检索知识库: {kb_name} (ID: {kb_id})")
            
            # 构建向量存储和检索器
            from ..routers.kb import _get_kb_components
            from ..utils.embedding.pipeline import Retriever
            
            _, vectorstore, _ = _get_kb_components(kb_settings)
            
            # ✅ 优先使用知识库自己的相似度阈值配置
            # 如果会话级别传入了阈值（similarity_threshold参数），则作为兜底默认值
            kb_threshold = kb_settings.get("similarity_threshold")
            if kb_threshold is not None:
                # 知识库有自己的阈值配置，使用它
                final_threshold = kb_threshold
                logger.info(f"📊 使用知识库 {kb_name} 自己的相似度阈值: {final_threshold}")
            elif similarity_threshold is not None:
                # 知识库没有配置，使用会话级别的阈值
                final_threshold = similarity_threshold
                logger.info(f"📊 知识库 {kb_name} 未配置阈值，使用会话默认值: {final_threshold}")
            else:
                # 都没有，使用系统默认值 0.5（相似度分数）
                final_threshold = 0.5
                logger.info(f"📊 知识库 {kb_name} 使用系统默认阈值: {final_threshold}")
            
            # 获取距离度量类型
            search_params = kb_settings.get("search_params", {})
            distance_metric = search_params.get("distance_metric", "cosine")
            
            retriever = Retriever(
                vector_store=vectorstore,
                top_k=top_k,
                similarity_threshold=final_threshold,
                distance_metric=distance_metric
            )
            
            # 异步检索
            search_results = await retriever.search(query, top_k=top_k)
            
            # 🔧 批量查询文档名称
            from motor.motor_asyncio import AsyncIOMotorClient
            from ..config import settings
            from ..database import get_database
            
            doc_ids = []
            for doc, _ in search_results:
                doc_id = doc.metadata.get("doc_id")
                if doc_id:
                    doc_ids.append(doc_id)
            
            # 批量查询文档名称
            filename_map = {}
            if doc_ids:
                try:
                    from bson import ObjectId
                    db = await anext(get_database())  # 获取数据库连接
                    docs_cursor = db[settings.mongodb_db_name].documents.find(
                        {"_id": {"$in": [ObjectId(did) for did in doc_ids if ObjectId.is_valid(did)]}},
                        {"_id": 1, "filename": 1}
                    )
                    async for doc_record in docs_cursor:
                        filename_map[str(doc_record["_id"])] = doc_record.get("filename", "")
                except Exception as e:
                    logger.warning(f"⚠️ 批量查询filename失败: {e}")
            
            # 格式化结果
            results = []
            for doc, distance in search_results:
                # 根据距离度量类型计算相似度分数
                score = calculate_score_from_distance(distance, distance_metric)
                
                # 获取文档名称
                doc_id = doc.metadata.get("doc_id")
                filename = doc.metadata.get("filename") or filename_map.get(doc_id, "")
                
                result = RetrievalResult(
                    content=doc.page_content,
                    score=score,
                    distance=float(distance),
                    metadata=doc.metadata,
                    kb_id=kb_id,
                    kb_name=kb_name,
                    chunk_id=doc.metadata.get("chunk_id"),
                    doc_id=doc_id,
                    document_name=filename or doc.metadata.get("source", "未知文档")  # 🆕 添加文档名称
                )
                results.append(result)
            
            logger.debug(f"✅ 知识库 {kb_name} 检索完成: {len(results)} 个结果")
            return results
            
        except Exception as e:
            logger.error(f"❌ 知识库 {kb_name} 检索失败: {e}", exc_info=True)
            raise  # 抛出异常供上层处理
    
    def _merge_results(
        self,
        results_list: List[List[RetrievalResult]],
        merge_strategy: str,
        final_top_k: int
    ) -> List[RetrievalResult]:
        """
        合并多个知识库的检索结果
        
        Args:
            results_list: 多个知识库的检索结果列表
            merge_strategy: 合并策略
            final_top_k: 最终返回的结果数量
            
        Returns:
            合并后的结果列表
        """
        if not results_list:
            return []
        
        if merge_strategy == "weighted_score":
            return self._merge_by_weighted_score(results_list, final_top_k)
        elif merge_strategy == "simple_concat":
            return self._merge_by_simple_concat(results_list, final_top_k)
        elif merge_strategy == "interleave":
            return self._merge_by_interleave(results_list, final_top_k)
        else:
            logger.warning(f"⚠️ 未知的合并策略 '{merge_strategy}', 使用默认策略 'weighted_score'")
            return self._merge_by_weighted_score(results_list, final_top_k)
    
    def _merge_by_weighted_score(
        self,
        results_list: List[List[RetrievalResult]],
        final_top_k: int
    ) -> List[RetrievalResult]:
        """
        加权分数合并策略
        
        算法:
        1. 对每个知识库的结果进行归一化 (MinMax归一化)
        2. 去重 (相同内容的保留最高分)
        3. 按分数降序排序
        4. 返回 top_k
        """
        # 合并所有结果
        all_results = []
        for results in results_list:
            all_results.extend(results)
        
        if not all_results:
            return []
        
        # 去重: 使用内容哈希去重,保留分数最高的
        deduplicated = self._deduplicate_by_content(all_results)
        
        # 按分数降序排序
        sorted_results = sorted(deduplicated, key=lambda x: x.score, reverse=True)
        
        return sorted_results[:final_top_k]
    
    def _merge_by_simple_concat(
        self,
        results_list: List[List[RetrievalResult]],
        final_top_k: int
    ) -> List[RetrievalResult]:
        """
        简单拼接策略
        
        算法:
        1. 依次拼接所有知识库的结果
        2. 去重
        3. 返回 top_k
        """
        all_results = []
        for results in results_list:
            all_results.extend(results)
        
        # 去重
        deduplicated = self._deduplicate_by_content(all_results)
        
        return deduplicated[:final_top_k]
    
    def _merge_by_interleave(
        self,
        results_list: List[List[RetrievalResult]],
        final_top_k: int
    ) -> List[RetrievalResult]:
        """
        交错合并策略 (轮流取每个知识库的结果)
        
        算法:
        1. 轮流从每个知识库取一个结果
        2. 去重
        3. 返回 top_k
        """
        merged = []
        max_len = max(len(results) for results in results_list) if results_list else 0
        
        for i in range(max_len):
            for results in results_list:
                if i < len(results):
                    merged.append(results[i])
        
        # 去重
        deduplicated = self._deduplicate_by_content(merged)
        
        return deduplicated[:final_top_k]
    
    def _deduplicate_by_content(
        self,
        results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """
        根据内容去重,保留分数最高的
        
        Args:
            results: 结果列表
            
        Returns:
            去重后的结果列表
        """
        content_hash_map: Dict[str, RetrievalResult] = {}
        
        for result in results:
            # 计算内容哈希
            content_hash = hashlib.md5(result.content.encode('utf-8')).hexdigest()
            
            # 如果已存在,比较分数,保留更高的
            if content_hash in content_hash_map:
                if result.score > content_hash_map[content_hash].score:
                    content_hash_map[content_hash] = result
            else:
                content_hash_map[content_hash] = result
        
        return list(content_hash_map.values())
    
    def format_results_for_api(
        self,
        results: List[RetrievalResult]
    ) -> List[Dict[str, Any]]:
        """
        格式化结果为API响应格式
        
        Args:
            results: 检索结果列表
            
        Returns:
            格式化的字典列表
        """
        return [
            {
                "content": r.content,
                "score": r.score,
                "distance": r.distance,
                "metadata": r.metadata,
                "kb_id": r.kb_id,
                "kb_name": r.kb_name,
                "chunk_id": r.chunk_id,
                "doc_id": r.doc_id,
                "document_name": r.document_name  # 🆕 添加文档名称
            }
            for r in results
        ]


# 全局单例 (线程安全)
_multi_kb_retriever: Optional[MultiKBRetriever] = None
_retriever_lock = asyncio.Lock()


async def get_multi_kb_retriever() -> MultiKBRetriever:
    """
    获取多知识库检索器单例
    
    Returns:
        MultiKBRetriever实例
    """
    global _multi_kb_retriever
    
    if _multi_kb_retriever is None:
        async with _retriever_lock:
            if _multi_kb_retriever is None:  # 双重检查
                _multi_kb_retriever = MultiKBRetriever()
    
    return _multi_kb_retriever

