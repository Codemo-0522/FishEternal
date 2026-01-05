import httpx
import asyncio
from typing import Optional, Dict, Any

from .base import AsyncImageGenerationService

class ModelScopeImageGenerationService(AsyncImageGenerationService):
    """ModelScope 异步图片生成服务"""

    def __init__(self, api_key: str, base_url: str = 'https://api-inference.modelscope.cn/v1'):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def submit_task(
        self,
        prompt: str,
        model: str,
        negative_prompt: Optional[str] = None,
        size: str = "1024*1024",
        n: int = 1,
        seed: Optional[int] = None,
        steps: int = 50,
        **kwargs: Any
    ) -> Optional[str]:
        parameters = {
            "size": size,
            "n": n,
            "steps": steps
        }
        if negative_prompt:
            parameters["negative_prompt"] = negative_prompt
        if seed:
            parameters["seed"] = seed

        payload = {
            "model": model,
            "prompt": prompt,
            "parameters": parameters
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/images/generations",
                    headers={**self.headers, "X-ModelScope-Async-Mode": "true"},
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                data = response.json()
                task_id = data.get("task_id")
                if not task_id:
                    print(f"提交失败，未获取到task_id: {data}")
                    return None
                return task_id
            except httpx.RequestError as e:
                print(f"提交任务时发生网络错误: {e}")
                return None

    async def get_task_result(self, task_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/tasks/{task_id}",
                    headers={**self.headers, "X-ModelScope-Task-Type": "image_generation"},
                    timeout=60
                )
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                print(f"查询结果时发生网络错误: {e}")
                return {"task_status": "FAILED", "output": {"message": str(e)}}
