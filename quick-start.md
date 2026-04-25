# Eido — 部署与启动手册

> 面向多种应用场景的 AI 智能体平台，通过 Claude Code SDK 实现自主规划与执行复杂任务。  
> 开源地址：<https://github.com/damaohongtu/eido-ai>

---

## 0. 部署形态总览

| 形态 | 适用场景 | 进程 / 容器 | 用户隔离强度 | 入口 |
|---|---|---|---|---|
| **本地开发** | 改代码、跑单测、调技能 | `python run.py` + `npm run dev` | 与开发机同进程 | `http://localhost:3000` |
| **单租户 Docker** | 私有部署、单人/小团队、内网试用 | 单镜像 `damaohongtu/eido:latest`（nginx + FastAPI + 调度） | 仅会话级隔离（同进程多用户共用 SQLite） | `http://host:80` |
| **沙箱多用户** | 多用户生产、SaaS、强隔离需求 | `eido-gateway` + 每用户一个 `eido-user` 容器 | 进程 / PID / 文件系统 / 网络命名空间均独立 | `http://host:80`（gateway 反代） |

后两种形态都使用 `docker/docker-compose.yml` 提供的 profile 切换，不存在两份配置。  
本文按部署难度从浅到深给出完整步骤。

---

## 1. 准备工作（所有形态必读）

### 1.1 LLM 凭据

Eido 通过 `claude_agent_sdk` 调用任意 Anthropic API 兼容服务。**至少配置一组**：

```bash
# MiniMax（推荐试用）
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=<your_minimax_key>

# DeepSeek
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=<your_deepseek_key>
ANTHROPIC_MODEL=deepseek-chat
ANTHROPIC_SMALL_FAST_MODEL=deepseek-chat
API_TIMEOUT_MS=600000
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
```

### 1.2 技能目录 `.claude/skills/`

技能是 `.claude/skills/<name>/SKILL.md` 形式的 Markdown 文件。容器化部署时必须把宿主机的 `.claude` 目录挂入容器（Docker `-v` 或 compose volume）；本地开发可直接放到仓库根的 `.claude/`。

### 1.3 系统依赖

- Docker ≥ 24（含 `docker compose` 子命令）
- 沙箱模式额外要求宿主机能挂载 `/var/run/docker.sock`，且 gateway 进程 uid 在 `docker` 组内（或以 root 身份运行 gateway 容器）。
- 本地开发要求 Python 3.11+ 与 Node.js 18+。

### 1.4 仓库准备

```bash
git clone https://github.com/damaohongtu/eido-ai.git
cd eido-ai
cp docker/.env.example docker/.env
$EDITOR docker/.env   # 至少填好 LLM 凭据
```

---

## 2. 本地开发模式

适用于改代码 / 调技能。**不依赖 Docker**，所有数据落在 `<repo>/.eido/`。

### 2.1 准备 Claude Code SDK

```bash
npm install -g @anthropic-ai/claude-code --registry https://registry.npmmirror.com
```

### 2.2 后端

```bash
cd backend
pip install -r requirements.txt

# 复制并填写 .env
cp .env.example .env

export ANTHROPIC_API_KEY='your-api-key'
export ANTHROPIC_BASE_URL='your-base-url'

python run.py
# → http://localhost:8000
# → API 文档: http://localhost:8000/api/v1/docs
```

健康检查：

```bash
curl -s http://localhost:8000/health
# {"status":"healthy","version":"1.0.0"}

curl -s -X POST http://localhost:8000/api/v1/chat/health
# {"status":"healthy","service":"chat"}
```

### 2.3 前端

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

前端默认通过 Vite 反代到 `http://localhost:8000`，已配置好。

### 2.4 关闭 CAS 鉴权（默认）

`backend/.env` 中保持 `AUTH_DISABLED=True`，所有请求会自动归到默认开发用户 `dev-local`。

---

## 3. 单租户 Docker 部署

把后端 + 前端 + nginx 打包进一个镜像，适合单人 / 小团队私有部署。

### 3.1 启动（compose 推荐）

```bash
# 在仓库根目录
docker compose -f docker/docker-compose.yml --profile default up -d
```

启动完成后访问 `http://<host>/ai-eido/`。

> compose 会读取 `docker/.env` 里的变量，所以请先按 §1 完成填写。

### 3.2 启动（裸 docker 命令，等价）

```bash
docker pull damaohongtu/eido:latest

docker run -d --name eido -p 80:80 \
  -e ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic \
  -e ANTHROPIC_API_KEY=<your_minimax_key> \
  -v /path/to/.claude:/workspace/.claude \
  -v ~/eido-logs/app:/var/log/eido/app \
  -v ~/eido-logs/litellm:/var/log/eido/litellm \
  -v ~/eido-logs/nginx:/var/log/eido/nginx \
  damaohongtu/eido:latest
```

### 3.3 停止 / 升级 / 查看日志

```bash
# 停止
docker compose -f docker/docker-compose.yml --profile default down

# 升级镜像
docker compose -f docker/docker-compose.yml --profile default pull
docker compose -f docker/docker-compose.yml --profile default up -d

# 应用日志
docker logs -f eido
tail -f ~/eido-logs/app/app.log
```

---

## 4. 沙箱多用户部署（推荐生产形态）

每个登录用户被路由到一个独立的 `eido-user` 容器，进程 / SQLite / workspace 物理隔离。

整体由两层组成：

```
[用户浏览器] → nginx :80 (eido-gateway 内置)
              → gateway FastAPI（CAS 鉴权 + 反代 + 调度 + sandbox 编排）
                    │
                    │ docker SDK
                    ▼
              eido-user-<safe_user_id> 容器（每用户一份）
                    │
                    └── 命名卷 eido-user-<safe>:/data
```

### 4.1 必填环境变量

在 `docker/.env` 中追加：

```bash
# 必填：32+ 字符随机串，gateway 与 user 容器之间共享密钥
EIDO_GATEWAY_SECRET=$(openssl rand -hex 32)

# 必填：随机 SESSION_SECRET_KEY（不能保留默认 dev-secret）
SESSION_SECRET_KEY=$(openssl rand -hex 32)

# 可选：用户镜像 tag、闲置回收 TTL、单容器资源限额
EIDO_USER_IMAGE=damaohongtu/eido-user:latest
EIDO_SANDBOX_IDLE_TTL=900     # 15 min
EIDO_USER_MEM=2g
EIDO_USER_CPUS=1.0
EIDO_USER_PIDS_LIMIT=500
```

> Gateway 启动时会校验这两个 secret，**长度不足或仍是默认值都会 fail-fast**。

### 4.2 准备镜像

仓库已提供两份 Dockerfile：

```bash
# 构建 Docker 镜像
docker build -f docker/app.Dockerfile -t damaohongtu/eido:latest .

# 构建 gateway 镜像
docker build -f docker/gateway.Dockerfile -t damaohongtu/eido-gateway:latest .

# 构建 user 沙箱镜像（gateway 通过 docker SDK 拉起）
docker build -f docker/user.Dockerfile -t damaohongtu/eido-user:latest .
```

如果使用上游官方镜像，跳过 build 即可。

### 4.3 启动

```bash
docker-compose -f docker/docker-compose.yml --profile sandbox up -d
```

启动后：

- `eido-gateway` 容器跑起来，监听 80 端口
- 暂时**没有任何** `eido-user-*` 容器，第一次有用户登录后才按需创建
- `eido-net` 网络与命名卷 `eido-gateway-data` 自动创建

### 4.4 验证流程

1. 浏览器访问 `http://<host>/ai-eido/`，CAS 登录或在 `AUTH_DISABLED=True` 下直接进入
2. 登录后前端会异步调用 `POST /api/v1/sandbox/warmup`，gateway 拉起当前用户容器
3. `docker ps --filter label=io.eido.role=user-sandbox` 应能看到 `eido-user-<safe_user_id>`
4. 发起一次对话，gateway 透传 SSE，停在 `[DONE]` 即成功
5. `docker volume ls | grep eido-user-` 应能看到该用户的命名卷

CLI 检查：

```bash
# 当前已注册的用户容器
curl -s http://localhost/ai-eido/api/v1/sandbox/status \
     -b "eido_session=<cookie>"   # 需带登录态

# gateway 内部 sandbox 注册表
docker exec eido-gateway sqlite3 /workspace/.eido/sandbox_registry.db \
    "SELECT user_id, container_name, status, datetime(last_active_at,'unixepoch') FROM sandbox_registry;"
```

### 4.5 用户容器生命周期

| 事件 | 行为 |
|---|---|
| 用户登录 | 前端发起 warmup，gateway 立即拉起容器并等 `/health` |
| 业务请求 | `ensure_running` 幂等，已运行则复用并刷新 `last_active_at` |
| 长 SSE 流 | 流结束时再刷一次 `last_active_at`，避免误回收 |
| 闲置 ≥ TTL | gateway 后台 GC 每 60s 扫描，stop+remove 容器，**volume 永远保留** |
| 用户重新登录 | 自动重建容器，挂回原 volume，会话/工作区无感恢复 |

### 4.6 升级与回滚

```bash
# 拉新镜像
docker compose -f docker/docker-compose.yml --profile sandbox pull

# 重启 gateway（user 容器会按需重新创建，命名卷不变）
docker compose -f docker/docker-compose.yml --profile sandbox up -d --force-recreate eido-gateway

# 临时回滚到单租户：先停 sandbox，再起 default
docker compose -f docker/docker-compose.yml --profile sandbox down
docker compose -f docker/docker-compose.yml --profile default up -d
```

### 4.7 与 CAS 叠加

```bash
docker compose -f docker/docker-compose.yml --profile sandbox --profile cas up -d
```

CAS 配置参考 §5。

---

## 5. CAS 单点登录（可选）

> 选择 sandbox profile 时强烈建议启用 CAS，否则用户不可分。

### 5.1 启动 CAS 容器

```bash
docker compose -f docker/docker-compose.yml --profile cas up -d cas
# 或者裸 docker（在仓库根目录执行）
docker rm -f cas-server 2>/dev/null
docker run -d --name cas-server -p 3331:8080 \
  -e CAS_AUTHN_ACCEPT_USERS="casuser::Mellon,test1::123456,test2::123456,admin::admin123" \
  -e CAS_TGC_SECURE=false \
  -e SERVER_SSL_ENABLED=false \
  -e SERVER_PORT=8080 \
  -e CAS_SERVICE_REGISTRY_JSON_LOCATION=file:/etc/cas/services/ \
  -e CAS_SERVICE_REGISTRY_CORE_INIT_FROM_JSON=true \
  -v "$(pwd)/docker/cas/config:/etc/cas/config" \
  -v "$(pwd)/docker/cas/services:/etc/cas/services" \
  apereo/cas:6.6.10
```

启动后确认服务已加载（数字必须 ≥ 1）：

```bash
docker logs cas-server 2>&1 | grep -i "Loaded"
# 期望：Loaded [N] service(s)，N ≥ 1
```

> `docker/cas/services/Localhost-10000001.json` 中 `serviceId` 是 `^https?://.*`，**仅适合本机测试**。生产请改成精确 URL 或严格正则。

### 5.2 后端开启 CAS

在 `docker/.env` 或后端 `.env` 中：

```bash
AUTH_DISABLED=False
CAS_SERVER_URL=http://cas-server:3331/cas/      # 必须带尾部 /
CAS_SERVICE_URL=http://<host>/api/v1/auth/callback
FRONTEND_URL=http://<host>/ai-eido/
```

> `python-cas` 用 `urljoin` 拼登录地址；如果写成 `http://host:3331/cas`（无末尾 `/`），会变成错误的 `http://host:3331/login`。`config.py` 已自动补全末尾 `/`，但建议手写正确避免歧义。

---

## 6. Nginx 与生产域名

`damaohongtu/eido:latest` 与 `damaohongtu/eido-gateway:latest` 镜像内置 nginx，对外暴露 80 端口，前缀统一为 `/ai-eido/`。

```
http://<host>/ai-eido/             # 前端
http://<host>/ai-eido/api/v1/...   # API
http://<host>/ai-eido/health       # 健康检查
```

如果需要把 Eido 摆在外层 nginx 后面：

```nginx
location /ai-eido/ {
    proxy_pass http://eido-host:80;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE 必备
    proxy_buffering off;
    proxy_cache     off;
    proxy_read_timeout 24h;
    proxy_set_header Connection '';
    chunked_transfer_encoding on;
}
```

仓库根的 [nginx.conf](nginx.conf) 已经把 SSE 透传配置写在内部 nginx，外层 nginx 按需照抄即可。

---

## 7. 数据存储位置

| 数据 | 单租户镜像 | 沙箱模式 |
|---|---|---|
| 会话与消息 | 容器内 `/workspace/.eido/chat_sessions.db` | user 容器 `/data/chat_sessions.db` （命名卷 `eido-user-<safe>`） |
| 会话工作区 | 容器内 `/workspace/.eido/workspaces/<sid>/` | user 容器 `/data/workspaces/<sid>/`（同卷） |
| 调度任务 | 容器内 `/workspace/.eido/scheduled_tasks.db` | gateway 命名卷 `eido-gateway-data:/workspace/.eido/scheduled_tasks.db` |
| sandbox 注册表 | — | gateway 命名卷 `eido-gateway-data:/workspace/.eido/sandbox_registry.db` |

> 想把这些数据落到宿主机目录，把 compose 中 `eido-gateway-data` 命名卷改为 bind-mount 即可（user 容器的命名卷由 gateway 动态创建，名称为 `eido-user-<safe_user_id>`）。

---

## 8. 故障排查

### 8.1 单租户 / 通用

| 症状 | 排查 |
|---|---|
| 502 / Bad Gateway | `docker logs eido` 看 supervisor 是否拉起 uvicorn；nginx 配置是否正确反代到 8000 |
| `/api/v1/chat/chat` 卡死 | 查 `~/eido-logs/app/app.log`，常见是 LLM 凭据错误或网络不通 |
| 上传 413 | nginx 的 `client_max_body_size` 已经在内置 nginx 调到 50m；外层 nginx 也要相应放开 |
| CAS 登录跳到 `:3331/login` | `CAS_SERVER_URL` 缺末尾 `/`；删容器加 `/` 重启 |

### 8.2 沙箱模式专属

| 症状 | 排查 |
|---|---|
| `gateway` 启动后立刻退出 | 多半是 secret 校验未过：检查 `EIDO_GATEWAY_SECRET ≥ 16 字符`、`SESSION_SECRET_KEY ≠ dev-secret-change-in-production` |
| 浏览器登录后报 502 | gateway 日志看 `ensure_running`：可能 user 镜像未本地构建 / pull、或 docker SDK 没权限。`docker exec eido-gateway curl -fsS http://eido-user-<safe>:8000/health` 直接验证 |
| `/api/v1/sandbox/warmup` 返回 401 | 入口 user_id 解析失败，确认 CAS 已登录 / `AUTH_DISABLED=True` 与是否带上 `eido_session` cookie |
| user 容器健康检查超时 | 大概率 LLM 凭据 / 网络问题；`docker logs eido-user-<safe>` 看 startup |
| user 之间数据“串了” | 走 `gateway` 反代时永远只能拿到本人 user_id；如果直接 hit user 容器要保证它只在 `eido-net` 内、且未发布到宿主机端口 |
| GC 不回收 | 检查 `EIDO_SANDBOX_IDLE_TTL`，长 SSE 期间会被刷新；可用 `curl -X POST .../api/v1/sandbox/status` 查 `last_active_at` |

### 8.3 gateway ⇄ user 之间快速验证

```bash
# 手动让 gateway 拉起一个用户容器（替换 <cookie>）
curl -s -X POST http://<host>/ai-eido/api/v1/sandbox/warmup -b "eido_session=<cookie>"

# 列出该用户容器
docker ps --filter label=io.eido.role=user-sandbox

# 在 gateway 容器内 ping user 容器
docker exec eido-gateway curl -fsS \
    -H "X-Eido-User-Id: <user_id>" \
    -H "X-Eido-Gateway-Secret: $EIDO_GATEWAY_SECRET" \
    http://eido-user-<safe>:8000/health
```

---

## 9. 新增技能（任意形态通用）

```bash
mkdir .claude/skills/my-skill
cat > .claude/skills/my-skill/SKILL.md << 'EOF'
---
name: 我的技能
description: 技能的简短描述，显示在选择菜单中
allowed_tools:
  - Read
  - Bash
---

# 技能执行指引

在此用自然语言描述技能的执行逻辑、输入输出格式等。
EOF
```

- 单租户镜像：重启容器即可加载（`docker restart eido`）
- 沙箱模式：`.claude/skills` 在所有 user 容器中是只读 bind-mount，gateway 不需要重启；user 容器在下次冷启动时自动看到新技能

`allowed_tools` 完整列表参见 [Claude Code SDK 文档](https://docs.anthropic.com/claude-code)。

---

## 10. 项目结构

```
eido-ai/
├── frontend/                React 19 + TypeScript 前端
├── backend/                 Python FastAPI 后端
│   ├── app/
│   │   ├── api/v1/          路由：auth · chat · sessions · workspace · skills · tasks · sandbox
│   │   ├── core/            config / auth / database
│   │   ├── services/        skill / chat_session_store / session_workspace / scheduler
│   │   └── gateway/         sandbox_manager · proxy · router_user
│   └── run.py
├── .claude/skills/          技能目录（SKILL.md）
├── docker/
│   ├── docker-compose.yml   default & sandbox & cas 三种 profile
│   ├── gateway.Dockerfile   gateway 镜像（含 nginx + 前端）
│   ├── user.Dockerfile      user 沙箱镜像（uvicorn-only）
│   └── cas/                 CAS 配置 + service registry
├── nginx.conf               生产 nginx 配置（SSE 透传）
└── docs/
    ├── architecture.md      架构文档（含 §7 沙箱章节）
    └── api.md               API 文档
```

更深层的设计与时序图见 [docs/architecture.md](docs/architecture.md)，REST/SSE 接口契约见 [docs/api.md](docs/api.md)。
