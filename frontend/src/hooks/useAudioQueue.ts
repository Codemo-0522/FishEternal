import { useRef, useState, useCallback, useEffect } from 'react';

interface AudioQueueItem {
  url: string;
  id: string;
  sequence?: number;  // 添加序号字段
}

export const useAudioQueue = () => {
  const [queue, setQueue] = useState<AudioQueueItem[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentAudio, setCurrentAudio] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const isProcessingRef = useRef(false);
  const queueRef = useRef<AudioQueueItem[]>([]);
  const nextExpectedSequence = useRef<number>(0);  // 下一个期望的序号
  const pendingAudios = useRef<Map<number, AudioQueueItem>>(new Map());  // 暂存未到序号的音频
  const sequenceTimeoutMap = useRef<Map<number, NodeJS.Timeout>>(new Map());  // 序号超时定时器
  
  // 同步队列到 ref
  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);

  // 跳过指定序号（失败或超时）
  const skipSequence = useCallback((sequence: number, reason: string) => {
    console.warn(`[AudioQueue] ⏭️ 跳过序号${sequence} (${reason})`);
    
    // 清除该序号的超时定时器
    const timer = sequenceTimeoutMap.current.get(sequence);
    if (timer) {
      clearTimeout(timer);
      sequenceTimeoutMap.current.delete(sequence);
    }
    
    // 如果正好是当前期望的序号，递增期望序号
    if (sequence === nextExpectedSequence.current) {
      nextExpectedSequence.current++;
      
      // 检查暂存区是否有后续序号
      while (pendingAudios.current.has(nextExpectedSequence.current)) {
        const pendingItem = pendingAudios.current.get(nextExpectedSequence.current)!;
        console.log(`[AudioQueue] ✅ 从暂存区取出序号${nextExpectedSequence.current}`);
        setQueue(prev => [...prev, pendingItem]);
        pendingAudios.current.delete(nextExpectedSequence.current);
        
        // 清除该序号的超时定时器
        const pendingTimer = sequenceTimeoutMap.current.get(nextExpectedSequence.current);
        if (pendingTimer) {
          clearTimeout(pendingTimer);
          sequenceTimeoutMap.current.delete(nextExpectedSequence.current);
        }
        
        nextExpectedSequence.current++;
      }
    }
  }, []);

  // 添加音频到队列（带序号）
  const addToQueue = useCallback((url: string, sequence?: number) => {
    const id = `${Date.now()}_${Math.random()}`;
    const item: AudioQueueItem = { url, id, sequence };
    
    console.log('[AudioQueue] 收到音频:', { sequence, url: url.substring(0, 50) });
    
    // 如果没有序号，直接加入队列（旧逻辑兼容）
    if (sequence === undefined) {
      console.log('[AudioQueue] 无序号，直接添加到队列');
      setQueue(prev => [...prev, item]);
      return;
    }
    
    // 如果是下一个期望的序号，直接加入队列
    if (sequence === nextExpectedSequence.current) {
      console.log(`[AudioQueue] ✅ 序号${sequence}符合预期，加入队列`);
      setQueue(prev => [...prev, item]);
      
      // 清除该序号的超时定时器
      const timer = sequenceTimeoutMap.current.get(sequence);
      if (timer) {
        clearTimeout(timer);
        sequenceTimeoutMap.current.delete(sequence);
      }
      
      nextExpectedSequence.current++;
      
      // 检查暂存区是否有后续序号
      while (pendingAudios.current.has(nextExpectedSequence.current)) {
        const pendingItem = pendingAudios.current.get(nextExpectedSequence.current)!;
        console.log(`[AudioQueue] ✅ 从暂存区取出序号${nextExpectedSequence.current}`);
        setQueue(prev => [...prev, pendingItem]);
        pendingAudios.current.delete(nextExpectedSequence.current);
        
        // 清除该序号的超时定时器
        const pendingTimer = sequenceTimeoutMap.current.get(nextExpectedSequence.current);
        if (pendingTimer) {
          clearTimeout(pendingTimer);
          sequenceTimeoutMap.current.delete(nextExpectedSequence.current);
        }
        
        nextExpectedSequence.current++;
      }
    } else if (sequence > nextExpectedSequence.current) {
      // 序号太大，暂存，并为缺失的序号设置超时
      console.log(`[AudioQueue] ⏳ 序号${sequence}大于期望${nextExpectedSequence.current}，暂存`);
      pendingAudios.current.set(sequence, item);
      
      // 为所有缺失的序号（从当前期望到收到的序号-1）设置超时
      for (let missingSeq = nextExpectedSequence.current; missingSeq < sequence; missingSeq++) {
        if (!sequenceTimeoutMap.current.has(missingSeq)) {
          const timeout = setTimeout(() => {
            console.warn(`[AudioQueue] ⏰ 序号${missingSeq}超时（30秒），自动跳过`);
            skipSequence(missingSeq, '超时');
          }, 60000);  // 60秒超时
          sequenceTimeoutMap.current.set(missingSeq, timeout);
          console.log(`[AudioQueue] ⏰ 为序号${missingSeq}设置30秒超时`);
        }
      }
    } else {
      // 序号太小，重复或乱序，忽略
      console.warn(`[AudioQueue] ⚠️ 序号${sequence}小于期望${nextExpectedSequence.current}，忽略`);
    }
  }, [skipSequence]);

  // 播放完成回调
  const onPlayComplete = useCallback(() => {
    console.log('[AudioQueue] 🏁 当前音频播放完成，准备播放下一个');
    
    // 先重置状态
    isProcessingRef.current = false;
    setIsPlaying(false);
    setCurrentAudio(null);
    
    // 从队列移除第一个元素
    setQueue(prev => {
      const newQueue = prev.slice(1);
      console.log('[AudioQueue] 📝 队列更新，剩余:', newQueue.length);
      return newQueue;
    });
  }, []);

  // 播放下一个音频
  const playNext = useCallback(() => {
    // 防止重复调用 - 严格检查
    if (isProcessingRef.current) {
      console.log('[AudioQueue] ⏸️ 正在播放中，跳过重复调用');
      return;
    }

    // 使用 ref 获取最新队列，避免闭包问题
    const currentQueue = queueRef.current;
    if (currentQueue.length === 0) {
      console.log('[AudioQueue] 📭 队列为空，无需播放');
      return;
    }

    const nextItem = currentQueue[0];
    console.log('[AudioQueue] ▶️ 开始播放:', nextItem.url, '队列剩余:', currentQueue.length - 1);
    
    // 立即设置为处理中，防止并发
    isProcessingRef.current = true;
    setIsPlaying(true);
    setCurrentAudio(nextItem.url);

    // 停止并清理当前音频
    if (audioRef.current) {
      try {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
        audioRef.current.src = '';
        // 移除所有事件监听器
        audioRef.current.onended = null;
        audioRef.current.onerror = null;
        audioRef.current.onloadeddata = null;
      } catch (e) {
        console.warn('[AudioQueue] ⚠️ 清理旧音频时出错:', e);
      }
      audioRef.current = null;
    }

    // 创建新的音频元素
    const audio = new Audio();
    audioRef.current = audio;

    // 设置音频源
    audio.src = nextItem.url;
    
    // 音频加载完成
    audio.onloadeddata = () => {
      console.log('[AudioQueue] 📥 音频加载完成，开始播放');
    };

    // 音频播放完成
    audio.onended = () => {
      console.log('[AudioQueue] ✅ 音频播放结束');
      onPlayComplete();
    };

    // 音频播放错误
    audio.onerror = (e) => {
      console.error('[AudioQueue] ❌ 音频加载/播放错误:', e);
      onPlayComplete();
    };

    // 开始播放
    audio.play().catch(error => {
      console.error('[AudioQueue] ❌ 播放失败:', error);
      onPlayComplete();
    });
  }, [onPlayComplete]);

  // 监听队列变化，自动播放
  useEffect(() => {
    if (queue.length > 0 && !isPlaying && !isProcessingRef.current) {
      console.log('[AudioQueue] 检测到队列有内容且未播放，触发播放');
      playNext();
    }
  }, [queue, isPlaying, playNext]);

  // 清空队列
  const clearQueue = useCallback(() => {
    console.log('[AudioQueue] 清空队列');
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      // 🔑 清除所有事件监听器，防止旧音频的回调干扰新消息
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.onloadeddata = null;
      audioRef.current = null;
    }
    setQueue([]);
    setIsPlaying(false);
    setCurrentAudio(null);
    isProcessingRef.current = false;
    
    // 清除所有超时定时器
    sequenceTimeoutMap.current.forEach((timer) => clearTimeout(timer));
    sequenceTimeoutMap.current.clear();
    
    // 重置序号和暂存区
    nextExpectedSequence.current = 0;
    pendingAudios.current.clear();
  }, []);

  // 暂停播放
  const pause = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
    }
    setIsPlaying(false);
  }, []);

  // 恢复播放
  const resume = useCallback(() => {
    if (audioRef.current && currentAudio) {
      audioRef.current.play().catch(error => {
        console.error('[AudioQueue] 恢复播放失败:', error);
      });
      setIsPlaying(true);
    }
  }, [currentAudio]);

  return {
    addToQueue,
    clearQueue,
    skipSequence,  // 导出跳过序号函数
    pause,
    resume,
    isPlaying,
    currentAudio,
    queueLength: queue.length,
    audioRef
  };
};

