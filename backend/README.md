# Eido Backend

基于 FastAPI 的后端服务，提供技能执行、普通对话和技能管理 API。

---

## 目录结构

- `app/main.py` 组装 FastAPI 应用、中间件和路由。
- `app/lifecycle.py` 按部署角色启动和关闭存储、Claude 会话池、调度器及沙盒管理器。
- `app/api/v1/` 定义 HTTP 请求、响应和 SSE。
- `app/services/` 按功能划分，具体目录见下表。
- `app/gateway/` 负责沙盒编排、业务转发和模型代理。
- `app/core/` 提供配置、认证、租户标识和日志。
- `requirements.txt` 是应用和镜像共用的依赖声明，`run.py` 是开发启动入口。

| 服务目录 | 职责 |
| --- | --- |
| `auth/` | CAS、GitHub OAuth 和通用 OIDC 认证提供方 |
| `chat/` | 对话执行、队列、会话存储和会话工作区 |
| `claude/` | 模型目录、提示词、原生会话和 SDK 执行 |
| `skills/` | 技能目录、导入和文件管理 |
| `mcp/` | MCP 配置存储和状态查询 |
| `projects/` | 项目上下文和共享资料工作区 |
| `tasks/` | 定时任务存储、调度和执行 |
| `files/` | 文件预览和文件类型规则 |

## 快速启动

```bash
conda activate eido
cd backend

# 首次安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 ANTHROPIC_API_KEY

# 启动开发服务器（热重载）
python run.py
```

服务启动后：
- API 文档（Swagger）：http://localhost:8000/api/v1/docs
- 健康检查：http://localhost:8000/health

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Claude Agent SDK API Key（推荐使用 Claude Console Key） | 必填* |
| `ANTHROPIC_BASE_URL` | Anthropic 兼容网关地址；官方 API 留空 | 空 |
| `ANTHROPIC_AUTH_TOKEN` | 部分兼容网关使用的 Bearer Token | 空 |
| `ANTHROPIC_MODEL` | 兼容旧部署的默认 provider 模型 | 服务默认 |
| `CLAUDE_MODELS_FILE` | YAML 模型目录路径 | `backend/config/models.yaml` |
| `GLM_*` / `DEEPSEEK_*` | 每个模型独立的 provider URL、Key/Token 与快速模型 | 空，未填字段回退全局 Anthropic 配置 |
| `CLAUDE_COMPACT_PERCENT` | Claude Code 自动压缩触发百分比 | `80` |
| `CLAUDE_SIMPLE_SYSTEM_PROMPT` | 原生精简系统提示，完整保留工具与扩展能力 | `true` |
| `SKILLS_DIR` | 技能目录路径 | `{workspace}/.claude/skills` |
| `WORKSPACE_ROOT` | 工作区根路径（传给 claude_agent_sdk） | 自动推断 |
| `LOG_LEVEL` | 日志级别 | `INFO` |

\* 使用 Bedrock、Vertex、Foundry 等官方支持的云平台认证时无需
`ANTHROPIC_API_KEY`。本机 `claude /login` 的 Claude.ai 登录不适用于 Eido 后端。

---

## API 说明

CAS 与 GitHub/OIDC 共用登录会话和固定 API Key。配置与扩展方式见
[认证接入](../docs/authentication.md)。

### POST `/api/v1/chat/completions`

通过 CAS 登录后获取的固定 API Key 调用。传入 `session_id` 时自动创建不存在的会话，
已有会话继续对话；省略时生成新的 ID。响应头 `X-Session-Id` 返回实际会话 ID。
ID 允许 1–64 位字母、数字、下划线、连字符；其他用户占用的 ID 返回 404，
会话正在执行时返回 409。同一个 ID 的并发创建只保留一个会话。

```bash
curl -iN 'http://localhost:19080/ai-eido/api/v1/chat/completions' \
  -H "X-API-Key: $EIDO_API_KEY" \
  -H 'Accept: text/event-stream' \
  --json '{"session_id":"external-chat-001","messages":[{"role":"user","content":"你好"}]}'
```

`assistant_message_id` 可选，省略时自动生成。`model`、`runtime_mode` 可选，
新会话使用服务端默认值，已有会话保留当前设置；显式传入时切换设置。
`context` 可传入额外上下文。技能通过消息中的 `@技能名` 调用。

响应为 SSE 流，以 `data: [DONE]` 结束，常见事件类型如下。

| type | 说明 |
|------|------|
| `thinking` | 执行状态提示 |
| `content` | 正文增量内容 |
| `tool_use` | 工具调用信息 |
| `error` | 执行错误 |

### POST `/api/v1/chat/chat`

原有接口继续使用已创建的会话，必须传入 `session_id` 和 `assistant_message_id`。

```json
{
  "session_id": "已有会话ID",
  "assistant_message_id": "assistant-001",
  "messages": [{"role": "user", "content": "你好"}]
}
```

### GET `/api/v1/skills/`

返回 `.claude/skills/` 目录下所有已注册技能。

```json
{
  "items": [
    {
      "id": "financial-report-analyst",
      "name": "A股财报点评",
      "description": "...",
      "is_system": true
    }
  ],
  "total": 2
}
```

### GET `/api/v1/skills/{skill_id}`

返回单个技能详情（含 SKILL.md 原文）。

---

## 技能和对话执行

`SkillCatalog` 读取技能元数据并生成 Claude Code 的原生技能视图。创建、修改和导入由 `SkillManagementService` 处理。目录变更会使相应用户的常驻 Claude 客户端失效。

`ClaudeRuntime.stream_events()` 编排会话续接和恢复，`claude/turn.py` 驱动单轮 SDK 执行。HTTP 对话、排队消息和定时任务都消费结构化事件。HTTP 路由将事件编码为 SSE。
