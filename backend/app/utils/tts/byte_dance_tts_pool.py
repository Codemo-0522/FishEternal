# -*- coding:utf-8 -*-
"""
字节跳动TTS连接池实现
"""
import asyncio
import json
import gzip
import uuid
import logging
import websockets
from typing import Callable, Any
from .base_tts_pool import BaseTTSConnectionPool

logger = logging.getLogger(__name__)


class ByteDanceTTSPool(BaseTTSConnectionPool):
    """字节跳动TTS连接池"""
    
    MESSAGE_TYPES = {
        11: "audio-only server response",
        12: "frontend server response",
        15: "error message from server"
    }
    
    def __init__(
        self,
        appid: str,
        token: str,
        cluster: str,
        max_connections: int = 5,
        connection_timeout: float = 10.0,  # 降低超时时间：30s -> 10s
        idle_timeout: float = 300.0,
        max_retries: int = 2  # 降低重试次数：3 -> 2
    ):
        """
        初始化字节跳动TTS连接池
        
        Args:
            appid: 应用ID
            token: 访问令牌
            cluster: 集群名称
            max_connections: 最大连接数
            connection_timeout: 连接超时时间
            idle_timeout: 空闲超时时间
            max_retries: 最大重试次数
        """
        super().__init__(max_connections, connection_timeout, idle_timeout, max_retries)
        
        self.appid = appid
        self.token = token
        self.cluster = cluster
        self.host = "openspeech.bytedance.com"
        self.api_url = f"wss://{self.host}/api/v1/tts/ws_binary"
        self.default_header = bytearray(b'\x11\x10\x11\x00')
        
        logger.info(f"初始化字节跳动TTS连接池: appid={appid}, cluster={cluster}")
    
    async def create_connection(self) -> Any:
        """创建新的WebSocket连接"""
        headers = {"Authorization": f"Bearer; {self.token}"}
        
        try:
            # websockets 11.x 使用 additional_headers 而不是 extra_headers
            websocket = await websockets.connect(
                self.api_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10
            )
            logger.info(f"字节跳动WebSocket连接已建立: {self.api_url}")
            return websocket
            
        except Exception as e:
            logger.error(f"创建字节跳动WebSocket连接失败: {e}")
            raise
    
    async def close_connection(self, websocket: Any):
        """关闭WebSocket连接"""
        try:
            await websocket.close()
            logger.info("字节跳动WebSocket连接已关闭")
        except Exception as e:
            logger.error(f"关闭字节跳动WebSocket连接失败: {e}")
    
    async def ping_connection(self, websocket: Any) -> bool:
        """检查连接是否存活"""
        try:
            # 检查WebSocket状态
            from websockets.protocol import State
            if websocket.state != State.OPEN:
                return False
            
            # 尝试发送ping（缩短超时：5s -> 2s）
            pong = await websocket.ping()
            await asyncio.wait_for(pong, timeout=2.0)
            return True
            
        except Exception as e:
            logger.warning(f"连接检查失败: {e}")
            return False
    
    def _create_request_json(self, text: str, voice_type: str) -> dict:
        """创建请求JSON"""
        return {
            "app": {
                "appid": self.appid,
                "token": "access_token",
                "cluster": self.cluster
            },
            "user": {
                "uid": "388808087185088"
            },
            "audio": {
                "voice_type": voice_type,
                "encoding": "mp3",
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "submit"
            }
        }
    
    def _create_request_bytes(self, text: str, voice_type: str) -> bytearray:
        """创建请求字节数组"""
        request_json = self._create_request_json(text, voice_type)
        payload_bytes = str.encode(json.dumps(request_json))
        payload_bytes = gzip.compress(payload_bytes)
        
        full_request = bytearray(self.default_header)
        full_request.extend(len(payload_bytes).to_bytes(4, 'big'))
        full_request.extend(payload_bytes)
        return full_request
    
    def _parse_response(self, res: bytes) -> tuple[bool, bytes | None, str | None]:
        """
        解析响应数据
        
        Returns:
            (is_done, audio_data, error_message)
        """
        try:
            protocol_version = res[0] >> 4
            header_size = res[0] & 0x0f
            message_type = res[1] >> 4
            message_type_specific_flags = res[1] & 0x0f
            serialization_method = res[2] >> 4
            message_compression = res[2] & 0x0f
            reserved = res[3]
            header_extensions = res[4:header_size * 4]
            payload = res[header_size * 4:]
            
            if message_type == 0xb:  # 音频数据响应
                if message_type_specific_flags == 0:
                    return False, None, None
                
                sequence_number = int.from_bytes(payload[:4], "big", signed=True)
                payload_size = int.from_bytes(payload[4:8], "big", signed=False)
                audio_data = payload[8:]
                
                return sequence_number < 0, audio_data, None  # 序列<0表示结束
            
            elif message_type == 0xf:  # 错误响应
                code = int.from_bytes(payload[:4], "big", signed=False)
                msg_size = int.from_bytes(payload[4:8], "big", signed=False)
                error_msg = payload[8:]
                if message_compression == 1:
                    error_msg = gzip.decompress(error_msg)
                error_msg = str(error_msg, "utf-8")
                logger.error(f"字节跳动TTS错误: code={code}, message={error_msg}")
                return True, None, error_msg
            
            elif message_type == 0xc:  # 前端消息响应
                msg_size = int.from_bytes(payload[:4], "big", signed=False)
                msg_data = payload[4:]
                if message_compression == 1:
                    msg_data = gzip.decompress(msg_data)
                logger.debug(f"字节跳动前端消息: {msg_data}")
                return False, None, None
            
            return False, None, None
            
        except Exception as e:
            logger.error(f"解析响应失败: {e}")
            return True, None, str(e)
    
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
            **kwargs: 其他参数（voice_type等）
            
        Returns:
            是否成功
        """
        voice_type = kwargs.get('voice_type', 'zh_female_wanwanxiaohe_moon_bigtts')
        
        try:
            # 发送请求
            request_bytes = self._create_request_bytes(text, voice_type)
            await websocket.send(request_bytes)
            logger.debug(f"已发送字节跳动TTS请求: text_length={len(text)}, voice_type={voice_type}")
            
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
                    is_done, audio_data, error_msg = self._parse_response(response)
                    
                    if error_msg:
                        has_error = True
                        error_message = error_msg
                        break
                    
                    if audio_data:
                        # 调用回调函数
                        callback(audio_data)
                    
                except asyncio.TimeoutError:
                    logger.error("接收字节跳动TTS响应超时")
                    has_error = True
                    error_message = "接收响应超时"
                    break
                except Exception as e:
                    logger.error(f"接收字节跳动TTS响应失败: {e}")
                    has_error = True
                    error_message = str(e)
                    break
            
            if has_error:
                logger.error(f"字节跳动TTS请求失败: {error_message}")
                return False
            
            logger.debug(f"字节跳动TTS请求成功: text_length={len(text)}")
            return True
            
        except Exception as e:
            logger.error(f"发送字节跳动TTS请求失败: {e}")
            return False

