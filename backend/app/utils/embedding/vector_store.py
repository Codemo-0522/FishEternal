from typing import List, Optional, Tuple
import threading
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document

from .interfaces import VectorStoreLike

logger = logging.getLogger(__name__)

# ⚡ 后台线程预加载 Chroma，避免启动时阻塞主线程
_CHROMA_AVAILABLE = None
_Chroma = None
_chroma_loading = False
_chroma_lock = threading.Lock()
_chroma_loaded_event = threading.Event()

def _preload_chroma_in_background():
	"""在后台线程预加载 Chroma，不阻塞主启动流程"""
	global _CHROMA_AVAILABLE, _Chroma, _chroma_loading
	
	with _chroma_lock:
		if _chroma_loading or _CHROMA_AVAILABLE is not None:
			return  # 已经在加载或已加载完成
		_chroma_loading = True
	
	def _load():
		global _CHROMA_AVAILABLE, _Chroma
		try:
			logger.info("后台预加载 ChromaDB 开始...")
			# 优先使用官方拆分包 langchain-chroma，其次回退到 langchain_community
			try:
				from langchain_chroma import Chroma  # 新版官方集成包
				_CHROMA_AVAILABLE = True
				_Chroma = Chroma
				logger.info("✓ ChromaDB 预加载成功 (langchain-chroma)")
			except Exception:
				try:
					from langchain_community.vectorstores import Chroma  # 旧版/社区包
					_CHROMA_AVAILABLE = True
					_Chroma = Chroma
					logger.info("✓ ChromaDB 预加载成功 (langchain_community)")
				except Exception as e:
					_CHROMA_AVAILABLE = False
					_Chroma = None
					logger.warning(f"ChromaDB 预加载失败: {e}")
		finally:
			_chroma_loaded_event.set()  # 标记加载完成
	
	thread = threading.Thread(target=_load, daemon=True, name="ChromaPreloader")
	thread.start()

def _get_chroma(timeout: float = 30.0):
	"""
	获取 Chroma 类，如果正在后台加载则等待加载完成
	
	Args:
		timeout: 等待超时时间（秒），默认30秒
	
	Returns:
		Chroma 类或 None
	"""
	global _CHROMA_AVAILABLE, _Chroma
	
	# 如果已经加载完成，直接返回
	if _CHROMA_AVAILABLE is not None:
		return _Chroma
	
	# 等待后台加载完成
	if _chroma_loading:
		logger.info(f"等待 ChromaDB 后台加载完成（最多等待 {timeout}秒）...")
		if _chroma_loaded_event.wait(timeout=timeout):
			logger.info("ChromaDB 加载完成")
		else:
			logger.warning(f"等待 ChromaDB 加载超时（{timeout}秒）")
	
	return _Chroma


class ChromaVectorStore(VectorStoreLike):
	"""
	Chroma 的轻量封装。通过传入 Embeddings 与持久化参数进行构造，避免在
	项目其他模块中出现对 Chroma 的直接依赖。
	
	所有检索方法均为异步实现，使用线程池包装 ChromaDB 的同步调用。
	"""

	# 共享线程池，用于异步调用（避免创建过多线程）
	_executor: Optional[ThreadPoolExecutor] = None
	_executor_lock = threading.Lock()

	@classmethod
	def _get_executor(cls) -> ThreadPoolExecutor:
		"""获取共享的线程池（延迟初始化）"""
		if cls._executor is None:
			with cls._executor_lock:
				if cls._executor is None:
					# 创建固定大小的线程池，避免无限制创建线程
					cls._executor = ThreadPoolExecutor(
						max_workers=4,  # 最多4个并发检索
						thread_name_prefix="VectorStore"
					)
		return cls._executor

	def __init__(
		self,
		embedding_function: Embeddings,
		persist_directory: Optional[str] = None,
		collection_name: Optional[str] = None,
		client_settings: Optional[dict] = None,
		distance_metric: str = "cosine",  # 新增：距离度量参数
	):
		"""
		初始化 ChromaVectorStore
		
		Args:
			embedding_function: Embedding 函数
			persist_directory: 持久化目录
			collection_name: 集合名称
			client_settings: 客户端设置
			distance_metric: 距离度量方式 ("cosine", "l2", "ip")
		"""
		# ⚡ 获取 Chroma（如果正在后台加载则等待）
		Chroma = _get_chroma(timeout=30.0)
		if Chroma is None:
			raise RuntimeError(
				"未检测到 Chroma 集成，请安装: pip install -U langchain-chroma 或 pip install -U langchain-community"
			)

		# 验证距离度量参数
		valid_metrics = ["cosine", "l2", "ip"]
		if distance_metric not in valid_metrics:
			logger.warning(f"无效的距离度量 '{distance_metric}'，使用默认值 'cosine'")
			distance_metric = "cosine"
		
		self._distance_metric = distance_metric
		self._persist_directory = persist_directory  # 保存以供WAL checkpoint使用
		self._collection_name = collection_name  # 保存collection名称
		logger.info(f"🎯 ChromaVectorStore 使用距离度量: {distance_metric}")

		kwargs = {
			"embedding_function": embedding_function,
			"persist_directory": persist_directory,
			"collection_name": collection_name,
			# Chroma 通过 collection_metadata 设置距离度量
			"collection_metadata": {"hnsw:space": distance_metric}
		}
		if client_settings is not None:
			kwargs["client_settings"] = client_settings

		self._store = Chroma(**kwargs)
		
		# 🔥 关键修复：创建后立即验证UUID一致性
		if persist_directory and collection_name:
			self._verify_and_fix_uuid_consistency(persist_directory, collection_name)
	
	def _verify_and_fix_uuid_consistency(self, persist_directory: str, collection_name: str):
		"""
		验证并修复ChromaDB的UUID一致性问题
		
		问题背景：
		在并发环境下，ChromaDB的get_or_create_collection()可能导致：
		- SQLite中记录的UUID与文件系统中的UUID目录不匹配
		- 导致后续读取时报错：Error loading hnsw index
		
		解决方案：
		1. 读取SQLite中的expected_uuid
		2. 检查文件系统中的实际UUID目录
		3. 如果不匹配，重命名目录以保持一致性
		"""
		import sqlite3
		from pathlib import Path
		import shutil
		
		try:
			# 1. 从SQLite读取expected UUID
			db_path = Path(persist_directory) / "chroma.sqlite3"
			if not db_path.exists():
				logger.warning(f"⚠️ SQLite数据库不存在: {db_path}")
				return
			
			conn = sqlite3.connect(str(db_path))
			cursor = conn.cursor()
			cursor.execute(
				"SELECT id FROM collections WHERE name = ?",
				(collection_name,)
			)
			row = cursor.fetchone()
			conn.close()
			
			if not row:
				logger.warning(f"⚠️ 未找到collection: {collection_name}")
				return
			
			expected_uuid = row[0]
			expected_dir = Path(persist_directory) / expected_uuid
			
			# 2. 检查文件系统中的UUID目录
			uuid_dirs = [
				d for d in Path(persist_directory).iterdir()
				if d.is_dir() and d.name not in ["chroma.sqlite3"]
			]
			
			# 过滤出看起来像UUID的目录
			import re
			uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
			uuid_dirs = [d for d in uuid_dirs if uuid_pattern.match(d.name)]
			
			# 3. 检查是否匹配
			if expected_dir.exists():
				# 匹配！清理额外的UUID目录
				extra_dirs = [d for d in uuid_dirs if d != expected_dir]
				if extra_dirs:
					logger.warning(f"🗑️ 发现{len(extra_dirs)}个额外的UUID目录，清理中...")
					for extra_dir in extra_dirs:
						try:
							shutil.rmtree(extra_dir)
							logger.info(f"  ✅ 已删除: {extra_dir.name}")
						except Exception as e:
							logger.error(f"  ❌ 删除失败 {extra_dir.name}: {e}")
			else:
				# 不匹配！需要修复
				if len(uuid_dirs) == 1:
					actual_dir = uuid_dirs[0]
					logger.warning(
						f"⚠️ UUID不匹配! "
						f"SQLite={expected_uuid}, 文件系统={actual_dir.name}"
					)
					logger.info(f"🔧 自动修复：重命名 {actual_dir.name} → {expected_uuid}")
					try:
						actual_dir.rename(expected_dir)
						logger.info("✅ UUID已修复")
					except Exception as e:
						logger.error(f"❌ UUID修复失败: {e}")
				elif len(uuid_dirs) > 1:
					logger.error(
						f"❌ 发现多个UUID目录: {[d.name for d in uuid_dirs]}, "
						f"expected: {expected_uuid}"
					)
				else:
					logger.warning(f"⚠️ 未找到任何UUID目录，expected: {expected_uuid}")
					
		except Exception as e:
			logger.error(f"❌ UUID一致性验证失败: {e}", exc_info=True)

	def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:
		"""
		🔒 内部方法：添加文档到向量存储
		
		⚠️ 警告：此方法仅供 VectorStoreWithLock 内部使用（在文件锁保护下调用）
		
		外部代码应使用:
		  vectorstore_mgr = get_vectorstore_manager()
		  vectorstore = vectorstore_mgr.get_or_create(...)
		  await vectorstore.add_documents_async(documents, ids)
		
		直接调用此方法会导致多进程并发写入，造成索引损坏！
		"""
		# 添加类型检查和调试日志
		if not documents:
			logger.warning("add_documents 收到空文档列表")
			return
			
		# 检查 documents 是否都是 Document 对象
		for idx, doc in enumerate(documents):
			if not isinstance(doc, Document):
				logger.error(f"文档 {idx} 不是 Document 对象，类型: {type(doc)}, 值: {doc!r}")
				raise TypeError(f"期望 Document 对象，但收到 {type(doc).__name__}")
		
		# 直接传递给底层 Chroma
		self._store.add_documents(documents, ids=ids)

	async def similarity_search_with_score(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:
		"""异步相似度检索（使用线程池包装，避免阻塞事件循环）
		
		将同步的 embedding + 向量检索操作放到线程池中执行，
		避免阻塞 asyncio 事件循环。
		"""
		loop = asyncio.get_event_loop()
		executor = self._get_executor()
		
		# 在线程池中执行同步操作
		result = await loop.run_in_executor(
			executor,
			self._store.similarity_search_with_score,
			query,
			k
		)
		return result

	def _get_by_ids_sync(self, ids: List[str]) -> List[Document]:
		"""内部同步方法：用于线程池执行"""
		if not ids:
			return []
		
		# 调试信息
		logger.info(f"🔍 ChromaVectorStore.get_by_ids: 查询 {len(ids)} 个 chunk_id")
		logger.info(f"🔍 ChromaVectorStore.get_by_ids: collection_name={self._store._collection.name}")
		logger.info(f"🔍 ChromaVectorStore.get_by_ids: 查询的 ids={ids[:3]}..." if len(ids) > 3 else f"🔍 ChromaVectorStore.get_by_ids: 查询的 ids={ids}")
		
		# langchain Chroma 的 get 支持 ids 参数，返回 dict
		raw = self._store._collection.get(ids=ids, include=["metadatas", "documents"])  # type: ignore
		
		logger.info(f"🔍 ChromaVectorStore.get_by_ids: 返回的 documents 数量={len(raw.get('documents', []) or [])}")
		logger.info(f"🔍 ChromaVectorStore.get_by_ids: 返回的 metadatas 数量={len(raw.get('metadatas', []) or [])}")
		
		# 调试：显示collection中实际有多少文档
		try:
			count = self._store._collection.count()
			logger.info(f"🔍 ChromaVectorStore.get_by_ids: collection总文档数={count}")
		except Exception as e:
			logger.warning(f"🔍 ChromaVectorStore.get_by_ids: 无法获取collection总数: {e}")
		
		docs: List[Document] = []
		for text, meta in zip(raw.get("documents", []) or [], raw.get("metadatas", []) or []):
			docs.append(Document(page_content=text, metadata=meta))
		return docs

	async def get_by_ids(self, ids: List[str]) -> List[Document]:
		"""异步获取文档（使用线程池包装）
		
		虽然 get_by_ids 通常很快（直接主键查询），但为了避免阻塞
		事件循环，统一使用异步实现。
		"""
		loop = asyncio.get_event_loop()
		executor = self._get_executor()
		
		# 在线程池中执行
		result = await loop.run_in_executor(
			executor,
			self._get_by_ids_sync,
			ids
		)
		return result


# ⚡ 后台线程预加载 FAISS，避免启动时阻塞主线程
_FAISS_AVAILABLE = None
_FAISS = None
_faiss_loading = False
_faiss_lock = threading.Lock()
_faiss_loaded_event = threading.Event()

def _preload_faiss_in_background():
	"""在后台线程预加载 FAISS，不阻塞主启动流程"""
	global _FAISS_AVAILABLE, _FAISS, _faiss_loading
	
	with _faiss_lock:
		if _faiss_loading or _FAISS_AVAILABLE is not None:
			return  # 已经在加载或已加载完成
		_faiss_loading = True
	
	def _load():
		global _FAISS_AVAILABLE, _FAISS
		try:
			logger.info("后台预加载 FAISS 开始...")
			try:
				from langchain_community.vectorstores import FAISS
				_FAISS_AVAILABLE = True
				_FAISS = FAISS
				logger.info("✓ FAISS 预加载成功 (langchain_community)")
			except Exception as e:
				_FAISS_AVAILABLE = False
				_FAISS = None
				logger.warning(f"FAISS 预加载失败: {e}")
		finally:
			_faiss_loaded_event.set()  # 标记加载完成
	
	thread = threading.Thread(target=_load, daemon=True, name="FAISSPreloader")
	thread.start()

def _get_faiss(timeout: float = 30.0):
	"""
	获取 FAISS 类，如果正在后台加载则等待加载完成
	
	Args:
		timeout: 等待超时时间（秒），默认30秒
	
	Returns:
		FAISS 类或 None
	"""
	global _FAISS_AVAILABLE, _FAISS
	
	# 如果已经加载完成，直接返回
	if _FAISS_AVAILABLE is not None:
		return _FAISS
	
	# 等待后台加载完成
	if _faiss_loading:
		logger.info(f"等待 FAISS 后台加载完成（最多等待 {timeout}秒）...")
		if _faiss_loaded_event.wait(timeout=timeout):
			logger.info("FAISS 加载完成")
		else:
			logger.warning(f"等待 FAISS 加载超时（{timeout}秒）")
	
	return _FAISS


class FAISSVectorStore(VectorStoreLike):
	"""
	FAISS 的轻量封装。通过传入 Embeddings 与持久化参数进行构造，避免在
	项目其他模块中出现对 FAISS 的直接依赖。
	
	所有检索方法均为异步实现，使用线程池包装 FAISS 的同步调用。
	
	FAISS 特性：
	- 高性能的向量相似度搜索
	- 支持本地持久化（保存/加载索引）
	- 内存友好的索引结构
	"""

	# 共享线程池，用于异步调用（避免创建过多线程）
	_executor: Optional[ThreadPoolExecutor] = None
	_executor_lock = threading.Lock()

	@classmethod
	def _get_executor(cls) -> ThreadPoolExecutor:
		"""获取共享的线程池（延迟初始化）"""
		if cls._executor is None:
			with cls._executor_lock:
				if cls._executor is None:
					# 创建固定大小的线程池，避免无限制创建线程
					cls._executor = ThreadPoolExecutor(
						max_workers=4,  # 最多4个并发检索
						thread_name_prefix="FAISSVectorStore"
					)
		return cls._executor

	def __init__(
		self,
		embedding_function: Embeddings,
		persist_directory: Optional[str] = None,
		collection_name: Optional[str] = None,
		distance_metric: str = "cosine",  # FAISS支持: "cosine", "l2", "ip"
	):
		"""
		初始化 FAISSVectorStore
		
		Args:
			embedding_function: Embedding 函数
			persist_directory: 持久化目录
			collection_name: 集合名称（用于文件名）
			distance_metric: 距离度量方式 ("cosine", "l2", "ip")
		"""
		# ⚡ 获取 FAISS（如果正在后台加载则等待）
		FAISS = _get_faiss(timeout=30.0)
		if FAISS is None:
			raise RuntimeError(
				"未检测到 FAISS 集成，请安装: pip install faiss-cpu 或 pip install faiss-gpu"
			)

		# 验证距离度量参数
		valid_metrics = ["cosine", "l2", "ip"]
		if distance_metric not in valid_metrics:
			logger.warning(f"无效的距离度量 '{distance_metric}'，使用默认值 'cosine'")
			distance_metric = "cosine"
		
		self._distance_metric = distance_metric
		self._persist_directory = persist_directory
		self._collection_name = collection_name or "default"
		self._embedding_function = embedding_function
		logger.info(f"🎯 FAISSVectorStore 使用距离度量: {distance_metric}")

		# 构建索引文件路径
		import os
		if persist_directory:
			os.makedirs(persist_directory, exist_ok=True)
			self._index_file = os.path.join(persist_directory, f"{self._collection_name}.faiss")
			self._pkl_file = os.path.join(persist_directory, f"{self._collection_name}.pkl")
		else:
			self._index_file = None
			self._pkl_file = None

		# 尝试加载已有索引
		if self._index_file and os.path.exists(self._index_file):
			try:
				logger.info(f"📂 加载已有 FAISS 索引: {self._index_file}")
				self._store = FAISS.load_local(
					persist_directory,
					embedding_function,
					self._collection_name,
					allow_dangerous_deserialization=True  # 允许加载pickle文件
				)
				logger.info(f"✅ FAISS 索引加载成功，文档数: {self._store.index.ntotal}")
			except Exception as e:
				logger.warning(f"⚠️ 加载 FAISS 索引失败: {e}，将创建新索引")
				self._store = None
		else:
			self._store = None

	def add_documents(self, documents: List[Document], ids: Optional[List[str]] = None) -> None:
		"""
		🔒 内部方法：添加文档到向量存储
		
		⚠️ 警告：此方法仅供 VectorStoreWithLock 内部使用（在文件锁保护下调用）
		
		外部代码应使用:
		  vectorstore_mgr = get_vectorstore_manager()
		  vectorstore = vectorstore_mgr.get_or_create(...)
		  await vectorstore.add_documents_async(documents, ids)
		
		直接调用此方法会导致多进程并发写入，造成索引损坏！
		"""
		# 添加类型检查和调试日志
		if not documents:
			logger.warning("add_documents 收到空文档列表")
			return
			
		# 检查 documents 是否都是 Document 对象
		for idx, doc in enumerate(documents):
			if not isinstance(doc, Document):
				logger.error(f"文档 {idx} 不是 Document 对象，类型: {type(doc)}, 值: {doc!r}")
				raise TypeError(f"期望 Document 对象，但收到 {type(doc).__name__}")
		
		# FAISS 处理逻辑
		FAISS = _get_faiss()
		if FAISS is None:
			raise RuntimeError("FAISS 未加载")
		
		if self._store is None:
			# 🎯 首次创建索引，根据距离度量选择合适的配置
			logger.info(f"🆕 创建新的 FAISS 索引，文档数: {len(documents)}，距离度量: {self._distance_metric}")
			
			# 根据距离度量确定是否需要归一化
			# - cosine: 需要归一化 + IP索引
			# - ip: 不归一化 + IP索引
			# - l2: 不归一化 + L2索引 (默认)
			normalize_L2 = (self._distance_metric == "cosine")
			
			# 创建索引，langchain FAISS 会根据 normalize_L2 自动选择索引类型
			self._store = FAISS.from_documents(
				documents,
				self._embedding_function,
				normalize_L2=normalize_L2  # 🔥 关键参数：是否归一化
			)
			
			# 如果是 L2 距离且 FAISS 默认创建了 IP 索引，需要手动替换
			if self._distance_metric == "l2" and not normalize_L2:
				import faiss
				dim = self._store.index.d
				new_index = faiss.IndexFlatL2(dim)
				# 复制向量到新索引
				if self._store.index.ntotal > 0:
					vectors = self._store.index.reconstruct_n(0, self._store.index.ntotal)
					new_index.add(vectors)
				self._store.index = new_index
				logger.info(f"🔄 已切换到 L2 索引: {type(new_index).__name__}")
		else:
			# 添加到已有索引
			logger.info(f"➕ 添加文档到 FAISS 索引，新增文档数: {len(documents)}")
			# FAISS 的 add_documents 方法
			self._store.add_documents(documents)
		
		# 持久化索引
		if self._persist_directory:
			try:
				logger.info(f"💾 保存 FAISS 索引到: {self._index_file}")
				self._store.save_local(self._persist_directory, self._collection_name)
				logger.info(f"✅ FAISS 索引保存成功，总文档数: {self._store.index.ntotal}")
			except Exception as e:
				logger.error(f"❌ FAISS 索引保存失败: {e}", exc_info=True)

	async def similarity_search_with_score(self, query: str, k: int = 4) -> List[Tuple[Document, float]]:
		"""异步相似度检索（使用线程池包装，避免阻塞事件循环）
		
		将同步的 embedding + 向量检索操作放到线程池中执行，
		避免阻塞 asyncio 事件循环。
		"""
		if self._store is None:
			logger.warning("⚠️ FAISS 索引未初始化，返回空结果")
			return []
		
		loop = asyncio.get_event_loop()
		executor = self._get_executor()
		
		# 在线程池中执行同步操作
		result = await loop.run_in_executor(
			executor,
			self._store.similarity_search_with_score,
			query,
			k
		)
		return result

	def _get_by_ids_sync(self, ids: List[str]) -> List[Document]:
		"""内部同步方法：用于线程池执行"""
		if not ids:
			return []
		
		if self._store is None:
			logger.warning("⚠️ FAISS 索引未初始化")
			return []
		
		logger.info(f"🔍 FAISSVectorStore.get_by_ids: 查询 {len(ids)} 个 ID")
		
		# FAISS 通过 docstore 获取文档
		# langchain FAISS 实现中，docstore 是一个字典映射
		docs: List[Document] = []
		
		try:
			if hasattr(self._store, 'docstore') and hasattr(self._store.docstore, '_dict'):
				# 使用内部字典获取文档
				for doc_id in ids:
					if doc_id in self._store.docstore._dict:
						docs.append(self._store.docstore._dict[doc_id])
			else:
				logger.warning("⚠️ FAISS docstore 结构不符合预期")
		except Exception as e:
			logger.error(f"❌ FAISS get_by_ids 失败: {e}", exc_info=True)
		
		logger.info(f"🔍 FAISSVectorStore.get_by_ids: 返回 {len(docs)} 个文档")
		return docs

	async def get_by_ids(self, ids: List[str]) -> List[Document]:
		"""异步获取文档（使用线程池包装）
		
		虽然 get_by_ids 通常很快（直接主键查询），但为了避免阻塞
		事件循环，统一使用异步实现。
		"""
		loop = asyncio.get_event_loop()
		executor = self._get_executor()
		
		# 在线程池中执行
		result = await loop.run_in_executor(
			executor,
			self._get_by_ids_sync,
			ids
		)
		return result


__all__ = ["VectorStoreLike", "ChromaVectorStore", "FAISSVectorStore", "_preload_chroma_in_background", "_preload_faiss_in_background"] 