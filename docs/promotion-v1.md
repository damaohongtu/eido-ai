# Eido 首次项目推广

> 🎥 本文配套演示视频，涵盖 5 个关键环节：Gateway 启动 → 用户登录 → 用户沙箱自动拉起 → 技能编写与上传 → 任务执行

---

## 一、Eido 是什么？

**Eido** 是一个面向多种应用场景的 AI 智能体平台。它基于 Claude Code SDK，让 AI 能够自主规划任务、调用工具、多轮迭代直至完成。与普通聊天机器人不同，Eido 的 Agent 可以读写文件、执行脚本、调用外部 API——像一个真正的数字员工。

**一句话定义**：人人都能定义、部署、使用的 AI 智能体工作平台。

---

## 二、核心创新：多租户用户沙箱

这是 Eido 区别于所有同类平台的**关键能力**——每个用户拥有一个独立的、物理隔离的 Docker 容器。

### 传统方案的痛点

| 痛点 | 说明 |
|------|------|
| 🤝 **多用户同进程** | 所有用户共享同一进程、同一文件系统、同一数据库，A 用户的文件可能被 B 用户的 Agent 读到 |
| 🔓 **安全隐患** | Agent 拥有 Bash/Read/Write 权限，同进程内几乎无法阻止跨用户数据泄露 |
| 💥 **资源抢占** | 一个用户的 Agent 跑满 CPU/内存，影响所有其他用户 |
| 📦 **技能冲突** | 不同用户的技能依赖冲突，难以隔离 |

### Eido 的方案：Per-User Container

```
用户 Alice ──→ [Gateway 鉴权 + 反代] ──→ eido-user-alice (独立容器)
                                              ├── 独立 SQLite 数据库
                                              ├── 独立工作区文件系统
                                              ├── 独立进程 & PID 命名空间
                                              └── CPU / 内存硬隔离

用户 Bob   ──→ [Gateway 鉴权 + 反代] ──→ eido-user-bob   (独立容器)
                                              └── ... 完全物理隔离
```

**演示视频第 3 步**展示了这一过程：用户登录后，Gateway 自动通过 Docker SDK 拉起专属容器——无需手动配置，对用户完全透明。

### 隔离矩阵

| 维度 | 隔离方式 |
|------|---------|
| 🗂️ 文件系统 | 每用户独立命名卷 `eido-user-<id>` |
| 🗄️ 数据库 | 每用户独立 `chat_sessions.db` |
| 🔧 进程 | 独立容器，cap_drop=ALL，no-new-privileges |
| 📊 资源 | CPU / 内存 / PID 硬限制 |
| 🔐 密钥 | `SKILL_SECRET__` 前缀统一管理 + SSE 输出脱敏 |
| 📖 技能库 | 只读 bind-mount，统一由 Gateway 管理 |

---

## 三、演示视频步骤详解

> 以下 5 个步骤完整展示了从零到一使用 Eido 的全过程。

### Step 1 · Gateway 启动

```bash
docker compose -f docker/docker-compose.yml --profile sandbox up -d
```

一条命令启动整个平台：
- **eido-gateway** 容器：内置 nginx + FastAPI，负责 CAS 鉴权、用户路由、沙箱编排
- **eido-net** 网络：Gateway 与所有 User 容器共享的 Docker bridge 网络
- 此时没有任何 User 容器——按需创建，零资源浪费

### Step 2 · 用户登录

浏览器访问 `http://<host>/ai-eido/`，支持两种鉴权模式：
- **CAS 单点登录**（推荐生产环境）：对接企业统一认证
- **开发模式**：AUTH_DISABLED=True，自动归入默认用户

登录后前端自动调用 `POST /api/v1/sandbox/warmup` 预热沙箱。

### Step 3 · 用户沙箱自动拉起（核心亮点）

这是 Eido 最独特的一步：

1. Gateway 的 `SandboxManager` 检测到用户首次请求
2. 通过 Docker SDK 创建 `eido-user-<safe_user_id>` 容器
3. 挂载该用户的命名卷（首次自动创建）
4. 只读挂载 `.claude/skills/` 技能库
5. 等待 `/health` 端点就绪后，开始反代业务请求

整个过程对用户**完全透明**——用户只需登录，剩下的全自动完成。

**容器生命周期**：
- 闲置超过 TTL（默认 15 分钟）→ 自动回收容器，**数据卷永久保留**
- 用户再次活跃 → 秒级重建容器，挂回原数据卷，会话和工作区无感恢复

### Step 4 · 技能编写与上传

Eido 提供三种方式定义技能，覆盖从零编写到一键导入的完整工作流。

#### 4.1 从 UI 创建技能

在「我的技能」页面点击**「新建技能」**，输入技能名称即可创建一个空白技能，随后自动进入 **SkillEditor** 编辑器。

#### 4.2 SkillEditor —— 所见即所得的技能编辑器

SkillEditor 是一个专业的 Markdown 编辑器，内置以下能力：

| 功能 | 说明 |
|------|------|
| 📝 **Markdown 编辑** | 支持完整 Markdown 语法（标题、列表、表格、代码块等） |
| 👁️ **实时预览** | 右侧面板同步渲染 Markdown，所见即所得 |
| 🔗 **@提及链接** | 输入 `@` 自动弹出工具和智能体列表，将工具/Agent 注入技能蓝图 |
| 🔲 **全屏模式** | 一键全屏编辑，充分利用屏幕空间 |
| 📋 **活动蓝图** | 底部栏实时展示当前技能引用了哪些工具和 Agent |

```markdown
---
name: 我的技能
description: 技能的简短描述
allowed_tools:
  - Read
  - Bash
  - Write
---

# 技能执行指引

在此用自然语言描述技能的执行逻辑……
```

**无需编写代码框架**，只需用 Markdown 描述：
- 技能名称和描述
- 允许使用的工具白名单（Read / Bash / Write / WebFetch 等）
- 用**自然语言**描述执行流程和输出格式
- 通过 `@工具名` 引用外部工具，`@Agent名` 注入推理人格

Agent 会自动理解 SKILL.md 中的指引，自主规划执行步骤。

#### 4.3 上传技能包

对于已有技能或从社区获取的技能包，Eido 支持**一键上传导入**：

- 在「我的技能」页面点击**「上传技能」**按钮
- 支持**拖拽上传**或点击选择文件
- 支持格式：`.zip`（技能包）、`.md`（单文件 SKILL.md）、`.skill`（技能定义文件）
- 单文件上限：**10 MB**
- 上传后自动解析并加载到技能库，即刻可用

```
┌─────────────────────────────────────────┐
│                                         │
│       📦 拖拽文件到此处上传              │
│                                         │
│     支持格式: .zip, .md, .skill         │
│     最大文件: 10 MB                     │
│                                         │
└─────────────────────────────────────────┘
```

#### 4.4 技能文件管理

进入技能详情页，切换到**「文件管理」**标签页，可以像操作本地文件系统一样管理技能目录：

| 操作 | 说明 |
|------|------|
| 📂 **浏览文件树** | 展开/折叠目录，查看技能内所有文件 |
| ✏️ **新建文件** | 直接在技能目录下创建脚本、配置等文件 |
| 📁 **新建文件夹** | 组织 `scripts/`、`references/` 等子目录 |
| 📄 **在线编辑** | 点击文件直接编辑内容，支持保存/取消 |
| 🗑️ **删除文件** | 删除文件或文件夹（SKILL.md 受保护不可删除） |
| 🔄 **刷新** | 同步最新的文件系统状态 |

> 💡 技能文件存储在 `.claude/skills/<技能名>/` 目录下，与 SKILL.md 同级。系统技能为只读，用户自定义技能可自由管理。

### Step 5 · 任务执行

用户在对话中输入任务，Agent 自动：
1. 读取技能指引，拆解任务为可执行步骤
2. 调用工具（Bash 执行脚本、Read 读取文件、Write 输出结果）
3. 多轮迭代直至完成
4. 通过 SSE 实时流式推送到前端——用户可看到 Agent 的完整思考过程

**多技能串联**：用户可以用 `@技能A` `@技能B` 串联多个技能，A 的输出自动作为 B 的输入——实现复杂的自动化工作流。

真实案例：`@sw-industry-report 获取行业行情` + `@email-master 发送给 damaohongtu@126.com`

---

## 四、技术架构一览

```
[用户浏览器]
     │
     ▼
[nginx :80] ─────────────────────────────────────────────
     │
     ▼
[eido-gateway]  ← CAS 鉴权 · SandboxManager · 反代
     │
     ├──→ eido-user-alice (Docker 容器)
     │       ├── SQLite (chat_sessions.db)
     │       ├── 工作区 (workspaces/<sid>/)
     │       └── 只读技能库 (.claude/skills/)
     │
     ├──→ eido-user-bob (Docker 容器)
     │       └── ... 完全隔离
     │
     └──→ eido-user-carol (Docker 容器)
             └── ... 完全隔离
```

**技术栈**：
- 前端：React 19 + TypeScript + Vite + TailwindCSS
- 后端：Python FastAPI + Claude Code SDK
- 基础设施：Docker + Docker Compose + Nginx
- 存储：SQLite（per-user）+ 命名卷
- AI 引擎：Claude Code SDK（兼容 DeepSeek / MiniMax / Anthropic）

---

## 五、为什么选择 Eido？

### 🚀 零代码扩展
用 Markdown 写 SKILL.md 即可定义新技能，无需修改任何后端代码。Agent 自动理解自然语言指引。

### 🔐 企业级隔离
每个用户独立容器——进程、文件系统、数据库物理隔离。支持 cap_drop、no-new-privileges、CPU/内存/PID 硬限制。

### 🔑 密钥安全
三 道防线：集中管理 + 运行时注入 + 输出脱敏。密钥永不出现在技能目录和 Agent 输出中。

### 📦 一键部署
```bash
docker compose -f docker/docker-compose.yml --profile sandbox up -d
```
支持 amd64 / arm64 多架构，单租户与多租户一键切换。

### 🔄 按需伸缩
User 容器按需创建，闲置自动回收。百级用户只需 Gateway 常驻，资源利用率极高。

### 🌐 多 LLM 兼容
兼容 Anthropic API 标准的任意服务：DeepSeek、MiniMax、Claude 等，灵活切换。

---

## 六、快速上手

```bash
# 1. 克隆仓库
git clone https://github.com/damaohongtu/eido-ai.git
cd eido-ai

# 2. 配置环境变量
cp docker/.env.example docker/.env
# 编辑 docker/.env，填入 LLM 凭据和 Gateway Secret

# 3. 一键启动（沙箱多用户模式）
docker compose -f docker/docker-compose.yml --profile sandbox up -d

# 4. 浏览器访问
open http://localhost/ai-eido/
```

详细部署文档：[quick-start.md](../quick-start.md) | 架构文档：[architecture.md](architecture.md)

---

## 七、适用场景

| 场景 | 说明 |
|------|------|
| 📊 **金融研报自动化** | 自动获取行情数据 → 生成分析报告 → 邮件发送 |
| 📧 **智能邮件助手** | 邮件收发、内容分类、自动回复 |
| 📄 **文档智能处理** | PDF 解析、文档摘要、格式转换 |
| 🔍 **信息聚合检索** | 多源搜索、数据整合、报告生成 |
| ⏰ **定时任务调度** | 定时执行技能工作流，结果推送到邮箱 |

---

## 八、开源与社区

- **GitHub**：[github.com/damaohongtu/eido-ai](https://github.com/damaohongtu/eido-ai)
- **License**：MIT
- **Docker Hub**：[damaohongtu/eido](https://hub.docker.com/r/damaohongtu/eido)

> 🎬 完整操作演示请观看配套视频：Gateway 启动 → 登录 → 沙箱拉起 → 技能编写与上传 → 任务执行

---

*Eido —— 让每个人都能拥有自己的 AI 智能体工厂*
