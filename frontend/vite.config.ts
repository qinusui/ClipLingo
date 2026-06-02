import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig(() => {
  const backendPort = process.env.BACKEND_PORT || '8000'
  return {
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
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
          timeout: 600000,
        },
        '/download': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
          timeout: 300000,
        },
        '/output': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
          timeout: 30000,
        },
        '/docs': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
          timeout: 30000,
        },
        '/api/themes': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
          timeout: 30000,
        },
      },
    },
  }
})
