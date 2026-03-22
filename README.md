# Eido Eido

面向投资研究场景的 AI 智能体平台。用户通过 `@技能` 驱动 Claude Code SDK 自主规划并执行复杂分析任务，支持多技能串行流水线和多轮对话。

---

## 架构概览

```
Eido/
├── frontend/               # React 19 + TypeScript 前端
├── backend/                # Python FastAPI 后端
├── .claude/
│   └── skills/             # 技能定义（SKILL.md 文件）
├── nginx.conf              # 生产环境 Nginx 配置
└── scripts/                # 部署辅助脚本
```

### 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19 · TypeScript · Vite · Tailwind CSS · Ant Design |
| 后端 | FastAPI · Uvicorn · Pydantic |
| AI 执行引擎 | Claude Code SDK (`claude_agent_sdk`) |
| 普通对话 | DeepSeek Chat (OpenAI 兼容协议) |
| 运行环境 | conda `eido` |

---

## 核心概念

### 技能（Skill）

技能是存放在 `.claude/skills/<skill-name>/SKILL.md` 的 Markdown 文件，YAML frontmatter 声明元数据，正文为自然语言的执行指引：

```yaml
---
name: A股财报点评
description: 分析A股上市公司财报...
allowed_tools:
  - Read
  - Glob
  - Bash
  - WebSearch
  - WebFetch
---

## 技能内容...
```

执行时，`claude_agent_sdk` 读取 SKILL.md 全文作为 prompt，结合完整的对话历史，自主规划并执行分析。

### 多技能流水线

在对话中同时 `@` 提及多个技能，系统按文本出现顺序串行执行，前一步输出自动作为下一步的上下文：

```
@文档解析 将 /path/to/report.pdf 转为 markdown，
然后 @A股财报点评 对上述文档进行点评
```

---

## 快速启动

### 前置要求

- conda 环境 `eido`（Python 3.11+）
- Node.js 18+
- 配置 `backend/.env`（参见 `backend/.env.example`）

### 后端

```bash
cd backend
conda activate eido
pip install -r requirements.txt
python run.py
# 服务启动在 http://localhost:8000
# API 文档: http://localhost:8000/api/v1/docs
```

```shell
curl -X POST "http://localhost:8000/api/v1/chat/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "伊朗最新消息"}
    ]
  }'
```

### 前端

```bash
cd frontend
npm install
npm run dev
# 服务启动在 http://localhost:5173
```

### MCP 服务（按需启动）

```bash
conda activate eido

# 财务数据服务
cd mcp_servers/fin_data
python ratio_server.py

# 搜索服务
cd mcp_servers/search
python server.py
```

---

## 生产部署

使用 Nginx 反向代理，统一 `/ai-eido` 前缀：

- 前端：`http://your-domain/ai-eido`
- 后端 API：`http://your-domain/ai-eido/api/`

```bash
# 构建前端
cd frontend && npm run build

# 复制 Nginx 配置并重载
sudo cp nginx.conf /etc/nginx/sites-available/eido
sudo nginx -s reload
```

---

## 新增技能

在 `.claude/skills/` 下创建新目录并添加 `SKILL.md`：

```bash
mkdir .claude/skills/my-skill
cat > .claude/skills/my-skill/SKILL.md << 'EOF'
---
name: 我的技能
description: 技能的简短描述，显示在选择菜单中
allowed_tools:
  - Read
  - Bash
---

# 技能执行指引

在此用自然语言描述技能的执行逻辑、输入输出格式等。
EOF
```

重启后端后技能自动加载，无需数据库操作。`allowed_tools` 完整列表参见 [Claude Code SDK 文档](https://docs.anthropic.com/claude-code)。

---

## 目录说明

| 路径 | 说明 |
|------|------|
| `backend/app/services/claude_skill_service.py` | 技能加载与执行核心服务 |
| `backend/app/api/v1/endpoints/chat.py` | 聊天与技能执行 API |
| `backend/app/api/v1/endpoints/skills.py` | 技能列表 API |
| `frontend/components/ChatArea.tsx` | 聊天区域 |
| `frontend/services/api.ts` | 前端 API 调用与 SSE 流处理 |
| `.claude/skills/` | 技能定义目录 |
