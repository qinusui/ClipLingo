import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 60000,
      },
      '/download': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 300000,
      },
      '/output': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 30000,
      },
      '/docs': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 30000,
      },
      '/api/themes': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        timeout: 30000,
      },
    },
  },
})
