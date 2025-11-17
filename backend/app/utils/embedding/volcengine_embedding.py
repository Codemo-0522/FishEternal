import os
import time
import torch
from typing import List, Optional
from volcenginesdkarkruntime import Ark

from langchain_core.embeddings import Embeddings


class ArkEmbeddings(Embeddings):
    """
    基于火山引擎 Ark 的嵌入模型封装，遵循 LangChain Embeddings 接口。

    模块化设计要点：
    - 不做文件读取、文本切分、向量库写入等任何 I/O 或策略决策；
      仅专注于“字符串 -> 向量”的转换。
    - 查询与文档嵌入行为一致，查询可选携带指令前缀以优化检索。
    - 可选维度截断（MRL）与向量归一化由本类内部完成。

    参数:
    - api_key: 必填。由调用方传入。
    - model: Ark 嵌入模型名，默认 "doubao-embedding-large-text-250515"。
    - mrl_dim: 可选的向量维度截断（如 2048 / 1024 / 512 / 256）。None 表示不截断。
    - normalize: 是否对输出向量进行 L2 归一化，默认 True。
    - query_instruction: 查询指令前缀，is_query=True 时生效；None/空串表示不加指令。
    """

    def __init__(
        self,
        api_key: str,
        model: str = "doubao-embedding-large-text-250515",
        mrl_dim: Optional[int] = None,
        normalize: bool = True,
        query_instruction: Optional[str] = (
            "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "
        ),
    ) -> None:
        if not api_key:
            raise ValueError("必须提供 api_key（由调用方传入）。")

        # 禁用 SDK 内置重试，避免与我们的重试机制冲突
        self.client = Ark(api_key=api_key, max_retries=0)
        self.model = model
        self.mrl_dim = mrl_dim
        self.normalize = normalize
        self.query_instruction = query_instruction or ""

    def _prepare_inputs(self, inputs: List[str], is_query: bool) -> List[str]:
        if is_query and self.query_instruction:
            prefix = self.query_instruction
            return [f"{prefix}{text}" for text in inputs]
        return inputs

    def _encode(self, inputs: List[str], is_query: bool = False, max_retries: int = 8) -> List[List[float]]:
        processed_inputs = self._prepare_inputs(inputs, is_query=is_query)

        # 带重试的请求逻辑（指数退避 + 抖动）
        for attempt in range(max_retries):
            try:
                resp = self.client.embeddings.create(
                    model=self.model,
                    input=processed_inputs,
                    encoding_format="float",
                )
                break  # 成功则跳出重试循环
            except Exception as e:
                # 检测限流错误（429 或 ServerOverloaded）
                is_rate_limit = (
                    "429" in str(e) or 
                    "TooManyRequests" in str(e) or 
                    "ServerOverloaded" in str(e) or
                    "RateLimitError" in str(type(e).__name__)
                )
                
                if is_rate_limit and attempt < max_retries - 1:
                    # 指数退避：5s, 10s, 20s, 40s, 80s, 160s, 320s
                    wait_time = 5 * (2 ** attempt)
                    print(f"⚠️  遇到限流（429 ServerOverloaded），等待 {wait_time}s 后重试（第 {attempt + 1}/{max_retries} 次）")
                    time.sleep(wait_time)
                    continue
                
                # 其他错误或最后一次重试失败，直接抛出
                raise

        embedding_tensor = torch.tensor(
            [d.embedding for d in resp.data], dtype=torch.bfloat16
        )

        # 维度截断（若指定）
        if self.mrl_dim is not None and self.mrl_dim > 0:
            max_dim = embedding_tensor.shape[1]
            slice_dim = min(self.mrl_dim, max_dim)
            embedding_tensor = embedding_tensor[:, :slice_dim]

        # L2 归一化（可选）
        if self.normalize:
            embedding_tensor = torch.nn.functional.normalize(embedding_tensor, dim=1, p=2)

        return embedding_tensor.float().tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # 降低批次大小以减少服务器压力
        batch_size = 128  # 从 256 降低到 128
        all_embeddings = []
        total_batches = (len(texts) + batch_size - 1) // batch_size
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_num = i // batch_size + 1
            print(f"📦 处理批次 {batch_num}/{total_batches}（{len(batch)} 条文本）")
            
            batch_embeddings = self._encode(batch, is_query=False)
            all_embeddings.extend(batch_embeddings)
            
            # 在批次之间添加更长延迟，避免触发限流
            if i + batch_size < len(texts):
                wait_time = 5  # 增加到 5 秒
                print(f"⏳ 批次间延迟 {wait_time}s，避免限流...")
                time.sleep(wait_time)
        
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        return self._encode([text], is_query=True)[0]


__all__ = ["ArkEmbeddings"]
