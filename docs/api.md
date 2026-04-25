# Eido API 文档（v1）

所有路由前缀 `/api/v1`。除 `/auth/*` 外其余接口均要求会话已登录（CAS Cookie）。

为简洁起见示例省略 `Cookie` 头。

---

## 一、Auth `/api/v1/auth`

| Method | Path | 说明 |
|---|---|---|
| GET | `/auth/login` | 跳转 CAS 登录 |
| GET | `/auth/callback` | CAS 回调，写入 session cookie |
| GET | `/auth/logout` | 清空 session 并跳转 CAS 登出 |
| GET | `/auth/me` | 当前登录用户 |

### `GET /auth/me`

```json
{ "user_id": "u_123", "username": "张三" }
```

未登录返回 `401 {"detail": "未登录"}`。

---

## 二、Sessions `/api/v1/sessions`（本期新增）

会话与消息的持久化接口。所有写操作按 `user_id` 自动过滤，杜绝越权。

### 数据模型

```ts
interface Session {
  id: string;
  user_id: string;
  title: string;
  skill_id: string | null;
  created_at: string;  // ISO8601
  updated_at: string;
}

interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  extra: Record<string, any>;  // thinking / executionSteps / references / workflowMermaid / ...
  created_at: string;
}
```

### `GET /sessions/`

列出当前用户全部会话（按 `updated_at` 倒序）。

```json
[
  {
    "id": "9b2c1d3a4f5e",
    "user_id": "u_123",
    "title": "中望软件 2025三季报",
    "skill_id": "financial-report-analyst",
    "created_at": "2026-04-25T01:30:00+00:00",
    "updated_at": "2026-04-25T01:35:12+00:00"
  }
]
```

### `POST /sessions/`

创建新会话。同时自动落地 `.eido/workspaces/<id>/{uploads,outputs}` 工作区目录。

请求：
```json
{ "title": "可选标题", "skill_id": "可选技能 id" }
```

响应：单个 `Session`（含后端生成的 `id`，长度 12 的 hex）。

### `GET /sessions/{id}`

返回会话元信息 + 全部消息（按 `created_at` 升序）。

```json
{
  "id": "9b2c1d3a4f5e",
  "user_id": "u_123",
  "title": "...",
  "skill_id": null,
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    {
      "id": "m-init-0",
      "session_id": "9b2c1d3a4f5e",
      "role": "assistant",
      "content": "你好！我是 **Eido** ...",
      "extra": {},
      "created_at": "..."
    }
  ]
}
```

### `PATCH /sessions/{id}`

部分更新会话（标题或关联技能）。

请求（任一字段可选）：
```json
{ "title": "新标题", "skill_id": "新技能 id" }
```

返回更新后的 `Session`。

### `DELETE /sessions/{id}`

删除会话 + 关联消息（CASCADE）+ 关联工作区目录。

```json
{ "deleted": true }
```

### `POST /sessions/{id}/messages`

追加一条消息。会自动刷新所属 session 的 `updated_at`。

注意：主聊天链路（用户提问、模型回答）**不依赖此接口**。`/chat/chat` 会在后端自动保存本轮 user 消息与 assistant 最终输出；本接口仅用于非主聊天场景（例如系统提示、人工补录或管理工具）。

请求：
```json
{
  "id": "可选客户端预生成的 id",
  "role": "user",
  "content": "请分析我上传的文件",
  "extra": {
    "thinking": "...",
    "executionSteps": [],
    "references": []
  }
}
```

响应：单条 `Message`。

---

## 三、Chat `/api/v1/chat`

### `POST /chat/upload`（本期改造：要求 `session_id`）

上传聊天附件到指定会话工作区。

请求（`multipart/form-data`）：
- `file`：文件（仅支持 `.md / .pdf / .csv / .xls / .xlsx`，≤ 20 MB）
- `session_id`：必填，文件将写到 `.eido/workspaces/<session_id>/uploads/`

后端会先校验该会话属于当前用户，再写入工作区；会话不存在或不属于当前用户返回 404。

响应：
```json
{
  "path": "/abs/path/to/.eido/workspaces/<sid>/uploads/<safe_name>",
  "name": "原文件名.pdf"
}
```

### `POST /chat/chat`（本期改造：要求 `session_id`，后端负责消息持久化）

统一聊天入口，由后端 `claude_agent_sdk` 自动识别并执行技能。**返回 SSE 流**。

持久化边界也在此接口内部：
- 请求进入后，后端保存本轮最新 `user` 消息
- SSE 透传过程中，后端累积 assistant 的最终 `content`、`thinking`、`executionSteps`、`references`、`workflowMermaid` 等字段
- 流结束、异常或客户端中断时，后端保存本轮 `assistant` 最终状态
- 前端只传 `message.id` 与 `assistant_message_id` 用于幂等写入，不主动调用 `/sessions/{id}/messages` 保存聊天内容

请求：
```json
{
  "messages": [
    { "id": "1745550000000", "role": "user", "content": "..." }
  ],
  "context": "可选，多技能流水线上一步输出",
  "session_id": "9b2c1d3a4f5e",
  "assistant_message_id": "1745550000001"
}
```

响应（SSE，`Content-Type: text/event-stream`）：

```
data: {"type": "thinking", "content": "正在分析请求..."}

data: {"type": "workflow_start", "skill_name": "auto"}

data: {"type": "execution_step", "step": {...}}

data: {"type": "content", "delta": "...", "full": "..."}

data: {"type": "workflow_complete"}

data: [DONE]
```

agent cwd 在执行期间被切换到 `.eido/workspaces/<session_id>/`，所有 Read / Write / Bash 都基于该目录的相对路径。技能库（`.claude/skills/`）通过**绝对路径**注入 prompt，agent 仍可读取所有 SKILL.md。

后端保存规则：
- 若最后一条请求消息是 `role=user`，保存为本轮 user 消息
- 使用 `assistant_message_id` 保存 assistant 输出；未提供时由后端生成
- `chat_messages` 使用 `(session_id, id)` 复合主键，保存逻辑采用幂等写入，重复请求不会生成重复消息

错误：
- `400` 缺 `session_id` 或非法字符
- `503` 技能服务未初始化

### `GET /chat/health`

健康检查：`{"status": "healthy", "service": "chat"}`。

---

## 四、Workspace `/api/v1/workspace`

### `GET /workspace/file`（本期增强：可选 `session_id`）

聊天消息中的图片预览或文件下载。

Query 参数：
| 名称 | 必填 | 说明 |
|---|---|---|
| `path` | 是 | 文件路径（绝对或相对） |
| `download` | 否 | `true` 时以附件下载 |
| `filename` | 否 | 下载时使用的文件名 |
| `session_id` | 否 | 传入后路径解析收窄到该会话工作区 |

行为：
- 不传 `session_id`：兼容历史路径，在 `WORKSPACE_ROOT` 全局范围内解析
- 传 `session_id`：先校验该会话属于当前用户，再把根收窄到 `.eido/workspaces/<session_id>/`
- 路径越界返回 403；会话不存在或不属于当前用户返回 404

响应：原始文件流；图片自动设置 `image/*` MIME。

---

## 五、Skills `/api/v1/skills`

| Method | Path | 说明 |
|---|---|---|
| GET | `/skills/` | 技能列表（query: `is_system`, `limit`, `offset`） |
| GET | `/skills/{id}` | 技能详情（含 SKILL.md 内容） |
| POST | `/skills/` | 上传 / 创建用户自定义技能 |
| DELETE | `/skills/{id}` | 删除用户技能 |

详细 schema 参考 `backend/app/schemas/skill.py`。

---

## 六、Tasks `/api/v1/tasks`

定时任务 CRUD（基于 APScheduler + SQLite 存储）。schema 与字段参见 `backend/app/api/v1/endpoints/tasks.py`。

| Method | Path | 说明 |
|---|---|---|
| GET | `/tasks/` | 列表 |
| POST | `/tasks/` | 创建 |
| GET | `/tasks/{id}` | 详情 |
| PATCH | `/tasks/{id}` | 修改 |
| DELETE | `/tasks/{id}` | 删除 |
| POST | `/tasks/{id}/run` | 立即触发一次 |

---

## 七、SSE 事件类型参考

`/chat/chat` 流可能 emit 的 `type` 字段：

| type | payload 字段 | 含义 |
|---|---|---|
| `thinking` | `content` | agent 思考片段 |
| `workflow_start` | `skill_name` | 开始一段工作流 |
| `workflow_complete` | — | 工作流执行完成 |
| `execution_step` | `step` | 添加 / 更新一个执行步骤 |
| `content` | `content` | assistant 增量文本 |
| `references` | `references[]` | 引用资源 |
| `workflow_mermaid` | `mermaid` | 工作流拓扑图 mermaid 源码 |
| `error` | `message` | 错误信息 |

流末尾固定以 `data: [DONE]\n\n` 结束。
