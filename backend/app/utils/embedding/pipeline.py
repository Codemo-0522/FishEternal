import os
import uuid
from typing import List, Optional, Tuple, TYPE_CHECKING

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from .interfaces import VectorStoreLike
from ..distance_utils import calculate_score_from_distance

# ⚡ 延迟导入 RecursiveCharacterTextSplitter（导入耗时约7秒）
if TYPE_CHECKING:
	from langchain_text_splitters import RecursiveCharacterTextSplitter


class TextIngestionPipeline:
	"""
	❌ 已废弃：此类使用同步 API，可能导致索引损坏
	
	请使用 AsyncTextIngestionPipeline 替代：
	from backend.app.utils.embedding.async_pipeline import AsyncTextIngestionPipeline
	
	理由：
	1. 同步的 add_documents 在多进程环境下不安全
	2. 可能绕过文件锁机制导致索引损坏
	3. 会阻塞事件循环，影响性能
	
	这不是建议，而是强制性要求！
	"""

	def __init__(self, *args, **kwargs):
		raise RuntimeError(
			"❌ TextIngestionPipeline 已废弃！\n"
			"为了防止索引损坏，请使用异步版本：\n"
			"from backend.app.utils.embedding.async_pipeline import AsyncTextIngestionPipeline\n"
			"\n"
			"示例用法：\n"
			"async with AsyncTextIngestionPipeline(config) as pipeline:\n"
			"    await pipeline.process_document_async(text, filename, kb_settings)\n"
			"\n"
			"这是强制性的安全措施，不存在例外。"
		)


class Retriever:
	"""
	与具体向量库解耦的检索器，依赖注入 `VectorStoreLike`。
	支持基于相似度阈值过滤检索结果。
	
	所有检索方法均为异步实现，避免阻塞事件循环。
	
	阈值过滤说明：
	- similarity_threshold: 相似度分数阈值 [0, 1]，1表示最相似
	  只返回 score >= threshold 的结果
	- 后端会自动将ChromaDB返回的距离转换为相似度分数（0-1）
	- 不同距离度量统一转换规则：
	  * cosine: score = 1 - distance  (distance ∈ [0,2])
	  * ip: score = 1 - distance  (distance ∈ [0,2]，归一化向量)
	  * l2: score = 1 - distance/2  (distance ∈ [0,4]，归一化向量)
	
	建议阈值：
	- 0.7-1.0: 非常严格，只返回高度相关的结果
	- 0.5-0.7: 中等严格，平衡精确度和召回率
	- 0.3-0.5: 宽松，返回更多可能相关的结果
	- 0.0-0.3: 非常宽松，可能包含不相关的结果
	"""

	def __init__(
		self, 
		vector_store: VectorStoreLike, 
		top_k: int = 3, 
		similarity_threshold: Optional[float] = None,
		distance_metric: str = "cosine"
	) -> None:
		self.vector_store = vector_store
		self.top_k = top_k
		self.similarity_threshold = similarity_threshold
		self.distance_metric = distance_metric  # 距离度量类型（用于距离→相似度转换）

	async def search(self, query: str, top_k: Optional[int] = None, similarity_threshold: Optional[float] = None):
		"""
		异步检索：执行相似度搜索，并根据阈值过滤结果。
		
		Args:
			query: 查询文本
			top_k: 返回的最大结果数（在过滤前）
			similarity_threshold: 相似度分数阈值 [0, 1]，1表示最相似
				只返回 score >= threshold 的结果
				None 表示不过滤。
		
		Returns:
			List[Tuple[Document, float]]: 过滤后的文档和距离列表
		
		注意：
			- ChromaDB返回的是距离值（越小越相似）
			- 本方法会将距离转换为相似度分数（0-1），然后用分数过滤
			- 返回的仍然是 (Document, distance) 元组，保持接口兼容性
		"""
		k = top_k if top_k is not None else self.top_k
		threshold = similarity_threshold if similarity_threshold is not None else self.similarity_threshold
		
		# 调用 VectorStore 的异步方法
		results = await self.vector_store.similarity_search_with_score(query, k=k)
		
		# 如果设置了阈值，将距离转换为相似度分数后过滤
		if threshold is not None:
			filtered_results = []
			for doc, distance in results:
				# 将距离转换为相似度分数（0-1）
				score = calculate_score_from_distance(float(distance), self.distance_metric)
				# 保留相似度分数 >= 阈值的结果
				if score >= threshold:
					filtered_results.append((doc, distance))
			return filtered_results
		
		return results


__all__ = ["TextIngestionPipeline", "Retriever"] 