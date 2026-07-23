#!/usr/bin/env bash
# Project 数据迁移/生命周期 smoke（sandbox 模式）。
#
# 该脚本直接从 gateway 容器访问当前用户的 user runtime，使用与 gateway 相同的受信头，
# 用于在没有浏览器 CAS Cookie 的发布环境验证 user image、SQLite 迁移和数据卷。
# 它不会读取或修改仓库内的 .eido/chat_sessions.db。
#
# 前置：目标用户容器已经由一次正常登录/warmup 拉起。
# 使用：
#   EIDO_GATEWAY_SECRET=... USER_ID=test-user bash tests/project-smoke.sh
set -euo pipefail

USER_ID="${USER_ID:-test-user}"
GATEWAY_CONTAINER="${GATEWAY_CONTAINER:-eido-gateway}"

if [[ -z "${EIDO_GATEWAY_SECRET:-}" ]]; then
  echo "缺少 EIDO_GATEWAY_SECRET" >&2
  exit 2
fi

if [[ ! "$USER_ID" =~ ^[A-Za-z0-9._@-]{1,128}$ ]]; then
  echo "USER_ID 格式非法" >&2
  exit 2
fi

if [[ -z "${USER_CONTAINER:-}" ]]; then
  USER_CONTAINER=$(docker ps -a \
    --filter 'label=io.eido.role=user-sandbox' \
    --filter "label=io.eido.user_id=$USER_ID" \
    --format '{{.Names}}' | sed -n '1p')
fi

if [[ -z "$USER_CONTAINER" ]] || ! docker inspect "$USER_CONTAINER" >/dev/null 2>&1; then
  echo "未找到 user_id=$USER_ID 的用户容器；请先让用户登录或调用 sandbox/warmup" >&2
  exit 2
fi
if [[ "$(docker inspect -f '{{.State.Running}}' "$USER_CONTAINER")" != "true" ]]; then
  echo "$USER_CONTAINER 未运行；请先完成 warmup" >&2
  exit 2
fi

BASE_URL="http://${USER_CONTAINER}:8000/api/v1"

api_call() {
  docker exec "$GATEWAY_CONTAINER" curl -fsS \
    -H "X-Eido-User-Id: $USER_ID" \
    -H "X-Eido-Gateway-Secret: $EIDO_GATEWAY_SECRET" \
    "$@"
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$field"
}

PROJECT_ID=""
SESSION_ID=""
cleanup() {
  if [[ -n "$PROJECT_ID" ]]; then
    api_call -X DELETE "$BASE_URL/projects/$PROJECT_ID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$SESSION_ID" ]]; then
    api_call -X DELETE "$BASE_URL/sessions/$SESSION_ID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

SUFFIX=$(date +%s)

echo "== 1) 创建 Project =="
PROJECT_JSON=$(api_call \
  -X POST "$BASE_URL/projects/" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"[smoke] project-$SUFFIX\",\"description\":\"release smoke\",\"instructions\":\"keep session workspace stable\"}")
PROJECT_ID=$(printf '%s' "$PROJECT_JSON" | json_field id)
test -n "$PROJECT_ID"

echo "== 2) 在 Project 中创建 Session =="
SESSION_JSON=$(api_call \
  -X POST "$BASE_URL/sessions/" \
  -H 'Content-Type: application/json' \
  -d "{\"title\":\"[smoke] session-$SUFFIX\",\"project_id\":\"$PROJECT_ID\"}")
SESSION_ID=$(printf '%s' "$SESSION_JSON" | json_field id)
BOUND_PROJECT=$(printf '%s' "$SESSION_JSON" | json_field project_id)
[[ "$BOUND_PROJECT" == "$PROJECT_ID" ]]

echo "== 3) 删除 Project，确认 Session 被解绑而非删除 =="
api_call -X DELETE "$BASE_URL/projects/$PROJECT_ID" >/dev/null
PROJECT_ID=""
SESSION_AFTER=$(api_call "$BASE_URL/sessions/$SESSION_ID")
printf '%s' "$SESSION_AFTER" | python3 -c '
import json, sys
session = json.load(sys.stdin)
assert session["project_id"] is None, session
assert isinstance(session.get("messages"), list), session
'

echo "== 4) 检查 SQLite 外键 =="
docker exec "$USER_CONTAINER" python -c '
import os, sqlite3
root = os.environ.get("EIDO_DATA_ROOT", "/data")
con = sqlite3.connect(os.path.join(root, "chat_sessions.db"))
errors = con.execute("PRAGMA foreign_key_check").fetchall()
assert not errors, errors
version = con.execute("PRAGMA user_version").fetchone()[0]
assert version > 0, version
print(f"schema_version={version} foreign_keys=ok")
'

echo "✓ Project smoke 通过"
