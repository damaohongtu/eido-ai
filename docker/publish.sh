#!/bin/bash
# =============================================================================
# 构建并推送镜像
# =============================================================================

# 构建前端
cd /Users/mao/workspace/Eido/frontend && npm run build

# 构建镜像
cd /Users/mao/workspace/Eido
docker build -f docker/app.Dockerfile -t damaohongtu/eido:latest .

docker images damaohongtu/eido

# 推送镜像
docker push damaohongtu/eido:latest


# =============================================================================
# 启动容器（按需选择一种方式，取消注释后执行）
# =============================================================================

# --- MiniMax ---
docker run -d -p 80:80 \
  -e ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic \
  -e ANTHROPIC_API_KEY=your_minimax_api_key \
  -v ~/.claude:/workspace/.claude \
  -v ~/eido-logs/app:/var/log/eido/app \
  -v ~/eido-logs/litellm:/var/log/eido/litellm \
  -v ~/eido-logs/nginx:/var/log/eido/nginx \
  damaohongtu/eido:latest

# --- DeepSeek ---
docker run -d -p 80:80 \
  -e ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
  -e ANTHROPIC_AUTH_TOKEN=your_deepseek_api_key \
  -e ANTHROPIC_MODEL=deepseek-chat \
  -e ANTHROPIC_SMALL_FAST_MODEL=deepseek-chat \
  -e API_TIMEOUT_MS=600000 \
  -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  -v ~/.claude:/workspace/.claude \
  -v ~/eido-logs/app:/var/log/eido/app \
  -v ~/eido-logs/litellm:/var/log/eido/litellm \
  -v ~/eido-logs/nginx:/var/log/eido/nginx \
  damaohongtu/eido:latest
