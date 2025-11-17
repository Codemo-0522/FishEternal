import httpx
import os
from typing import Union, BinaryIO
import logging

logger = logging.getLogger(__name__)


class SiliconFlowASR:
    """
    硅基流动 ASR 客户端
    
    设计说明：
    - 每次调用时实例化新对象（与 TTS 保持一致）
    - 支持多用户并发，每个用户使用自己的配置
    - 使用 httpx 支持异步调用
    """
    
    def __init__(self, api_key: str, base_url: str, model_name: str):
        """
        初始化 ASR 客户端
        
        Args:
            api_key: API 密钥
            base_url: API 地址
            model_name: 模型名称
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

    async def transcribe_async(self, audio_file_path: str) -> str:
        """
        异步语音识别（推荐使用）
        
        Args:
            audio_file_path: 音频文件路径
            
        Returns:
            识别的文本
            
        Raises:
            FileNotFoundError: 音频文件不存在
            RuntimeError: ASR 请求失败
        """
        if not os.path.exists(audio_file_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_file_path}")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(audio_file_path, "rb") as f:
                    files = {"file": (os.path.basename(audio_file_path), f, "audio/wav")}
                    data = {"model": self.model_name}

                    response = await client.post(
                        self.base_url,
                        headers=self.headers,
                        data=data,
                        files=files
                    )
                    response.raise_for_status()
                    result = response.json()
                    return result.get("text", "").strip()
                    
        except httpx.HTTPStatusError as e:
            error_msg = f"ASR 请求失败 (状态码 {e.response.status_code})"
            logger.error(f"{error_msg}: {e}")
            raise RuntimeError(error_msg)
        except httpx.RequestError as e:
            error_msg = f"ASR 网络请求失败: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"解析 ASR 响应失败: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    async def transcribe_from_bytes_async(self, audio_data: bytes, filename: str = "audio.wav") -> str:
        """
        从字节数据异步识别语音
        
        Args:
            audio_data: 音频字节数据
            filename: 文件名（用于 API 请求）
            
        Returns:
            识别的文本
        """
        logger.info(f"🔵 [ASR] 开始转录 - 文件: {filename}, 大小: {len(audio_data)} bytes")
        
        try:
            # 设置合理的超时时间：连接5秒，读取30秒
            timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                files = {"file": (filename, audio_data, "audio/wav")}
                data = {"model": self.model_name}
                
                logger.info(f"🔵 [ASR] 发送请求到 {self.base_url}")
                
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    data=data,
                    files=files
                )
                
                logger.info(f"🔵 [ASR] 收到响应 - 状态码: {response.status_code}")
                
                response.raise_for_status()
                result = response.json()
                text = result.get("text", "").strip()
                
                logger.info(f"🟢 [ASR] 转录成功 - 文本: {text[:50]}...")
                return text
                
        except httpx.TimeoutException as e:
            error_msg = f"ASR 请求超时: {e}"
            logger.error(f"🔴 [ASR] {error_msg}")
            raise RuntimeError(error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"ASR HTTP 错误 (状态码 {e.response.status_code}): {e.response.text}"
            logger.error(f"🔴 [ASR] {error_msg}")
            raise RuntimeError(error_msg)
        except httpx.RequestError as e:
            error_msg = f"ASR 网络请求失败: {e}"
            logger.error(f"🔴 [ASR] {error_msg}")
            raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"从字节数据识别失败: {e}"
            logger.error(f"🔴 [ASR] {error_msg}", exc_info=True)
            raise RuntimeError(f"ASR 请求失败: {e}")
    
    def transcribe(self, audio_file_path: str) -> str:
        """
        同步语音识别（兼容旧代码）
        
        注意：在异步环境中请使用 transcribe_async()
        """
        import asyncio
        
        try:
            # 尝试获取当前事件循环
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在异步环境中，建议使用 transcribe_async
                logger.warning("在异步环境中使用同步方法，建议使用 transcribe_async()")
                raise RuntimeError("请在异步环境中使用 transcribe_async() 方法")
            return loop.run_until_complete(self.transcribe_async(audio_file_path))
        except RuntimeError:
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.transcribe_async(audio_file_path))
            finally:
                loop.close()


if __name__ == "__main__":
    """
    测试示例
    
    支持的模型：
    1. "TeleAI/TeleSpeechASR"
    2. "FunAudioLLM/SenseVoiceSmall"
    """
    import asyncio
    
    async def test_asr():
        API_KEY = "sk-test123456789"
        BASE_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
        AUDIO_PATH = "tts_test.wav"

        # 实例化客户端（每次调用都创建新实例）
        client = SiliconFlowASR(
            api_key=API_KEY, 
            base_url=BASE_URL, 
            model_name="FunAudioLLM/SenseVoiceSmall"
        )
        
        try:
            # 使用异步方法
            text = await client.transcribe_async(AUDIO_PATH)
            print("转录结果:", text)
        except Exception as e:
            print("ASR 错误:", e)
    
    # 运行异步测试
    asyncio.run(test_asr())