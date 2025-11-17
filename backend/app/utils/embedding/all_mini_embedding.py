import os
import sys
from typing import List, Optional

import torch
from langchain_core.embeddings import Embeddings

try:
	from sentence_transformers import SentenceTransformer
except Exception:
	print("[错误] 需要安装 sentence-transformers，请先执行: pip install -U sentence-transformers", file=sys.stderr)
	raise


class MiniLMEmbeddings(Embeddings):
	"""
	基于 SentenceTransformers 的 all-MiniLM-L6-v2 封装，遵循 LangChain Embeddings 接口。

	模块化设计要点：
	- 仅负责“字符串 -> 向量”的转换；不做切分、入库等其它流程。
	- 支持本地路径或在线模型名；默认优先本地目录 `models/all-MiniLM-L6-v2`。
	- 可选 L2 归一化、批量编码与最大长度设置，便于在低配 CPU 上稳定运行。

	参数:
	- model_name_or_path: 模型名或本地路径。默认 `models/all-MiniLM-L6-v2`（随脚本下载）。
	- device: 推理设备（如 "cpu" / "cuda"）。None 则自动选择，可在无 GPU 环境下安全回退到 CPU。
	- normalize: 是否对输出向量进行 L2 归一化，默认 True。
	- max_length: 模型编码的最大 token 长度，默认 512（较稳且速度更快）。
	- batch_size: 批大小，默认 16。内存紧张时可调小（如 4）。
	"""

	def __init__(
		self,
		model_name_or_path: Optional[str] = None,
		device: Optional[str] = None,
		normalize: bool = True,
		max_length: int = 512,
		batch_size: int = 16,
	) -> None:
		# 默认优先使用本地缓存目录
		default_local = os.path.join("models", "all-MiniLM-L6-v2")
		self.model_name_or_path = model_name_or_path or default_local

		self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
		self.normalize = normalize
		self.max_length = max_length
		self.batch_size = batch_size

		# 检查模型路径是否存在（防止自动从 HuggingFace 下载）
		if not os.path.exists(self.model_name_or_path):
			raise FileNotFoundError(
				f"本地模型路径不存在: {self.model_name_or_path}\n"
				f"请确保模型文件已下载到该目录。\n"
				f"您可以从 HuggingFace 手动下载模型并放置到指定路径。"
			)
		
		# 加载模型（设置 local_files_only=True 防止自动下载）
		try:
			self.model = SentenceTransformer(
				self.model_name_or_path, 
				device=self.device,
				local_files_only=True  # 仅使用本地文件，不从 HuggingFace 下载
			)
		except Exception as e:
			raise RuntimeError(
				f"加载本地模型失败: {self.model_name_or_path}\n"
				f"错误信息: {str(e)}\n"
				f"请确保模型文件完整且格式正确。"
			)
		
		# 控制最大长度
		if isinstance(self.max_length, int) and self.max_length > 0:
			self.model.max_seq_length = self.max_length

	def _encode(self, inputs: List[str]) -> List[List[float]]:
		if not inputs:
			return []
		# 使用 numpy 数组返回，避免 list 对象没有 .float() 的问题
		emb = self.model.encode(
			inputs,
			batch_size=self.batch_size,
			normalize_embeddings=self.normalize,
			convert_to_numpy=True,
			show_progress_bar=False,
		)
		# 返回 python 列表（float）
		return emb.tolist()

	def embed_documents(self, texts: List[str]) -> List[List[float]]:
		return self._encode(texts)

	def embed_query(self, text: str) -> List[float]:
		return self._encode([text])[0]


__all__ = ["MiniLMEmbeddings"] 