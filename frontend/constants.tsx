import { Message } from './types';

// Web 端默认走同源代理（开发环境 vite proxy, 生产环境 nginx）。
// Chrome 插件运行在 chrome-extension:// 源下，需通过 VITE_EIDO_BACKEND_URL 指向真实后端。
const isChromeExtension =
  typeof window !== 'undefined' &&
  window.location.protocol === 'chrome-extension:';

export const BACKEND_URL =
  import.meta.env.VITE_EIDO_BACKEND_URL ||
  (isChromeExtension ? 'http://localhost:8000' : '/ai-eido');

export const INITIAL_CHAT_STATE: Message[] = [
  {
    id: 'm1',
    role: 'assistant',
    content: "你好！我是 **Eido**，你的知识助手。今天我能帮你什么？",
    timestamp: Date.now(),
  }
];
