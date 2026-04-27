#!/bin/bash
# 在仓库根执行时，docker compose 默认只加载「当前目录」的 .env，不会读 docker/.env。
# 不 source 时 ${CAS_*} 等未展开，容器内会落回 Pydantic 默认（如 callback 为 :8000），与 docker/.env 不一致。
# 本脚本只采用 source docker/.env，再执行「docker compose」（两词一行，子命令）；
# 不要写成 docker --env-file（那是非法的）；--env-file 仅属于 docker compose 子命令，且非必需。
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

# 必须是「docker」空格「compose」两个词；手打成「docker -f」会报 unknown shorthand flag: 'f'
run_compose() {
  if docker compose version &>/dev/null; then
    docker compose "$@"
  elif command -v docker-compose &>/dev/null; then
    docker-compose "$@"
  else
    echo "未找到 docker compose 或 docker-compose，请安装 Docker Compose 插件" >&2
    exit 1
  fi
}

HOST_IP=192.168.138.49           # 你当前宿主机的局域网 IP，已确认 gateway/浏览器均可达
NEW_GATEWAY_SECRET=$(openssl rand -hex 32)
NEW_SESSION=$(openssl rand -hex 32)

cp docker/.env docker/.env.bak

# CAS 4 项必须用同一个 host
sed -i '' \
  -e "s|^CAS_SERVER_URL=.*|CAS_SERVER_URL=http://${HOST_IP}:3331/cas/|" \
  -e "s|^CAS_SERVICE_URL=.*|CAS_SERVICE_URL=http://${HOST_IP}/ai-eido/api/v1/auth/callback|" \
  -e "s|^FRONTEND_URL=.*|FRONTEND_URL=http://${HOST_IP}/ai-eido/|" \
  -e "s|^SESSION_SECRET_KEY=.*|SESSION_SECRET_KEY=${NEW_SESSION}|" \
  -e "s|^EIDO_GATEWAY_SECRET=.*|EIDO_GATEWAY_SECRET=${NEW_GATEWAY_SECRET}|" \
  docker/.env

# EIDO_TRUST_GATEWAY 仅由 sandbox_manager 注入 user 容器，不要写入 docker/.env
# 否则 gateway 容器会误入 user-runtime 分支丢失 auth 路由

echo '== 修复后 key 配置 (docker/.env) =='
grep -E '^(AUTH_DISABLED|CAS_|FRONTEND_URL|SESSION_SECRET_KEY|EIDO_GATEWAY_SECRET)=' docker/.env

# 将 docker/.env 注入当前 shell，供 compose 做 ${VAR} 替换；覆盖宿主机里可能残留的 export
set -a
# shellcheck disable=SC1091
. "${ROOT}/docker/.env"
# .env 中的 ~ 不会被 source 展开，必须在 set -a 生效期间修正并自动 export
CLAUDE_DIR="${CLAUDE_DIR/#\~/$HOME}"
LOG_DIR="${LOG_DIR/#\~/$HOME}"
set +a

# 子命令是 compose：docker compose -f ...（「compose」不能省，否则变成 docker -f 报错）
echo "== 将执行: run_compose -f <repo>/docker/docker-compose.yml --profile sandbox up -d --force-recreate eido-gateway =="
run_compose -f "${ROOT}/docker/docker-compose.yml" --profile sandbox up -d --force-recreate eido-gateway

sleep 8

# 再次确认进容器的环境变量
docker exec eido-gateway sh -lc '
  echo "trust=$EIDO_TRUST_GATEWAY (应为空或 0)"
  echo "sandbox_mode=$EIDO_SANDBOX_MODE"
  echo "secret_len=${#EIDO_GATEWAY_SECRET}"
  echo "session_key_len=${#SESSION_SECRET_KEY}"
  echo "cas_server=$CAS_SERVER_URL"
  echo "cas_service=$CAS_SERVICE_URL"
'