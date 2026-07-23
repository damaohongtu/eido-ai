# Eido 部署指南

## 构建镜像

```bash
# 1. 构建前端
cd frontend && npm run build && cd ..

# 2. 构建 Docker 镜像
docker build -f docker/app.Dockerfile -t damaohongtu/eido:latest .

# 构建amd和arm版
docker buildx build -f docker/app.Dockerfile --platform linux/amd64,linux/arm64 -t damaohongtu/eido:latest .

```

---

## 导出镜像（离线部署）

```bash
# 导出为压缩包（约 1-2 GB）
docker save damaohongtu/eido:latest | gzip > eido-latest.tar.gz
```

传输到目标机器：

```bash
scp eido-latest.tar.gz user@host:/home/user/
```

在目标机器上加载：

```bash
docker load < eido-latest.tar.gz
```

---

## 启动容器

### 数据卷（必须先确认）

当前 Compose 的单容器 profile 使用命名卷 `eido-data:/data`，并设置
`EIDO_DATA_ROOT=/data`。以下数据会随容器重建保留：

- `chat_sessions.db`（Project、Session、Message、Project File 元数据）；
- `scheduled_tasks.db`；
- `projects/<project_id>/files/`；
- `workspaces/<session_id>/`。

Project 资料默认配额为单 Project 100 个/512 MiB、单用户 500 个/2 GiB。可在 Compose
环境中设置 `EIDO_PROJECT_MAX_FILES`、`EIDO_PROJECT_MAX_BYTES`、
`EIDO_USER_PROJECT_MAX_FILES`、`EIDO_USER_PROJECT_MAX_BYTES`；sandbox 模式会由 gateway
传入新创建的 user 容器，已有 user 容器需按升级流程重建后生效。

直接使用 `docker run` 时也必须增加：

```bash
-e EIDO_DATA_ROOT=/data \
-v eido-data:/data
```

否则数据只存在于容器可写层，删除容器后无法恢复。

#### 从旧单容器版本升级

旧版本默认把数据写在容器内 `/workspace/.eido`。**不要先删除旧容器**。先停止写入并复制
数据，再启动使用 `/data` 的新版本：

```bash
# 1. 停止旧容器，确保 SQLite WAL 不再变化
docker stop eido

# 2. 从仍然存在的旧容器复制完整 .eido（包括可能存在的 -wal/-shm）
mkdir -p ./eido-data-backup
docker cp eido:/workspace/.eido/. ./eido-data-backup/

# 3. 初始化新版命名卷并导入旧数据
docker volume create eido-data
docker run --rm \
  -v eido-data:/data \
  -v "$PWD/eido-data-backup:/backup:ro" \
  alpine:3.20 sh -c 'cp -a /backup/. /data/'

# 4. 再按新版 Compose 或 docker run 配置启动
```

升级后先确认 `/data/chat_sessions.db` 存在、历史会话可读取，再删除旧容器和本地备份。
若旧部署本来就 bind-mount 了 `.eido`，应从对应宿主目录导入，不要从空容器层覆盖它。

### MiniMax

```bash
docker run -d -p 80:80 \
  -e ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic \
  -e ANTHROPIC_API_KEY=<your_minimax_key> \
  -e EIDO_DATA_ROOT=/data \
  -v /path/to/.claude:/workspace/.claude \
  -v eido-data:/data \
  -v ~/eido-logs/app:/var/log/eido/app \
  -v ~/eido-logs/litellm:/var/log/eido/litellm \
  -v ~/eido-logs/nginx:/var/log/eido/nginx \
  damaohongtu/eido:latest
```

### DeepSeek

```bash
docker run -d -p 80:80 \
  -e ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
  -e ANTHROPIC_AUTH_TOKEN=<your_deepseek_key> \
  -e ANTHROPIC_MODEL=deepseek-chat \
  -e ANTHROPIC_SMALL_FAST_MODEL=deepseek-chat \
  -e API_TIMEOUT_MS=600000 \
  -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  -e EIDO_DATA_ROOT=/data \
  -v /path/to/.claude:/workspace/.claude \
  -v eido-data:/data \
  -v ~/eido-logs/app:/var/log/eido/app \
  -v ~/eido-logs/litellm:/var/log/eido/litellm \
  -v ~/eido-logs/nginx:/var/log/eido/nginx \
  damaohongtu/eido:latest
```

> `-v /path/to/.claude` 替换为宿主机上 `.claude` 目录的实际路径，例如 `/home/user/.claude`
> 日志目录映射到宿主机 `~/eido-logs/` 下，按 app / litellm / nginx 分开存放，按日滚动保留 7 天

---

## 访问

浏览器打开：`http://<host>/ai-eido`

---

## 常用命令

```bash
# 查看运行日志
docker logs -f <container_id>

# 进入容器排查
docker exec -it <container_id> bash

# 停止容器
docker stop <container_id>

# 推送到镜像仓库
docker push damaohongtu/eido:latest
```

---

## Project 版本发布检查

Project 版本会在 user/local runtime 启动时升级 `chat_sessions.db`。发布前必须备份数据；发布后
至少检查：

1. `/health` 进程存活；
2. 创建、读取、修改和删除一个临时 Project；
3. 把临时 Session 绑定到 Project，再删除 Project，确认 Session 与 Workspace 保留并变为未归类；
4. 重建容器后再次读取 Project 和历史会话；
5. 若删除响应出现 `cleanup_pending: true`，确认 `storage_cleanup_jobs` 在启动或周期清理后归零；
6. 执行 `PRAGMA foreign_key_check` 无结果。

当前 `/health` 不代表数据库迁移成功，因此第 2 步 Project API smoke 是必要的 readiness 替代。

Sandbox 模式需要同时发布支持 Project 的 gateway image 和 user image。已经运行的
`eido-user-*` 旧容器不会自动更新；应 stop/remove 旧 user 容器但保留 `eido-user-*` volumes，
再由 gateway 懒启动新版容器。不要删除用户 volume。

数据库升级是 additive：新增表和 nullable 列，不移动 Session Workspace。应用回滚时保留升级后的
数据库和 `/data/projects`，不要尝试反向删除表或列。完整方案见
[`../docs/project-design.md`](../docs/project-design.md)。
