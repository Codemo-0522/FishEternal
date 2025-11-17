# coding=utf-8

'''
requires Python 3.6 or later
pip install websocket-client
pip install gzip
'''

import websocket
import uuid
import json
import gzip
import os
import logging
import threading
import time
from typing import Optional, BinaryIO

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ByteDanceTTS:
    """字节跳动语音合成客户端（同步版本）"""

    MESSAGE_TYPES = {
        11: "audio-only server response",
        12: "frontend server response",
        15: "error message from server"
    }
    MESSAGE_TYPE_SPECIFIC_FLAGS = {
        0: "no sequence number",
        1: "sequence number > 0",
        2: "last message from server (seq < 0)",
        3: "sequence number < 0"
    }
    MESSAGE_SERIALIZATION_METHODS = {
        0: "no serialization",
        1: "JSON",
        15: "custom type"
    }
    MESSAGE_COMPRESSIONS = {
        0: "no compression",
        1: "gzip",
        15: "custom compression method"
    }

    def __init__(self, appid: str, token: str, cluster: str):
        """初始化TTS客户端"""
        self.appid = appid
        self.token = token  # 实际token，用于Authorization头
        self.cluster = cluster
        self.host = "openspeech.bytedance.com"
        self.api_url = f"wss://{self.host}/api/v1/tts/ws_binary"
        self.default_header = bytearray(b'\x11\x10\x11\x00')
        # 加在创建tts_client之后
        print(f"appid: {self.appid}")
        print(f"token: {self.token}")
        print(f"cluster: {self.cluster}")

        # 用于同步版本的状态变量
        self.is_done = False
        self.is_success = False
        self.error_message = None
        self.output_file = None

    def _create_request_json(self, text: str, voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts") -> dict:
        """创建请求JSON（与非类代码保持一致）"""
        return {
            "app": {
                "appid": self.appid,
                # 请求体中token固定为"access_token"
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
        """创建请求字节数组（与非类代码逻辑一致）"""
        request_json = self._create_request_json(text, voice_type)
        payload_bytes = str.encode(json.dumps(request_json))
        payload_bytes = gzip.compress(payload_bytes)  # 保持压缩逻辑

        full_request = bytearray(self.default_header)
        full_request.extend(len(payload_bytes).to_bytes(4, 'big'))  # 4字节 payload长度
        full_request.extend(payload_bytes)  # 附加payload
        return full_request

    def _parse_response(self, res: bytes, file: Optional[BinaryIO] = None) -> tuple[bool, Optional[bytes]]:
        """解析响应数据（与非类代码逻辑一致）"""
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_method = res[2] >> 4
        message_compression = res[2] & 0x0f
        reserved = res[3]
        header_extensions = res[4:header_size * 4]
        payload = res[header_size * 4:]

        logger.debug(f"Protocol version: {protocol_version:#x}")
        logger.debug(f"Header size: {header_size:#x} - {header_size * 4} bytes")
        logger.debug(f"Message type: {message_type:#x} - {self.MESSAGE_TYPES.get(message_type, 'unknown')}")
        logger.debug(f"Message flags: {message_type_specific_flags:#x}")
        logger.debug(f"Serialization: {serialization_method:#x}")
        logger.debug(f"Compression: {message_compression:#x}")

        if message_type == 0xb:  # 音频数据响应
            if message_type_specific_flags == 0:
                return False, None

            sequence_number = int.from_bytes(payload[:4], "big", signed=True)
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            audio_data = payload[8:]

            if file:
                file.write(audio_data)

            return sequence_number < 0, audio_data  # 序列<0表示结束

        elif message_type == 0xf:  # 错误响应
            code = int.from_bytes(payload[:4], "big", signed=False)
            msg_size = int.from_bytes(payload[4:8], "big", signed=False)
            error_msg = payload[8:]
            if message_compression == 1:
                error_msg = gzip.decompress(error_msg)
            error_msg = str(error_msg, "utf-8")
            logger.error(f"Error code: {code}, message: {error_msg}")
            self.error_message = error_msg
            return True, None

        elif message_type == 0xc:  # 前端消息响应
            msg_size = int.from_bytes(payload[:4], "big", signed=False)
            msg_data = payload[4:]
            if message_compression == 1:
                msg_data = gzip.decompress(msg_data)
            logger.info(f"Frontend message: {msg_data}")
            return False, None

        return True, None

    def synthesize_to_file(self, text: str, output_file: str,
                           voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts") -> bool:
        """合成音频到文件（同步版本）"""
        self.output_file = output_file
        self.is_done = False
        self.is_success = False
        self.error_message = None

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        # 创建WebSocket参数
        request_bytes = self._create_request_bytes(text, voice_type)
        headers = {"Authorization": f"Bearer; {self.token}"}

        # 创建并配置WebSocket
        ws = websocket.WebSocketApp(
            self.api_url,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )

        # 保存请求数据
        ws.request_bytes = request_bytes

        # 在独立线程中运行WebSocket
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()

        # 等待合成完成或超时
        timeout = 30  # 30秒超时
        start_time = time.time()
        while not self.is_done and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        # 检查是否超时
        if not self.is_done:
            logger.error(f"合成超时: {timeout}秒")
            ws.close()
            return False

        # 检查是否成功
        if not self.is_success:
            logger.error(f"合成失败: {self.error_message}")
            return False

        # 验证文件大小
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            return True
        else:
            logger.error(f"生成的文件为空: {output_file}")
            return False

    def _on_open(self, ws):
        """WebSocket连接打开时的回调"""
        logger.info("WebSocket连接已建立")
        ws.send(ws.request_bytes)  # 发送请求数据

    def _on_message(self, ws, message):
        """收到WebSocket消息时的回调"""
        try:
            # 以二进制方式处理消息
            if isinstance(message, str):
                message = message.encode('utf-8')

            # 打开文件进行追加写入
            with open(self.output_file, 'ab') as f:
                done, _ = self._parse_response(message, f)

            # 检查是否完成
            if done:
                self.is_done = True
                self.is_success = True
                ws.close()

        except Exception as e:
            logger.error(f"处理消息时出错: {str(e)}")
            self.is_done = True
            self.is_success = False
            self.error_message = str(e)
            ws.close()

    def _on_error(self, ws, error):
        """WebSocket出错时的回调"""
        logger.error(f"WebSocket错误: {str(error)}")
        self.is_done = True
        self.is_success = False
        self.error_message = str(error)

    def _on_close(self, ws, close_status_code, close_msg):
        """WebSocket关闭时的回调"""
        logger.info(f"WebSocket连接已关闭: {close_status_code} {close_msg}")
        if not self.is_done:
            self.is_done = True
            self.is_success = False
            self.error_message = f"连接意外关闭: {close_status_code} {close_msg}"