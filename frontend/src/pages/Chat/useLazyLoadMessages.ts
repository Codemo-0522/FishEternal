import { useState, useCallback, useRef, useEffect } from 'react';
import axios from 'axios';
import type { ChatMessage } from './Chat';

interface LazyLoadState {
  messages: ChatMessage[];
  isLoading: boolean;
  hasMore: boolean;
  total: number;
  loaded: number;
  error: string | null;
}

interface UseLazyLoadMessagesOptions {
  sessionId: string | null;
  batchSize?: number;
}

interface UseLazyLoadMessagesReturn extends LazyLoadState {
  loadMoreMessages: () => Promise<void>;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  reset: () => void;
  handleInitialHistory: (historyData: any) => void;
}

/**
 * SessionStorage 缓存配置
 */
const SESSION_CACHE_KEY_PREFIX = 'chat_messages_cache_';
const MAX_CACHED_MESSAGES = 50; // 每个会话最多缓存50条消息，防止前端卡顿

/**
 * 从 SessionStorage 恢复消息缓存
 */
const loadMessagesFromCache = (sessionId: string | null): ChatMessage[] => {
  if (!sessionId) return [];
  
  try {
    const cacheKey = `${SESSION_CACHE_KEY_PREFIX}${sessionId}`;
    const cached = sessionStorage.getItem(cacheKey);
    if (cached) {
      const messages = JSON.parse(cached);
      console.log(`[LazyLoad] 从缓存恢复 ${messages.length} 条消息 (sessionId: ${sessionId})`);
      return messages;
    }
  } catch (error) {
    console.error('[LazyLoad] 恢复消息缓存失败:', error);
  }
  return [];
};

/**
 * 保存消息到 SessionStorage（限制数量）
 */
const saveMessagesToCache = (sessionId: string | null, messages: ChatMessage[]) => {
  if (!sessionId) return;
  
  try {
    const cacheKey = `${SESSION_CACHE_KEY_PREFIX}${sessionId}`;
    // 只缓存最新的 MAX_CACHED_MESSAGES 条消息
    const messagesToCache = messages.slice(-MAX_CACHED_MESSAGES);
    sessionStorage.setItem(cacheKey, JSON.stringify(messagesToCache));
    console.log(`[LazyLoad] 缓存 ${messagesToCache.length} 条消息 (sessionId: ${sessionId})`);
  } catch (error) {
    console.error('[LazyLoad] 保存消息缓存失败:', error);
  }
};

/**
 * 清除指定会话的消息缓存
 */
const clearMessagesCache = (sessionId: string | null) => {
  if (!sessionId) return;
  
  try {
    const cacheKey = `${SESSION_CACHE_KEY_PREFIX}${sessionId}`;
    sessionStorage.removeItem(cacheKey);
    console.log(`[LazyLoad] 清除消息缓存 (sessionId: ${sessionId})`);
  } catch (error) {
    console.error('[LazyLoad] 清除消息缓存失败:', error);
  }
};

/**
 * 企业级消息懒加载Hook
 * 
 * 功能：
 * 1. 滚动到顶部自动加载更多历史消息
 * 2. 防止重复加载
 * 3. 错误处理和重试机制
 * 5. 页面跳转返回时自动恢复消息（通过 SessionStorage）
 * 6. 智能缓存限制（每个会话最多缓存50条消息，防止卡顿）
 */
export const useLazyLoadMessages = ({
  sessionId,
  batchSize = 20
}: UseLazyLoadMessagesOptions): UseLazyLoadMessagesReturn => {
  
  // 从缓存恢复初始状态
  const [state, setState] = useState<LazyLoadState>(() => {
    const cachedMessages = loadMessagesFromCache(sessionId);
    return {
      messages: cachedMessages,
      isLoading: false,
      hasMore: false,
      total: cachedMessages.length,
      loaded: cachedMessages.length,
      error: null
    };
  });

  // 防止重复加载
  const loadingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentSessionIdRef = useRef<string | null>(sessionId);

  /**
   * 重置状态（切换会话时使用）
   */
  const reset = useCallback(() => {
    // 取消进行中的请求
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    
    // 清除旧会话的缓存
    clearMessagesCache(currentSessionIdRef.current);
    
    loadingRef.current = false;
    setState({
      messages: [],
      isLoading: false,
      hasMore: false,
      total: 0,
      loaded: 0,
      error: null
    });
  }, []);

  /**
   * 处理WebSocket初始历史消息
   */
  const handleInitialHistory = useCallback((historyData: any) => {
    console.log('[LazyLoad] 处理初始历史消息:', historyData);
    
    const messages = historyData.messages || [];
    const total = historyData.total || messages.length;
    const loaded = historyData.loaded || messages.length;
    const hasMore = historyData.has_more || false;

    setState({
      messages: messages,
      isLoading: false,
      hasMore: hasMore,
      total: total,
      loaded: loaded,
      error: null
    });
    
    // 保存到缓存
    saveMessagesToCache(sessionId, messages);
  }, [sessionId]);

  /**
   * 加载更多历史消息
   */
  const loadMoreMessages = useCallback(async () => {
    // 防止重复加载
    if (loadingRef.current || !state.hasMore || !sessionId) {
      return;
    }

    // 如果当前消息数量已经等于或超过loaded，说明需要加载更多
    const currentOffset = state.messages.length;
    
    // 如果已加载数量等于总数，不需要再加载
    if (currentOffset >= state.total) {
      console.log('[LazyLoad] 已加载全部消息');
      setState(prev => ({ ...prev, hasMore: false }));
      return;
    }

    console.log(`[LazyLoad] 开始加载更多消息 - 当前: ${currentOffset}, 总数: ${state.total}`);
    
    loadingRef.current = true;
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      // 创建AbortController用于取消请求
      abortControllerRef.current = new AbortController();
      
      // 计算需要加载的范围（从最早的消息开始）
      const oldestLoadedCount = state.total - currentOffset;
      const offset = Math.max(0, oldestLoadedCount - batchSize);
      const limit = oldestLoadedCount - offset;

      console.log(`[LazyLoad] 请求参数 - offset: ${offset}, limit: ${limit}`);

      // 传统模式
      const response = await axios.get(`/api/chat/sessions/${sessionId}/messages`, {
        params: { offset, limit },
        signal: abortControllerRef.current.signal
      });

      const data = response.data;
      const newMessages = data.messages;

      if (newMessages && newMessages.length > 0) {
        console.log(`[LazyLoad] 成功加载 ${newMessages.length} 条历史消息`);
        
        setState(prev => {
          const updatedMessages = [...newMessages, ...prev.messages];  // 前置插入旧消息
          
          // 保存到缓存（自动限制数量）
          saveMessagesToCache(sessionId, updatedMessages);
          
          return {
            ...prev,
            messages: updatedMessages,
            loaded: prev.loaded + newMessages.length,
            hasMore: offset > 0,  // 还有更早的消息
            isLoading: false
          };
        });
      } else {
        setState(prev => ({
          ...prev,
          hasMore: false,
          isLoading: false
        }));
      }

    } catch (error: any) {
      if (error.name === 'CanceledError' || error.code === 'ERR_CANCELED') {
        console.log('[LazyLoad] 请求已取消');
      } else {
        console.error('[LazyLoad] 加载更多消息失败:', error);
        setState(prev => ({
          ...prev,
          isLoading: false,
          error: '加载失败，请重试'
        }));
      }
    } finally {
      loadingRef.current = false;
      abortControllerRef.current = null;
    }
  }, [sessionId, state.hasMore, state.messages.length, state.total, batchSize]);

  /**
   * 直接设置消息（用于实时消息追加）
   */
  const setMessages = useCallback((updater: React.SetStateAction<ChatMessage[]>) => {
    setState(prev => {
      const newMessages = typeof updater === 'function' ? updater(prev.messages) : updater;
      
      // 保存到缓存（自动限制数量）
      saveMessagesToCache(sessionId, newMessages);
      
      return {
        ...prev,
        messages: newMessages,
        loaded: newMessages.length
      };
    });
  }, [sessionId]);

  // 监听 sessionId 变化，更新 ref
  useEffect(() => {
    currentSessionIdRef.current = sessionId;
  }, [sessionId]);

  // 组件卸载时取消请求
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return {
    ...state,
    loadMoreMessages,
    setMessages,
    reset,
    handleInitialHistory
  };
};

