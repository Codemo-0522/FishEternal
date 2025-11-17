import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [
    react(), 
    basicSsl(),
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://192.168.178.103:8000',  // 后端地址
        changeOrigin: true,
        secure: false,  // 允许代理到 HTTP
        ws: true  // 启用 WebSocket 代理
      },
      '/audio': {
        target: 'http://192.168.178.103:8000',  // 后端地址
        changeOrigin: true,
        secure: false  // 允许代理到 HTTP
      }
    }
  },
  css: {
    modules: {
      localsConvention: 'camelCase',
      generateScopedName: '[name]__[local]__[hash:base64:5]'
    }
  },
  // 仅在生产环境移除所有 console 和 debugger 调用
  esbuild: mode === 'production' ? { drop: ['console', 'debugger'] } : undefined
})) 