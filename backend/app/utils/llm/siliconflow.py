from .unified_openai import UnifiedOpenAIService


class SiliconFlowService(UnifiedOpenAIService):
    """
    硅基流动服务
    
    使用统一的 OpenAI 兼容服务，只需指定 provider 即可
    所有特性通过配置自动适配
    """
    
    def __init__(self, base_url: str, api_key: str, model_name: str):
        super().__init__(base_url, api_key, model_name, provider="siliconflow")
