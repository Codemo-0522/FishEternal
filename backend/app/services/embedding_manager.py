"""
全局 Embedding 模型实例管理器
确保同一个模型配置只加载一次到内存，所有用户共享同一个实例
"""
import logging
import threading
from typing import Dict, Tuple, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingKey:
    """Embedding 模型的唯一标识符（用作缓存 key）"""
    provider: str  # "ollama", "local", "ark"
    model: str     # 模型名称或路径
    base_url: Optional[str] = None  # API 服务地址（ollama/ark）
    
    def __hash__(self):
        return hash((self.provider, self.model, self.base_url))


class EmbeddingManager:
    """
    全局 Embedding 实例管理器（单例模式）
    
    职责：
    1. 管理所有 Embedding 模型实例的生命周期
    2. 确保相同配置的模型只加载一次
    3. 线程安全的实例获取
    4. 支持所有 provider: ollama, local, ark
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._instances: Dict[EmbeddingKey, Any] = {}
            self._instance_lock = threading.Lock()
            self._initialized = True
            logger.info("✅ EmbeddingManager 初始化完成")
    
    def get_or_create(
        self,
        provider: str,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        local_model_path: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        获取或创建 Embedding 实例
        
        Args:
            provider: 提供商 ("ollama", "local", "ark")
            model: 模型名称
            base_url: API 服务地址（ollama/ark）
            api_key: API 密钥（ark）
            local_model_path: 本地模型路径（local）
            **kwargs: 其他模型特定参数
            
        Returns:
            Embedding 实例（所有用户共享）
            
        Raises:
            ValueError: 参数错误
            RuntimeError: 模型加载失败
        """
        # 1. 标准化参数
        provider = provider.lower()
        
        if provider == "ollama":
            base_url = base_url or "http://localhost:11434"
            model = model or "nomic-embed-text:v1.5"
            cache_key = EmbeddingKey(provider="ollama", model=model, base_url=base_url)
            
        elif provider == "local":
            # 确定实际模型路径
            if local_model_path:
                model_path = local_model_path
            elif model:
                model_path = f"checkpoints/embeddings/{model}"
            else:
                model_path = "checkpoints/embeddings/all-MiniLM-L6-v2"
            
            # 使用路径作为 key
            cache_key = EmbeddingKey(provider="local", model=model_path)
            
        elif provider == "ark":
            if not api_key:
                raise ValueError("ArkEmbeddings 需要提供 api_key")
            model = model or "doubao-embedding-large-text-250515"
            # api_key 不作为 key，因为同一个模型的 api_key 应该相同
            cache_key = EmbeddingKey(provider="ark", model=model, base_url=base_url)
            
        else:
            raise ValueError(f"未知的 provider: {provider}")
        
        # 2. 检查是否已存在（双重检查锁定）
        if cache_key in self._instances:
            logger.info(f"♻️ 复用已加载的 Embedding 实例: {cache_key}")
            return self._instances[cache_key]
        
        # 3. 加载新实例（线程安全）
        with self._instance_lock:
            # 再次检查（可能其他线程已创建）
            if cache_key in self._instances:
                logger.info(f"♻️ 复用已加载的 Embedding 实例: {cache_key}")
                return self._instances[cache_key]
            
            logger.info(f"⏳ 开始加载 Embedding 模型: {cache_key}")
            
            try:
                instance = self._create_instance(
                    provider=provider,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    local_model_path=local_model_path,
                    cache_key=cache_key,
                    **kwargs
                )
                
                self._instances[cache_key] = instance
                logger.info(f"✅ Embedding 模型加载成功: {cache_key}")
                logger.info(f"📊 当前已加载模型数量: {len(self._instances)}")
                
                return instance
                
            except Exception as e:
                logger.error(f"❌ Embedding 模型加载失败: {cache_key} - {e}")
                raise RuntimeError(f"Embedding 模型加载失败: {e}") from e
    
    def _create_instance(
        self,
        provider: str,
        model: Optional[str],
        base_url: Optional[str],
        api_key: Optional[str],
        local_model_path: Optional[str],
        cache_key: EmbeddingKey,
        **kwargs
    ) -> Any:
        """
        实际创建 Embedding 实例的方法
        
        这里延迟导入重量级模块，避免启动时加载
        """
        import os
        
        if provider == "ollama":
            from ..utils.embedding.ollama_embedding import OllamaEmbeddings
            return OllamaEmbeddings(model=model, base_url=base_url)
        
        elif provider == "local":
            from ..utils.embedding.all_mini_embedding import MiniLMEmbeddings
            
            # 确定最终路径
            if local_model_path:
                model_path = local_model_path
            elif model:
                model_path = f"checkpoints/embeddings/{model}"
            else:
                model_path = "checkpoints/embeddings/all-MiniLM-L6-v2"
            
            # 检查路径是否存在
            if not os.path.exists(model_path):
                raise FileNotFoundError(
                    f"本地模型路径不存在: {model_path}。请确保模型文件已下载到该目录。"
                )
            
            # 获取模型参数
            max_length = kwargs.get('max_length', 512)
            batch_size = kwargs.get('batch_size', 8)
            normalize = kwargs.get('normalize', True)
            
            return MiniLMEmbeddings(
                model_name_or_path=model_path,
                max_length=max_length,
                batch_size=batch_size,
                normalize=normalize
            )
        
        elif provider == "ark":
            from ..utils.embedding.volcengine_embedding import ArkEmbeddings
            return ArkEmbeddings(api_key=api_key, model=model)
        
        else:
            raise ValueError(f"未知的 provider: {provider}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        return {
            "loaded_models": len(self._instances),
            "models": [
                {
                    "provider": key.provider,
                    "model": key.model,
                    "base_url": key.base_url
                }
                for key in self._instances.keys()
            ]
        }
    
    def clear(self):
        """清空所有缓存的实例（仅用于测试或重启）"""
        with self._instance_lock:
            count = len(self._instances)
            self._instances.clear()
            logger.warning(f"⚠️ 已清空所有 Embedding 实例 (共 {count} 个)")


# 全局单例实例
_embedding_manager: Optional[EmbeddingManager] = None


def get_embedding_manager() -> EmbeddingManager:
    """获取全局 EmbeddingManager 单例"""
    global _embedding_manager
    if _embedding_manager is None:
        _embedding_manager = EmbeddingManager()
    return _embedding_manager

