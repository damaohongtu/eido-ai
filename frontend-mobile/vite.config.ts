import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 移动端 H5 独立工程；后端 API 完全复用 PC 端同源代理路径 /ai-eido/api。
export default defineConfig({
  base: '/ai-eido/m/',
  server: {
    port: 3001,
    host: '0.0.0.0',
    // 复用 PC 端 ../frontend 下的 api.ts / types.ts / constants.tsx，需放开上级目录读取
    fs: {
      allow: [path.resolve(__dirname), path.resolve(__dirname, '..', 'frontend')],
    },
    proxy: {
      '/ai-eido/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/ai-eido\/api/, '/api'),
        cookieDomainRewrite: { '*': '' },
      },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      // 复用 PC 端逻辑层（service / types / constants），保持单一数据源、零漂移
      '@shared': path.resolve(__dirname, '..', 'frontend'),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'markdown-vendor': ['react-markdown', 'remark-gfm'],
          'antd-mobile-vendor': ['antd-mobile'],
        },
      },
    },
  },
});
