import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Layout, Button, Switch, Dropdown, message } from 'antd';
import type { MenuProps } from 'antd';
import {
  MoreOutlined,
  PictureOutlined,
  PhoneOutlined,
  VideoCameraOutlined,
  MessageOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined
} from '@ant-design/icons';
import { useAuthStore } from '../../stores/authStore';
import styles from './Call.module.css';
import { useNavigate } from 'react-router-dom';
import { useChatStore } from '../../stores/chatStore';
import { useLazyLoadMessages } from '../Chat/useLazyLoadMessages';
import { useSmartRecorder } from '../../hooks/useSmartRecorder';
import chatWSManager from '../../utils/ChatWSManager';
import authAxios from '../../utils/authAxios';
import { getFullUrl } from '../../config';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  images?: string[];
  reference?: any;
  id?: string;
}

const Call: React.FC = () => {
  const navigate = useNavigate();
  const { currentSession } = useChatStore();
  
  // UI 状态
  const [showSubtitle, setShowSubtitle] = useState(false);
  const [showHistory, setShowHistory] = useState(true); // 显示历史消息遮罩层
  const [isCallPaused, setIsCallPaused] = useState(false); // 通话暂停状态
  const [callStatus, setCallStatus] = useState<'connecting' | 'ready' | 'listening' | 'thinking' | 'speaking'>('connecting');
  const [subtitle, setSubtitle] = useState('正在连接...');
  const [showBackground, setShowBackground] = useState(true); // 是否显示背景
  const [backgroundImageUrl, setBackgroundImageUrl] = useState<string>(''); // 背景图片URL
  
  // 懒加载消息（共享 Chat.tsx 的数据）
  const { messages, setMessages, handleInitialHistory } = useLazyLoadMessages({
    sessionId: currentSession?.session_id || null,
    isAssistantMode: false
  });
  
  // 消息列表滚动引用
  const historyContainerRef = useRef<HTMLDivElement | null>(null);
  
  // 智能录音
  const { isRecording, isSpeaking, startRecording, cancelRecording } = useSmartRecorder();
  
  // TTS 播放管理
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  
  // 🎵 音频播放队列管理（解决多段音频同时播放问题）
  const audioQueueRef = useRef<Array<{ data: string; mime_type: string; sequence: number }>>([]);
  const isPlayingQueueRef = useRef(false);
  const nextExpectedSequenceRef = useRef(0); // 期望的下一个序号
  
  // WebSocket 连接状态
  const currentSessionIdRef = useRef<string | null>(null);
  const isProcessingRef = useRef(false); // 防止重复处理
  const autoRecordingEnabledRef = useRef(true); // 控制自动录音循环
  
  // 保存清理函数的引用，用于组件卸载时清理
  const cancelRecordingRef = useRef(cancelRecording);
  const startAutoRecordingRef = useRef<(() => Promise<void>) | null>(null);
  
  // 持续更新 ref 引用
  useEffect(() => {
    cancelRecordingRef.current = cancelRecording;
  }, [cancelRecording]);
  
  /**
   * 🎵 播放单个音频片段（从队列中取出）
   */
  const playAudioFromQueue = useCallback(async function playAudioFromQueueFn() {
    if (audioQueueRef.current.length === 0) {
      isPlayingQueueRef.current = false;
      console.log('[Call] ✅ 音频队列已播放完毕');
      setIsPlaying(false);
      
      // 所有音频播放完成，延迟后开始下一轮录音
      setTimeout(() => {
        if (autoRecordingEnabledRef.current && startAutoRecordingRef.current) {
          console.log('[Call] 🎤 所有TTS播放完成，开始下一轮录音');
          setCallStatus('listening');
          setSubtitle('请说话...');
          startAutoRecordingRef.current();
        }
      }, 500);
      return;
    }
    
    // 取出第一个音频片段
    const audioItem = audioQueueRef.current.shift()!;
    console.log(`[Call] 🎵 播放音频片段 #${audioItem.sequence}`);
    
    setCallStatus('speaking');
    setSubtitle('正在回复...');
    setIsPlaying(true);
    
    try {
      // 转换Base64为Blob URL
      const binaryString = atob(audioItem.data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: audioItem.mime_type });
      const audioSrc = URL.createObjectURL(blob);
      
      // 创建音频元素
      const audio = new Audio(audioSrc);
      audioRef.current = audio;
      
      // 监听播放完成事件 - 继续播放下一个
      audio.onended = () => {
        console.log(`[Call] ✅ 音频片段 #${audioItem.sequence} 播放完成`);
        URL.revokeObjectURL(audioSrc); // 释放Blob URL
        audioRef.current = null;
        
        // 递归播放下一个
        playAudioFromQueueFn();
      };
      
      // 监听错误事件
      audio.onerror = (error) => {
        console.error(`[Call] ❌ 音频片段 #${audioItem.sequence} 播放失败:`, error);
        URL.revokeObjectURL(audioSrc);
        audioRef.current = null;
        
        // 播放失败，继续下一个
        playAudioFromQueueFn();
      };
      
      // 开始播放
      await audio.play();
      console.log(`[Call] 🎵 正在播放音频片段 #${audioItem.sequence}...`);
      
    } catch (error) {
      console.error(`[Call] ❌ 音频片段 #${audioItem.sequence} 播放失败:`, error);
      // 播放失败，继续下一个
      playAudioFromQueueFn();
    }
  }, []);
  
  /**
   * 🎵 添加音频到播放队列
   */
  const enqueueAudio = useCallback((audioData: { data: string; mime_type: string; sequence: number }) => {
    if (isCallPaused) {
      console.log('[Call] ⏸️ 通话已暂停，跳过音频');
      return;
    }
    
    console.log(`[Call] 📥 收到音频片段 #${audioData.sequence}，添加到队列`);
    
    // 添加到队列
    audioQueueRef.current.push(audioData);
    
    // 按序号排序（确保按顺序播放）
    audioQueueRef.current.sort((a, b) => a.sequence - b.sequence);
    
    console.log(`[Call] 📋 当前队列长度: ${audioQueueRef.current.length}`);
    
    // 如果当前没有在播放，开始播放
    if (!isPlayingQueueRef.current) {
      isPlayingQueueRef.current = true;
      playAudioFromQueue();
    }
  }, [isCallPaused, playAudioFromQueue]);
  
  /**
   * 🎤 ASR 转录
   */
  const transcribeAudio = useCallback(async (audioBlob: Blob): Promise<string | null> => {
    console.log('[Call] 📥 开始 ASR 转录，音频大小:', audioBlob.size);
    setCallStatus('thinking');
    setSubtitle('正在识别...');
    
    try {
      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.wav');
      
      const response = await authAxios.post('/api/asr/transcribe', formData);
      
      if (response.data.success && response.data.text?.trim()) {
        const transcribedText = response.data.text.trim();
        console.log('[Call] ✅ ASR 转录成功:', transcribedText);
        return transcribedText;
      } else {
        console.log('[Call] ⚠️ 未识别到语音内容');
        return null;
      }
    } catch (error: any) {
      console.error('[Call] ❌ ASR 转录失败:', error);
      message.error('语音识别失败');
      return null;
    }
  }, []);
  
  /**
   * 📤 发送消息到 WebSocket
   */
  const sendMessage = useCallback(async (text: string) => {
    if (!currentSession || !text.trim()) return;
    
    console.log('[Call] 📤 发送消息:', text);
    setCallStatus('thinking');
    setSubtitle('正在思考...');
    
    // 🧹 清空音频队列（准备接收新的音频）
    audioQueueRef.current = [];
    isPlayingQueueRef.current = false;
    nextExpectedSequenceRef.current = 0;
    console.log('[Call] 🧹 清空旧音频队列，准备接收新消息');
    
    // 立即添加用户消息到界面
    const userMessage: ChatMessage = {
      role: 'user',
      content: text.trim(),
      timestamp: new Date().toISOString(),
      id: `temp-user-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    };
    
    setMessages(prev => [...prev, userMessage]);
    
    // 发送到 WebSocket
    try {
      await chatWSManager.ensureAuthorized(8000);
      chatWSManager.send({
        type: 'chat',
        session_id: currentSession.session_id,
        message: text.trim(),
        enable_voice: true // 🔑 关键：启用 TTS（后端字段是 enable_voice）
      });
      console.log('[Call] ✅ 消息已发送，等待 AI 回复...');
    } catch (error) {
      console.error('[Call] ❌ 发送消息失败:', error);
      message.error('发送失败，请重试');
      
      // 发送失败，继续下一轮录音
      setTimeout(() => {
        if (autoRecordingEnabledRef.current && startAutoRecordingRef.current) {
          startAutoRecordingRef.current();
        }
      }, 1000);
    }
  }, [currentSession, setMessages]);
  
  /**
   * 🔄 自动录音循环：录音 → ASR → 发送
   */
  const startAutoRecording = useCallback(async () => {
    if (!autoRecordingEnabledRef.current || isProcessingRef.current) {
      console.log('[Call] ⏸️ 自动录音已暂停或正在处理中');
      return;
    }
    
    console.log('[Call] 🎤 开始自动录音...');
    setCallStatus('listening');
    setSubtitle('请说话...');
    
    try {
      // 使用 useSmartRecorder 的 VAD 自动检测功能
      await startRecording(async (audioBlob: Blob) => {
        if (!autoRecordingEnabledRef.current) {
          console.log('[Call] ⏸️ 自动录音已停止，忽略此音频');
          return;
        }
        
        // 防止重复处理
        if (isProcessingRef.current) {
          console.log('[Call] ⏳ 正在处理中，忽略此音频');
          return;
        }
        
        isProcessingRef.current = true;
        console.log('[Call] 📦 VAD 检测到静音，收到音频片段:', audioBlob.size);
        
        try {
          // 1. ASR 转录
          const text = await transcribeAudio(audioBlob);
          
          if (text && text.trim()) {
            // 2. 发送消息（WebSocket 会返回 AI 回复 + TTS 音频）
            await sendMessage(text);
          } else {
            // 没有识别到内容，继续录音
            console.log('[Call] ⚠️ 未识别到内容，继续录音...');
            setCallStatus('listening');
            setSubtitle('请说话...');
            // VAD 已经自动创建了新的 MediaRecorder，无需手动重启
          }
        } finally {
          isProcessingRef.current = false;
        }
      });
      
    } catch (error) {
      console.error('[Call] ❌ 启动录音失败:', error);
      message.error('启动录音失败');
      isProcessingRef.current = false;
      
      // 重试
      setTimeout(() => {
        if (autoRecordingEnabledRef.current && startAutoRecordingRef.current) {
          startAutoRecordingRef.current();
        }
      }, 2000);
    }
  }, [startRecording, transcribeAudio, sendMessage]);
  
  // 🔄 更新 startAutoRecording 的 ref
  useEffect(() => {
    startAutoRecordingRef.current = startAutoRecording;
  }, [startAutoRecording]);
  
  /**
   * ⏸️ 暂停/继续通话
   */
  const handleTogglePause = useCallback(() => {
    if (isCallPaused) {
      // 继续通话
      console.log('[Call] ▶️ 继续通话');
      setIsCallPaused(false);
      autoRecordingEnabledRef.current = true;
      setCallStatus('listening');
      setSubtitle('请说话...');
      // 立即开始录音
      if (startAutoRecordingRef.current) {
        startAutoRecordingRef.current();
      }
      message.success('通话已继续');
    } else {
      // 暂停通话
      console.log('[Call] ⏸️ 暂停通话');
      setIsCallPaused(true);
      autoRecordingEnabledRef.current = false;
      
      // 停止当前录音
      if (isRecording) {
        console.log('[Call] 🛑 停止当前录音');
        cancelRecording();
      }
      
      // 停止当前播放并清空队列
      if (audioRef.current) {
        console.log('[Call] 🛑 停止当前播放');
        audioRef.current.pause();
        audioRef.current = null;
        setIsPlaying(false);
      }
      
      // 清空音频队列
      audioQueueRef.current = [];
      isPlayingQueueRef.current = false;
      console.log('[Call] 🧹 音频队列已清空');
      
      setCallStatus('ready');
      setSubtitle('通话已暂停');
      message.info('通话已暂停');
    }
  }, [isCallPaused, isRecording, cancelRecording, startAutoRecording]);
  
  /**
   * 🔌 建立 WebSocket 连接
   */
  useEffect(() => {
    if (!currentSession) {
      console.log('[Call] ⚠️ 没有当前会话，无法建立连接');
      setCallStatus('connecting');
      setSubtitle('请先选择一个会话');
      return;
    }
    
    console.log('[Call] 🔌 开始建立 WebSocket 连接...');
    console.log('[Call] 📝 当前会话 ID:', currentSession.session_id);
    console.log('[Call] 📝 当前会话名称:', currentSession.name);
    currentSessionIdRef.current = currentSession.session_id;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/chat/ws/chat/${currentSession.session_id}`;
    
    console.log('[Call] 🌐 WebSocket URL:', wsUrl);
    console.log('[Call] 🌐 Protocol:', protocol);
    console.log('[Call] 🌐 Host:', host);
    
    chatWSManager.updateSessionContext({
      url: wsUrl,
      sessionId: currentSession.session_id,
      isAssistantMode: false
    });
    
    console.log('[Call] 📋 WebSocket 配置已更新');
    
    chatWSManager.setCallbacks({
      onOpen: () => {
        console.log('[Call] ✅ WebSocket 连接成功！');
        setCallStatus('ready');
        setSubtitle('连接成功，准备开始对话...');
        
        // ⚠️ 不需要手动请求历史消息，后端连接建立时会自动发送
        // 延迟 1 秒后自动开始第一轮录音
        setTimeout(() => {
          if (autoRecordingEnabledRef.current && startAutoRecordingRef.current) {
            console.log('[Call] 🎤 自动开始第一轮录音');
            startAutoRecordingRef.current();
          }
        }, 1000);
      },
      
      onMessage: (event: MessageEvent) => {
        if (currentSessionIdRef.current !== currentSession.session_id) {
          console.log('[Call] ⚠️ 忽略非当前会话的消息');
          return;
        }
        
        try {
          const data = JSON.parse(event.data);
          console.log('[Call] 📩 收到 WebSocket 消息:', data.type);
          
          // 错误处理
          if (data.type === 'error') {
            console.error('[Call] ❌ 收到错误:', data.content);
            message.error(data.content);
            setCallStatus('ready');
            
            // 错误后继续录音
            setTimeout(() => {
              if (autoRecordingEnabledRef.current && startAutoRecordingRef.current) {
                startAutoRecordingRef.current();
              }
            }, 1000);
            return;
          }
          
          // 历史消息
          if (data.type === 'history') {
            const converted: ChatMessage[] = (data.messages || []).map((msg: any) => ({
              role: msg.role,
              content: msg.content || '',
              timestamp: msg.timestamp || msg.create_time || msg.created_at,
              images: msg.images,
              reference: msg.reference,
              id: msg.id
            }));
            
            handleInitialHistory({
              messages: converted,
              total: data.total,
              loaded: data.loaded,
              has_more: data.has_more
            });
            
            console.log('[Call] 📜 历史消息已加载:', converted.length);
            return;
          }
          
          // AI 回复的流式消息
          if (data.type === 'message') {
            setMessages(prev => {
              const last = prev[prev.length - 1];
              if (last && last.role === 'assistant') {
                // 追加到现有消息
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...last,
                  content: (last.content || '') + (data.content || ''),
                  reference: data.reference || last.reference
                };
                return updated;
              } else {
                // 创建新的 AI 消息
                const aiMessage: ChatMessage = {
                  role: 'assistant',
                  content: data.content || '',
                  timestamp: data.assistant_timestamp || new Date().toISOString(),
                  reference: data.reference,
                  id: data.message_id || `temp-ai-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
                };
                return [...prev, aiMessage];
              }
            });
            return;
          }
          
          // 🔑 关键：TTS 音频返回（使用队列管理）
          if (data.type === 'audio') {
            if (data.data && data.mime_type) {
              const sequence = data.sequence ?? 0; // 获取序号，默认为0
              console.log(`[Call] 🎵 收到 TTS Base64音频 #${sequence}:`, data.mime_type);
              enqueueAudio({ 
                data: data.data, 
                mime_type: data.mime_type,
                sequence: sequence 
              });
            }
            return;
          }
          
          // 音频合成失败通知
          if (data.type === 'audio_failed') {
            const sequence = data.sequence ?? 0;
            console.warn(`[Call] ⚠️ TTS音频片段 #${sequence} 合成失败:`, data.error);
            // 可以选择跳过该片段或显示提示
            return;
          }
          
          // done 消息
          if (data.type === 'done') {
            console.log('[Call] ✅ 消息处理完成');
            
            // 更新时间戳
            if (data.user_timestamp || data.assistant_timestamp) {
              setMessages(prev => {
                const updated = [...prev];
                
                if (data.user_timestamp) {
                  for (let i = updated.length - 1; i >= 0; i--) {
                    if (updated[i].role === 'user') {
                      updated[i] = { ...updated[i], timestamp: data.user_timestamp };
                      break;
                    }
                  }
                }
                
                if (data.assistant_timestamp) {
                  for (let i = updated.length - 1; i >= 0; i--) {
                    if (updated[i].role === 'assistant') {
                      updated[i] = { ...updated[i], timestamp: data.assistant_timestamp };
                      break;
                    }
                  }
                }
                
                return updated;
              });
            }
            
            // ⚠️ 注意：不要在这里开始下一轮录音！
            // 下一轮录音应该在 TTS 播放完成后才开始（在 playTTSAudio 的 onended 回调中）
            return;
          }
          
        } catch (error) {
          console.error('[Call] ❌ 解析 WebSocket 消息失败:', error);
        }
      },
      
      onClose: (event?: CloseEvent) => {
        console.log('[Call] 🔌 WebSocket 已断开');
        console.log('[Call] 🔌 关闭代码:', event?.code);
        console.log('[Call] 🔌 关闭原因:', event?.reason);
        console.log('[Call] 🔌 是否正常关闭:', event?.wasClean);
        setCallStatus('connecting');
        setSubtitle('连接已断开，正在重连...');
      },
      
      onError: (error?: Event) => {
        console.error('[Call] ❌ WebSocket 发生错误:', error);
        console.error('[Call] ❌ 错误类型:', error?.type);
        console.error('[Call] ❌ 错误目标:', (error?.target as any)?.url);
        message.error('连接错误，正在重试...');
      }
    });
    
    console.log('[Call] 🚀 开始连接 WebSocket...');
    chatWSManager.connect();
    console.log('[Call] 📞 chatWSManager.connect() 已调用');
    
    // 检查是否已经连接（复用场景）
    const currentState = chatWSManager.getState();
    const currentSocket = chatWSManager.getSocket();
    console.log('[Call] 🔍 当前状态:', currentState);
    console.log('[Call] 🔍 Socket readyState:', currentSocket?.readyState);
    
    if (currentState === 'open' && currentSocket?.readyState === WebSocket.OPEN) {
      console.log('[Call] ✅ 检测到已有连接，立即触发 onOpen 回调');
      console.log('[Call] 🔍 autoRecordingEnabledRef.current:', autoRecordingEnabledRef.current);
      
      // 立即触发 onOpen 回调
      setCallStatus('ready');
      setSubtitle('连接成功，准备开始对话...');
      
      // ⚠️ 不需要手动请求历史消息，后端连接建立时会自动发送
      // 延迟 1 秒后自动开始第一轮录音
      setTimeout(() => {
        console.log('[Call] ⏰ 1秒延迟结束，准备开始录音');
        console.log('[Call] 🔍 autoRecordingEnabledRef.current:', autoRecordingEnabledRef.current);
        console.log('[Call] 🔍 startAutoRecordingRef.current:', typeof startAutoRecordingRef.current);
        
        if (autoRecordingEnabledRef.current && startAutoRecordingRef.current) {
          console.log('[Call] 🎤 自动开始第一轮录音（复用连接）');
          startAutoRecordingRef.current();
        } else {
          console.log('[Call] ⚠️ autoRecordingEnabledRef 是 false，无法开始录音');
        }
      }, 1000);
    }
    
    // 清理函数
    return () => {
      console.log('[Call] 🧹 清理 WebSocket 连接');
      // 不要关闭连接，保持给 Chat 页面复用
      // chatWSManager.close();
    };
    // ⚠️ 注意：不要把 startAutoRecording 和 playTTSAudio 加入依赖项！
    // 它们会频繁重新创建，导致 useEffect 无限循环重新执行。
    // handleInitialHistory 和 setMessages 来自 useLazyLoadMessages，应该是稳定的引用，
    // 但为了避免潜在的问题，我们只依赖 currentSession.session_id。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSession?.session_id]);
  
  /**
   * 📱 挂断电话：停止录音和播放，返回 Chat 页面
   */
  const handleHangup = useCallback(() => {
    console.log('[Call] 📞 挂断电话');
    
    // 停止自动录音循环
    autoRecordingEnabledRef.current = false;
    
    // 停止录音
    if (isRecording) {
      cancelRecording();
    }
    
    // 停止 TTS 播放并清空队列
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setIsPlaying(false);
    audioQueueRef.current = [];
    isPlayingQueueRef.current = false;
    
    // 返回 Chat 页面（不关闭 WebSocket，保持连接）
    navigate('/chat');
  }, [isRecording, cancelRecording, navigate]);
  
  /**
   * 🖼️ 加载会话背景图片
   */
  useEffect(() => {
    (async () => {
      try {
        const token = useAuthStore.getState().token;
        if (!token || !currentSession?.session_id) {
          setBackgroundImageUrl('');
          return;
        }

        const resp = await fetch(`/api/auth/role-background/${encodeURIComponent(currentSession.session_id)}`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (resp.ok) {
          const data = await resp.json();
          const url = data.data_url || data.background_url || '';
          setBackgroundImageUrl(url);
        } else {
          setBackgroundImageUrl('');
        }
      } catch (e) {
        console.error('[Call] 背景图片加载失败:', e);
        setBackgroundImageUrl('');
      }
    })();
  }, [currentSession?.session_id]);

  const menuItems: MenuProps['items'] = [
    {
      key: 'background',
      icon: <PictureOutlined />,
      label: (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
          <span>显示背景</span>
          <Switch 
            size="small"
            checked={showBackground}
            onChange={(checked) => {
              setShowBackground(checked);
              message.success(checked ? '背景已显示' : '背景已隐藏');
            }}
            onClick={(_, e) => e.stopPropagation()}
          />
        </div>
      )
    }
  ];
  
  // 组件挂载时启用自动录音，卸载时停止录音
  useEffect(() => {
    console.log('[Call] 🎬 组件挂载，启用自动录音');
    autoRecordingEnabledRef.current = true;
    
    return () => {
      console.log('[Call] 🎬 组件卸载，停止所有资源');
      
      // 1. 禁用自动录音循环
      autoRecordingEnabledRef.current = false;
      
      // 2. 停止录音（使用 ref 获取最新的 cancelRecording）
      console.log('[Call] 🛑 停止录音（使用最新 ref）');
      cancelRecordingRef.current();
      
      // 3. 停止 TTS 播放并清空队列
      if (audioRef.current) {
        console.log('[Call] 🔇 停止 TTS 播放');
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
        audioRef.current = null;
      }
      audioQueueRef.current = [];
      isPlayingQueueRef.current = false;
      
      console.log('[Call] ✅ 所有资源已清理');
    };
  }, []); // 空依赖数组，只在挂载和卸载时执行
  
  // 显示最近的对话作为字幕
  const getSubtitleText = useCallback(() => {
    if (!showSubtitle) return null;
    
    const lastMessage = messages[messages.length - 1];
    if (!lastMessage) return subtitle;
    
    // 根据状态显示不同内容
    if (callStatus === 'listening') {
      return '请说话...';
    } else if (callStatus === 'thinking') {
      return lastMessage.role === 'user' 
        ? `你: ${lastMessage.content.substring(0, 50)}...` 
        : '正在思考...';
    } else if (callStatus === 'speaking') {
      return lastMessage.role === 'assistant'
        ? lastMessage.content.substring(0, 100)
        : '正在回复...';
    }
    
    return subtitle;
  }, [messages, callStatus, showSubtitle, subtitle]);
  
  // 自动滚动到历史消息底部
  useEffect(() => {
    if (showHistory && historyContainerRef.current) {
      historyContainerRef.current.scrollTop = historyContainerRef.current.scrollHeight;
    }
  }, [messages, showHistory]);

  return (
    <Layout 
      className={styles.callLayout}
      style={{
        backgroundImage: showBackground && backgroundImageUrl ? `url(${backgroundImageUrl})` : undefined,
        backgroundSize: 'cover',
        backgroundPosition: 'center'
      }}
    >
      {/* 左侧主要内容区域（横屏时为左半部分） */}
      <div className={`${styles.mainContent} ${!showHistory ? styles.fullWidth : ''}`}>
      {/* 顶部菜单区域 */}
      <div className={`${styles.topBar} ${showHistory ? styles.topBarFloating : ''}`}>
        <Dropdown menu={{ items: menuItems }} trigger={['click']}>
          <Button type="text" className={styles.menuButton} icon={<MoreOutlined />} />
        </Dropdown>
          <div className={styles.topRight}>
            <Switch
              checkedChildren={<MessageOutlined />}
              unCheckedChildren={<MessageOutlined />}
              checked={showHistory}
              onChange={setShowHistory}
              title="显示对话历史"
            />
        <Switch
          checkedChildren="字幕"
          unCheckedChildren="字幕"
              checked={showSubtitle}
          onChange={setShowSubtitle}
        />
          </div>
      </div>

      {/* 中间内容区域 */}
      <div className={styles.content}>
          {/* 头像/可视化圆圈 - 显示背景时隐藏 */}
          {!(showBackground && backgroundImageUrl) && (
            <div 
              className={styles.circleContainer}
              style={{
                backgroundImage: currentSession?.role_avatar_url 
                  ? `url(${getFullUrl(currentSession.role_avatar_url)})` 
                  : undefined,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                animation: isPlaying 
                  ? 'pulse 1.5s ease-in-out infinite' 
                  : isSpeaking 
                  ? 'pulse 0.8s ease-in-out infinite'
                  : 'none'
              }}
            />
          )}
          
          {/* 状态指示 - 仅在历史消息未显示时显示在中间 */}
          {!showHistory && (
        <div className={styles.status}>
                {callStatus === 'connecting' && '正在连接...'}
                {callStatus === 'ready' && '准备就绪'}
                {callStatus === 'listening' && '正在聆听...'}
                {callStatus === 'thinking' && '正在思考...'}
                {callStatus === 'speaking' && '正在回复...'}
        </div>
          )}

          {/* 字幕 */}
        {showSubtitle && (
          <div className={styles.subtitle}>
              {getSubtitleText()}
          </div>
        )}
      </div>

      {/* 底部控制栏 */}
      <div className={styles.bottomBar}>
        <Button 
            icon={isCallPaused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
          size="large"
            onClick={handleTogglePause}
            title={isCallPaused ? '继续通话' : '暂停通话'}
            style={{
              color: isCallPaused ? '#52c41a' : undefined
            }}
        />
        <div className={styles.hangupContainer}>
        <Button 
          className={styles.hangupBtn}
          icon={<PhoneOutlined />}
          size="large"
          onClick={handleHangup}
              title="挂断"
          />
          {/* 状态指示 - 在历史消息显示时显示在挂断按钮下方 */}
          {showHistory && (
            <div className={styles.statusInHangup}>
                {callStatus === 'connecting' && '正在连接...'}
                {callStatus === 'ready' && '准备就绪'}
                {callStatus === 'listening' && '正在聆听...'}
                {callStatus === 'thinking' && '正在思考...'}
                {callStatus === 'speaking' && '正在回复...'}
            </div>
          )}
        </div>
        <Button 
          icon={<VideoCameraOutlined />} 
          size="large"
            disabled
            title="视频通话（开发中）"
        />
        </div>
      </div>

      {/* 历史消息面板（手机端全屏，电脑/平板横屏时右侧固定） */}
      {showHistory && (
        <div className={styles.historyOverlay}>
          <div className={styles.historyContent} ref={historyContainerRef}>
            {messages.length === 0 ? (
              <div className={styles.emptyHistory}>暂无对话记录</div>
            ) : (
              messages.map((msg, index) => (
                <div 
                  key={msg.id || index} 
                  className={
                    msg.role === 'user' 
                      ? styles.historyMessageUser 
                      : styles.historyMessageAssistant
                  }
                >
                  <div className={styles.historyMessageRole}>
                    {msg.role === 'user' ? '你' : currentSession?.name || 'AI'}
                  </div>
                  <div className={styles.historyMessageContent}>
                    {msg.content}
                  </div>
                  {msg.timestamp && (
                    <div className={styles.historyMessageTime}>
                      {new Date(msg.timestamp).toLocaleTimeString('zh-CN', {
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
      
      {/* 添加呼吸动画 */}
      <style>{`
        @keyframes pulse {
          0% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.05); opacity: 0.8; }
          100% { transform: scale(1); opacity: 1; }
        }
      `}</style>
    </Layout>
  );
};

export default Call; 