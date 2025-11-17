"""
向量存储接口定义
这个模块只包含接口定义，不导入任何重量级依赖（如 ChromaDB）
"""
from typing import List, Optional, Tuple
from langchain_core.documents import Document


class VectorStoreLike:
	"""
	抽象接口，适配不同向量库
	
	所有检索方法均为异步实现，避免阻塞事件循环。
	实现类需使用线程池包装同步库（如 ChromaDB）。
	"""

	def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:  # pragma: no cover - interface
		"""添加文档（同步方法，仅在初始化时使用）"""
		raise NotImplementedError

	async def similarity_search_with_score(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:  # pragma: no cover - interface
		"""异步相似度搜索（避免阻塞事件循环）
		
		实现方式由具体向量库决定：
		- 如果底层嵌入模型本身是异步的，直接 await
		- 如果底层嵌入模型是同步的，使用 run_in_executor 包装
		"""
		raise NotImplementedError

	async def get_by_ids(self, ids: List[str]) -> List[Document]:  # pragma: no cover - interface
		"""异步获取文档（根据主键ID列表）"""
		raise NotImplementedError

