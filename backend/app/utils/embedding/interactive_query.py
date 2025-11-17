import os
import sys
import asyncio

from volcengine_embedding import ArkEmbeddings
from all_mini_embedding import MiniLMEmbeddings
from ollama_embedding import OllamaEmbeddings

from dotenv import dotenv_values

from vector_store import ChromaVectorStore
from pipeline import Retriever


# 纯向量检索测试，不做任何与身份/模型无关的输出

def _prompt_select_embeddings():
	print("请选择嵌入模型：")
	print("  1) 火山引擎 ArkEmbeddings")
	print("  2) 本地 MiniLMEmbeddings (sentence-transformers/all-MiniLM-L6-v2)")
	print("  3) 本地 Ollama Embeddings (可选模型，如 nomic-embed-text:v1.5)")
	choice = input("输入序号并回车 (默认 2): ").strip() or "2"
	if choice == "1":
		# 优先从输入获取 API Key，若留空则尝试 .env
		api_key = input("请输入 ARK_API_KEY（留空则尝试从 .env 读取）: ").strip()
		if not api_key:
			env_config = dotenv_values()
			api_key = env_config.get("ARK_API_KEY")
			if not api_key:
				raise ValueError("未提供 ARK_API_KEY，且 .env 中也未找到。")
		model = input("Ark 模型名 (默认 doubao-embedding-large-text-250515): ").strip() or "doubao-embedding-large-text-250515"
		embeddings = ArkEmbeddings(
			api_key=api_key,
			model=model,
		)
		print("将使用 ArkEmbeddings。")
		return embeddings, "ark"
	elif choice == "3":
		base_url = input("Ollama 服务地址 (默认 http://localhost:11434): ").strip() or "http://localhost:11434"
		model_name = input("Ollama 模型名称 (例如 nomic-embed-text:v1.5): ").strip() or "nomic-embed-text:v1.5"
		embeddings = OllamaEmbeddings(model=model_name, base_url=base_url)
		print(f"将使用 OllamaEmbeddings（model={model_name}）。")
		return embeddings, "ollama"
	else:
		# MiniLM 交互参数（均可回车使用默认）
		local_dir = input("可选：MiniLM 本地模型目录（如 models/all-MiniLM-L6-v2），留空则使用在线模型名: ").strip() or None
		max_len_raw = input("可选：max_length (默认 512): ").strip()
		batch_raw = input("可选：batch_size (默认 16): ").strip()
		try:
			max_length = int(max_len_raw) if max_len_raw else 512
			batch_size = int(batch_raw) if batch_raw else 16
		except Exception:
			raise ValueError("max_length 和 batch_size 需为整数。")
		embeddings = MiniLMEmbeddings(
			model_name_or_path=local_dir,
			device=None,
			normalize=True,
			max_length=max_length,
			batch_size=batch_size,
		)
		print("将使用 MiniLMEmbeddings。")
		return embeddings, "minilm"


def _prompt_kb_name(default_name: str = "default") -> str:
	name = input(f"请输入要检索的知识库名称 (默认 {default_name}): ").strip()
	return name or default_name


def build_vectorstore(persist_dir: str, collection_name: str = "my_knowledge_base"):
	"""
	构建向量存储（使用全局单例管理器，避免重复加载）
	
	注意：交互式脚本需要手动选择模型，但实际应用中会自动复用已加载的实例
	"""
	# 选择嵌入模型（需与入库阶段一致）
	embeddings, embed_tag = _prompt_select_embeddings()
	
	# 使用全局管理器（如果已加载则复用）
	try:
		from ...services.vectorstore_manager import get_vectorstore_manager
		vectorstore_mgr = get_vectorstore_manager()
		vectorstore = vectorstore_mgr.get_or_create(
			collection_name=collection_name,
			persist_dir=persist_dir,
			embedding_function=embeddings,
			vector_db_type="chroma"
		)
	except ImportError:
		# 如果管理器不可用（独立运行时），直接创建
		from vector_store import ChromaVectorStore
		vectorstore = ChromaVectorStore(
			embedding_function=embeddings,
			persist_directory=persist_dir,
			collection_name=collection_name,
		)
	
	return vectorstore


async def main_async():
	"""异步主函数"""
	from .path_utils import build_chroma_persist_dir
	kb_name = _prompt_kb_name()
	persist_dir = build_chroma_persist_dir(kb_name)
	collection_name = kb_name
	if not os.path.exists(persist_dir):
		print(f"[错误] 未找到持久化向量库目录: {persist_dir}，请先运行入库脚本。", file=sys.stderr)
		sys.exit(1)

	print("\n加载向量库中...")
	try:
		vectorstore = build_vectorstore(persist_dir, collection_name)
	except Exception as e:  # noqa: E722 - 保持交互友好
		print(f"[错误] 构建向量库失败: {e}", file=sys.stderr)
		sys.exit(1)
	print("加载完成。输入你的问题开始检索。支持指令: /exit 退出，/k=数字 设置返回条数 (默认3)。\n")

	retriever = Retriever(vector_store=vectorstore, top_k=3)

	top_k: int = 3
	while True:
		try:
			query = input("Query> ").strip()
		except (EOFError, KeyboardInterrupt):
			print("\n已退出。")
			break

		if not query:
			continue

		if query.lower() in {"/exit", "exit", "quit", ":q"}:
			print("已退出。")
			break

		if query.startswith("/k="):
			try:
				new_k = int(query.split("=", 1)[1])
				if new_k <= 0:
					raise ValueError
				top_k = new_k
				retriever.top_k = top_k
				print(f"已设置返回条数 top_k={top_k}")
			except Exception:
				print("设置失败，请使用格式如 /k=5 且为正整数。")
			continue

		try:
			# 使用异步检索方法
			results = await retriever.search(query, top_k=top_k)
		except Exception as e:
			print(f"[错误] 检索失败: {e}")
			continue

		if not results:
			print("未检索到结果。")
			continue

		for rank, (doc, score) in enumerate(results, start=1):
			print(f"\nTop {rank} | score={score:.4f}")
			print(f"source={doc.metadata.get('source')} chunk_index={doc.metadata.get('chunk_index')}")
			content = doc.page_content or ""
			preview = content[:500] + ("..." if len(content) > 500 else "")
			print(preview)


def main():
	"""同步包装器，用于向后兼容"""
	asyncio.run(main_async())


if __name__ == "__main__":
	try:
		main()
	except Exception as e:
		print(f"[错误] {e}", file=sys.stderr)
		sys.exit(1) 