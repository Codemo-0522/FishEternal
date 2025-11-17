import { useState, useRef, useCallback, useEffect } from 'react';

/**
 * 企业级 VAD 配置
 */
interface EnterpriseVADOptions {
  /** 语音开始音量阈值（0-1），默认 0.03 */
  speechStartThreshold?: number;
  /** 语音持续音量阈值（0-1），默认 0.02 */
  speechContinueThreshold?: number;
  /** 语音开始前需要的最小持续时间（毫秒），防止误触发，默认 200ms */
  minSpeechDuration?: number;
  /** 静音持续时长（毫秒），超过此时长自动停止，默认 1500ms */
  silenceDuration?: number;
  /** 最大录音时长（毫秒），超过自动停止，默认 60 秒 */
  maxRecordingDuration?: number;
  /** 是否启用调试日志 */
  debug?: boolean;
  /** 语音开始回调 */
  onSpeechStart?: () => void;
  /** 语音结束回调 */
  onSpeechEnd?: () => void;
  /** 最大录音时长到达回调 */
  onMaxDurationReached?: () => void;
}

interface UseEnterpriseVADReturn {
  /** 是否正在说话 */
  isSpeaking: boolean;
  /** 启动 VAD */
  startVAD: (stream: MediaStream) => void;
  /** 停止 VAD */
  stopVAD: () => void;
  /** 当前音量（0-1） */
  currentVolume: number;
  /** 录音持续时间（毫秒） */
  recordingDuration: number;
}

/**
 * 企业级 VAD Hook
 * 
 * 特性：
 * - 双阈值检测：启动阈值 + 持续阈值
 * - 防误触发：需要持续一定时间才认为是语音
 * - 智能静音检测：持续静音才停止
 * - 最大时长限制：防止录音过长
 * - 完善的状态管理：使用 ref 避免闭包陷阱
 */
export const useEnterpriseVAD = (options: EnterpriseVADOptions = {}): UseEnterpriseVADReturn => {
  const {
    speechStartThreshold = 0.03,
    speechContinueThreshold = 0.02,
    minSpeechDuration = 200,
    silenceDuration = 1500,
    maxRecordingDuration = Infinity, // 默认不限制录音时长
    debug = false,
    onSpeechStart,
    onSpeechEnd,
    onMaxDurationReached,
  } = options;

  const [isSpeaking, setIsSpeaking] = useState(false);
  const [currentVolume, setCurrentVolume] = useState(0);
  const [recordingDuration, setRecordingDuration] = useState(0);

  // 使用 ref 存储状态，避免闭包问题
  const isSpeakingRef = useRef(false);
  const currentVolumeRef = useRef(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // 计时器
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const speechStartTimerRef = useRef<NodeJS.Timeout | null>(null);
  const maxDurationTimerRef = useRef<NodeJS.Timeout | null>(null);
  const recordingStartTimeRef = useRef<number | null>(null);
  const durationIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // 音量历史记录（用于更准确的判断）
  const volumeHistoryRef = useRef<number[]>([]);
  const HISTORY_SIZE = 5;

  const log = (...args: any[]) => {
    if (debug) {
      console.log('[EnterpriseVAD]', ...args);
    }
  };

  /**
   * 计算音量的移动平均
   */
  const getAverageVolume = useCallback((history: number[]): number => {
    if (history.length === 0) return 0;
    return history.reduce((sum, v) => sum + v, 0) / history.length;
  }, []);

  /**
   * 启动 VAD
   */
  const startVAD = useCallback((stream: MediaStream) => {
    log('🚀 启动企业级 VAD');
    log('📊 配置:', {
      speechStartThreshold,
      speechContinueThreshold,
      minSpeechDuration,
      silenceDuration,
      maxRecordingDuration,
    });

    // 保存 stream 引用
    streamRef.current = stream;
    recordingStartTimeRef.current = Date.now();

    // 重置状态
    isSpeakingRef.current = false;
    setIsSpeaking(false);
    volumeHistoryRef.current = [];
    setRecordingDuration(0);

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

    // 开始更新录音时长
    durationIntervalRef.current = setInterval(() => {
      if (recordingStartTimeRef.current) {
        const duration = Date.now() - recordingStartTimeRef.current;
        setRecordingDuration(duration);
      }
    }, 100);

    // 设置最大时长计时器（仅在有限时长时设置）
    if (maxRecordingDuration !== Infinity && maxRecordingDuration > 0) {
      maxDurationTimerRef.current = setTimeout(() => {
        log('⏰ 达到最大录音时长:', maxRecordingDuration, 'ms');
        onMaxDurationReached?.();
        onSpeechEnd?.();
      }, maxRecordingDuration);
    }

    // 开始检测音量
    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const detectVolume = () => {
      if (!analyserRef.current) return;

      analyser.getByteFrequencyData(dataArray);

      // 计算平均音量
      const average = dataArray.reduce((sum, value) => sum + value, 0) / dataArray.length;
      const volume = average / 255; // 归一化到 0-1

      // 更新音量状态
      currentVolumeRef.current = volume;
      setCurrentVolume(volume);

      // 更新音量历史
      volumeHistoryRef.current.push(volume);
      if (volumeHistoryRef.current.length > HISTORY_SIZE) {
        volumeHistoryRef.current.shift();
      }

      const avgVolume = getAverageVolume(volumeHistoryRef.current);

      // VAD 逻辑
      if (!isSpeakingRef.current) {
        // 当前未在说话状态
        if (avgVolume > speechStartThreshold) {
          // 音量超过启动阈值
          if (!speechStartTimerRef.current) {
            log('🎤 检测到可能的语音，开始验证... (音量:', avgVolume.toFixed(3), ')');

            // 启动语音开始验证计时器
            speechStartTimerRef.current = setTimeout(() => {
              // 再次检查音量，确保不是瞬间噪音
              const currentAvgVolume = getAverageVolume(volumeHistoryRef.current);
              if (currentAvgVolume > speechStartThreshold) {
                log('✅ 确认语音开始 (平均音量:', currentAvgVolume.toFixed(3), ')');
                isSpeakingRef.current = true;
                setIsSpeaking(true);
                onSpeechStart?.();
              } else {
                log('❌ 误判为噪音，取消语音开始 (平均音量:', currentAvgVolume.toFixed(3), ')');
              }
              speechStartTimerRef.current = null;
            }, minSpeechDuration);
          }
        } else {
          // 音量低于启动阈值，清除验证计时器
          if (speechStartTimerRef.current) {
            log('🔇 音量下降，取消语音验证 (音量:', avgVolume.toFixed(3), ')');
            clearTimeout(speechStartTimerRef.current);
            speechStartTimerRef.current = null;
          }
        }
      } else {
        // 当前正在说话状态
        if (avgVolume > speechContinueThreshold) {
          // 音量超过持续阈值，继续说话
          if (silenceTimerRef.current) {
            log('🔊 检测到语音，取消静音计时器 (音量:', avgVolume.toFixed(3), ')');
            clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = null;
          }
        } else {
          // 音量低于持续阈值，检测静音
          if (!silenceTimerRef.current) {
            log('🔇 检测到静音，开始计时... (音量:', avgVolume.toFixed(3), ')');

            // 启动静音计时器
            silenceTimerRef.current = setTimeout(() => {
              log('⏱️ 静音超过', silenceDuration, 'ms，触发语音结束');
              isSpeakingRef.current = false;
              setIsSpeaking(false);
              onSpeechEnd?.();
              silenceTimerRef.current = null;
            }, silenceDuration);
          }
        }
      }

      // 继续检测
      animationFrameRef.current = requestAnimationFrame(detectVolume);
    };

    detectVolume();
    log('✅ VAD 已启动');
  }, [
    speechStartThreshold,
    speechContinueThreshold,
    minSpeechDuration,
    silenceDuration,
    maxRecordingDuration,
    onSpeechStart,
    onSpeechEnd,
    onMaxDurationReached,
    getAverageVolume,
  ]);

  /**
   * 停止 VAD
   */
  const stopVAD = useCallback(() => {
    log('🛑 停止 VAD');

    // 停止音量检测
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }

    // 清除所有计时器
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }

    if (speechStartTimerRef.current) {
      clearTimeout(speechStartTimerRef.current);
      speechStartTimerRef.current = null;
    }

    if (maxDurationTimerRef.current) {
      clearTimeout(maxDurationTimerRef.current);
      maxDurationTimerRef.current = null;
    }

    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current);
      durationIntervalRef.current = null;
    }

    // 关闭音频上下文
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    analyserRef.current = null;
    streamRef.current = null;
    isSpeakingRef.current = false;
    recordingStartTimeRef.current = null;
    volumeHistoryRef.current = [];
    
    setIsSpeaking(false);
    setCurrentVolume(0);
    setRecordingDuration(0);

    log('✅ VAD 已停止');
  }, []);

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      stopVAD();
    };
  }, [stopVAD]);

  return {
    isSpeaking,
    startVAD,
    stopVAD,
    currentVolume,
    recordingDuration,
  };
};

