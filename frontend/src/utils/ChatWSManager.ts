export type ChatWSCallbacks = {
  onOpen?: () => void;
  onAuthSuccess?: () => void;
  onMessage?: (event: MessageEvent) => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
};

// 连接状态
type ConnectionState = 'idle' | 'connecting' | 'open' | 'closing' | 'closed';

export class ChatWSManager {
  private static instance: ChatWSManager | null = null;

  private ws: WebSocket | null = null;
  private url: string | null = null;
  private sessionId: string | null = null;
  private state: ConnectionState = 'idle';

  private callbacks: ChatWSCallbacks = {};
  private heartbeatTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempts: number = 0;
  private explicitlyClosed: boolean = false;

  // 队列：在未鉴权或未OPEN期间积压消息
  private sendQueue: string[] = [];
  private authorized: boolean = false;
  private awaitingAuthResolve: ((v: boolean) => void) | null = null;

  // 记录当前已连接的上下文，用于判断是否需要重连
  private connectedUrl: string | null = null;
  private connectedSessionId: string | null = null;

  // 单例获取
  public static getInstance(): ChatWSManager {
    if (!ChatWSManager.instance) {
      ChatWSManager.instance = new ChatWSManager();
    }
    return ChatWSManager.instance;
  }

  public getSocket(): WebSocket | null {
    return this.ws;
  }

  public getState(): ConnectionState {
    return this.state;
  }

  public setCallbacks(callbacks: ChatWSCallbacks) {
    this.callbacks = callbacks;
  }

  public updateSessionContext(options: { url: string; sessionId: string }) {
    const nextUrl = options.url;
    const nextSessionId = options.sessionId;

    const urlChanged = this.url !== nextUrl;
    const sessionChanged = this.sessionId !== nextSessionId;

    this.url = nextUrl;
    this.sessionId = nextSessionId;

    // 如已连接且上下文变化，则主动断开以便后续重连到新会话
    if (this.ws && this.state === 'open' && (urlChanged || sessionChanged)) {
      this.close();
    }
  }

  public async connect(): Promise<void> {
    console.log('[WSManager] 📞 connect() 被调用');
    console.log('[WSManager] 📝 URL:', this.url);
    console.log('[WSManager] 📝 Session ID:', this.sessionId);
    
    if (!this.url || !this.sessionId) {
      console.error('[WSManager] ❌ URL 或 Session ID 为空，无法连接');
      return;
    }

    // 如果已经连接到相同URL/会话且状态正常，则复用；否则断开并重连
    if (this.ws && this.state === 'open' && this.ws.readyState === WebSocket.OPEN) {
      const sameTarget = this.connectedUrl === this.url && this.connectedSessionId === this.sessionId;
      console.log('[WSManager] 🔄 已有连接，相同目标:', sameTarget);
      if (sameTarget) {
        console.log('[WSManager] ✅ 复用现有连接');
        return;
      }
      // 连接目标已变化，关闭后继续建立新的连接
      console.log('[WSManager] 🔄 目标已变化，关闭旧连接');
      this.close();
    }

    // 避免并发connect
    if (this.state === 'connecting') {
      console.log('[WSManager] ⏳ 正在连接中，跳过重复调用');
      return;
    }

    this.explicitlyClosed = false;
    this.authorized = false;
    this.state = 'connecting';
    console.log('[WSManager] 🚀 开始建立 WebSocket 连接...');

    try {
      const currentUrl = this.url!;
      const currentSession = this.sessionId!;
      console.log('[WSManager] 🌐 创建 WebSocket 实例:', currentUrl);
      const ws = new WebSocket(currentUrl);
      this.ws = ws;

      // 预先记录将要连接的目标，用于后续复用判断
      this.connectedUrl = currentUrl;
      this.connectedSessionId = currentSession;

      ws.onopen = () => {
        console.log('[WSManager] ✅ WebSocket.onopen 触发');
        console.log('[WSManager] ✅ 连接已建立！');
        this.state = 'open';
        this.reconnectAttempts = 0;
        this.startHeartbeat();
        console.log('[WSManager] 🔔 调用 callbacks.onOpen');
        this.callbacks.onOpen && this.callbacks.onOpen();
        console.log('[WSManager] 🔐 发送授权信息');
        this.sendAuthorization();
      };

      ws.onmessage = (event) => {
        // 拦截鉴权成功/心跳
        try {
          const data = JSON.parse(event.data);
          console.log('[WSManager] 📩 收到消息:', data.type);
          
          if (data && data.type === 'auth_success') {
            const becameAuthorized = !this.authorized;
            this.authorized = true;
            console.log('[WSManager] ✅ 授权成功！');
            if (becameAuthorized) {
              // flush 队列
              this.flushQueue();
              this.callbacks.onAuthSuccess && this.callbacks.onAuthSuccess();
            }
            if (this.awaitingAuthResolve) {
              this.awaitingAuthResolve(true);
              this.awaitingAuthResolve = null;
            }
            return;
          }
          if (data && (data.type === 'pong')) {
            // 心跳响应（不打印，避免刷屏）
            return;
          }
          // 某些后端不返回专门的 auth_success，而是直接下发历史或内容
          if (data && (data.type === 'history' || data.type === 'message' || data.type === 'reference' || data.type === 'audio' || data.type === 'done')) {
            if (!this.authorized) {
              this.authorized = true;
              console.log('[WSManager] ✅ 隐式授权成功（收到业务消息）');
              this.flushQueue();
              this.callbacks.onAuthSuccess && this.callbacks.onAuthSuccess();
              if (this.awaitingAuthResolve) {
                this.awaitingAuthResolve(true);
                this.awaitingAuthResolve = null;
              }
            }
            // 透传这些业务消息给上层
          }
        } catch (err) {
          // 非JSON或非控制消息，直接透传
          console.log('[WSManager] 📩 收到非 JSON 消息或解析失败');
        }
        this.callbacks.onMessage && this.callbacks.onMessage(event);
      };

      ws.onclose = (event) => {
        console.log('[WSManager] 🔌 WebSocket.onclose 触发');
        console.log('[WSManager] 🔌 关闭代码:', event.code);
        console.log('[WSManager] 🔌 关闭原因:', event.reason);
        console.log('[WSManager] 🔌 是否正常关闭:', event.wasClean);
        this.state = 'closed';
        this.stopHeartbeat();
        this.callbacks.onClose && this.callbacks.onClose(event);
        if (!this.explicitlyClosed) {
          console.log('[WSManager] 🔄 计划重连...');
          this.scheduleReconnect();
        } else {
          console.log('[WSManager] ⏹️ 主动关闭，不重连');
        }
      };

      ws.onerror = (event) => {
        console.error('[WSManager] ❌ WebSocket.onerror 触发:', event);
        console.error('[WSManager] ❌ 错误类型:', event.type);
        console.error('[WSManager] ❌ 当前状态:', this.state);
        this.callbacks.onError && this.callbacks.onError(event);
      };
      
      console.log('[WSManager] 🎯 WebSocket 实例已创建，等待连接...');
    } catch (err) {
      console.error('[WSManager] ❌ 创建 WebSocket 失败:', err);
      this.state = 'closed';
      this.scheduleReconnect();
    }
  }

  public close() {
    this.explicitlyClosed = true;
    this.stopHeartbeat();
    if (this.ws) {
      this.state = 'closing';
      try { this.ws.close(); } catch {}
      this.ws = null;
    }
    this.state = 'closed';
    this.clearReconnectTimer();
    this.sendQueue = [];
    this.authorized = false;
  }

  public async ensureAuthorized(timeoutMs: number = 8000): Promise<boolean> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN && this.authorized) return true;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      await this.connect();
    }
    if (this.authorized) return true;
    return new Promise<boolean>((resolve) => {
      let settled = false;
      const timer = window.setTimeout(() => {
        if (!settled) {
          settled = true;
          this.awaitingAuthResolve = null;
          resolve(false);
        }
      }, timeoutMs);
      this.awaitingAuthResolve = (v: boolean) => {
        if (!settled) {
          settled = true;
          window.clearTimeout(timer);
          resolve(v);
        }
      };
    });
  }

  public send(data: any) {
    const payload = typeof data === 'string' ? data : JSON.stringify(data);
    if (this.ws && this.ws.readyState === WebSocket.OPEN && this.authorized) {
      try { this.ws.send(payload); } catch { this.enqueue(payload); }
      return;
    }
    // 未OPEN或未鉴权：入队
    this.enqueue(payload);
    // 触发连接（若需要）
    this.connect();
  }

  private enqueue(payload: string) {
    // 限制队列长度，避免内存膨胀
    const MAX_QUEUE = 100;
    if (this.sendQueue.length >= MAX_QUEUE) {
      this.sendQueue.shift();
    }
    this.sendQueue.push(payload);
  }

  private flushQueue() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.authorized) return;
    while (this.sendQueue.length > 0) {
      const item = this.sendQueue.shift();
      if (item === undefined) break;
      try { this.ws.send(item); } catch { break; }
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      try {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
        }
      } catch {}
    }, 25000);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect() {
    if (this.explicitlyClosed) {
      console.log('[WSManager] ⏹️ 已显式关闭，不重连');
      return;
    }
    if (!this.url || !this.sessionId) {
      console.log('[WSManager] ⚠️ URL 或 Session ID 为空，无法重连');
      return;
    }
    if (this.reconnectTimer) {
      console.log('[WSManager] ⏳ 重连定时器已存在');
      return;
    }

    const base = 1000;
    const max = 15000;
    const attempt = Math.min(this.reconnectAttempts + 1, 10);
    const jitter = Math.random() * 300;
    const delay = Math.min(base * Math.pow(2, attempt - 1), max) + jitter;
    this.reconnectAttempts = attempt;

    console.log(`[WSManager] 🔄 计划在 ${Math.round(delay)}ms 后重连（第 ${attempt} 次尝试）`);

    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      console.log('[WSManager] 🔄 执行重连...');
      this.connect();
    }, delay);
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private sendAuthorization() {
    console.log('[WSManager] 🔐 开始发送授权信息...');
    const tokenRaw = localStorage.getItem('auth-storage');
    if (!tokenRaw) {
      console.error('[WSManager] ❌ 未找到 auth-storage');
      return;
    }
    try {
      const authData = JSON.parse(tokenRaw);
      const token = authData?.state?.token;
      if (!token) {
        console.error('[WSManager] ❌ Token 为空');
        return;
      }
      console.log('[WSManager] ✅ Token 已找到，发送授权消息');
      this.ws?.send(JSON.stringify({ type: 'authorization', token: `Bearer ${token}` }));
      console.log('[WSManager] ✅ 授权消息已发送');
    } catch (err) {
      console.error('[WSManager] ❌ 发送授权失败:', err);
    }
  }
}

const chatWSManager = ChatWSManager.getInstance();
export default chatWSManager; 