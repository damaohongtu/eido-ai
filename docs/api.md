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

## 二、Projects `/api/v1/projects`

Project 是当前用户私有的会话与共享上下文容器。所有接口都从登录态解析 `user_id`；客户端
不能指定或覆盖项目所有者。云端 Project 不与 Chrome 本机 OpenCode 项目目录同步。

### 数据模型

```ts
interface Project {
  id: string;
  user_id: string;
  name: string;
  description: string;
  instructions: string;
  context_revision: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  session_count: number;
}

interface ProjectFile {
  id: string;
  project_id: string;
  display_name: string;
  media_type: string | null;
  size_bytes: number;
  sha256: string;
  source_session_id: string | null;
  created_at: string;
  // 仅新增/导入响应返回；列表中的文件记录可省略。
  context_revision?: number;
}
```

### Project CRUD

| Method | Path | 说明 |
|---|---|---|
| GET | `/projects/` | 当前用户项目列表；默认不含已归档项目 |
| POST | `/projects/` | 创建项目 |
| GET | `/projects/{project_id}` | 项目详情 |
| PATCH | `/projects/{project_id}` | 更新名称、说明、指令或归档状态 |
| DELETE | `/projects/{project_id}` | 删除项目；会话解绑但不删除 |

创建请求：

```json
{
  "name": "广州房地产研究",
  "description": "长期跟踪供需、政策与价格",
  "instructions": "优先使用项目资料，结论注明数据日期"
}
```

修改名称、说明、`instructions` 或项目文件会递增 `context_revision`。删除项目时，关联 Session
会被设置为未归类，消息和 `.eido/workspaces/<session_id>` 保留；项目共享文件副本随项目删除。
删除响应包含 `cleanup_pending`：为 `true` 时逻辑删除已经完成，磁盘清理由持久化任务在启动时重试。

### Project Files

| Method | Path | 说明 |
|---|---|---|
| GET | `/projects/{project_id}/files` | 列出项目共享文件 |
| POST | `/projects/{project_id}/files` | 上传一个项目共享文件 |
| GET | `/projects/{project_id}/files/{file_id}` | 读取或下载项目文件 |
| DELETE | `/projects/{project_id}/files/{file_id}` | 删除项目文件 |
| POST | `/projects/{project_id}/files/import` | 将目标项目内会话的 `outputs/` 生成产物复制为项目资料 |

导入采用复制语义，源会话文件不移动、不删除。上传和导入均校验项目归属、文件大小、路径边界，
服务端以随机 `storage_name` 落盘，不直接信任原文件名。

项目资料支持 `.md / .pdf / .csv / .xls / .xlsx / .html / .htm / .txt / .json / .png / .jpg /
.jpeg / .gif / .webp / .svg / .doc / .docx / .ppt / .pptx`，单文件不超过 20 MiB。
`files/import` 仅接受当前目标 Project 内会话的 `outputs/` 文件；成功返回的文件记录包含最新
`context_revision`。HTML、SVG 和 Office 文档下载时强制使用 attachment。

默认配额为单文件 20 MiB、单 Project 100 个文件/512 MiB、单用户 500 个项目文件/2 GiB；累计
配额可通过 `EIDO_PROJECT_MAX_*` 与 `EIDO_USER_PROJECT_MAX_*` 环境变量调整。待物理清理的文件
仍计入配额；同一用户的上传/导入串行执行，并按当前剩余容量流式截断，防止并发请求先占满磁盘。
上传锁在 multipart 解析前获取；部署提供的 Nginx 配置已关闭该接口链路的请求体缓冲。

常见错误：

- `400` 参数、文件类型或路径非法；
- `413` 单文件或累计 Project/用户配额超限；
- `404` 项目或文件不存在，也用于隐藏其他用户资源；
- `409` 项目状态不允许当前操作。

完整的数据与迁移约束见 [`project-design.md`](project-design.md)。

---

## 三、Sessions `/api/v1/sessions`

会话与消息的持久化接口。所有写操作按 `user_id` 自动过滤，杜绝越权。

### 数据模型

```ts
interface Session {
  id: string;
  user_id: string;
  title: string;
  skill_id: string | null;
  project_id: string | null;
  applied_context_revision: number | null;
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

可选过滤参数：

- `project_id=<id>`：只返回指定项目中的会话；
- `unassigned=true`：只返回未归类会话；
- 两者不能同时使用。不传时保持旧行为，返回当前用户全部会话。

`applied_context_revision` 是服务端执行状态，只读且不能通过 Session PATCH 设置。项目上下文版本
变化后，下一次 Chat 会重建原生 Agent 上下文，并用服务端持久化的有界近期消息恢复对话连续性。

```json
[
  {
    "id": "9b2c1d3a4f5e",
    "user_id": "u_123",
    "title": "中望软件 2025三季报",
    "skill_id": "financial-report-analyst",
    "project_id": "a1b2c3d4e5f6",
    "created_at": "2026-04-25T01:30:00+00:00",
    "updated_at": "2026-04-25T01:35:12+00:00"
  }
]
```

### `POST /sessions/`

创建新会话。同时自动落地 `.eido/workspaces/<id>/{uploads,outputs}` 工作区目录。

请求：
```json
{ "title": "可选标题", "skill_id": "可选技能 id", "project_id": "可选项目 id" }
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

部分更新会话（标题、关联技能或所属项目）。显式传 `"project_id": null` 会把会话移到未归类；
绑定其他用户的项目返回 404。

请求（任一字段可选）：
```json
{ "title": "新标题", "skill_id": "新技能 id", "project_id": null }
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

## 四、Chat `/api/v1/chat`

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

## 五、Workspace `/api/v1/workspace`

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

## 六、Skills `/api/v1/skills`

| Method | Path | 说明 |
|---|---|---|
| GET | `/skills/` | 技能列表（query: `is_system`, `limit`, `offset`） |
| GET | `/skills/{id}` | 技能详情（含 SKILL.md 内容） |
| POST | `/skills/` | 上传 / 创建用户自定义技能 |
| DELETE | `/skills/{id}` | 删除用户技能 |

详细 schema 参考 `backend/app/schemas/skill.py`。

---

## 七、Tasks `/api/v1/tasks`

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

## 八、Sandbox `/api/v1/sandbox`

仅在 `EIDO_SANDBOX_MODE=docker`（gateway）模式下生效；`local` 模式下接口仍存在，但
为 no-op，方便前端代码逻辑统一。

### `POST /sandbox/warmup`

登录成功后调用，提前拉起当前用户的沙箱容器，把首条消息的冷启动开销摊到登录后的等待期。

请求：无请求体。

响应：

```json
{
  "user_id": "u_123",
  "container": "eido-user-u_123",
  "status": "running",
  "ready": true
}
```

`local` 模式响应：`{"ready": true, "mode": "local"}`。

错误：

- `400` user_id 不符合白名单 `^[A-Za-z0-9._@\\-]{1,128}$`
- `502` user 容器健康检查超时（gateway 已重置该用户的注册表，下次请求会重建）

### `GET /sandbox/status`

返回当前用户容器的运行状态（无副作用，不会触发拉起）。

```json
{
  "user_id": "u_123",
  "running": true,
  "container": "eido-user-u_123",
  "last_active_at": 1745605812.345
}
```

未拉起时返回 `{"user_id": "...", "running": false}`。

---

## 九、SSE 事件类型参考

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
