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

### MiniMax

```bash
docker run -d -p 80:80 \
  -e ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic \
  -e ANTHROPIC_API_KEY=<your_minimax_key> \
  -v /path/to/.claude:/workspace/.claude \
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
  -v /path/to/.claude:/workspace/.claude \
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
