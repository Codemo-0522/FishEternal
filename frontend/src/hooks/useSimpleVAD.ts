import { useState, useRef, useCallback } from 'react';

/**
 * 简单的 VAD 实现 - 基于 Web Audio API 音量检测
 * 不依赖任何外部库，纯浏览器 API 实现
 */

interface SimpleVADOptions {
  /** 音量阈值（0-1），超过此值认为是语音 */
  volumeThreshold?: number;
  /** 静音持续时长（毫秒），超过此时长自动停止 */
  silenceDuration?: number;
  /** 语音开始回调 */
  onSpeechStart?: () => void;
  /** 语音结束回调 */
  onSpeechEnd?: () => void;
}

interface UseSimpleVADReturn {
  /** 是否正在说话 */
  isSpeaking: boolean;
  /** 启动 VAD */
  startVAD: (stream: MediaStream) => void;
  /** 停止 VAD */
  stopVAD: () => void;
  /** 当前音量（0-1） */
  currentVolume: number;
}

export const useSimpleVAD = (options: SimpleVADOptions = {}): UseSimpleVADReturn => {
  const {
    volumeThreshold = 0.02, // 音量阈值（调低一点更敏感）
    silenceDuration = 1500, // 1.5秒静音后结束
    onSpeechStart,
    onSpeechEnd,
  } = options;

  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentVolume, setCurrentVolume] = useState(0);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startVAD = useCallback((stream: MediaStream) => {
    console.log('[SimpleVAD] 🚀 启动音量检测 VAD');
    
    // 保存 stream 引用
    streamRef.current = stream;

    // 创建音频上下文
    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    audioContextRef.current = audioContext;

    // 创建分析器节点
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.8;
    analyserRef.current = analyser;

    // 连接音频源
    const source = audioContext.createMediaStreamSource(stream);
    source.connect(analyser);

    // 开始检测音量
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    
    const detectVolume = () => {
      if (!analyserRef.current) return;

      analyser.getByteFrequencyData(dataArray);
      
      // 计算平均音量
      const average = dataArray.reduce((sum, value) => sum + value, 0) / dataArray.length;
      const volume = average / 255; // 归一化到 0-1
      
      setCurrentVolume(volume);

      // 判断是否在说话
      if (volume > volumeThreshold) {
        // 检测到语音
        if (!isSpeaking) {
          console.log('[SimpleVAD] 🎤 检测到语音开始, 音量:', volume.toFixed(3));
          setIsSpeaking(true);
          onSpeechStart?.();
        }

        // 清除静音计时器
        if (silenceTimerRef.current) {
          clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = null;
        }
      } else {
        // 检测到静音
        if (isSpeaking && !silenceTimerRef.current) {
          console.log('[SimpleVAD] 🔇 检测到静音，开始计时...');
          
          // 启动静音计时器
          silenceTimerRef.current = setTimeout(() => {
            console.log('[SimpleVAD] ⏱️ 静音超过', silenceDuration, 'ms，触发语音结束');
            setIsSpeaking(false);
            onSpeechEnd?.();
            silenceTimerRef.current = null;
          }, silenceDuration);
        }
      }

      // 继续检测
      animationFrameRef.current = requestAnimationFrame(detectVolume);
    };

    detectVolume();
  }, [volumeThreshold, silenceDuration, onSpeechStart, onSpeechEnd, isSpeaking]);

  const stopVAD = useCallback(() => {
    console.log('[SimpleVAD] 🛑 停止 VAD');

    // 停止音量检测
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }

    // 清除静音计时器
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    // 关闭音频上下文
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    analyserRef.current = null;
    streamRef.current = null;
    setIsSpeaking(false);
    setCurrentVolume(0);
  }, []);

  return {
    isSpeaking,
    startVAD,
    stopVAD,
    currentVolume,
  };
};

