# Eido Project 技术方案与发布约束

> 状态：Project v1 实施基线。本文中的 Project 指 Eido 云端业务对象，不等同于
> Chrome 本机模式的 OpenCode 项目目录。

## 1. 范围与非目标

Project v1 是**当前用户私有**的对话与上下文容器：

- 一个 Project 属于一个 `user_id`，可以包含多条 Chat Session。
- 一条 Chat Session 最多属于一个 Project，也可以保持“未归类”。
- Project 可以保存说明、项目指令和共享文件。
- 历史会话、未归类会话及旧客户端继续工作。

首版不支持项目成员、跨用户共享、角色权限或公开链接。当前 sandbox 架构为每个用户
分配独立容器和数据卷；协作项目需要中央元数据、对象存储和 ACL，不能通过放宽现有
`user_id` 校验实现。

## 2. 术语

| 名称 | 含义 |
| --- | --- |
| Eido Project | 服务端的个人项目，聚合会话、指令和共享文件 |
| Chat Session | 一条 Eido 对话，API 仍使用 `/sessions` |
| Session Workspace | `.eido/workspaces/<session_id>/`，该会话的上传与产物目录 |
| Project Files | `.eido/projects/<project_id>/files/`，项目级共享文件副本 |
| OpenCode Project Directory | Chrome 本机模式选择的本地目录，只保存在本机 |
| Auth Session | CAS 登录 Cookie，与 Chat Session 无关 |

代码中的 `Settings.PROJECT_NAME` 和 Claude Code 的 `setting_sources=["project"]` 也不表示
Eido Project。

## 3. 数据模型

Project 与现有会话、消息保存在同一个 `chat_sessions.db`，从而让归属校验、解绑和删除
可以在一个 SQLite 事务中完成。

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    context_revision INTEGER NOT NULL DEFAULT 1,
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL
);

ALTER TABLE chat_sessions ADD COLUMN project_id TEXT
    REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE chat_sessions ADD COLUMN applied_context_revision INTEGER;

CREATE TABLE project_files (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    storage_name TEXT NOT NULL,
    media_type TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    source_session_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, storage_name),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(source_session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
);

CREATE TABLE storage_cleanup_jobs (
    id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    project_id TEXT NOT NULL,
    storage_name TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    file_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT ''
);
```

必要索引：

```sql
CREATE INDEX idx_projects_user_activity
    ON projects(user_id, archived_at, last_activity_at DESC);
CREATE INDEX idx_chat_sessions_user_project
    ON chat_sessions(user_id, project_id, updated_at DESC);
CREATE INDEX idx_project_files_project
    ON project_files(project_id, created_at);
```

所有 Project 和 Project File 操作都必须先按当前 `user_id` 校验 Project。`project_id` 使用
`NULL` 表示未归类；“未归类”是前端虚拟分组，不创建隐式默认项目。

## 4. 文件与执行边界

已有 Session Workspace 路径保持不变：

```text
<data_root>/
├── chat_sessions.db
├── projects/<project_id>/files/
└── workspaces/<session_id>/
    ├── uploads/
    └── outputs/
```

将会话加入、移出或移动到另一个 Project 时，**不得移动** `workspaces/<session_id>`。
历史消息可能保存绝对路径，Claude Code/OpenCode 原生 Session 也可能绑定原 cwd；移动目录
会破坏历史文件链接和续聊。

将生成结果晋升为项目资料采用复制语义：来源会话必须由当前用户拥有且在请求时仍属于目标
Project，来源路径必须解析到该会话的 `outputs/` 目录；允许 Agent 返回的绝对 outputs 路径，但
拒绝 `uploads/`、目录、跨 Project/未归属会话以及解析后逃出 outputs 的符号链接。源 Session
Workspace 保持不变，Project 保存独立副本、SHA-256 和来源会话 ID。Project 文件名不能直接作为
磁盘文件名，服务端应生成 `storage_name` 并在解析路径时再次校验 Project 根目录。导入成功响应
同时返回递增后的 `context_revision`，下一轮 Chat 会据此重建 provider 上下文并读到新资料。

项目资料支持 Markdown、PDF、CSV、Excel、HTML、纯文本、JSON、常见 Web 图片，以及
Word/PowerPoint 产物。MIME 类型只由服务端认可的扩展名决定，并返回
`X-Content-Type-Options: nosniff`；HTML、SVG 和 Office 文档一律以 attachment 下载，不能作为
同源主动内容内联执行。

Project 名称、说明、指令或文件发生变化时递增 `context_revision`。一次 Chat 请求在开始执行时
解析并固定项目上下文快照；运行中的请求不受随后修改项目设置的影响。
`applied_context_revision` 用于记录会话最后应用的版本，不应由客户端自行指定。

Chat 启动前必须在服务端比较 `applied_context_revision` 与当前 Project 的
`context_revision`。首次应用或版本不一致时，先以事务清空该会话的 Claude/OpenCode 原生
Session ID，再驱逐 OpenHarness 的会话缓存，然后把本次快照版本写入
`applied_context_revision`。这样下一次执行不会续接仍包含旧项目指令或旧文件清单的原生上下文。

清空原生 Session ID 不等于清空 Eido 对话。重建 Agent 上下文时，服务端从当前用户、当前
Session 的 `chat_messages` 加载一段有界的近期历史，并与本轮最新消息去重后交给执行后端；不能
只传最后一句，也不能信任客户端回传的完整历史作为事实来源。注入 prompt 的历史使用字符预算，
超限时从最旧消息开始裁剪。只有 Project 版本一致且 provider Session ID 仍有效时，才沿用原生
续聊机制。

同一进程内对同一个 Chat Session 采用 single-flight 执行守卫：已有请求尚未结束时，新 Chat
请求返回 `409`；不同 Session 可并行。provider Session ID 写回还必须同时匹配请求开始时的
`project_id` 与 `context_revision`，避免项目移动或上下文刷新后，较早的 in-flight 请求把过期
原生 Session ID 写回数据库。Project 还使用共享/独占租约：聊天、上传、导入和迁入持共享租约，
删除资料、删除或归档 Project 持独占租约；这样同一 Project 的不同会话仍可并行，又不会在删除
快照后迁入新会话。当前每个用户容器运行单后端进程；若改为多 worker 或多副本，必须把该守卫
升级为跨进程锁。

共享资料默认限制为：单文件 20 MiB、单 Project 100 个/512 MiB、单用户 500 个/2 GiB。累计
配额可通过 `EIDO_PROJECT_MAX_FILES`、`EIDO_PROJECT_MAX_BYTES`、
`EIDO_USER_PROJECT_MAX_FILES`、`EIDO_USER_PROJECT_MAX_BYTES` 调整；检查与元数据插入在同一个
SQLite 写事务中完成。
上传入口在解析 multipart 请求体之前获取用户级上传锁和 Project 共享租约，反向代理关闭请求体
缓冲；解析器按当前剩余容量截断输入，避免并发请求先在代理或临时目录完整落盘。

`cwd` 只是 Agent 的默认目录，不是同一用户内的 OS 安全边界。Claude/OpenCode 可以使用 Bash、
Read、Write 等工具，因此 Project v1 是组织和上下文边界；真正的跨用户安全边界仍是 per-user
container、`user_id` 校验和文件 API 的安全路径解析。

## 5. 生命周期

- 创建会话时可提交 `project_id`；省略或传 `null` 即未归类。
- 更新会话的 `project_id` 表示加入、移出或移动 Project，必须验证目标 Project 属于当前用户。
- 项目归档只影响默认列表、新会话绑定和新增资料入口，不删除任何数据；已有会话仍可使用上下文。
- 删除 Project 时，在同一事务中将其会话 `project_id`、`applied_context_revision` 和 provider
  Session ID 清空，再删除 Project 元数据；同时逐个驱逐这些会话的 OpenHarness 缓存。
- 删除 Project 会删除项目共享文件副本，但**不删除**会话、消息或 Session Workspace。
- 删除会话仍只删除该会话、消息和 Session Workspace；已复制到 Project 的共享文件不受影响。

SQLite 与文件系统不能组成一个原子事务。删除 Project/资料时，元数据事务会同时写入
`storage_cleanup_jobs`；物理删除成功后才移除任务。失败时 API 返回 `cleanup_pending: true`，
任务会在应用启动和运行期间周期重试，因此不会产生无法定位的孤儿文件。任务保留所属用户、文件
数量和字节数，磁盘尚未真正释放时仍计入配额。空 Project 不预建目录，首个文件写入时才创建。
新增文件若元数据提交失败，会先确认不存在已提交记录，再删除文件；清理失败同样写入重试队列。
启动时还会对服务端生成的 `.upload/.import` 临时名及 UUID 存储名执行元数据对账，清理进程崩溃
窗口留下的孤儿；人工命名文件不会自动删除。

Project ID、Project File ID 和磁盘 `storage_name` 由服务端随机生成且不可经公开 API 指定。
离线恢复工具不得复用已经删除的这些 ID；若未来需要支持 ID 复用或多进程清理 worker，应为清理
任务增加 generation/claim，并以 compare-and-delete 完成任务，防止旧 worker 清除新的删除意图。

清空 provider Session ID 是为了避免会话解绑后继续复用包含旧项目指令或文件上下文的原生
会话。若产品未来允许跨项目移动已有对话，需要明确展示该上下文变化，而不能静默复用旧上下文。

## 6. 云端与本机模式

PC、移动 H5 和 Chrome 的云端模式共享服务端 Project API，因此可以跨设备同步。

Chrome 本机 OpenCode 模式保持现有隐私边界：

- 本地项目目录、文件、会话和 OpenCode Session 映射不上传 Eido。
- 本机模式不调用 Eido `projects/chat/sessions/skills/workspace/tasks/sandbox` API；除认证外只与
  回环地址上的 OpenCode 通信。
- 本地 Project ID 与云端 Project ID 不共用命名空间。
- 若后续在本机模式支持项目列表，存储键必须带 schema 版本，并将
  `{local_project_id, session_id, endpoint, canonical_directory, provider_session_id}` 一起绑定。
- 文件列表、预览和发送请求必须使用会话绑定的目录快照，不能只读取当前全局 `/path`。

因此，云端 Project 不提供“同步到本机目录”开关；目录同步需要独立的用户确认、冲突处理和
凭据安全设计。

## 7. SQLite 迁移

仓库曾出现以下历史形态：

1. `chat_sessions` 只有基础字段；
2. 增加 `claude_session_id`；
3. 再增加 `opencode_session_id`；
4. 部分实际旧库的 `chat_messages` 仍以 `id` 为单主键，而当前目标是
   `(session_id, id)` 复合主键。

迁移不能只依赖版本号，必须结合 `PRAGMA table_info` 检查实际表形状。推荐流程：

1. `BEGIN IMMEDIATE` 获取写锁；
2. 创建 Project 表；
3. 按缺失列逐个 `ALTER TABLE ... ADD COLUMN`；
4. 若消息主键不是目标形态，创建新表、完整复制、删除旧表、重命名并重建索引；
5. 执行 `PRAGMA foreign_key_check`；
6. 更新 `PRAGMA user_version` 后提交。

Project schema 版本沿用单调递增规则：v1 为 Project、Session 归属及共享资料基础表；v2 为早期
持久化清理队列；v3 为清理任务增加 `user_id/file_count/size_bytes` 配额记账。程序仍会结合实际
表形状修复历史库，因此已有 v2 数据库会在同一事务中补列并升级到 v3，绝不回写更低版本。
迁移过程不要使用会隐式提交的 `sqlite3.Connection.executescript()`。遇到孤儿消息、复制计数
不一致或 FK 检查失败时必须回滚并让 readiness 失败，不能静默丢数据。重复执行迁移应为 no-op。

## 8. 发布与回滚

推荐顺序：

1. 停止写入并备份 SQLite 与文件目录；WAL 模式下使用 SQLite backup API，或停机后 checkpoint。
2. 发布新版 user image。
3. 发布支持 `/projects/**` 反代的 gateway/backend。
4. 执行 Project CRUD、历史会话和重启持久化 smoke。
5. 最后发布 PC、移动端和 Chrome extension。

Sandbox 模式下，已运行的旧 `eido-user-*` 容器不会自动变成新镜像。升级时应 stop/remove 旧
user 容器但保留同名 volume，随后由 gateway 懒启动新容器并执行迁移。长期应给 user 容器增加
应用/schema 版本标签，并由 gateway 检测镜像不一致。

数据库变更保持 additive：旧后端会忽略新表和 nullable 列，因此回滚应用无需降级数据库。
回滚不能删除 Project 表或移动会话目录。

应用当前 `/health` 只代表进程存活。正式发布应增加 `/ready` 或等价 readiness，至少验证
ChatSessionStore 已连接、schema version 达标、`foreign_key_check` 通过且数据根目录可写；在此之前，
部署脚本必须通过一次 Project API smoke 判断迁移是否成功。

## 9. 最低验收矩阵

- 新库初始化与所有历史 schema 升级；迁移重复运行无变化。
- 旧消息主键修复后，两个会话可以保存相同 message ID。
- 用户不能读取、修改、删除或绑定其他用户的 Project。
- 删除 Project 后会话、消息和 Session Workspace 均保留且变为未归类。
- Project 文件上传、导入、读取和删除均经过归属与路径越界校验。
- PC、移动 H5、Chrome 云端模式展示一致；旧客户端不传 `project_id` 仍可聊天。
- Chrome 本机模式切换目录后不会串用 OpenCode Session，且不产生 Eido Project 请求。
- 单容器和 sandbox 容器重建后，Project、会话和文件仍存在。
