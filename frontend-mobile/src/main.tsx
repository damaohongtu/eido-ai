import React from 'react';
import ReactDOM, { createRoot } from 'react-dom/client';
import { unstableSetRender } from 'antd-mobile';
import App from './App';
import './index.css';

// antd-mobile v5 的命令式 API（Dialog/Toast/Modal 等）默认走 React 18 的 ReactDOM.render，
// 在 React 19 下已失效（弹窗不渲染 → 删除确认框无法点击）。用官方 unstableSetRender 适配 19。
// 参考：https://mobile.ant.design/guide/v5-for-19
unstableSetRender((node, container) => {
  const c = container as Element & { _reactRoot?: ReturnType<typeof createRoot> };
  c._reactRoot ||= createRoot(c);
  const root = c._reactRoot;
  root.render(node);
  return async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    root.unmount();
  };
});

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Could not find root element to mount to');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
