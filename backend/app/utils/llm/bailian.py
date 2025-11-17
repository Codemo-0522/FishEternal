from .unified_openai import UnifiedOpenAIService


class BaiLianService(UnifiedOpenAIService):
    """
    阿里云百炼（通义千问）服务
    
    使用统一的 OpenAI 兼容服务，只需指定 provider 即可
    所有特性通过配置自动适配
    
    注意：阿里云百炼提供两个地域的服务：
    - 北京地域：https://dashscope.aliyuncs.com/compatible-mode/v1
    - 新加坡地域：https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    """
    
    def __init__(self, base_url: str, api_key: str, model_name: str):
        super().__init__(base_url, api_key, model_name, provider="bailian")

