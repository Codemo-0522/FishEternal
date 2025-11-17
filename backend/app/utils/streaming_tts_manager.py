# -*- coding:utf-8 -*-
import asyncio
import logging
import os
import uuid
from typing import Optional, Dict
from .text_splitter import split_text_for_streaming_tts
from .tts.xfyun_tts import pcm_to_wav, clean_text_for_tts
from .tts.byte_dance_tts_pool import ByteDanceTTSPool
from .tts.xfyun_tts_pool import XfyunTTSPool

logger = logging.getLogger(__name__)

# 全局TTS连接池实例
_tts_pools: Dict[str, any] = {}


def get_tts_pool(tts_type: str, tts_config: dict):
    """获取或创建TTS连接池"""
    pool_key = f"{tts_type}_{tts_config.get('appId', '')}"
    
    if pool_key not in _tts_pools:
        if tts_type == "xfyun" or tts_type == "xfyun_tts":
            _tts_pools[pool_key] = XfyunTTSPool(
                appid=tts_config.get("appId", ""),
                api_key=tts_config.get("apiKey", ""),
                api_secret=tts_config.get("apiSecret", ""),
                max_connections=50,  # 连接池大小：支持50个并发WebSocket连接（通过队列可处理更多请求）
                connection_timeout=30.0,
                idle_timeout=300.0
            )
            logger.info(f"创建讯飞TTS连接池: {pool_key}, max_connections=50")
        elif tts_type == "bytedance" or tts_type == "bytedance_tts":
            _tts_pools[pool_key] = ByteDanceTTSPool(
                appid=tts_config.get("appId", ""),
                token=tts_config.get("token", ""),
                cluster=tts_config.get("cluster", ""),
                max_connections=50,  # 连接池大小：支持50个并发WebSocket连接（通过队列可处理更多请求）
                connection_timeout=30.0,
                idle_timeout=300.0
            )
            logger.info(f"创建字节跳动TTS连接池: {pool_key}, max_connections=50")
        else:
            raise ValueError(f"不支持的TTS类型: {tts_type}")
    
    return _tts_pools[pool_key]


class StreamingTTSManager:
    """流式TTS管理器 - 边接收边合成边发送"""
    
    def __init__(self):
        self.sessions: Dict[str, 'TTSSession'] = {}
    
    def create_session(
        self,
        session_id: str,
        websocket,
        tts_type: str,
        tts_config: dict,
        voice_settings: dict,
        enable_text_cleaning: bool = True,
        cleaning_patterns: Optional[str] = None,
        preserve_quotes: bool = True
    ) -> 'TTSSession':
        """创建一个TTS会话"""
        tts_session = TTSSession(
            session_id=session_id,
            websocket=websocket,
            tts_type=tts_type,
            tts_config=tts_config,
            voice_settings=voice_settings,
            enable_text_cleaning=enable_text_cleaning,
            cleaning_patterns=cleaning_patterns,
            preserve_quotes=preserve_quotes
        )
        self.sessions[session_id] = tts_session
        logger.info(f"✨ 创建流式TTS会话: {session_id}")
        return tts_session
    
    def get_session(self, session_id: str) -> Optional['TTSSession']:
        """获取TTS会话"""
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str):
        """移除TTS会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"🗑️ 移除流式TTS会话: {session_id}")


class TTSSession:
    """单个流式TTS会话"""
    
    def __init__(
        self,
        session_id: str,
        websocket,
        tts_type: str,
        tts_config: dict,
        voice_settings: dict,
        enable_text_cleaning: bool = True,
        cleaning_patterns: Optional[str] = None,
        preserve_quotes: bool = True
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.tts_type = tts_type
        self.tts_config = tts_config
        self.voice_settings = voice_settings
        self.enable_text_cleaning = enable_text_cleaning
        self.cleaning_patterns = cleaning_patterns
        self.preserve_quotes = preserve_quotes
        
        # 获取TTS连接池
        self.tts_pool = get_tts_pool(tts_type, tts_config)
        
        # 文本缓冲区
        self.text_buffer = ""
        # 积累阈值：达到此字符数后，在下一个句子边界发送（避免句子中断）
        self.accumulate_threshold = 100  # 积累100字符
        # 强制分割阈值：超过此字符数且没有标点时才强制分割（防止极端情况）
        self.force_split_threshold = 300  # 300字符强制分割
        # 句子结束符号（用于智能分割，保持TTS的情绪和韵律）
        # 只使用完整句子的结束符：句号、感叹号、问号、省略号、换行符
        # 移除了分号、逗号、顿号等，避免过度分割导致播放卡顿
        self.sentence_end_marks = ['。', '！', '？', '...', '…', '.', '!', '?', '\n']
        # TTS任务队列
        self.tts_queue = asyncio.Queue()
        # 是否已完成
        self.is_done = False
        # 代码块检测标志（用于跳过代码块内容）
        self.in_code_block = False
        # TTS任务
        self.tts_task = None
        # TTS序号（确保按顺序播放）
        self.tts_sequence = 0
        # 并发控制：限制同时进行的TTS任务数量
        self.max_concurrent_tts = 5  # 最多5个并发TTS任务
        self.tts_semaphore = asyncio.Semaphore(5)
    
    async def start(self):
        """启动TTS处理任务"""
        self.tts_task = asyncio.create_task(self._process_tts_queue())
        logger.info(f"🚀 启动流式TTS处理任务: {self.session_id}")
    
    async def add_text(self, text: str):
        """
        添加文本到缓冲区，智能分割策略：
        1. 积累到100字符后，在下一个句子边界发送（避免句子中断）
        2. 使用完整句子结束符（。！？等）作为边界
        3. 超过300字符强制分割（防止极端情况）
        """
        if not text:
            return
        
        # ⚡ 让出执行权，确保队列消费者协程有机会运行
        await asyncio.sleep(0)
        
        self.text_buffer += text
        
        # 尝试从缓冲区提取完整的句子
        import re
        # 句子边界：句号、感叹号、问号、省略号、换行符
        sentence_pattern = r'([^。！？…\.\!\?\n]+(?:[。！？]+|\.{3}|…+|[\!\?]+|\n+))'
        
        # 查找所有完整的句子
        matches = list(re.finditer(sentence_pattern, self.text_buffer))
        
        if matches:
            # 计算缓冲区实际字符数（排除空白和标点）
            import unicodedata
            actual_chars = ''.join(c for c in self.text_buffer if unicodedata.category(c) not in ['Zs', 'Po', 'Ps', 'Pe'])
            buffer_length = len(actual_chars)
            
            # 策略：只有达到积累阈值(100字符)后，才在下一个句子边界发送
            if buffer_length >= self.accumulate_threshold:
                # 找到最后一个完整句子的位置
                last_match = matches[-1]
                last_end = last_match.end()
                
                # 提取到最后一个句子边界为止的所有文本
                text_to_send = self.text_buffer[:last_end].strip()
                
                if text_to_send:
                    await self.tts_queue.put(text_to_send)
                    logger.info(f"📝 [智能分割] 达到阈值({buffer_length}字符)，在句子边界发送: [{len(text_to_send)}字符] {text_to_send[:50]}...")
                    
                    # 保留剩余文本（未完成的句子）
                    self.text_buffer = self.text_buffer[last_end:].lstrip()
        
        # 如果缓冲区过长但没有完整句子，强制分割（防止极端情况）
        if len(self.text_buffer) >= self.force_split_threshold:
            text_to_synthesize = self.text_buffer.strip()
            self.text_buffer = ""
            if text_to_synthesize:
                await self.tts_queue.put(text_to_synthesize)
                logger.warning(f"⚠️ [强制分割] 缓冲区超过{self.force_split_threshold}字符，强制发送: [{len(text_to_synthesize)}字符] {text_to_synthesize[:50]}...")
    
    async def finish(self):
        """完成文本输入，处理剩余文本"""
        # 处理缓冲区剩余文本
        if self.text_buffer.strip():
            await self.tts_queue.put(self.text_buffer.strip())
            logger.info(f"📝 处理剩余文本: [{len(self.text_buffer)}字符] {self.text_buffer[:50]}...")
            self.text_buffer = ""
        
        # 标记完成
        self.is_done = True
        # 发送完成信号到队列
        await self.tts_queue.put(None)
        
        # 等待TTS任务完成
        if self.tts_task:
            await self.tts_task
        
        logger.info(f"✅ 流式TTS会话完成: {self.session_id}")
    
    async def _process_tts_queue(self):
        """处理TTS队列（并行模式，带序号）"""
        tasks = []
        
        while True:
            # 从队列获取文本
            text = await self.tts_queue.get()
            
            # None表示结束
            if text is None:
                logger.info(f"🏁 TTS队列处理完成，等待 {len(tasks)} 个并行任务: {self.session_id}")
                # 等待所有并行任务完成
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                break
            
            # 生成序号并递增
            sequence = self.tts_sequence
            self.tts_sequence += 1
            
            # 创建并行任务（不等待），传入序号
            task = asyncio.create_task(self._synthesize_and_send_safe(text, sequence))
            tasks.append(task)
            self.tts_queue.task_done()
            
            logger.info(f"🚀 启动并行TTS任务 #{sequence+1} (序号{sequence}): {text[:20]}...")
    
    async def _synthesize_and_send_safe(self, text: str, sequence: int):
        """安全的TTS合成（捕获异常，带并发控制）"""
        # 使用信号量控制并发数量
        async with self.tts_semaphore:
            try:
                await self._synthesize_and_send(text, sequence)
            except Exception as e:
                logger.error(f"❌ TTS合成失败 (序号{sequence}): {e}", exc_info=True)
                # 发送失败通知给前端，带上序号，让前端可以跳过该序号
                try:
                    await self.websocket.send_json({
                        "type": "audio_failed",
                        "sequence": sequence,
                        "text": text[:100],  # 发送失败的文本片段
                        "error": str(e)
                    })
                    logger.info(f"📤 已发送TTS失败通知 (序号{sequence})")
                except Exception as send_error:
                    logger.error(f"❌ 发送TTS失败通知时出错: {send_error}")
    
    async def _synthesize_and_send(self, text: str, sequence: int):
        """合成语音并发送给前端"""
        try:
            # 文本清洗
            if self.enable_text_cleaning:
                text_for_tts = clean_text_for_tts(text, self.cleaning_patterns, self.preserve_quotes)
            else:
                text_for_tts = text
            
            if not text_for_tts.strip():
                logger.info("⏭️ 清洗后文本为空，跳过TTS")
                return
            
            
            logger.info(f"🎙️ 开始TTS合成: [{len(text_for_tts)}字符] {text_for_tts[:50]}...")
            
            # 生成唯一的任务ID
            audio_uuid = str(uuid.uuid4())
            task_id = f"{self.session_id}_{audio_uuid}"
            
            if self.tts_type == "xfyun" or self.tts_type == "xfyun_tts":
                # 讯飞云TTS
                voice_type = self.voice_settings.get("voiceType", "x4_yezi")
                
                # 使用连接池进行流式合成
                pcm_data = bytearray()
                
                def audio_callback(audio_chunk: bytes):
                    """音频数据回调"""
                    pcm_data.extend(audio_chunk)
                
                success = await self.tts_pool.synthesize_streaming(
                    text=text_for_tts,
                    callback=audio_callback,
                    task_id=task_id,
                    vcn=voice_type
                )
                
                if success and pcm_data:
                    # 转换为WAV格式（在内存中）
                    wav_data = await self._pcm_to_wav_in_memory(bytes(pcm_data))
                    
                    if wav_data:
                        # 直接发送Base64编码的音频数据（带序号）
                        await self._send_audio_data(wav_data, "audio/wav", sequence)
                        logger.info(f"✅ 讯飞云TTS成功 (序号{sequence}): {len(wav_data)} bytes")
                    else:
                        logger.warning(f"⚠️ PCM转WAV失败(继续处理后续音频) (序号{sequence}): {text_for_tts[:20]}")
                else:
                    logger.warning(f"⚠️ 讯飞云TTS合成失败(继续处理后续音频) (序号{sequence}): {text_for_tts[:20]}")
            
            elif self.tts_type == "bytedance" or self.tts_type == "bytedance_tts":
                # 字节跳动TTS
                voice_type = self.voice_settings.get("voiceType", "zh_female_wanwanxiaohe_moon_bigtts")
                
                # 使用连接池进行流式合成
                audio_data = bytearray()
                
                def audio_callback(audio_chunk: bytes):
                    """音频数据回调"""
                    audio_data.extend(audio_chunk)
                
                success = await self.tts_pool.synthesize_streaming(
                    text=text_for_tts,
                    callback=audio_callback,
                    task_id=task_id,
                    voice_type=voice_type
                )
                
                if success and audio_data:
                    # 直接发送Base64编码的音频数据（带序号）
                    await self._send_audio_data(bytes(audio_data), "audio/mpeg", sequence)
                    logger.info(f"✅ 字节跳动TTS成功 (序号{sequence}): {len(audio_data)} bytes")
                else:
                    logger.warning(f"⚠️ 字节跳动TTS合成失败(继续处理后续音频) (序号{sequence}): {text_for_tts[:20]}")
            
            else:
                logger.error(f"❌ 不支持的TTS类型: {self.tts_type}")
        
        except Exception as e:
            # 任何异常都只记录警告，不中断后续TTS处理
            logger.warning(f"⚠️ TTS合成异常(继续处理后续音频): {e}")
            logger.debug(f"失败文本: {text_for_tts}", exc_info=True)
    
    async def _pcm_to_wav_in_memory(self, pcm_data: bytes) -> bytes:
        """在内存中将PCM数据转换为WAV格式"""
        try:
            import io
            import wave
            
            # 创建WAV文件的字节流
            wav_buffer = io.BytesIO()
            
            # 写入WAV头和数据
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)  # 单声道
                wav_file.setsampwidth(2)  # 16位
                wav_file.setframerate(16000)  # 16kHz
                wav_file.writeframes(pcm_data)
            
            # 获取WAV数据
            wav_data = wav_buffer.getvalue()
            wav_buffer.close()
            
            return wav_data
        except Exception as e:
            logger.error(f"❌ PCM转WAV失败: {e}")
            return None
    
    async def _send_audio_data(self, audio_data: bytes, mime_type: str, sequence: int):
        """发送Base64编码的音频数据到前端（带序号）"""
        try:
            import base64
            from fastapi.encoders import jsonable_encoder
            
            # Base64编码
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
            # 发送给前端（携带序号）
            await self.websocket.send_json(jsonable_encoder({
                "type": "audio",
                "data": audio_base64,
                "mime_type": mime_type,
                "sequence": sequence  # 添加序号字段
            }))
        except Exception as e:
            logger.error(f"❌ 发送音频数据失败: {e}")


# 全局管理器实例
streaming_tts_manager = StreamingTTSManager()

