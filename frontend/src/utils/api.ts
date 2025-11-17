import axios from 'axios';
import { API_BASE_URL } from '../config';

// 创建axios实例
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 从 localStorage 获取认证数据
    const authData = localStorage.getItem('auth-storage');
    if (authData) {
      try {
        const { state } = JSON.parse(authData);
        if (state.token) {
          config.headers.Authorization = `Bearer ${state.token}`;
        }
      } catch (error) {
        console.error('解析认证数据失败:', error);
      }
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      // 清除过期的认证信息
      localStorage.removeItem('auth-storage');
      // 可以在这里添加跳转到登录页的逻辑
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// API方法定义
export const authAPI = {
  // 登录
  login: (credentials: { username: string; password: string }) =>
    api.post('/api/auth/login', credentials),
  
  // 注册
  register: (userData: { account: string; email?: string; password: string }) =>
    api.post('/api/auth/register', userData),
  
  // 带邮箱验证的注册
  registerWithEmail: (userData: { 
    account: string; 
    email: string; 
    password: string; 
    verification_code: string;
  }) => api.post('/api/auth/register-with-email', userData),
  
  // 获取用户信息
  getUserInfo: () => api.get('/api/auth/user'),
  
  // 刷新token
  refreshToken: () => api.post('/api/auth/refresh'),

  // 获取应用配置（包含邮箱验证开关）
  getAppSettings: () => api.get('/api/auth/settings'),
};

export const verificationAPI = {
  // 发送验证码
  sendCode: (email: string) =>
    api.post('/api/verification/send-code', { email }),
  
  // 验证验证码
  verifyCode: (email: string, code: string) =>
    api.post('/api/verification/verify-code', { email, code }),
  
  // 获取验证状态
  getStatus: () => api.get('/api/verification/status'),
};

export default api; 