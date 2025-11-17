import json
import time
import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class OllamaEmbeddings:
    """Embedding wrapper compatible with LangChain's embedding_function interface.

    Calls local Ollama server's /api/embeddings endpoint.
    """

    def __init__(
        self,
        model: str,  # ✅ 移除默认值，强制用户明确指定模型
        base_url: str = "http://localhost:11434",  # 保留默认值，因为大多数情况下都是本地服务
        timeout_seconds: int = 15,  # 🔧 降低超时时间从60秒到15秒
        max_retries: int = 2,  # 🔧 降低重试次数从3到2
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._session = requests.Session()

    def _embed_one(self, text: str) -> List[float]:
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self.model, "prompt": text}
        last_err: Optional[Exception] = None
        
        logger.debug(f"🔍 Ollama请求: url={url}, model={self.model}, timeout={self.timeout_seconds}s")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"🔄 Ollama请求尝试 {attempt}/{self.max_retries}")
                resp = self._session.post(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout_seconds,
                )
                resp.raise_for_status()
                data = resp.json()
                emb = data.get("embedding")
                if not isinstance(emb, list):
                    raise ValueError(f"Unexpected response (no 'embedding'): {data}")
                logger.debug(f"✅ Ollama请求成功，向量维度: {len(emb)}")
                return emb
            except requests.exceptions.Timeout as e:
                last_err = e
                logger.warning(f"⏱️ Ollama请求超时 (尝试 {attempt}/{self.max_retries}): {self.base_url} - 超时时间: {self.timeout_seconds}s")
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                else:
                    raise RuntimeError(
                        f"❌ Ollama服务无响应（{self.base_url}），已超时 {self.timeout_seconds}秒。"
                        f"请检查：1) Ollama服务是否启动 2) 端口是否正确 3) 模型'{self.model}'是否已下载"
                    )
            except requests.exceptions.ConnectionError as e:
                last_err = e
                logger.error(f"🔌 无法连接到Ollama服务: {self.base_url}")
                raise RuntimeError(
                    f"❌ 无法连接到Ollama服务（{self.base_url}）。"
                    f"请检查：1) Ollama服务是否启动 2) 地址和端口是否正确"
                )
            except Exception as e:
                last_err = e
                logger.error(f"❌ Ollama请求失败 (尝试 {attempt}/{self.max_retries}): {type(e).__name__}: {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
                else:
                    raise RuntimeError(
                        f"❌ Ollama embeddings请求失败（{self.max_retries}次尝试后）: {last_err}"
                    )
        raise RuntimeError("Unreachable")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_one(text)


__all__ = ["OllamaEmbeddings"] 