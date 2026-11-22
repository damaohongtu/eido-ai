import { Message } from './types';

// Web 端默认走同源代理（开发环境 vite proxy, 生产环境 nginx）。
export const BACKEND_URL = import.meta.env.VITE_EIDO_BACKEND_URL || '/ai-eido';

export const INITIAL_CHAT_STATE: Message[] = [
  {
    id: 'm1',
    role: 'assistant',
    content: "你好！我是 **Eido**，你的知识助手。今天我能帮你什么？",
    timestamp: Date.now(),
  }
];
