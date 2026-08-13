import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  base: '/travel/', // 子路径部署（nginx 反代）
  plugins: [react()],
  server: {
    proxy: {
      '/travel/api': {
        target: 'http://localhost:8000',
        rewrite: (p) => p.replace(/^\/travel/, ''),
      },
      '/t/': {
        target: 'http://localhost:8000',
        rewrite: (p) => p.replace(/^\/t\//, '/api/trips/t/'),
      },
    },
  },
})
