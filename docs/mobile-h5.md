# PC 与移动端 H5

PC 与 H5 是两套独立入口和界面，统一访问 `/ai-eido/`，统一调用 `/ai-eido/api/v1/*`。不增加 `/mobile` 或 `/h5` 页面前缀，也不使用浏览器脚本跳转来识别设备。

## 代码结构

| 目录 | 用途 |
| --- | --- |
| `frontend/App.tsx`、`frontend/components/` | 原有 PC 界面 |
| `frontend/mobile/` | 移动端入口、底部导航、会话与项目抽屉、聊天、各业务页面 |
| `frontend/hooks/useAppController.ts` | 两端共用的鉴权、会话、项目和消息状态 |
| `frontend/hooks/useChatController.ts` | 两端共用的流式执行、停止、排队、Steer、多技能调用和上传逻辑 |
| `frontend/services/`、`frontend/types.ts`、`frontend/utils/` | 共用 API、类型与文件工具 |

H5 支持登录与退出、历史会话、项目及资料、模型与执行模式选择、聊天附件、技能提及与流水线、排队消息管理、执行记录、参考来源、生成文件预览与下载、技能创建/导入/编辑/删除和文本文件管理、MCP 服务新增/编辑/启停/删除及统一配置、自动任务。自动任务复用 PC 的表单与调度工具，支持新建、编辑、启停、删除、立即执行、Cron 和固定间隔。技能权限仍以服务端返回的 `is_owner` 等字段为准，服务端继续执行权限校验。

移动端使用与 PC 一致的灰白配色。左侧导航抽屉从屏幕左边滑入，顶部固定新建会话，底部固定用户信息，中间导航、项目和历史会话区域独立滚动；表单和资料使用原生 dialog 底部弹层，适配安全区和可视窗口高度。输入框的 Enter 保留换行，点击发送按钮发送，也支持 Ctrl/Cmd + Enter。Mermaid 在需要展示流程图时才加载。

## 本地开发和构建

在 `frontend/` 中执行：

```bash
npm ci
npm run dev          # PC: http://localhost:3000/ai-eido/
npm run dev:mobile   # H5: http://localhost:3001/ai-eido/
```

两个开发服务器都将 `/ai-eido/api` 代理到本机 `8000` 后端。本地分别通过端口查看两套界面，生产环境才由 Nginx 在同一端口分流。

```bash
npm run typecheck
npm run build        # 同时输出 dist/ 和 dist-mobile/
# 也可以单独执行 npm run build:pc 或 npm run build:mobile
```

| 构建 | 页面 base | 资源 URL | 镜像中的目录 |
| --- | --- | --- | --- |
| PC | `/ai-eido/` | `/ai-eido/assets/*` | `/var/www/ai-eido/` |
| H5 | `/ai-eido/` | `/ai-eido/mobile-assets/*` | `/var/www/h5/ai-eido/` |

## Nginx 和部署

`docker/nginx.conf` 与仓库根目录的 `nginx.conf` 都包含 `map $http_user_agent $eido_frontend_root`。将配置放在 Nginx 的 **http 上下文**中加载（常规安装的 `conf.d/*.conf` 即可），不能将整个配置粘贴到已有 `server {}` 内。

- iPhone、Android、iPad、带 Mobile 标记的浏览器和 HarmonyOS 等移动 UA 使用 H5；其他请求默认使用 PC。
- UA 识别负责选择页面目录。`/ai-eido/assets/` 固定读取 PC 资源，`/ai-eido/mobile-assets/` 固定读取 H5 资源，即使资源请求的 UA 变化也不会串包。
- HTML 返回 `Vary: User-Agent` 与 `Cache-Control: no-cache`；带 hash 的资源可长期缓存。前置 CDN/反向代理需保留这些响应头，不应跨设备共用 HTML 缓存。
- `/ai-eido` 自动规范到 `/ai-eido/` 并保留查询参数。两端使用相同 SPA 回退路径，登录回调沿用原地址。
- API、健康检查、受信网关头过滤和 SSE 配置独立于设备分流。

Docker 的 app 与 gateway 镜像已经同时复制两套产物，Kubernetes 使用这些镜像时无需增加移动端 Service 或 Ingress。

```bash
# 仓库根目录：构建两端后构建镜像
(cd frontend && npm ci && npm run build)
docker buildx bake -f docker/docker-bake.hcl --load base app
# sandbox 部署使用对应的 gateway/user 镜像构建流程
```

独立 Nginx 部署时，分别将 `frontend/dist/` 的内容放到 `/var/www/ai-eido/`，将 `frontend/dist-mobile/` 的内容放到 `/var/www/h5/ai-eido/`，然后加载根目录的 `nginx.conf`。两个目录都需要同步发布。

```bash
nginx -t
# 确认配置和文件部署后，按环境现有流程 reload Nginx。
curl -I -A 'Mozilla/5.0 (iPhone) Mobile' http://localhost/ai-eido/
curl -I -A 'Mozilla/5.0 (Macintosh)' http://localhost/ai-eido/
```

UA 采用服务端规则识别；移动浏览器选择「桌面网站」后可能获得 PC 页面。需要改变平板策略时，在 `map` 中调整规则。

## 回归验证

```bash
# 真实 Nginx：两份配置的设备分流、深链接、资源隔离、API 和 SSE。
python3 tests/frontend-delivery.py

# 浏览器：先安装 Chromium，然后对构建产物运行。
cd frontend
npx playwright install chromium
npm run build
npm run test:e2e
# 使用本机已有 Chrome 时：PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

浏览器用例使用隔离的模拟 API，覆盖 PC 聊天回归，以及 H5 的 320/390/768px 布局、页面导航、流式聊天和历史恢复、项目上下文、技能文件只读权限与 OAuth 链接。它们不会调用线上模型、发送业务消息或修改真实用户数据。真实账号登录、模型服务与真机键盘行为仍需在目标环境验收。
