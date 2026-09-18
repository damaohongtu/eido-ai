# Eido Chrome Extension

Chrome Manifest V3 插件版前端，复用 `../frontend-mobile` 的窄屏 React 界面，并共享 `../frontend` 的 API、类型和常量。

## 功能

- 点击扩展图标后在 Chrome 右侧 Side Panel 打开 Eido。
- 保留 Web 前端的会话、技能、附件、引用面板、会话文件、自动任务等能力。
- 读取当前网页内容，并可从已打开的标签页中选择其他页面加入分析上下文。
- 通过后端 Claude Code 分析选中的网页，支持模型选择和原生会话续接。

## 本地构建

```bash
cd frontend-extension
npm install
npm run build
npm test
```

然后在 Chrome 打开 `chrome://extensions`，启用开发者模式，选择“加载已解压的扩展程序”，目录选择：

```text
frontend-extension/dist
```

## 私有自动更新构建

正式 CRX 必须始终使用同一把私钥打包，否则扩展 ID 会变化且 Chrome 会拒绝更新。私钥不要放进仓库。

```bash
cd frontend-extension
EIDO_EXTENSION_UPDATE_URL=https://updates.eido.example.com/v1/chrome/stable \
EIDO_EXTENSION_PRIVATE_KEY=/secure/path/eido-extension.pem \
npm run pack:release
```

生成文件：

```text
frontend-extension/release/eido-extension-<version>.crx
```

`pack:release` 会先构建扩展，在构建产物的 `manifest.json` 中写入 `update_url`，然后调用 Chrome 生成 CRX。日常 `npm run build` 不写入更新地址，仍可用于加载已解压的开发版本。

私钥需为未加密的 RSA PEM。脚本可直接使用 PKCS#8，也会把常见的 PKCS#1 临时转换为 Chrome 要求的 PKCS#8；转换文件在打包结束后删除，不会覆盖原私钥。打包成功后命令会输出由该私钥派生的 32 位 Extension ID，把它配置到独立更新服务和 Chrome 企业策略。

把 CRX 复制到独立更新服务器后，配置并重新创建 [`../extension-update-server`](../extension-update-server/README.md) 容器。Windows/macOS 首次安装非商店 CRX 仍需 Chrome 企业策略；策略中配置的扩展 ID 必须与该私钥生成的 ID 一致。

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
