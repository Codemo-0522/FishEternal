/**
 * 群聊WebSocket管理器
 * 
 * 功能：
 * 1. 自动重连 - 连接断开后自动重连
 * 2. 心跳保活 - 定时发送ping保持连接
 * 3. 状态管理 - 连接状态追踪
 * 4. 消息队列 - 断线期间消息缓存
 * 5. 事件监听 - 灵活的事件系统
 */

export enum WSState {
  CONNECTING = 'CONNECTING',
  CONNECTED = 'CONNECTED',
  DISCONNECTING = 'DISCONNECTING',
  DISCONNECTED = 'DISCONNECTED',
  RECONNECTING = 'RECONNECTING',
  ERROR = 'ERROR'
}

interface WSMessage {
  type: string;
  data?: any;
}

interface WSConfig {
  groupId: string;
  userId: string;
  token: string;
  // 心跳间隔（毫秒）
  heartbeatInterval?: number;
  // 重连配置
  reconnect?: {
    enabled: boolean;
    maxAttempts: number;
    delay: number; // 重连延迟（毫秒）
    backoff: number; // 退避系数
    maxDelay: number; // 最大延迟（毫秒）
  };
  // 消息队列配置
  messageQueue?: {
    enabled: boolean;
    maxSize: number;
  };
}

type MessageHandler = (message: WSMessage) => void;
type StateChangeHandler = (state: WSState) => void;
type ErrorHandler = (error: any) => void;

export class GroupChatWSManager {
  private ws: WebSocket | null = null;
  private config: Required<WSConfig>;
  private state: WSState = WSState.DISCONNECTED;
  
  // 心跳定时器
  private heartbeatTimer: NodeJS.Timeout | null = null;
  
  // 重连配置
  private reconnectAttempts = 0;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private shouldReconnect = true; // 控制是否应该重连
  
  // 消息队列（断线期间缓存的消息）
  private messageQueue: WSMessage[] = [];
  
  // 事件监听器
  private messageHandlers: MessageHandler[] = [];
  private stateChangeHandlers: StateChangeHandler[] = [];
  private errorHandlers: ErrorHandler[] = [];
  
  constructor(config: WSConfig) {
    this.config = {
      ...config,
      heartbeatInterval: config.heartbeatInterval || 30000, // 默认30秒
      reconnect: {
        enabled: true,
        maxAttempts: 10,
        delay: 1000,
        backoff: 1.5,
        maxDelay: 30000,
        ...config.reconnect
      },
      messageQueue: {
        enabled: true,
        maxSize: 100,
        ...config.messageQueue
      }
    };
  }
  
  /**
   * 连接WebSocket
   */
  connect(): void {
    if (this.state === WSState.CONNECTED || this.state === WSState.CONNECTING) {
      console.log('🔌 WebSocket已连接或正在连接中，跳过');
      return;
    }
    
    this.setState(WSState.CONNECTING);
    this.shouldReconnect = true;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/api/group-chat/ws/${this.config.groupId}`;
    
    console.log('🔌 连接 WebSocket:', wsUrl);
    
    try {
      this.ws = new WebSocket(wsUrl);
      this.setupEventHandlers();
    } catch (error) {
      console.error('❌ 创建WebSocket连接失败:', error);
      this.handleError(error);
      this.scheduleReconnect();
    }
  }
  
  /**
   * 设置WebSocket事件处理器
   */
  private setupEventHandlers(): void {
    if (!this.ws) return;
    
    this.ws.onopen = () => {
      console.log('✅ WebSocket 连接成功');
      this.setState(WSState.CONNECTED);
      this.reconnectAttempts = 0; // 重置重连计数
      
      // 发送认证消息
      this.sendAuth();
      
      // 启动心跳
      this.startHeartbeat();
      
      // 发送队列中的消息
      this.flushMessageQueue();
    };
    
    this.ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);
        console.log('📨 收到 WebSocket 消息:', message.type);
        
        // 分发消息给所有监听器
        this.messageHandlers.forEach(handler => {
          try {
            handler(message);
          } catch (error) {
            console.error('❌ 消息处理器执行错误:', error);
          }
        });
      } catch (error) {
        console.error('❌ 解析 WebSocket 消息失败:', error);
        this.handleError(error);
      }
    };
    
    this.ws.onerror = (error) => {
      console.error('❌ WebSocket 错误:', error);
      this.handleError(error);
    };
    
    this.ws.onclose = (event) => {
      console.log('🔌 WebSocket 连接关闭:', {
        code: event.code,
        reason: event.reason,
        wasClean: event.wasClean
      });
      
      this.stopHeartbeat();
      this.setState(WSState.DISCONNECTED);
      this.ws = null;
      
      // 如果应该重连且未超过最大重连次数
      if (this.shouldReconnect && this.config.reconnect.enabled) {
        this.scheduleReconnect();
      }
    };
  }
  
  /**
   * 发送认证消息
   */
  private sendAuth(): void {
    this.send({
      type: 'auth',
      data: {
        token: this.config.token,
        user_id: this.config.userId
      }
    });
  }
  
  /**
   * 启动心跳
   */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    
    this.heartbeatTimer = setInterval(() => {
      if (this.state === WSState.CONNECTED) {
        console.log('💓 发送心跳 ping');
        this.send({ type: 'ping' });
      }
    }, this.config.heartbeatInterval);
  }
  
  /**
   * 停止心跳
   */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
  
  /**
   * 计划重连
   */
  private scheduleReconnect(): void {
    if (!this.config.reconnect.enabled) {
      console.log('❌ 重连已禁用');
      return;
    }
    
    if (this.reconnectAttempts >= this.config.reconnect.maxAttempts) {
      console.error(`❌ 已达到最大重连次数 (${this.config.reconnect.maxAttempts})，停止重连`);
      this.setState(WSState.ERROR);
      return;
    }
    
    this.reconnectAttempts++;
    
    // 指数退避算法计算延迟
    const delay = Math.min(
      this.config.reconnect.delay * Math.pow(this.config.reconnect.backoff, this.reconnectAttempts - 1),
      this.config.reconnect.maxDelay
    );
    
    console.log(`🔄 计划重连 (${this.reconnectAttempts}/${this.config.reconnect.maxAttempts})，延迟: ${delay}ms`);
    this.setState(WSState.RECONNECTING);
    
    // 清除之前的重连定时器
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    
    this.reconnectTimer = setTimeout(() => {
      console.log(`🔄 开始重连 (第 ${this.reconnectAttempts} 次)`);
      this.connect();
    }, delay);
  }
  
  /**
   * 发送消息
   */
  send(message: WSMessage): boolean {
    if (this.state !== WSState.CONNECTED || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('⚠️ WebSocket 未连接，消息加入队列:', message.type);
      
      // 加入消息队列
      if (this.config.messageQueue.enabled) {
        if (this.messageQueue.length < this.config.messageQueue.maxSize) {
          this.messageQueue.push(message);
        } else {
          console.warn('⚠️ 消息队列已满，丢弃最旧的消息');
          this.messageQueue.shift();
          this.messageQueue.push(message);
        }
      }
      
      return false;
    }
    
    try {
      this.ws.send(JSON.stringify(message));
      return true;
    } catch (error) {
      console.error('❌ 发送消息失败:', error);
      this.handleError(error);
      return false;
    }
  }
  
  /**
   * 发送聊天消息
   */
  sendMessage(content: string, options?: {
    images?: string[];
    mentions?: string[];
    reply_to?: string;
  }): boolean {
    return this.send({
      type: 'message',
      data: {
        content,
        images: options?.images || [],
        mentions: options?.mentions || [],
        reply_to: options?.reply_to
      }
    });
  }
  
  /**
   * 刷新消息队列
   */
  private flushMessageQueue(): void {
    if (this.messageQueue.length === 0) return;
    
    console.log(`📤 发送队列中的 ${this.messageQueue.length} 条消息`);
    
    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift();
      if (message) {
        this.send(message);
      }
    }
  }
  
  /**
   * 断开连接
   */
  disconnect(): void {
    console.log('🔌 主动断开 WebSocket');
    
    this.shouldReconnect = false; // 禁用自动重连
    this.stopHeartbeat();
    
    // 清除重连定时器
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    
    if (this.ws) {
      this.setState(WSState.DISCONNECTING);
      this.ws.close(1000, 'Client disconnect'); // 正常关闭
      this.ws = null;
    }
    
    this.setState(WSState.DISCONNECTED);
  }
  
  /**
   * 销毁管理器
   */
  destroy(): void {
    this.disconnect();
    this.messageHandlers = [];
    this.stateChangeHandlers = [];
    this.errorHandlers = [];
    this.messageQueue = [];
  }
  
  /**
   * 设置状态
   */
  private setState(newState: WSState): void {
    if (this.state === newState) return;
    
    const oldState = this.state;
    this.state = newState;
    
    console.log(`🔄 WebSocket 状态变更: ${oldState} -> ${newState}`);
    
    // 通知所有状态监听器
    this.stateChangeHandlers.forEach(handler => {
      try {
        handler(newState);
      } catch (error) {
        console.error('❌ 状态变更处理器执行错误:', error);
      }
    });
  }
  
  /**
   * 处理错误
   */
  private handleError(error: any): void {
    this.errorHandlers.forEach(handler => {
      try {
        handler(error);
      } catch (err) {
        console.error('❌ 错误处理器执行错误:', err);
      }
    });
  }
  
  /**
   * 监听消息
   */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.push(handler);
    
    // 返回取消监听的函数
    return () => {
      const index = this.messageHandlers.indexOf(handler);
      if (index > -1) {
        this.messageHandlers.splice(index, 1);
      }
    };
  }
  
  /**
   * 监听状态变更
   */
  onStateChange(handler: StateChangeHandler): () => void {
    this.stateChangeHandlers.push(handler);
    
    return () => {
      const index = this.stateChangeHandlers.indexOf(handler);
      if (index > -1) {
        this.stateChangeHandlers.splice(index, 1);
      }
    };
  }
  
  /**
   * 监听错误
   */
  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.push(handler);
    
    return () => {
      const index = this.errorHandlers.indexOf(handler);
      if (index > -1) {
        this.errorHandlers.splice(index, 1);
      }
    };
  }
  
  /**
   * 获取当前状态
   */
  getState(): WSState {
    return this.state;
  }
  
  /**
   * 是否已连接
   */
  isConnected(): boolean {
    return this.state === WSState.CONNECTED;
  }
  
  /**
   * 获取重连信息
   */
  getReconnectInfo() {
    return {
      attempts: this.reconnectAttempts,
      maxAttempts: this.config.reconnect.maxAttempts,
      isReconnecting: this.state === WSState.RECONNECTING
    };
  }
  
  /**
   * 获取消息队列信息
   */
  getQueueInfo() {
    return {
      size: this.messageQueue.length,
      maxSize: this.config.messageQueue.maxSize
    };
  }
}

