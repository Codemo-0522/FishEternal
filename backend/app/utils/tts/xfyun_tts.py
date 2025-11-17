# -*- coding:utf-8 -*-
import websocket
import datetime
import hashlib
import base64
import hmac
import json
from urllib.parse import urlencode
import time
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread
import os
import wave
import logging
from typing import Optional
import uuid
import asyncio
import websockets
from typing import Optional, Dict, Any, List
from ..text_cleaner import clean_text, parse_pattern_string

# 配置日志
logger = logging.getLogger(__name__)

class Ws_Param(object):
    """语音合成Websocket参数类"""
    def __init__(self, appid, api_key, api_secret, text, outfile='./output.pcm',
                 vcn='x4_yezi', aue='raw', auf='audio/L16;rate=16000', tte='utf8'):
        self.appid = appid
        self.api_key = api_key
        self.api_secret = api_secret
        self.text = text
        self.outfile = outfile

        # 公共参数
        self.common_args = {"app_id": self.appid}
        # 业务参数
        self.business_args = {"aue": aue, "auf": auf, "vcn": vcn, "tte": tte}
        # 待合成文本数据
        self.data = {"status": 2, "text": str(base64.b64encode(self.text.encode('utf-8')), "UTF8")}

    def create_url(self):
        """生成带有鉴权信息的websocket连接URL"""
        url = 'wss://tts-api.xfyun.cn/v2/tts'
        host = 'tts-api.xfyun.cn'  # 修复：使用正确的host，必须与URL中的域名一致
        
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))
        
        # 拼接鉴权字符串
        signature_origin = "host: " + host + "\n"
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
            "host": host
        }
        return url + '?' + urlencode(v)

def clean_text_for_tts(
    text: str, 
    patterns: Optional[str] = None,
    preserve_quotes: bool = True
) -> str:
    """
    清洗文本用于TTS生成（已废弃，保留以兼容旧代码）
    
    Args:
        text: 原始文本
        patterns: 正则表达式字符串（用分号分隔），或 None 使用默认规则
        preserve_quotes: 是否保留引号内容
    
    Returns:
        清洗后的文本
    """
    # 如果 patterns 是字符串，解析为列表
    if isinstance(patterns, str):
        pattern_list = parse_pattern_string(patterns)
    else:
        pattern_list = None
    
    return clean_text(text, pattern_list, preserve_quotes)

class XfyunTTSClient:
    """科大讯飞语音合成客户端"""
    def __init__(self, appid: str, api_key: str, api_secret: str):
        self.appid = appid
        self.api_key = api_key
        self.api_secret = api_secret
        self.pcm_file = None
        self.is_success = False

    def synthesize(self, text: str, outfile: str, vcn: str = 'x4_yezi') -> bool:
        """执行语音合成"""
        self.pcm_file = outfile
        self.is_success = False

        # 确保输出目录存在
        os.makedirs(os.path.dirname(os.path.abspath(outfile)), exist_ok=True)

        # 创建WebSocket参数
        ws_param = Ws_Param(
            appid=self.appid,
            api_key=self.api_key,
            api_secret=self.api_secret,
            text=text,
            outfile=outfile,
            vcn=vcn
        )

        # 创建WebSocket连接
        websocket.enableTrace(False)
        ws_url = ws_param.create_url()

        # 定义回调函数
        def on_message(ws, message):
            try:
                message = json.loads(message)
                code = message["code"]
                sid = message["sid"]

                if code != 0:
                    err_msg = message["message"]
                    logger.error(f"sid:{sid} 调用错误:{err_msg} 错误码:{code}")
                    ws.close()
                    return

                if "data" in message and "audio" in message["data"]:
                    audio = message["data"]["audio"]
                    status = message["data"]["status"]
                    
                    # 检查audio是否为None（讯飞云偶尔会发送空的audio字段）
                    if audio is None:
                        logger.warning(f"收到空的audio字段，status={status}，跳过此帧")
                        # 如果是最后一帧且之前有数据，仍然标记为成功
                        if status == 2 and os.path.exists(outfile) and os.path.getsize(outfile) > 0:
                            self.is_success = True
                            logger.info(f"合成完成（收到空的最后一帧），音频已保存至: {outfile}")
                            ws.close()
                        return
                    
                    # 解码音频数据
                    try:
                        audio = base64.b64decode(audio)
                    except Exception as e:
                        logger.error(f"音频数据解码失败: {e}, audio类型: {type(audio)}")
                        return

                    # 追加音频数据到文件
                    try:
                        with open(outfile, 'ab') as f:
                            f.write(audio)
                    except Exception as e:
                        logger.error(f"写入音频数据失败: {e}")
                        ws.close()
                        return

                    # 最后一帧时标记成功
                    if status == 2:
                        self.is_success = True
                        logger.info(f"合成完成，音频已保存至: {outfile}")
                        ws.close()

            except Exception as e:
                logger.error(f"接收消息解析异常: {e}")
                ws.close()

        def on_error(ws, error):
            logger.error(f"WebSocket错误: {error}")
            self.is_success = False

        def on_close(ws, close_status_code=None, close_msg=None):
            logger.info("WebSocket连接已关闭")

        def on_open(ws):
            def run(*args):
                try:
                    d = {
                        "common": ws_param.common_args,
                        "business": ws_param.business_args,
                        "data": ws_param.data,
                    }
                    d = json.dumps(d)
                    logger.info("------>开始发送文本数据")
                    ws.send(d)
                except Exception as e:
                    logger.error(f"发送数据失败: {e}")
                    ws.close()

            thread.start_new_thread(run, ())

        # 创建WebSocket应用并运行
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

        return self.is_success

def pcm_to_wav(pcm_file: str, wav_file: str, channels: int = 1, 
               sample_width: int = 2, sample_rate: int = 16000) -> bool:
    """将PCM文件转换为WAV文件"""
    try:
        logger.info(f"开始转换PCM到WAV - 输入: {pcm_file}, 输出: {wav_file}")
        
        # 检查输入文件
        if not os.path.exists(pcm_file):
            logger.error(f"错误: PCM文件不存在: {pcm_file}")
            return False
            
        pcm_size = os.path.getsize(pcm_file)
        if pcm_size == 0:
            logger.error("错误: PCM文件为空")
            return False
        
        # 读取PCM数据
        with open(pcm_file, 'rb') as pcm_f:
            pcm_data = pcm_f.read()
            logger.info(f"已读取PCM数据: {len(pcm_data)} 字节")
        
        # 创建WAV文件
        with wave.open(wav_file, 'wb') as wav_f:
            wav_f.setnchannels(channels)
            wav_f.setsampwidth(sample_width)
            wav_f.setframerate(sample_rate)
            wav_f.writeframes(pcm_data)
            logger.info(f"WAV文件写入完成: {wav_file}")
        
        # 验证输出文件
        if os.path.exists(wav_file):
            wav_size = os.path.getsize(wav_file)
            logger.info(f"WAV文件大小: {wav_size} 字节")
            return True
        else:
            logger.error("错误: WAV文件未能创建")
            return False
            
    except Exception as e:
        logger.error(f"PCM转WAV出错: {e}")
        return False

if __name__=="__main__":
    pass
