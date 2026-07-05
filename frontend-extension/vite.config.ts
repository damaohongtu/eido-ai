import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const extensionNodeModules = path.resolve(__dirname, 'node_modules');

export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: {
    dedupe: ['react', 'react-dom', 'react/jsx-runtime'],
    alias: {
      '@': path.resolve(__dirname, '../frontend'),
      react: path.join(extensionNodeModules, 'react'),
      'react-dom': path.join(extensionNodeModules, 'react-dom'),
      'react/jsx-runtime': path.join(extensionNodeModules, 'react/jsx-runtime.js'),
      antd: path.join(extensionNodeModules, 'antd'),
      '@ant-design/icons': path.join(extensionNodeModules, '@ant-design/icons'),
      'react-markdown': path.join(extensionNodeModules, 'react-markdown'),
      'remark-gfm': path.join(extensionNodeModules, 'remark-gfm'),
      mermaid: path.join(extensionNodeModules, 'mermaid'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: {
        side_panel: path.resolve(__dirname, 'side_panel.html'),
      },
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          'markdown-vendor': ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },
});
