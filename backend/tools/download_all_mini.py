import os
import sys
import argparse
from pathlib import Path


def ensure_packages() -> None:
	try:
		import sentence_transformers  # noqa: F401
	except Exception:
		print("[错误] 未安装 sentence-transformers，请先执行: pip install -U sentence-transformers", file=sys.stderr)
		sys.exit(1)


def download_and_save(dest_dir: str) -> str:
	from sentence_transformers import SentenceTransformer

	model_name = "all-MiniLM-L6-v2"  # 即大家常说的 all_mini 模型
	print(f"准备下载模型: {model_name}")

	# 下载并缓存到默认 HF 缓存目录
	model = SentenceTransformer(model_name)

	# 保存为可携带的本地目录
	dest_path = Path(dest_dir).expanduser().resolve()
	dest_path.mkdir(parents=True, exist_ok=True)
	print(f"保存模型到: {dest_path}")
	model.save(str(dest_path))

	# 额外写入一个标记文件，记录来源模型名
	(source_info := dest_path / "SOURCE_MODEL.txt").write_text(
		f"source_model={model_name}\n",
		encoding="utf-8",
	)
	return str(dest_path)


def main() -> None:
	parser = argparse.ArgumentParser(description="下载并离线保存 all-MiniLM-L6-v2 嵌入模型")
	parser.add_argument(
		"--dest",
		default=os.path.join(os.getcwd(), "models", "all-MiniLM-L6-v2"),
		help="模型保存目录（默认: ./models/all-MiniLM-L6-v2）",
	)
	args = parser.parse_args()

	ensure_packages()
	try:
		final_path = download_and_save(args.dest)
		print(f"下载与保存完成，路径: {final_path}")
		print("现在可以通过 SentenceTransformer(final_path) 离线加载该模型。")
	except Exception as e:
		print(f"[错误] 下载失败: {e}", file=sys.stderr)
		sys.exit(1)


if __name__ == "__main__":
	main() 