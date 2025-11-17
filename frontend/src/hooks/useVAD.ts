import { useEffect, useRef, useState } from 'react';
import { MicVAD, utils } from '@ricky0123/vad-web';

export interface UseVADOptions {
  /** VAD 检测到语音开始的回调 */
  onSpeechStart?: () => void;
  /** VAD 检测到语音结束的回调（静音一段时间后） */
  onSpeechEnd?: (audio: Float32Array) => void;
  /** VAD 错误回调 */
  onVADError?: (error: Error) => void;
  /** 静音持续多久后认为语音结束（毫秒），默认 1500ms */
  positiveSpeechThreshold?: number;
  /** 负语音阈值（毫秒），默认 1000ms */
  negativeSpeechThreshold?: number;
  /** 最小语音帧数 */
  minSpeechFrames?: number;
  /** 是否启用 */
  enabled?: boolean;
}

export interface UseVADReturn {
  /** VAD 是否正在运行 */
  isVADActive: boolean;
  /** VAD 是否正在检测到语音 */
  isSpeaking: boolean;
  /** 启动 VAD */
  startVAD: () => Promise<void>;
  /** 停止 VAD */
  stopVAD: () => Promise<void>;
  /** VAD 是否准备就绪 */
  isVADReady: boolean;
  /** VAD 加载错误 */
  vadError: Error | null;
}

/**
 * 使用 @ricky0123/vad-web 实现的 VAD Hook
 * 用于自动检测语音活动，实现智能录音开始/结束
 */
export const useVAD = (options: UseVADOptions = {}): UseVADReturn => {
  const {
    onSpeechStart,
    onSpeechEnd,
    onVADError,
    positiveSpeechThreshold = 1500, // 1.5秒静音后结束
    negativeSpeechThreshold = 1000,
    minSpeechFrames = 3,
    enabled = true,
  } = options;

  const [isVADActive, setIsVADActive] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isVADReady, setIsVADReady] = useState(false);
  const [vadError, setVadError] = useState<Error | null>(null);

  const vadRef = useRef<MicVAD | null>(null);
  const audioChunksRef = useRef<Float32Array[]>([]);

  useEffect(() => {
    if (!enabled) return;

    // 预加载 VAD 模型
    const initVAD = async () => {
      try {
        // 这里不立即启动，只是预加载模型
        setIsVADReady(true);
      } catch (error) {
        const err = error instanceof Error ? error : new Error('VAD 初始化失败');
        setVadError(err);
        onVADError?.(err);
      }
    };

    initVAD();
  }, [enabled, onVADError]);

  const startVAD = async () => {
    if (vadRef.current) {
      console.warn('VAD 已经在运行中');
      return;
    }

    try {
      audioChunksRef.current = [];
      
      const vad = await MicVAD.new({
        // VAD 参数配置
        positiveSpeechThreshold,
        negativeSpeechThreshold,
        minSpeechFrames,
        
        // 采样率配置（与 useAudioRecorder 保持一致）
        // @ricky0123/vad-web 内部使用 16kHz
        
        // 回调函数
        onSpeechStart: () => {
          console.log('[VAD] 检测到语音开始');
          setIsSpeaking(true);
          onSpeechStart?.();
        },
        
        onSpeechEnd: (audio) => {
          console.log('[VAD] 检测到语音结束（静音）');
          setIsSpeaking(false);
          
          // 将音频数据传递给回调
          if (audio && audio.length > 0) {
            onSpeechEnd?.(audio);
          }
        },
        
        onVADMisfire: () => {
          console.log('[VAD] 误触发（声音太短）');
          setIsSpeaking(false);
        },
        
        // 实时音频帧处理（可选）
        onFrameProcessed: (probs) => {
          // probs: { isSpeech: number, notSpeech: number }
          // 可以用于可视化
        },
      });

      vadRef.current = vad;
      setIsVADActive(true);
      await vad.start();
      console.log('[VAD] 启动成功');
    } catch (error) {
      const err = error instanceof Error ? error : new Error('VAD 启动失败');
      setVadError(err);
      onVADError?.(err);
      throw err;
    }
  };

  const stopVAD = async () => {
    if (!vadRef.current) {
      return;
    }

    try {
      await vadRef.current.pause();
      vadRef.current.destroy();
      vadRef.current = null;
      setIsVADActive(false);
      setIsSpeaking(false);
      audioChunksRef.current = [];
      console.log('[VAD] 停止成功');
    } catch (error) {
      console.error('[VAD] 停止失败:', error);
    }
  };

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (vadRef.current) {
        vadRef.current.pause();
        vadRef.current.destroy();
      }
    };
  }, []);

  return {
    isVADActive,
    isSpeaking,
    startVAD,
    stopVAD,
    isVADReady,
    vadError,
  };
};

