
from abc import ABC, abstractmethod
from typing import AsyncGenerator

class ModelService(ABC):
    """模型服务的抽象基类"""
    @abstractmethod
    async def generate_stream(self, prompt: str, system_prompt: str, **kwargs) -> AsyncGenerator[str, None]:
        """生成流式响应的抽象方法"""
        pass