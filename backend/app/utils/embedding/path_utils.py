"""
ChromaDB路径构建工具函数
统一管理向量数据库的路径构建逻辑，避免重复目录问题
"""
import os
import re
import uuid
import hashlib
from pathlib import Path
from typing import Optional


def _sanitize_collection_name(name: str) -> str:
    """
    Chroma constraints:
    - 3-63 chars
    - start/end alphanumeric
    - allowed: alnum, '_', '-'
    - no consecutive periods; we avoid '.' entirely
    - not an IPv4 address (we avoid by using letters)
    """
    original_name = name  # 保存原始名称用于生成确定性哈希
    if not name:
        name = "kb"
    # Replace unsupported chars with '-'
    name = re.sub(r"[^A-Za-z0-9_-]", "-", name)
    # Collapse multiple '-' or '_' to single '-'
    name = re.sub(r"[-_]{2,}", "-", name)
    # Trim non-alnum from ends
    name = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", name)
    # Ensure minimum length by padding with deterministic suffix
    if len(name) < 3:
        # 使用原始名称的哈希值生成确定性的后缀
        original_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:6]
        name = f"kb-{original_hash}"
    # Enforce max length 63
    if len(name) > 63:
        name = name[:63]
    # Final guard: if ends with non-alnum after slice, fix
    name = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", name)
    # If empty again, fallback with deterministic hash
    if not name:
        # 使用原始输入名称生成确定性的名称
        original_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:6]
        name = f"kb-{original_hash}"
    return name


def _sanitize_folder_name(name: str) -> str:
    """允许 Unicode 的文件夹名清洗（仅去除文件系统不允许或危险字符）"""
    name = name or "kb"
    # 去除非法字符
    _def_fs_forbidden = r"[<>:\\/\|?*]"
    name = re.sub(_def_fs_forbidden, "-", name)
    # 去掉首尾空白及点/空格（Windows 末尾点与空格不合法）
    name = name.strip().strip(". ")
    # 避免空字符串
    if not name:
        name = f"kb-{uuid.uuid4().hex[:6]}"
    # 限长，避免过长路径
    if len(name) > 100:
        name = name[:100].rstrip(". ")
    return name


def get_backend_root() -> Path:
    """获取backend包的根目录"""
    # 从当前文件位置向上查找backend目录
    current_file = Path(__file__).resolve()
    
    # 当前文件在 backend/app/utils/embedding/path_utils.py
    # 需要向上4级到达backend目录
    backend_root = current_file.parents[3]  # backend/
    
    return backend_root


def build_chroma_persist_dir(collection_name_raw: str) -> str:
    """
    构建ChromaDB持久化目录路径
    
    Args:
        collection_name_raw: 原始集合名称（可包含中文）
        
    Returns:
        str: 绝对路径字符串
    """
    # 文件夹名允许中文，仅去除文件系统非法字符
    folder_name = _sanitize_folder_name(collection_name_raw)
    
    # 获取backend根目录
    backend_root = get_backend_root()
    
    # 构建完整路径: backend/data/chromas/{folder_name}
    persist_dir = backend_root / "data" / "chromas" / folder_name
    
    # 确保目录存在
    persist_dir.mkdir(parents=True, exist_ok=True)
    
    return str(persist_dir)


def get_chroma_collection_name(collection_name_raw: str) -> str:
    """
    获取ChromaDB集合名称（ASCII安全）
    
    Args:
        collection_name_raw: 原始集合名称
        
    Returns:
        str: 安全的集合名称
    """
    return _sanitize_collection_name(collection_name_raw)


def build_faiss_persist_dir(collection_name_raw: str) -> str:
	"""
	构建FAISS持久化目录路径
	
	Args:
		collection_name_raw: 原始集合名称（可包含中文）
		
	Returns:
		str: 绝对路径字符串
	"""
	# 文件夹名允许中文，仅去除文件系统非法字符
	folder_name = _sanitize_folder_name(collection_name_raw)
	
	# 获取backend根目录
	backend_root = get_backend_root()
	
	# 构建完整路径: backend/data/faiss/{folder_name}
	persist_dir = backend_root / "data" / "faiss" / folder_name
	
	# 确保目录存在
	persist_dir.mkdir(parents=True, exist_ok=True)
	
	return str(persist_dir)


def get_faiss_collection_name(collection_name_raw: str) -> str:
	"""
	获取FAISS集合名称（用于文件名）
	
	Args:
		collection_name_raw: 原始集合名称
		
	Returns:
		str: 安全的集合名称
	"""
	return _sanitize_folder_name(collection_name_raw)


def debug_chroma_paths(collection_name_raw: str) -> dict:
	"""
	调试ChromaDB路径信息
	
	Args:
		collection_name_raw: 原始集合名称
		
	Returns:
		dict: 包含路径调试信息的字典
	"""
	collection_name = _sanitize_collection_name(collection_name_raw)
	folder_name = _sanitize_folder_name(collection_name_raw)
	persist_dir = build_chroma_persist_dir(collection_name_raw)
	backend_root = get_backend_root()
	
	return {
		"collection_name_raw": collection_name_raw,
		"collection_name_sanitized": collection_name,
		"folder_name": folder_name,
		"persist_dir": persist_dir,
		"backend_root": str(backend_root),
		"directory_exists": os.path.exists(persist_dir),
		"directory_contents": os.listdir(persist_dir) if os.path.exists(persist_dir) else []
	}


def debug_faiss_paths(collection_name_raw: str) -> dict:
	"""
	调试FAISS路径信息
	
	Args:
		collection_name_raw: 原始集合名称
		
	Returns:
		dict: 包含路径调试信息的字典
	"""
	collection_name = _sanitize_folder_name(collection_name_raw)
	persist_dir = build_faiss_persist_dir(collection_name_raw)
	backend_root = get_backend_root()
	
	return {
		"collection_name_raw": collection_name_raw,
		"collection_name_sanitized": collection_name,
		"persist_dir": persist_dir,
		"backend_root": str(backend_root),
		"directory_exists": os.path.exists(persist_dir),
		"directory_contents": os.listdir(persist_dir) if os.path.exists(persist_dir) else []
	}
