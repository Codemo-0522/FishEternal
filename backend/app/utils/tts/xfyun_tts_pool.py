# -*- coding:utf-8 -*-
"""
讯飞TTS连接池实现
"""
import asyncio
import json
import base64
import hashlib
import hmac
import logging
import websockets
from datetime import datetime
from time import mktime
from wsgiref.handlers import format_date_time
from urllib.parse import urlencode
from typing import Callable, Any
from .base_tts_pool import BaseTTSConnectionPool

logger = logging.getLogger(__name__)


class XfyunTTSPool(BaseTTSConnectionPool):
    """讯飞TTS连接池"""
    
    def __init__(
        self,
        appid: str,
        api_key: str,
        api_secret: str,
        max_connections: int = 5,
        connection_timeout: float = 10.0,  # 降低超时时间：30s -> 10s
        idle_timeout: float = 300.0,
        max_retries: int = 2  # 降低重试次数：3 -> 2
    ):
        """
        初始化讯飞TTS连接池
        
        Args:
            appid: 应用ID
            api_key: API密钥
            api_secret: API密钥
            max_connections: 最大连接数
            connection_timeout: 连接超时时间
            idle_timeout: 空闲超时时间
            max_retries: 最大重试次数
        """
        super().__init__(max_connections, connection_timeout, idle_timeout, max_retries)
        
        self.appid = appid
        self.api_key = api_key
        self.api_secret = api_secret
        self.host = "tts-api.xfyun.cn"
        self.base_url = "wss://tts-api.xfyun.cn/v2/tts"
        
        logger.info(f"初始化讯飞TTS连接池: appid={appid}")
    
    def _create_auth_url(self) -> str:
        """生成带有鉴权信息的websocket连接URL"""
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))
        
        # 拼接鉴权字符串
        signature_origin = "host: " + self.host + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/tts " + "HTTP/1.1"
        
        # 进行hmac-sha256加密
        signature_sha = hmac.new(
            self.api_secret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')
        
        # 构建Authorization参数
        authorization_origin = "api_key=\"%s\", algorithm=\"%s\", headers=\"%s\", signature=\"%s\"" % (
            self.api_key, "hmac-sha256", "host date request-line", signature_sha)
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        
        # 构建完整URL
        v = {
            "authorization": authorization,
            "date": date,
            "host": self.host
        }
        return self.base_url + '?' + urlencode(v)
    
    async def create_connection(self) -> Any:
        """创建新的WebSocket连接"""
        try:
            url = self._create_auth_url()
            websocket = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10
            )
            logger.info(f"讯飞WebSocket连接已建立: {self.base_url}")
            return websocket
            
        except Exception as e:
            logger.error(f"创建讯飞WebSocket连接失败: {e}")
            raise
    
    async def close_connection(self, websocket: Any):
        """关闭WebSocket连接"""
        try:
            await websocket.close()
            logger.info("讯飞WebSocket连接已关闭")
        except Exception as e:
            logger.error(f"关闭讯飞WebSocket连接失败: {e}")
    
    async def ping_connection(self, websocket: Any) -> bool:
        """检查连接是否存活"""
        try:
            # 检查WebSocket状态
            from websockets.protocol import State
            if websocket.state != State.OPEN:
                return False
            
            # 🔧 讯飞服务器对连接超时要求严格，禁用连接复用
            # 即使 ping 成功，也不复用连接，始终创建新连接
            logger.info("讯飞TTS不复用连接，始终创建新连接")
            return False
            
        except Exception as e:
            logger.warning(f"连接检查失败: {e}")
            return False
    
    def _create_request_json(self, text: str, vcn: str) -> dict:
        """创建请求JSON"""
        return {
            "common": {
                "app_id": self.appid
            },
            "business": {
                "aue": "raw",
                "auf": "audio/L16;rate=16000",
                "vcn": vcn,
                "tte": "utf8"
            },
            "data": {
                "status": 2,
                "text": str(base64.b64encode(text.encode('utf-8')), "UTF8")
            }
        }
    
    async def send_request(
        self,
        websocket: Any,
        text: str,
        callback: Callable[[bytes], None],
        **kwargs
    ) -> bool:
        """
        发送TTS请求并处理响应
        
        Args:
            websocket: WebSocket连接
            text: 要合成的文本
            callback: 音频数据回调函数
            **kwargs: 其他参数（vcn等）
            
        Returns:
            是否成功
        """
        vcn = kwargs.get('vcn', 'x4_yezi')
        
        try:
            # 发送请求
            request_json = self._create_request_json(text, vcn)
            await websocket.send(json.dumps(request_json))
            logger.debug(f"已发送讯飞TTS请求: text_length={len(text)}, vcn={vcn}")
            
            # 接收响应
            is_done = False
            has_error = False
            error_message = None
            
            while not is_done:
                try:
                    # 设置接收超时
                    response = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=self.connection_timeout
                    )
                    
                    # 解析响应
                    message = json.loads(response)
                    code = message.get("code")
                    sid = message.get("sid")
                    
                    if code != 0:
                        error_msg = message.get("message", "未知错误")
                        logger.error(f"讯飞TTS错误: sid={sid}, code={code}, message={error_msg}")
                        has_error = True
                        error_message = error_msg
                        break
                    
                    # 处理音频数据
                    if "data" in message and "audio" in message["data"]:
                        audio = message["data"]["audio"]
                        status = message["data"]["status"]
                        
                        # 检查audio是否为None
                        if audio is None:
                            logger.warning(f"收到空的audio字段，status={status}，跳过此帧")
                            if status == 2:
                                is_done = True
                            continue
                        
                        # 解码音频数据
                        try:
                            audio_data = base64.b64decode(audio)
                            callback(audio_data)
                        except Exception as e:
                            logger.error(f"音频数据解码失败: {e}")
                            has_error = True
                            error_message = str(e)
                            break
                        
                        # 最后一帧
                        if status == 2:
                            is_done = True
                    
                except asyncio.TimeoutError:
                    logger.error("接收讯飞TTS响应超时")
                    has_error = True
                    error_message = "接收响应超时"
                    break
                except Exception as e:
                    logger.error(f"接收讯飞TTS响应失败: {e}")
                    has_error = True
                    error_message = str(e)
                    break
            
            if has_error:
                logger.error(f"讯飞TTS请求失败: {error_message}")
                return False
            
            logger.debug(f"讯飞TTS请求成功: text_length={len(text)}")
            return True
            
        except Exception as e:
            logger.error(f"发送讯飞TTS请求失败: {e}")
            return False

