import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

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
      // Admin CRUD routes: /api/admin/* → /v1/admin/* (must be listed before catch-all)
      '/api/admin': {
        target: 'http://localhost:8081',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/admin/, '/v1/admin'),
      },
      // Viz routes: /api/* → /v1/viz/*
      '/api': {
        target: 'http://localhost:8081',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '/v1/viz'),
      },
    },
  },
})
