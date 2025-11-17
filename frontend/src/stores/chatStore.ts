import { create } from 'zustand'
import axios from 'axios'

interface ModelSettings {
  modelService: string;
  baseUrl: string;
  apiKey: string;
  modelName: string;
  modelParams?: Record<string, any>;
}

export interface ChatSession {
  session_id: string;
  name: string;
  created_at: string;
  model_settings: ModelSettings;
  system_prompt?: string;
  context_count?: number | null; // null表示不限制上下文
  message_count?: number; // 消息数量
  role_avatar_url?: string; // 角色头像URL
  role_background_url?: string; // 会话背景URL
  kb_settings?: any; // 知识库配置
  kb_parsed?: boolean; // 知识库是否已解析入库
  tts_settings?: {
    provider: string;
    config: Record<string, string>;
    voice_settings?: Record<string, any>;
  }; // TTS配置
  session_type?: 'personal' | 'group'; // 会话类型：个人对话或群聊
  group_id?: string; // 群聊ID（当session_type为'group'时使用）
}

interface ChatStore {
  sessions: ChatSession[];
  currentSession: ChatSession | null;
  isLoading: boolean;
  error: string | null;
  
  // 创建新会话
  createSession: (modelSettings: ModelSettings, systemPrompt?: string) => Promise<ChatSession>;
  // 获取所有会话
  fetchSessions: () => Promise<void>;
  // 设置当前会话
  setCurrentSession: (session: ChatSession | null) => void;
  // 设置错误
  setError: (error: string | null) => void;
  updateSession: (sessionId: string, updateData: Partial<ChatSession>) => Promise<void>;
  updateSessionMessageCount: (sessionId: string, messageCount: number) => void;
  deleteSession: (sessionId: string) => Promise<void>;
}

export const useChatStore = create<ChatStore>((set) => ({
  sessions: [],
  currentSession: null,
  isLoading: false,
  error: null,

  createSession: async (modelSettings: ModelSettings, systemPrompt?: string) => {
    // 安全日志：不打印完整模型配置，避免泄露API密钥
    console.log('[ChatStore] 开始创建新会话');
    console.log('[ChatStore] 模型服务:', modelSettings.modelService, '模型名称:', modelSettings.modelName);
    console.log('[ChatStore] System Prompt长度:', systemPrompt?.length || 0);
    set({ isLoading: true, error: null });
    try {
      const sessionName = new Date().toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      });
      console.log('[ChatStore] 生成会话名称:', sessionName);

      const requestData = {
        name: sessionName,
        model_settings: modelSettings,
        system_prompt: systemPrompt
      };
      // 安全日志：不打印包含API密钥的请求数据
      console.log('[ChatStore] 准备创建会话，会话名:', sessionName);

      const response = await axios.post('/api/chat/sessions', requestData);
      console.log('[ChatStore] 创建会话成功，会话ID:', response.data.session_id);

      const newSession: ChatSession = {
        session_id: response.data.session_id,
        name: response.data.name,
        created_at: response.data.created_at,
        model_settings: response.data.model_settings,
        system_prompt: response.data.system_prompt,
        context_count: response.data.context_count,
        message_count: response.data.message_count || 0,
        role_avatar_url: response.data.role_avatar_url,
        kb_settings: response.data.kb_settings,
        kb_parsed: false,
        session_type: response.data.session_type || 'personal', // 默认为个人会话
        group_id: response.data.group_id
      };

      console.log('[ChatStore] 新会话格式化完成');

      set(state => {
        console.log('[ChatStore] 更新状态 - 当前会话数:', state.sessions.length);
        // 新会话添加到列表开头
        return {
          sessions: [newSession, ...state.sessions],
          currentSession: newSession,
          isLoading: false
        };
      });
      console.log('[ChatStore] 状态更新完成 - 新会话已添加到列表开头并设置为当前会话');
      
      return newSession;
    } catch (error) {
      console.error('[ChatStore] 创建会话失败:', error);
      if (axios.isAxiosError(error)) {
        console.error('[ChatStore] 请求错误详情:', {
          status: error.response?.status,
          data: error.response?.data,
          message: error.message
        });
      }
      set({ error: '创建会话失败，请重试', isLoading: false });
      throw error;
    }
  },

  fetchSessions: async () => {
    console.log('[ChatStore] 开始获取会话列表');
    set({ isLoading: true, error: null });
    try {
      const response = await axios.get('/api/chat/sessions');
      console.log('[ChatStore] 获取会话列表成功，原始数据:', response.data);

      // 确保每个会话对象都有正确的字段
      const formattedSessions: ChatSession[] = response.data.map((session: any) => ({
        session_id: session.session_id || session._id,
        name: session.name,
        created_at: session.created_at,
        model_settings: session.model_settings,
        system_prompt: session.system_prompt,
        context_count: session.context_count,
        message_count: session.message_count || 0,
        role_avatar_url: session.role_avatar_url,
        kb_settings: session.kb_settings,
        kb_parsed: session.kb_parsed === true,
        session_type: session.session_type || 'personal', // 默认为个人会话
        group_id: session.group_id
      }));

      // 按创建时间倒序排序（新的在前）
      formattedSessions.sort((a, b) => {
        const dateA = new Date(a.created_at).getTime();
        const dateB = new Date(b.created_at).getTime();
        return dateB - dateA; // 倒序排列
      });

      console.log('[ChatStore] 格式化并排序后的会话列表:', formattedSessions);

      // 更新状态时用新列表中的同一会话对象刷新 currentSession（以获取最新字段如 kb_settings）
      set(state => {
        const refreshedCurrent = state.currentSession
          ? (formattedSessions.find(s => s.session_id === state.currentSession!.session_id) || state.currentSession)
          : null;
        return {
          sessions: formattedSessions,
          currentSession: refreshedCurrent,
          isLoading: false
        };
      });
      console.log('[ChatStore] 会话列表已更新，数量:', formattedSessions.length);
    } catch (error) {
      console.error('[ChatStore] 获取会话列表失败:', error);
      if (axios.isAxiosError(error)) {
        console.error('[ChatStore] 请求错误详情:', {
          status: error.response?.status,
          data: error.response?.data,
          message: error.message
        });
      }
      set({ error: '获取会话列表失败，请重试', isLoading: false });
    }
  },

  setCurrentSession: (session) => {
    console.log('[ChatStore] 设置当前会话:', session);
    if (session) {
      console.log('[ChatStore] 会话ID:', session.session_id);
    }
    set({ currentSession: session });
  },

  setError: (error) => {
    console.log('[ChatStore] 设置错误信息:', error);
    set({ error });
  },

  updateSession: async (sessionId: string, updateData: Partial<ChatSession>) => {
    console.log('[ChatStore] 开始更新会话:', sessionId, updateData);
    set({ isLoading: true, error: null });
    try {
      const response = await axios.put(`/api/chat/sessions/${sessionId}`, updateData);
      console.log('[ChatStore] 更新会话成功，服务器响应:', response.data);

      // 更新会话列表中的会话
      set(state => ({
        sessions: state.sessions.map(session =>
          session.session_id === sessionId ? { ...session, ...response.data } : session
        ),
        currentSession: state.currentSession?.session_id === sessionId
          ? { ...state.currentSession, ...response.data }
          : state.currentSession,
        isLoading: false
      }));
    } catch (error) {
      console.error('[ChatStore] 更新会话失败:', error);
      set({ error: '更新会话失败，请重试', isLoading: false });
      throw error;
    }
  },

  updateSessionMessageCount: (sessionId: string, messageCount: number) => {
    console.log('[ChatStore] 更新会话消息数量:', sessionId, messageCount);
    set(state => ({
      sessions: state.sessions.map(session =>
        session.session_id === sessionId
          ? { ...session, message_count: messageCount }
          : session
      ),
      currentSession: state.currentSession?.session_id === sessionId
        ? { ...state.currentSession, message_count: messageCount }
        : state.currentSession
    }));
  },

  deleteSession: async (sessionId: string) => {
    console.log('[ChatStore] 开始删除会话:', sessionId);
    set({ isLoading: true, error: null });
    try {
      await axios.delete(`/api/chat/sessions/${sessionId}`);
      console.log('[ChatStore] 删除会话成功');

      // 更新状态，移除已删除的会话
      set(state => {
        const newState: any = {
          sessions: state.sessions.filter(session => session.session_id !== sessionId),
          isLoading: false
        };

        // 如果删除的是当前会话，清除当前会话
        if (state.currentSession?.session_id === sessionId) {
          newState.currentSession = null;
        }

        return newState;
      });
    } catch (error) {
      console.error('[ChatStore] 删除会话失败:', error);
      set({ error: '删除会话失败，请重试', isLoading: false });
      throw error;
    }
  }
})); 