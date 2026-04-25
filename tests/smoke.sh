#!/usr/bin/env bash
# Sandbox 模式端到端 smoke：通过受信网关头绕开 CAS，直接打 gateway 内部 8000 端口。
# 使用：
#   EIDO_GATEWAY_SECRET=$(grep ^EIDO_GATEWAY_SECRET= docker/.env | cut -d= -f2-) \
#   USER_ID=test-user \
#   bash tests/smoke.sh
set -euo pipefail

BASE=http://127.0.0.1/ai-eido
USER_ID="${USER_ID:-test-user}"

if [[ -z "${EIDO_GATEWAY_SECRET:-}" ]]; then
  if [[ -f docker/.env ]]; then
    EIDO_GATEWAY_SECRET=$(grep -E '^EIDO_GATEWAY_SECRET=' docker/.env | head -1 | cut -d= -f2-)
  fi
fi
if [[ -z "${EIDO_GATEWAY_SECRET:-}" ]]; then
  echo "✗ 缺 EIDO_GATEWAY_SECRET 环境变量（也没法从 docker/.env 读到）" >&2
  exit 1
fi

SAFE_USER=$(echo -n "$USER_ID" | tr -c 'A-Za-z0-9._@\-' '_')

echo '== 1) 外层 nginx /health =='
curl -s $BASE/health && echo

echo
echo '== 2) gateway 内部 warmup（受信网关头）=='
docker exec eido-gateway sh -lc "
  curl -sS -X POST http://127.0.0.1:8000/api/v1/sandbox/warmup \
    -H 'X-Eido-User-Id: $USER_ID' \
    -H 'X-Eido-Gateway-Secret: $EIDO_GATEWAY_SECRET'
"
echo

echo
echo '== 3) 列出 user 容器 =='
docker ps --filter label=io.eido.role=user-sandbox \
          --format 'table {{.Names}}\t{{.Status}}'

echo
echo '== 4) gateway 注册表（用 python 替代 sqlite3 CLI）=='
docker exec eido-gateway python -c "
import sqlite3, datetime
con = sqlite3.connect('/workspace/.eido/sandbox_registry.db')
for row in con.execute('SELECT user_id, container_name, status, last_active_at FROM sandbox_registry'):
    uid, cname, status, ts = row
    when = datetime.datetime.fromtimestamp(ts).isoformat() if ts else '-'
    print(f'{uid:20s} {cname:40s} {status:10s} {when}')
"

echo
echo "== 5) gateway 直 ping user 容器（eido-user-$SAFE_USER）=="
docker exec eido-gateway sh -lc "curl -fsS http://eido-user-$SAFE_USER:8000/health" && echo

echo
echo '== 6) 通过 gateway 反代调用 user 容器接口（GET /sandbox/status）=='
docker exec eido-gateway sh -lc "
  curl -sS http://127.0.0.1:8000/api/v1/sandbox/status \
    -H 'X-Eido-User-Id: $USER_ID' \
    -H 'X-Eido-Gateway-Secret: $EIDO_GATEWAY_SECRET'
"
echo
