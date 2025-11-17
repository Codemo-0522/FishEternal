import os
from pathlib import Path

def init_app():
    """初始化应用程序所需的配置和资源"""
    # 确保必要的目录存在
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    data_dir = base_dir / "backend" / "data"
    # 移除chroma_dir和models_dir
    # chroma_dir = data_dir / "chroma_db"
    # models_dir = data_dir / "models"

    # 创建必要的目录
    # for directory in [data_dir, chroma_dir, models_dir]:
    for directory in [data_dir]:
        directory.mkdir(exist_ok=True)

    return True 