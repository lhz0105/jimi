import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5174,
    proxy: {
      // 演示平台后端（含 SSE 代理）
      '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true },
      '/files': { target: 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
})
