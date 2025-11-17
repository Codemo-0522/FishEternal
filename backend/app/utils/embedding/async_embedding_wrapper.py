"""
企业级异步嵌入模型包装器
支持高并发、连接池、熔断器、重试机制等企业级特性
"""
import asyncio
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any, Union
from dataclasses import dataclass
from contextlib import asynccontextmanager
import aiohttp
import json
from functools import wraps

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingConfig:
    """嵌入处理配置"""
    # 并发控制
    max_workers: int = 4  # 最大工作线程数
    max_concurrent_requests: int = 10  # 最大并发请求数
    batch_size: int = 32  # 批处理大小
    
    # 超时配置
    request_timeout: float = 30.0  # 单次请求超时
    total_timeout: float = 300.0  # 总处理超时
    
    # 重试配置
    max_retries: int = 3  # 最大重试次数
    retry_delay: float = 1.0  # 重试延迟基数
    
    # 熔断器配置
    failure_threshold: int = 5  # 失败阈值
    recovery_timeout: float = 60.0  # 恢复超时
    
    # 连接池配置
    connector_limit: int = 100  # 连接池大小
    connector_limit_per_host: int = 30  # 每个主机的连接数


class CircuitBreaker:
    """熔断器实现"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    def can_execute(self) -> bool:
        """检查是否可以执行"""
        if self.state == "CLOSED":
            return True
        elif self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        else:  # HALF_OPEN
            return True
    
    def record_success(self):
        """记录成功"""
        self.failure_count = 0
        self.state = "CLOSED"
        
    def record_failure(self):
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"


def async_retry(max_retries: int = 3, delay: float = 1.0):
    """异步重试装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = delay * (2 ** attempt)  # 指数退避
                        logger.warning(f"重试 {attempt + 1}/{max_retries}, 等待 {wait_time}s: {str(e)}")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"重试失败，已达到最大重试次数: {str(e)}")
            raise last_exception
        return wrapper
    return decorator


class AsyncEmbeddingPool:
    """异步嵌入处理池"""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.executor = ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="embedding"
        )
        self.semaphore = asyncio.Semaphore(config.max_concurrent_requests)
        self.circuit_breaker = CircuitBreaker(
            config.failure_threshold,
            config.recovery_timeout
        )
        self._session = None
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        connector = aiohttp.TCPConnector(
            limit=self.config.connector_limit,
            limit_per_host=self.config.connector_limit_per_host,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self._session:
            await self._session.close()
        self.executor.shutdown(wait=True)
        
    async def execute_with_circuit_breaker(self, func, *args, **kwargs):
        """带熔断器的执行"""
        if not self.circuit_breaker.can_execute():
            raise Exception("熔断器开启，拒绝执行")
            
        try:
            result = await func(*args, **kwargs)
            self.circuit_breaker.record_success()
            return result
        except Exception as e:
            self.circuit_breaker.record_failure()
            raise


class AsyncMiniLMEmbeddings:
    """异步本地嵌入模型包装器"""
    
    def __init__(self, base_embedding: Embeddings, config: EmbeddingConfig):
        self.base_embedding = base_embedding
        self.config = config
        self.pool = AsyncEmbeddingPool(config)
        
    async def __aenter__(self):
        await self.pool.__aenter__()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.pool.__aexit__(exc_type, exc_val, exc_tb)
    
    @async_retry(max_retries=3, delay=1.0)
    async def embed_documents_async(self, texts: List[str]) -> List[List[float]]:
        """异步批量嵌入文档"""
        if not texts:
            return []
            
        async with self.pool.semaphore:
            return await self.pool.execute_with_circuit_breaker(
                self._embed_batch, texts
            )
    
    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入处理"""
        # 分批处理大量文本
        batch_size = self.config.batch_size
        results = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            # 在线程池中执行CPU密集型操作
            loop = asyncio.get_event_loop()
            batch_result = await loop.run_in_executor(
                self.pool.executor,
                self.base_embedding.embed_documents,
                batch
            )
            results.extend(batch_result)
            
            # 让出控制权，避免长时间阻塞
            await asyncio.sleep(0.001)
            
        return results
    
    async def embed_query_async(self, text: str) -> List[float]:
        """异步嵌入查询"""
        async with self.pool.semaphore:
            return await self.pool.execute_with_circuit_breaker(
                self._embed_single, text
            )
    
    async def _embed_single(self, text: str) -> List[float]:
        """单个文本嵌入"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.pool.executor,
            self.base_embedding.embed_query,
            text
        )


class AsyncArkEmbeddings:
    """异步火山引擎嵌入模型包装器"""
    
    def __init__(self, api_key: str, model: str, config: EmbeddingConfig):
        self.api_key = api_key
        self.model = model
        self.config = config
        self.pool = AsyncEmbeddingPool(config)
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3/embeddings"
        
    async def __aenter__(self):
        await self.pool.__aenter__()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.pool.__aexit__(exc_type, exc_val, exc_tb)
    
    @async_retry(max_retries=5, delay=2.0)
    async def embed_documents_async(self, texts: List[str]) -> List[List[float]]:
        """异步批量嵌入文档"""
        if not texts:
            return []
            
        async with self.pool.semaphore:
            return await self.pool.execute_with_circuit_breaker(
                self._embed_via_api, texts, False
            )
    
    async def embed_query_async(self, text: str) -> List[float]:
        """异步嵌入查询"""
        async with self.pool.semaphore:
            result = await self.pool.execute_with_circuit_breaker(
                self._embed_via_api, [text], True
            )
            return result[0] if result else []
    
    async def _embed_via_api(self, texts: List[str], is_query: bool) -> List[List[float]]:
        """通过API进行嵌入"""
        # 处理查询指令
        if is_query:
            query_instruction = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "
            processed_texts = [f"{query_instruction}{text}" for text in texts]
        else:
            processed_texts = texts
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "input": processed_texts,
            "encoding_format": "float"
        }
        
        async with self.pool._session.post(
            self.base_url,
            headers=headers,
            json=payload
        ) as response:
            if response.status == 429:
                # 处理限流
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"API限流，等待 {retry_after}s")
                await asyncio.sleep(retry_after)
                raise aiohttp.ClientResponseError(
                    request_info=response.request_info,
                    history=response.history,
                    status=429,
                    message="Rate limited"
                )
            
            response.raise_for_status()
            data = await response.json()
            
            return [item["embedding"] for item in data["data"]]


class EmbeddingManager:
    """嵌入管理器 - 统一管理不同类型的嵌入模型"""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._embeddings: Dict[str, Any] = {}
        
    async def get_embedding(self, provider: str, **kwargs) -> Union[AsyncMiniLMEmbeddings, AsyncArkEmbeddings]:
        """获取嵌入实例"""
        cache_key = f"{provider}_{hash(str(sorted(kwargs.items())))}"
        
        if cache_key not in self._embeddings:
            if provider == "local":
                from .all_mini_embedding import MiniLMEmbeddings
                base_embedding = MiniLMEmbeddings(**kwargs)
                embedding = AsyncMiniLMEmbeddings(base_embedding, self.config)
            elif provider == "ark":
                embedding = AsyncArkEmbeddings(
                    api_key=kwargs["api_key"],
                    model=kwargs.get("model", "doubao-embedding-large-text-250515"),
                    config=self.config
                )
            else:
                raise ValueError(f"不支持的嵌入提供商: {provider}")
                
            self._embeddings[cache_key] = embedding
            
        return self._embeddings[cache_key]
    
    async def cleanup(self):
        """清理资源"""
        for embedding in self._embeddings.values():
            if hasattr(embedding, '__aexit__'):
                await embedding.__aexit__(None, None, None)
        self._embeddings.clear()


# 全局嵌入管理器实例
_embedding_manager = None

async def get_embedding_manager() -> EmbeddingManager:
    """获取全局嵌入管理器"""
    global _embedding_manager
    if _embedding_manager is None:
        config = EmbeddingConfig()
        _embedding_manager = EmbeddingManager(config)
    return _embedding_manager


__all__ = [
    "EmbeddingConfig",
    "AsyncMiniLMEmbeddings", 
    "AsyncArkEmbeddings",
    "EmbeddingManager",
    "get_embedding_manager"
]
