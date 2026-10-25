import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/v1': 'http://127.0.0.1:4000' } },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: { output: { manualChunks: { echarts: ['echarts'] } } },
  },
})
