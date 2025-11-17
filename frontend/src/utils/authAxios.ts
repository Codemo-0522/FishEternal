import axios from 'axios';

// 创建专门用于认证的axios实例
// 设置较长的超时时间以支持 ASR（语音识别）等耗时操作
const authAxios = axios.create({
  timeout: 60000, // 60秒超时，足够处理 ASR 请求
});

// 添加请求拦截器
authAxios.interceptors.request.use(
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

export default authAxios; 