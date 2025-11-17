import { useState, useRef, useCallback } from 'react';
import { message } from 'antd';
import { useEnterpriseVAD } from './useEnterpriseVAD';

interface UseSmartRecorderReturn {
  /** 是否正在录音 */
  isRecording: boolean;
  /** 是否检测到说话 */
  isSpeaking: boolean;
  /** 当前音量（0-1） */
  currentVolume: number;
  /** 录音持续时间（毫秒） */
  recordingDuration: number;
  /** 开始录音 */
  startRecording: (onAutoStop?: (blob: Blob) => void) => Promise<void>;
  /** 停止录音（返回音频 Blob） */
  stopRecording: () => Promise<Blob | null>;
  /** 取消录音 */
  cancelRecording: () => void;
}

/**
 * 浏览器兼容性检查
 */
const checkMediaDevicesSupport = () => {
  const errors: string[] = [];

  if (!navigator.mediaDevices) {
    errors.push('您的浏览器不支持 mediaDevices API');
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    errors.push('您的浏览器不支持 getUserMedia API');
  }

  if (!window.MediaRecorder) {
    errors.push('您的浏览器不支持 MediaRecorder API');
  }

  if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
    errors.push('非 HTTPS 环境下无法使用麦克风（本地开发除外）');
  }

  return {
    supported: errors.length === 0,
    errors,
  };
};

/**
 * 智能录音 Hook
 * 集成企业级 VAD（Voice Activity Detection）自动检测语音结束
 * 
 * 工作流程：
 * 1. 用户点击录音 -> 开始录音 + 启动 VAD
 * 2. VAD 检测到语音开始（持续 200ms 以上）-> 标记为说话中
 * 3. VAD 检测到静音 1.5 秒 -> 自动停止录音
 * 4. 用户再次点击 -> 立即停止录音
 * 5. 达到最大时长（60 秒）-> 自动停止录音
 */
export const useSmartRecorder = (): UseSmartRecorderReturn => {
  const [isRecording, setIsRecording] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const onAutoStopCallbackRef = useRef<((blob: Blob) => void) | null>(null);
  const stopRecordingRef = useRef<(() => Promise<Blob | null>) | null>(null);
  const isStoppingRef = useRef(false); // 防止重复触发停止
  const isStartingRef = useRef(false); // 防止重复调用 startRecording

  // 使用企业级 VAD 实现
  const { isSpeaking, currentVolume, recordingDuration, startVAD, stopVAD } = useEnterpriseVAD({
    speechStartThreshold: 0.03,      // 语音启动阈值
    speechContinueThreshold: 0.02,   // 语音持续阈值
    minSpeechDuration: 200,          // 最小持续 200ms 才认为是语音
    silenceDuration: 2000,           // 静音 2 秒后停止
    maxRecordingDuration: Infinity,  // 不限制录音时长
    debug: true,                     // 启用调试日志
    onSpeechStart: () => {
      console.log('[SmartRecorder] 🎤 检测到语音开始');
    },
    onSpeechEnd: async () => {
      console.log('[SmartRecorder] 🤐 检测到静音 - 发送当前片段，继续录音');
      
      // 防重入保护：如果已经在处理中，直接返回
      if (isStoppingRef.current) {
        console.log('[SmartRecorder] ⚠️ 已在处理中，忽略重复调用');
        return;
      }
      
      isStoppingRef.current = true;
      
      try {
        // 🔥 关键：停止当前 MediaRecorder，创建新的继续录音
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording' && streamRef.current) {
          const currentMimeType = mediaRecorderRef.current.mimeType;
          
          // 1️⃣ 获取当前已录制的数据
          const currentChunks = [...audioChunksRef.current];
          console.log('[SmartRecorder] 📦 当前音频 chunks 数量:', currentChunks.length);
          
          // 2️⃣ 停止当前 MediaRecorder
          await new Promise<void>((resolve) => {
            if (mediaRecorderRef.current) {
              mediaRecorderRef.current.onstop = () => {
                console.log('[SmartRecorder] ✅ 当前 MediaRecorder 已停止');
                resolve();
              };
              mediaRecorderRef.current.stop();
            } else {
              resolve();
            }
          });
          
          // 3️⃣ 清空 chunks 并创建新的 MediaRecorder 继续录音
          audioChunksRef.current = [];
          const newMediaRecorder = new MediaRecorder(streamRef.current, { mimeType: currentMimeType });
          
          newMediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
              audioChunksRef.current.push(event.data);
              console.log('[SmartRecorder] [新] 收到音频数据块:', event.data.size, 'bytes');
            }
          };
          
          newMediaRecorder.onstop = () => {
            console.log('[SmartRecorder] [新] MediaRecorder 已停止');
          };
          
          newMediaRecorder.onerror = (event: Event) => {
            console.error('[SmartRecorder] [新] MediaRecorder 错误:', event);
          };
          
          // 开始新的录音
          newMediaRecorder.start(100);
          mediaRecorderRef.current = newMediaRecorder;
          console.log('[SmartRecorder] ✅ 新的 MediaRecorder 已启动');
          
          // 4️⃣ 发送之前录制的音频片段
          if (currentChunks.length > 0) {
            const audioBlob = new Blob(currentChunks, { type: currentMimeType });
            console.log('[SmartRecorder] 📦 创建音频片段:', audioBlob.size, 'bytes');
            
            if (audioBlob.size > 0 && onAutoStopCallbackRef.current) {
              console.log('[SmartRecorder] ✅ 发送音频片段到后端');
              onAutoStopCallbackRef.current(audioBlob);
            }
          }
        }
      } catch (error) {
        console.error('[SmartRecorder] ❌ 处理 onSpeechEnd 失败:', error);
      } finally {
        // 重置防重入标志
        isStoppingRef.current = false;
      }
    },
    onMaxDurationReached: async () => {
      console.log('[SmartRecorder] ⏰ 达到最大录音时长，自动停止');
      
      // 防重入保护：如果已经在停止过程中，直接返回
      if (isStoppingRef.current) {
        console.log('[SmartRecorder] ⚠️ 已在停止过程中，忽略重复调用');
        return;
      }
      
      isStoppingRef.current = true;
      
      // 先停止 VAD，避免后续干扰
      stopVAD();
      
      // 调用内部停止录音
      if (stopRecordingRef.current) {
        const audioBlob = await stopRecordingRef.current();
        
        // 停止媒体流
        if (streamRef.current) {
          streamRef.current.getTracks().forEach(track => track.stop());
          streamRef.current = null;
        }
        
        // 重置状态
        setIsRecording(false);
        mediaRecorderRef.current = null;
        audioChunksRef.current = [];
        
        if (audioBlob && onAutoStopCallbackRef.current) {
          console.log('[SmartRecorder] ✅ 触发最大时长停止回调');
          onAutoStopCallbackRef.current(audioBlob);
        }
      }
      
      // 重置防重入标志
      isStoppingRef.current = false;
    },
  });

  /**
   * 开始录音
   */
  const startRecording = useCallback(async (onAutoStop?: (blob: Blob) => void) => {
    console.log('[Recorder] 🎙️ 开始录音流程');
    
    // 🚨 防止重复调用：如果正在启动中，忽略新的请求
    if (isStartingRef.current) {
      console.warn('[Recorder] ⚠️ 正在启动中，忽略重复调用');
      return;
    }
    
    // 🚨 防止重复调用：如果已经在录音中，忽略新的请求
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      console.warn('[Recorder] ⚠️ 已经在录音中，忽略重复调用 (当前状态:', mediaRecorderRef.current.state, ')');
      return;
    }
    
    // 设置启动标志
    isStartingRef.current = true;
    console.log('[Recorder] 🚀 设置启动标志');
    
    // 如果有旧的 MediaRecorder，先清理
    if (mediaRecorderRef.current) {
      console.log('[Recorder] 🧹 清理旧的 MediaRecorder');
      const oldRecorder = mediaRecorderRef.current;
      oldRecorder.ondataavailable = null;
      oldRecorder.onstop = null;
      oldRecorder.onerror = null;
      mediaRecorderRef.current = null;
    }
    
    // 如果有旧的 MediaStream，先释放
    if (streamRef.current) {
      console.log('[Recorder] 🧹 释放旧的 MediaStream');
      streamRef.current.getTracks().forEach(track => {
        track.stop();
        console.log('[Recorder]   - 停止旧音轨:', track.kind, track.label);
      });
      streamRef.current = null;
    }
    
    try {
      // 重置防重入标志
      isStoppingRef.current = false;
      
      // 保存自动停止回调
      onAutoStopCallbackRef.current = onAutoStop || null;

      // 检查浏览器兼容性
      const supportCheck = checkMediaDevicesSupport();
      if (!supportCheck.supported) {
        const errorMsg = supportCheck.errors.join('；');
        throw new Error(`您的浏览器不支持录音功能：${errorMsg}`);
      }

      // 请求麦克风权限
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      console.log('[Recorder] ✅ 麦克风权限已获取');

      streamRef.current = stream;
      audioChunksRef.current = [];

      // 检测音频格式
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')
        ? 'audio/ogg;codecs=opus'
        : 'audio/wav';
      console.log('[Recorder] 使用音频格式:', mimeType);

      // 创建 MediaRecorder
      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
          console.log('[Recorder] 收到音频数据块:', event.data.size, 'bytes');
        }
      };

      mediaRecorder.onstop = () => {
        console.log('[Recorder] MediaRecorder 已停止');
      };

      mediaRecorder.onerror = (event: Event) => {
        console.error('[Recorder] MediaRecorder 错误:', event);
        message.error('录音出错，请重试');
      };

      // 开始录音
      mediaRecorder.start(100); // 每 100ms 触发一次 dataavailable
      setIsRecording(true);
      console.log('[Recorder] ✅ 录音已开始');

      // 启动 VAD
      startVAD(stream);
      console.log('[Recorder] ✅ VAD 已启动');
      
      // ✅ 录音启动成功，清除启动标志
      isStartingRef.current = false;
      console.log('[Recorder] ✅ 录音启动成功，清除启动标志');

    } catch (error) {
      console.error('[Recorder] 启动失败:', error);
      
      // ❌ 录音启动失败，清除启动标志
      isStartingRef.current = false;
      console.log('[Recorder] ❌ 录音启动失败，清除启动标志');
      
      if (error instanceof Error && error.name === 'NotAllowedError') {
        message.error('麦克风权限被拒绝，请允许使用麦克风');
      } else if (error instanceof Error && error.name === 'NotFoundError') {
        message.error('未检测到麦克风设备');
      } else {
        message.error(`录音失败: ${error instanceof Error ? error.message : '未知错误'}`);
      }
      throw error;
    }
  }, [startVAD]);

  /**
   * 停止录音（内部函数）
   */
  const internalStopRecording = useCallback(async (): Promise<Blob | null> => {
    console.log('[Recorder] 🛑 停止录音');

    if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') {
      console.warn('[Recorder] MediaRecorder 未在录音或已停止');
      return null;
    }

    return new Promise((resolve) => {
      const mediaRecorder = mediaRecorderRef.current!;

      mediaRecorder.onstop = () => {
        console.log('[Recorder] MediaRecorder 已停止，合并音频数据');
        
        if (audioChunksRef.current.length === 0) {
          console.warn('[Recorder] 没有录制到音频数据');
          resolve(null);
          return;
        }

        const audioBlob = new Blob(audioChunksRef.current, { type: mediaRecorder.mimeType });
        console.log('[Recorder] ✅ 音频 Blob 已生成:', audioBlob.size, 'bytes');
        resolve(audioBlob);
      };

      mediaRecorder.stop();
    });
  }, []);

  // 保存 stopRecording 引用
  stopRecordingRef.current = internalStopRecording;

  /**
   * 停止录音（对外接口）
   */
  const stopRecording = useCallback(async (): Promise<Blob | null> => {
    try {
      // 停止 VAD
      stopVAD();

      // 停止 MediaRecorder
      const audioBlob = await internalStopRecording();

      // 停止媒体流
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      }

      setIsRecording(false);
      mediaRecorderRef.current = null;
      audioChunksRef.current = [];

      return audioBlob;
    } catch (error) {
      console.error('[Recorder] 停止录音失败:', error);
      return null;
    }
  }, [internalStopRecording, stopVAD]);

  /**
   * 取消录音
   */
  const cancelRecording = useCallback(() => {
    console.log('[Recorder] 🚫 取消录音');

    // 停止 VAD
    stopVAD();

    // 停止 MediaRecorder
    if (mediaRecorderRef.current) {
      const recorder = mediaRecorderRef.current;
      
      // 先清理所有事件处理器（防止内存泄漏和僵尸事件）
      console.log('[Recorder] 🧹 清理 MediaRecorder 事件处理器');
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      recorder.onstart = null;
      recorder.onpause = null;
      recorder.onresume = null;
      
      // 再停止录音
      if (recorder.state !== 'inactive') {
        console.log('[Recorder] 🛑 停止 MediaRecorder (状态:', recorder.state, ')');
        recorder.stop();
      }
    }

    // 停止媒体流（释放麦克风）
    if (streamRef.current) {
      const tracks = streamRef.current.getTracks();
      console.log('[Recorder] 🎤 释放麦克风，共', tracks.length, '个音轨');
      tracks.forEach(track => {
        console.log('[Recorder]   - 停止音轨:', track.kind, track.label, '(状态:', track.readyState, ')');
        track.stop();
        console.log('[Recorder]   - 音轨已停止，新状态:', track.readyState);
      });
      streamRef.current = null;
    }

    setIsRecording(false);
    mediaRecorderRef.current = null;
    audioChunksRef.current = [];
    onAutoStopCallbackRef.current = null;

    console.log('[Recorder] ✅ 录音已取消，所有资源已释放');
  }, [stopVAD]);

  return {
    isRecording,
    isSpeaking,
    currentVolume,
    recordingDuration,
    startRecording,
    stopRecording,
    cancelRecording,
  };
};
