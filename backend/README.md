# Eido Backend

基于 FastAPI 的后端服务，提供技能执行、普通对话和技能管理 API。

---

## 目录结构

```
backend/
├── app/
│   ├── main.py                     # FastAPI 应用入口、启动事件
│   ├── api/v1/
│   │   ├── api.py                  # 路由注册
│   │   └── endpoints/
│   │       ├── chat.py             # POST /chat/chat — 对话与技能执行
│   │       ├── skills.py           # GET  /skills/   — 技能列表与详情
│   │       ├── mcp.py              # MCP 工具注册相关
│   │       └── workflow.py         # 健康检查
│   ├── core/
│   │   └── config.py               # Pydantic Settings（读取 .env）
│   ├── schemas/
│   │   └── chat.py                 # 请求/响应 Pydantic 模型
│   └── services/
│       ├── claude_skill_service.py # 技能加载 + claude_agent_sdk 执行
│       ├── llm_service.py          # DeepSeek 普通对话
│       └── mcp_registry.py         # MCP 工具注册表
├── alembic/                        # 数据库迁移（保留备用）
├── scripts/                        # 辅助脚本
├── requirements.txt
├── run.py                          # 开发启动入口
└── .env.example                    # 环境变量模板
```

---

## 快速启动

```bash
conda activate eido
cd backend

# 首次安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 DEEPSEEK_API_KEY

# 启动开发服务器（热重载）
python run.py
```

服务启动后：
- API 文档（Swagger）：http://localhost:8000/api/v1/docs
- 健康检查：http://localhost:8000/api/v1/workflow/health

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | 必填 |
| `DEEPSEEK_MODEL` | 使用的模型 | `deepseek-chat` |
| `SKILLS_DIR` | 技能目录路径 | `{workspace}/.claude/skills` |
| `WORKSPACE_ROOT` | 工作区根路径（传给 claude_agent_sdk） | 自动推断 |
| `LOG_LEVEL` | 日志级别 | `INFO` |

---

## API 说明

### POST `/api/v1/chat/chat`

统一对话入口，根据 `skill_id` 决定执行模式。

**携带 `skill_id`（技能执行模式）：**
```json
{
  "messages": [
    {"role": "user", "content": "@A股财报点评 分析中望软件2024年报"}
  ],
  "skill_id": "financial-report-analyst",
  "context": "（可选）上一步技能的输出，用于多技能流水线",
  "stream": true
}
```

响应为 SSE 流，事件类型：

| type | 说明 |
|------|------|
| `thinking` | 执行状态提示 |
| `workflow_start` | 技能开始执行 |
| `content` | 正文增量内容 |
| `tool_use` | 工具调用信息 |
| `workflow_complete` | 执行完成 |
| `error` | 执行错误 |

**不携带 `skill_id`（普通对话模式）：**
```json
{
  "messages": [{"role": "user", "content": "你好"}],
  "stream": true,
  "temperature": 0.7
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

## 技能服务（ClaudeSkillService）

核心服务位于 `app/services/claude_skill_service.py`：

- **`scan_skills()`** — 扫描 `SKILLS_DIR`，解析每个子目录的 `SKILL.md` frontmatter
- **`get_skill(skill_id)`** — 按目录名加载单个技能
- **`execute_stream(skill_id, messages, context)`** — 构建 prompt 并调用 `claude_agent_sdk.query()`，以 SSE 格式流式返回

Prompt 结构：
```
{技能 SKILL.md 全文}

---

## 对话历史

**用户**: ...
**助手**: ...（较旧的截断至 300 字符）
**用户**: 当前请求（完整保留）

[## 上一步执行结果  ← 仅多技能流水线时附加]
```
