#!/usr/bin/env bash
# 从 docker/.env 生成 k8s/30-secret.yaml（eido-system/eido-secrets）
#
# 用法：cd k8s && ./gen-secret.sh
# 依赖：kubectl、openssl；docker/.env 已含模型凭据
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/docker/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "✗ 未找到 $ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
# 注意：macOS bash 3.2 下 `source <(pipeline)` 不生效（zsh 正常），改用 eval
eval "$(grep -E '^[A-Z_]+=' "$ENV_FILE" | sed 's/^/export /')"

# 会话/网关密钥缺失时生成随机值（仅首次；重新生成会使所有会话失效）
gen() { openssl rand -hex 32; }
SESSION_SECRET_KEY="${SESSION_SECRET_KEY:-$(gen)}"
EIDO_GATEWAY_SECRET="${EIDO_GATEWAY_SECRET:-$(gen)}"
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"

if [[ -z "$ANTHROPIC_BASE_URL" || ( -z "$ANTHROPIC_API_KEY" && -z "$ANTHROPIC_AUTH_TOKEN" ) ]]; then
  echo "✗ docker/.env 缺少 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY（provider relay 无法工作）" >&2
  exit 1
fi

kubectl -n eido-system create secret generic eido-secrets \
  --from-literal=SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
  --from-literal=EIDO_GATEWAY_SECRET="$EIDO_GATEWAY_SECRET" \
  --from-literal=ANTHROPIC_BASE_URL="$ANTHROPIC_BASE_URL" \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --from-literal=ANTHROPIC_AUTH_TOKEN="$ANTHROPIC_AUTH_TOKEN" \
  --dry-run=client -o yaml > "$(dirname "$0")/30-secret.yaml"

echo "✓ 已生成 k8s/30-secret.yaml（含敏感凭据，勿提交 git）"
