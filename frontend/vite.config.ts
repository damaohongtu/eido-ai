import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  // 所有环境统一使用 /ai-eido 基础路径
  base: '/ai-eido/',
  server: {
    port: 3000,
    host: '0.0.0.0',
    // 配置代理，将 API 请求转发到后端
    proxy: {
      '/ai-eido/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ai-eido\/api/, '/api'),
        cookieDomainRewrite: { '*': '' },
      },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'markdown-vendor': ['react-markdown', 'remark-gfm'],
        }
      }
    }
  }
});
