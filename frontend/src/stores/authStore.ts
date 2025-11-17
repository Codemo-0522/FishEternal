import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import axios from 'axios'

interface User {
  // _id: string  // MongoDB ObjectId 的字符串形式
  id: string  // 兼容字段，某些接口返回id而不是_id
  account: string
  email: string
  avatar_url?: string
  full_name?: string
  gender?: string
  birth_date?: string  // 出生日期，格式：YYYY-MM-DD
  age?: number  // 计算属性，由后端根据birth_date动态计算
  signature?: string
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  login: (identifier: string, password: string) => Promise<void>  // 更改参数名为identifier
  register: (account: string, email: string, password: string) => Promise<void>
  logout: () => void
  initializeAuth: () => Promise<void>
  updateUser: (user: User) => void  // 新增：更新用户信息的方法
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      initializeAuth: async () => {
        try {
          const state = get();
          if (!state.token) {
            return;
          }

          // 设置请求头
          axios.defaults.headers.common['Authorization'] = `Bearer ${state.token}`;
          
          // 验证 token
          const response = await axios.get('/api/auth/me');
          
          if (response.status === 200 && response.data) {
            set({ 
              user: response.data,
              isAuthenticated: true 
            });
          } else {
            throw new Error('Token validation failed');
          }
        } catch (error) {
          console.error('Auth initialization failed:', error);
          set({ user: null, token: null, isAuthenticated: false });
          delete axios.defaults.headers.common['Authorization'];
        }
      },

      login: async (identifier: string, password: string) => {
        try {
          const formData = new FormData();
          formData.append('username', identifier);  // OAuth2标准仍使用username字段
          formData.append('password', password);
          formData.append('grant_type', 'password');
          
          const response = await axios.post('/api/auth/token', formData);  // 使用/api/auth/token端点
          const { access_token } = response.data;
          
          // 设置请求头
          axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
          
          // 获取用户信息
          const userResponse = await axios.get('/api/auth/me');
          
          // 更新状态
          set({ 
            user: userResponse.data, 
            token: access_token, 
            isAuthenticated: true 
          });
        } catch (error) {
          console.error('Login failed:', error);
          throw error;
        }
      },

      register: async (account: string, email: string, password: string) => {
        try {
          await axios.post('/api/auth/register', {
            account,
            email,
            password,
          });
        } catch (error) {
          console.error('Registration failed:', error);
          throw error;
        }
      },

      logout: () => {
        set({ user: null, token: null, isAuthenticated: false });
        delete axios.defaults.headers.common['Authorization'];
      },

      updateUser: (user: User) => {
        set({ user });
      },
    }),
    {
      name: 'auth-storage',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated
      })
    }
  )
); 