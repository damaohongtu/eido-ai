#!/bin/bash
# 本地容器测试：CAS 登录 (test1/123456) + glm 聊天链路验证
set -uo pipefail

BASE="http://localhost:8088/ai-eido"
CAS_BASE="http://192.168.138.122:3331/cas"
JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT

echo "== 1. 触发后端登录跳转 =="
LOGIN_URL=$(curl -s -o /dev/null -w "%{redirect_url}" -c "$JAR" "$BASE/api/v1/auth/login")
echo "CAS 跳转: $LOGIN_URL"
[ -z "$LOGIN_URL" ] && { echo "FAIL: 未获取到 CAS 跳转"; exit 1; }

echo "== 2. 获取 CAS 登录表单 =="
CAS_LOGIN_PAGE=$(curl -s -c "$JAR" -b "$JAR" "$LOGIN_URL")
EXECUTION=$(echo "$CAS_LOGIN_PAGE" | grep -o 'name="execution" value="[^"]*"' | head -1 | sed 's/name="execution" value="//;s/"$//')
[ -z "$EXECUTION" ] && { echo "FAIL: 未找到 execution token"; echo "$CAS_LOGIN_PAGE" | head -20; exit 1; }
echo "execution: ${EXECUTION:0:30}..."

echo "== 3. 提交 test1 凭据 =="
CALLBACK=$(curl -s -o /dev/null -w "%{redirect_url}" -c "$JAR" -b "$JAR" \
  -X POST "$LOGIN_URL" \
  --data-urlencode "username=test1" \
  --data-urlencode "password=123456" \
  --data-urlencode "execution=$EXECUTION" \
  --data-urlencode "_eventId=submit")
echo "回调: $CALLBACK"
case "$CALLBACK" in
  *ticket=*) echo "获取到 ticket" ;;
  *) echo "FAIL: 登录失败（无 ticket），可能凭据错误或 CAS 表单变化"; exit 1 ;;
esac

echo "== 4. 完成 OAuth 回调（换取 eido 会话）=="
FINAL=$(curl -s -o /dev/null -w "%{redirect_url}" -c "$JAR" -b "$JAR" "$CALLBACK")
echo "最终跳转: $FINAL"

echo "== 5. 验证会话 /auth/me =="
ME=$(curl -s -b "$JAR" "$BASE/api/v1/auth/me")
echo "$ME"
echo "$ME" | grep -q "test1" && echo "登录成功: test1" || { echo "FAIL: 会话未生效"; exit 1; }

echo "== 6. 模型列表 =="
curl -s -b "$JAR" "$BASE/api/v1/chat/models"; echo

echo "== 7. 创建会话 =="
SESSION_RESP=$(curl -s -b "$JAR" -X POST "$BASE/api/v1/sessions/" -H "Content-Type: application/json" -d '{}')
echo "$SESSION_RESP" | head -c 300; echo
SESSION_ID=$(echo "$SESSION_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id') or d.get('session_id') or '')")
[ -z "$SESSION_ID" ] && { echo "FAIL: 未获取到 session_id"; exit 1; }
echo "session_id: $SESSION_ID"

echo "== 8. 发送 glm 聊天消息（SSE）=="
curl -s -N --max-time 120 -b "$JAR" -X POST "$BASE/api/v1/chat/chat" \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [{\"id\": \"m-$SESSION_ID\", \"role\": \"user\", \"content\": \"请只回复两个字：收到\"}],
    \"session_id\": \"$SESSION_ID\",
    \"assistant_message_id\": \"a-$SESSION_ID\",
    \"model\": \"glm\",
    \"runtime_mode\": \"qa\"
  }" | head -c 4000
echo
echo "== 完成 =="
