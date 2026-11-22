#!/bin/bash
# =============================================================================
# 构建并推送镜像
# =============================================================================

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

# 构建前端（PC + H5）
(cd frontend && npm run build) || exit 1

# 构建镜像
docker buildx bake -f docker/docker-bake.hcl --load base app || exit 1

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
  -v ~/eido-logs/nginx:/var/log/eido/nginx \
  damaohongtu/eido:latest
