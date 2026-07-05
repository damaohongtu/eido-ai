# Eido Chrome Extension

Chrome Manifest V3 插件版前端，复用 `../frontend-mobile` 的窄屏 React 界面，并共享 `../frontend` 的 API、类型和常量。

## 功能

- 点击扩展图标后在 Chrome 右侧 Side Panel 打开 Eido。
- 保留 Web 前端的会话、技能、附件、引用面板、会话文件、自动任务等能力。
- 读取当前网页内容，并可从已打开的标签页中选择其他页面加入分析上下文。
- 发送聊天消息时，已选择网页会自动通过 `context` 传给后端 `/api/v1/chat/chat`。

## 本地构建

```bash
cd frontend-extension
npm install
npm run build
```

然后在 Chrome 打开 `chrome://extensions`，启用开发者模式，选择“加载已解压的扩展程序”，目录选择：

```text
frontend-extension/dist
```

## 后端地址

插件默认连接：

```text
http://localhost:8000
```

如需连接其他后端：

```bash
VITE_EIDO_BACKEND_URL=https://your-domain.example.com npm run build
```

后端已默认允许 `chrome-extension://...` 的 CORS origin。若生产环境需要收紧权限，可以将 `BACKEND_CORS_ORIGIN_REGEX` 改成固定扩展 ID。

## 空白页排查

插件侧边栏如果显示空白，常见原因是未登录、后端未启动、CORS/Cookie 被拦截、或 React 运行时异常。

现在有三种调试入口：

1. 右键 Chrome 工具栏里的 Eido 扩展图标，点击“打开 Eido 插件调试控制台”。
2. 如果侧边栏能打开，进入“我的设置”，打开“插件调试控制台”。
3. 打开 `chrome://extensions`，进入本扩展详情页，在 “Inspect views / 检查视图” 里打开 Side Panel 的原生 DevTools。

调试控制台会展示 `console.warn/error`、`window.onerror` 和 `unhandledrejection`。如果看到 `Eido extension auth required`，说明插件本身已正常加载，只是需要先在新标签页完成 Eido 登录。
