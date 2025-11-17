import { create } from 'zustand';
import { useAuthStore } from './authStore';
import api from '../utils/api';
import { GroupChatWSManager, WSState } from '../utils/GroupChatWSManager';

// ============ 类型定义 ============

export interface GroupMember {
  member_id: string;
  member_type: 'user' | 'ai';
  nickname: string;
  avatar?: string;
  status: 'online' | 'offline' | 'busy';
  role: 'owner' | 'admin' | 'member';
  joined_at: string;
}

export interface GroupMessage {
  message_id: string;
  sender_id: string;
  sender_name: string;
  content: string;
  timestamp: string;
  read_by: string[];
  images?: string[];  // 消息中的图片
  reference?: any[];  // 知识库引用（与普通会话字段名一致）
}

export interface Group {
  group_id: string;
  name: string;
  description?: string;
  avatar?: string;
  role_background_url?: string;  // 群聊背景图
  members: GroupMember[];
  created_at: string;
  updated_at: string;
  last_message?: GroupMessage;
  unread_count: number;
}

interface GroupChatState {
  // 当前用户信息
  currentUserId: string;
  
  // 群组列表
  groups: Group[];
  
  // 当前选中的群组
  currentGroupId: string | null;
  
  // 当前群组的消息
  messages: Record<string, GroupMessage[]>;
  
  // 懒加载状态（每个群组独立）
  messageMetadata: Record<string, {
    total: number;
    loaded: number;
    hasMore: boolean;
    isLoading: boolean;
    oldestTimestamp?: number;  // 最旧消息的时间戳，用于游标分页
  }>;
  
  // 加载状态
  loading: boolean;
  
  // 错误信息
  error: string | null;
  
  // WebSocket 连接
  websocketManager: GroupChatWSManager | null;
  websocketState: WSState;
  
  // ============ Actions ============
  
  // 设置当前用户ID
  setCurrentUserId: (userId: string) => void;
  
  // 获取群组列表
  fetchGroups: () => Promise<void>;
  
  // 创建群组
  createGroup: (name: string, description?: string, memberIds?: string[]) => Promise<string>;
  
  // 选择群组
  selectGroup: (groupId: string) => Promise<void>;
  
  // 获取群组详情
  fetchGroupDetail: (groupId: string) => Promise<void>;
  
  // 发送消息（HTTP fallback，不推荐使用）
  sendMessageHttp: (groupId: string, content: string) => Promise<void>;
  
  // 通过 WebSocket 发送消息（推荐）
  sendMessage: (content: string, images?: string[], mentions?: string[], replyTo?: string) => void;
  
  // 获取群组消息
  fetchMessages: (groupId: string, limit?: number) => Promise<void>;
  
  // 懒加载更多消息
  loadMoreMessages: (groupId: string) => Promise<void>;
  
  // 处理初始历史消息（WebSocket推送）
  handleInitialHistory: (groupId: string, data: { messages: GroupMessage[], total: number, loaded: number, has_more: boolean }) => void;
  
  // 添加成员
  addMember: (groupId: string, memberType: 'user' | 'ai', memberId: string, nickname?: string) => Promise<void>;
  
  // 移除成员
  removeMember: (groupId: string, memberId: string) => Promise<void>;
  
  // 设置成员为管理员
  setMemberAdmin: (groupId: string, memberId: string) => Promise<void>;
  
  // 取消成员的管理员身份
  removeMemberAdmin: (groupId: string, memberId: string) => Promise<void>;
  
  // AI上线
  aiGoOnline: (groupId: string, aiMemberId: string) => Promise<void>;
  
  // AI下线
  aiGoOffline: (groupId: string, aiMemberId: string) => Promise<void>;
  
  // 批量AI上线
  batchAiGoOnline: (groupId: string) => Promise<any>;
  
  // 批量AI下线
  batchAiGoOffline: (groupId: string) => Promise<any>;
  
  // 更新群组信息
  updateGroup: (groupId: string, updates: Partial<Pick<Group, 'name' | 'description' | 'avatar'>>) => Promise<void>;
  
  // 删除群组
  deleteGroup: (groupId: string) => Promise<void>;
  
  // 清除错误
  clearError: () => void;
  
  // 实时更新消息（供WebSocket使用）
  addMessageRealtime: (groupId: string, message: GroupMessage) => void;
  
  // 更新成员状态（供WebSocket使用）
  updateMemberStatus: (groupId: string, memberId: string, status: 'online' | 'offline' | 'busy') => void;
  
  // WebSocket 连接管理
  connectWebSocket: (groupId: string, userId: string, token: string) => void;
  disconnectWebSocket: () => void;
  
  // 清除当前群组ID（切换到非群聊会话时调用）
  clearCurrentGroup: () => void;
}

// ============ Store Implementation ============

export const useGroupChatStore = create<GroupChatState>((set, get) => ({
  currentUserId: '',
  groups: [],
  currentGroupId: null,
  messages: {},
  messageMetadata: {},
  loading: false,
  error: null,
  websocketManager: null,
  websocketState: WSState.DISCONNECTED,
  
  setCurrentUserId: (userId: string) => {
    set({ currentUserId: userId });
  },
  
  fetchGroups: async () => {
    try {
      set({ loading: true, error: null });
      
      console.log('📡 获取群组列表，Token:', useAuthStore.getState().token ? '✅ 存在' : '❌ 不存在');
      
      const response = await api.get('/api/group-chat/groups');
      
      console.log('✅ 获取群组成功:', response.data);
      set({ groups: response.data || [], loading: false });
    } catch (error: any) {
      console.error('❌ 获取群组失败:', error.response?.data || error.message);
      set({ 
        error: error.response?.data?.detail || '获取群组列表失败', 
        loading: false 
      });
    }
  },
  
  createGroup: async (name: string, description?: string, memberIds?: string[]) => {
    try {
      set({ loading: true, error: null });
      
      const response = await api.post('/api/group-chat/groups', {
        name,
        description,
        initial_ai_sessions: memberIds || []
      });
      
      const newGroup = response.data;
      
      // 直接添加到本地列表，避免重新获取
      set(state => ({
        groups: Array.isArray(state.groups) ? [newGroup, ...state.groups] : [newGroup],
        loading: false
      }));
      
      return newGroup.group_id;
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || '创建群组失败', 
        loading: false 
      });
      throw error;
    }
  },
  
  selectGroup: async (groupId: string) => {
    set({ currentGroupId: groupId });
    // ✅ 不再主动调用 fetchMessages，历史消息由 WebSocket 自动推送
    // WebSocket 连接成功后，后端会自动发送 history 消息
    
    // 🔥 刷新群组详情，确保成员列表是最新的（包含最新头像）
    try {
      await get().fetchGroupDetail(groupId);
    } catch (error) {
      console.warn('刷新群组详情失败:', error);
    }
  },
  
  fetchGroupDetail: async (groupId: string) => {
    try {
      set({ loading: true, error: null });
      
      const response = await api.get(`/api/group-chat/groups/${groupId}`);
      
      // 更新群组列表中的该群组
      set(state => ({
        groups: state.groups.map(g => 
          g.group_id === groupId ? { ...g, ...response.data } : g
        ),
        loading: false
      }));
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || '获取群组详情失败', 
        loading: false 
      });
    }
  },
  
  sendMessage: (content: string, images?: string[], mentions?: string[], replyTo?: string) => {
    const { websocketManager } = get();
    
    if (!websocketManager || !websocketManager.isConnected()) {
      console.error('❌ WebSocket 未连接，无法发送消息');
      set({ error: 'WebSocket未连接，消息将在重连后发送' });
      
      // 即使未连接，也尝试发送（会自动加入队列）
      if (websocketManager) {
        websocketManager.sendMessage(content, {
          images: images || [],
          mentions: mentions || [],
          reply_to: replyTo
        });
      }
      return;
    }
    
    console.log('📤 发送消息:', content);
    websocketManager.sendMessage(content, {
      images: images || [],
      mentions: mentions || [],
      reply_to: replyTo
    });
  },
  
  sendMessageHttp: async (groupId: string, content: string) => {
    try {
      const response = await api.post(`/api/group-chat/groups/${groupId}/messages`, {
        sender_id: get().currentUserId,
        content
      });
      
      // 立即添加到本地消息列表
      const newMessage = response.data.message;
      set(state => ({
        messages: {
          ...state.messages,
          [groupId]: [...(state.messages[groupId] || []), newMessage]
        }
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '发送消息失败' });
      throw error;
    }
  },
  
  fetchMessages: async (groupId: string, limit: number = 50) => {
    try {
      const response = await api.get(`/api/group-chat/groups/${groupId}/messages`, {
        params: { limit }
      });
      
      set(state => ({
        messages: {
          ...state.messages,
          [groupId]: response.data.messages
        }
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '获取消息失败' });
    }
  },
  
  loadMoreMessages: async (groupId: string) => {
    const state = get();
    const metadata = state.messageMetadata[groupId];
    
    // 如果没有更多消息或正在加载，直接返回
    if (!metadata?.hasMore || metadata?.isLoading) {
      console.log('⏸️ 跳过加载更多消息:', { hasMore: metadata?.hasMore, isLoading: metadata?.isLoading });
      return;
    }
    
    // 设置加载状态
    set(state => ({
      messageMetadata: {
        ...state.messageMetadata,
        [groupId]: {
          ...state.messageMetadata[groupId],
          isLoading: true
        }
      }
    }));
    
    try {
      const currentMessages = state.messages[groupId] || [];
      const limit = 20; // 每次加载20条
      
      // 使用最旧消息的时间戳作为游标
      const beforeTimestamp = metadata.oldestTimestamp;
      
      console.log('📥 加载更多群聊消息:', { groupId, beforeTimestamp, limit });
      
      const response = await api.get(`/api/group-chat/groups/${groupId}/messages`, {
        params: { 
          limit, 
          before_timestamp: beforeTimestamp 
        }
      });
      
      const data = response.data;
      const newMessages = data.messages || [];
      
      console.log('✅ 加载更多消息成功:', {
        新消息数: newMessages.length,
        总消息数: data.total,
        还有更多: data.has_more,
        最旧时间戳: data.oldest_timestamp
      });
      
      // 将新消息添加到列表前面（因为是历史消息）
      set(state => ({
        messages: {
          ...state.messages,
          [groupId]: [...newMessages, ...currentMessages]
        },
        messageMetadata: {
          ...state.messageMetadata,
          [groupId]: {
            total: data.total,
            loaded: currentMessages.length + newMessages.length,
            hasMore: data.has_more,
            isLoading: false,
            oldestTimestamp: data.oldest_timestamp  // 更新最旧时间戳
          }
        }
      }));
    } catch (error: any) {
      console.error('❌ 加载更多消息失败:', error);
      set(state => ({
        error: error.response?.data?.detail || '加载更多消息失败',
        messageMetadata: {
          ...state.messageMetadata,
          [groupId]: {
            ...state.messageMetadata[groupId],
            isLoading: false
          }
        }
      }));
    }
  },
  
  handleInitialHistory: (groupId: string, data: { messages: GroupMessage[], total: number, loaded: number, has_more: boolean }) => {
    console.log('📨 处理初始历史消息:', {
      groupId,
      消息数: data.messages.length,
      总数: data.total,
      已加载: data.loaded,
      还有更多: data.has_more
    });
    
    // 找到最旧消息的时间戳
    let oldestTimestamp: number | undefined;
    if (data.messages.length > 0) {
      // 消息按时间倒序排列，最后一条是最旧的
      const oldestMessage = data.messages[data.messages.length - 1];
      oldestTimestamp = new Date(oldestMessage.timestamp).getTime();
    }
    
    set(state => ({
      messages: {
        ...state.messages,
        [groupId]: data.messages
      },
      messageMetadata: {
        ...state.messageMetadata,
        [groupId]: {
          total: data.total,
          loaded: data.loaded,
          hasMore: data.has_more,
          isLoading: false,
          oldestTimestamp  // 初始化最旧时间戳
        }
      }
    }));
  },
  
  addMember: async (groupId: string, memberType: 'user' | 'ai', memberId: string, nickname?: string) => {
    try {
      await api.post(`/api/group-chat/groups/${groupId}/members`, {
        member_id: memberId,
        member_type: memberType === 'user' ? 'human' : 'ai',  // 转换为后端期望的类型
        display_name: nickname  // 后端期望的字段名是 display_name
      });
      
      // 刷新群组详情
      await get().fetchGroupDetail(groupId);
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '添加成员失败' });
      throw error;
    }
  },
  
  removeMember: async (groupId: string, memberId: string) => {
    try {
      await api.delete(`/api/group-chat/groups/${groupId}/members/${memberId}`);
      
      // 刷新群组详情
      await get().fetchGroupDetail(groupId);
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '移除成员失败' });
      throw error;
    }
  },
  
  setMemberAdmin: async (groupId: string, memberId: string) => {
    try {
      await api.put(`/api/group-chat/groups/${groupId}/members/${memberId}/role`, null, {
        params: { role: 'admin' }
      });
      
      // 刷新群组详情
      await get().fetchGroupDetail(groupId);
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '设置管理员失败' });
      throw error;
    }
  },
  
  removeMemberAdmin: async (groupId: string, memberId: string) => {
    try {
      await api.put(`/api/group-chat/groups/${groupId}/members/${memberId}/role`, null, {
        params: { role: 'member' }
      });
      
      // 刷新群组详情
      await get().fetchGroupDetail(groupId);
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '取消管理员失败' });
      throw error;
    }
  },
  
  aiGoOnline: async (groupId: string, aiMemberId: string) => {
    try {
      await api.post(`/api/group-chat/groups/${groupId}/ai/${aiMemberId}/online`);
      
      // 更新本地成员状态
      set(state => ({
        groups: state.groups.map(g => {
          if (g.group_id === groupId) {
            return {
              ...g,
              members: g.members.map(m => 
                m.member_id === aiMemberId ? { ...m, status: 'online' } : m
              )
            };
          }
          return g;
        })
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'AI上线失败' });
      throw error;
    }
  },
  
  aiGoOffline: async (groupId: string, aiMemberId: string) => {
    try {
      await api.post(`/api/group-chat/groups/${groupId}/ai/${aiMemberId}/offline`);
      
      // 更新本地成员状态
      set(state => ({
        groups: state.groups.map(g => {
          if (g.group_id === groupId) {
            return {
              ...g,
              members: g.members.map(m => 
                m.member_id === aiMemberId ? { ...m, status: 'offline' } : m
              )
            };
          }
          return g;
        })
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || 'AI下线失败' });
      throw error;
    }
  },
  
  batchAiGoOnline: async (groupId: string) => {
    try {
      const response = await api.post(`/api/group-chat/groups/${groupId}/ai/batch-online`);
      
      // 更新本地所有AI成员状态为在线
      set(state => ({
        groups: state.groups.map(g => {
          if (g.group_id === groupId) {
            return {
              ...g,
              members: g.members.map(m => 
                m.member_type === 'ai' ? { ...m, status: 'online' } : m
              )
            };
          }
          return g;
        })
      }));
      
      return response.data;
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '批量上线AI失败' });
      throw error;
    }
  },
  
  batchAiGoOffline: async (groupId: string) => {
    try {
      const response = await api.post(`/api/group-chat/groups/${groupId}/ai/batch-offline`);
      
      // 更新本地所有AI成员状态为离线
      set(state => ({
        groups: state.groups.map(g => {
          if (g.group_id === groupId) {
            return {
              ...g,
              members: g.members.map(m => 
                m.member_type === 'ai' ? { ...m, status: 'offline' } : m
              )
            };
          }
          return g;
        })
      }));
      
      return response.data;
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '批量下线AI失败' });
      throw error;
    }
  },
  
  updateGroup: async (groupId: string, updates: Partial<Pick<Group, 'name' | 'description' | 'avatar'>>) => {
    try {
      await api.put(`/api/group-chat/groups/${groupId}`, updates);
      
      // 更新本地群组信息
      set(state => ({
        groups: state.groups.map(g => 
          g.group_id === groupId ? { ...g, ...updates } : g
        )
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '更新群组失败' });
      throw error;
    }
  },
  
  deleteGroup: async (groupId: string) => {
    try {
      await api.delete(`/api/group-chat/groups/${groupId}`);
      
      // 从本地移除群组
      set(state => ({
        groups: state.groups.filter(g => g.group_id !== groupId),
        currentGroupId: state.currentGroupId === groupId ? null : state.currentGroupId
      }));
    } catch (error: any) {
      set({ error: error.response?.data?.detail || '删除群组失败' });
      throw error;
    }
  },
  
  clearError: () => {
    set({ error: null });
  },
  
  addMessageRealtime: (groupId: string, message: GroupMessage) => {
    set(state => {
      const currentMessages = state.messages[groupId] || [];
      const existingIndex = currentMessages.findIndex(m => m.message_id === message.message_id);
      
      let updatedMessages;
      if (existingIndex >= 0) {
        // 更新已存在的消息（流式更新）
        updatedMessages = [...currentMessages];
        updatedMessages[existingIndex] = message;
      } else {
        // 添加新消息
        updatedMessages = [...currentMessages, message];
      }
      
      return {
        messages: {
          ...state.messages,
          [groupId]: updatedMessages
        },
        groups: state.groups.map(g => 
          g.group_id === groupId 
            ? { ...g, last_message: message, unread_count: existingIndex >= 0 ? g.unread_count : g.unread_count + 1 }
            : g
        )
      };
    });
  },
  
  updateMemberStatus: (groupId: string, memberId: string, status: 'online' | 'offline' | 'busy') => {
    set(state => ({
      groups: state.groups.map(g => {
        if (g.group_id === groupId) {
          return {
            ...g,
            members: g.members.map(m => 
              m.member_id === memberId ? { ...m, status } : m
            )
          };
        }
        return g;
      })
    }));
  },
  
  connectWebSocket: (groupId: string, userId: string, token: string) => {
    // 断开已有连接
    const { websocketManager } = get();
    if (websocketManager) {
      websocketManager.destroy();
    }
    
    // 创建新的 WebSocket 管理器
    const manager = new GroupChatWSManager({
      groupId,
      userId,
      token,
      heartbeatInterval: 30000, // 30秒心跳
      reconnect: {
        enabled: true,
        maxAttempts: 10,
        delay: 1000,
        backoff: 1.5,
        maxDelay: 30000
      }
    });
    
    // 监听消息
    manager.onMessage((message) => {
      console.log('📨 收到 WebSocket 消息:', message.type);
      
      switch (message.type) {
        case 'auth_success':
          console.log('✅ WebSocket 认证成功');
          break;
          
        case 'history':
          // 加载历史消息（懒加载模式）
          if (message.data?.messages) {
            get().handleInitialHistory(groupId, {
              messages: message.data.messages,
              total: message.data.total || message.data.messages.length,
              loaded: message.data.loaded || message.data.messages.length,
              has_more: message.data.has_more || false
            });
          }
          break;
          
        case 'message':
          // 新消息
          if (message.data) {
            console.log('📩 收到新消息:', message.data);
            get().addMessageRealtime(groupId, message.data);
          }
          break;
          
        case 'message_sent':
          // 消息发送确认 - 立即显示在聊天框
          if (message.data) {
            console.log('✅ 消息已发送，添加到聊天框:', message.data);
            get().addMessageRealtime(groupId, message.data);
          }
          break;
          
        case 'member_status':
          // 成员状态变更
          if (message.data?.member_id && message.data?.status) {
            get().updateMemberStatus(groupId, message.data.member_id, message.data.status);
          }
          break;
          
        case 'messages_cleared':
          // 历史消息已被清空
          console.log('🗑️ 历史消息已被清空:', message.data);
          set(state => ({
            messages: {
              ...state.messages,
              [groupId]: []
            },
            messageMetadata: {
              ...state.messageMetadata,
              [groupId]: {
                total: 0,
                loaded: 0,
                hasMore: false,
                isLoading: false,
                oldestTimestamp: undefined
              }
            }
          }));
          break;
          
        case 'error':
          console.error('❌ WebSocket 错误:', message.data?.message);
          set({ error: message.data?.message || 'WebSocket错误' });
          break;
          
        default:
          console.log('未知消息类型:', message.type);
      }
    });
    
    // 监听状态变更
    manager.onStateChange((state) => {
      console.log('🔄 WebSocket 状态变更:', state);
      set({ websocketState: state });
      
      // 如果连接失败且达到最大重连次数，显示错误
      if (state === WSState.ERROR) {
        set({ error: 'WebSocket连接失败，请刷新页面重试' });
      }
    });
    
    // 监听错误
    manager.onError((error) => {
      console.error('❌ WebSocket 错误:', error);
    });
    
    // 连接
    manager.connect();
    
    set({ websocketManager: manager });
  },
  
  disconnectWebSocket: () => {
    const { websocketManager } = get();
    if (websocketManager) {
      console.log('🔌 主动断开 WebSocket');
      websocketManager.disconnect();
      set({ websocketManager: null, websocketState: WSState.DISCONNECTED });
    }
  },
  
  clearCurrentGroup: () => {
    console.log('🧹 清除当前群组ID');
    set({ currentGroupId: null });
  }
}));

