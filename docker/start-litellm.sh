#!/bin/bash
# LiteLLM 代理启动脚本
# 将 Anthropic API 格式转发到自定义 OpenAI 兼容端点
#
# 上游端点: https://127.0.0.1:5000/v1/chat/chat/completions
# 代理端口: 4000
# 暴露接口: http://localhost:4000  (Anthropic + OpenAI 双格式)

set -e

# 上游接口的认证 token
export LITELLM_API_KEY="${UPSTREAM_API_KEY:-your_token_here}"

# 安装（如未安装）
if ! command -v litellm &>/dev/null; then
    echo "安装 litellm[proxy]..."
    pip install 'litellm[proxy]'
fi

echo "启动 LiteLLM 代理，监听端口 4000..."
litellm --config "$(dirname "$0")/litellm-config.yaml" --port 4000
