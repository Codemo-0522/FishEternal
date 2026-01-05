from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

class AsyncImageGenerationService(ABC):
    """图片生成服务的抽象基类"""

    @abstractmethod
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
        """提交一个异步图片生成任务并返回任务ID"""
        pass

    @abstractmethod
    async def get_task_result(
        self,
        task_id: str
    ) -> Dict[str, Any]:
        """根据任务ID获取任务状态和结果"""
        pass
