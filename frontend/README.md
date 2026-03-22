# Eido Frontend

基于 React 19 + TypeScript 的前端应用。

---

## 技术栈

- React 19 · TypeScript · Vite
- Tailwind CSS · Ant Design
- React Markdown + remark-gfm
- Mermaid（工作流图渲染）

---

## 目录结构

```
frontend/
├── components/
│   ├── ChatArea.tsx        # 聊天区域（@提及、多技能流水线、多轮对话）
│   ├── Sidebar.tsx         # 左侧导航 + 历史会话列表
│   ├── HomeView.tsx        # 首页技能卡片
│   ├── SkillManager.tsx    # 技能浏览页（只读）
│   ├── ReferenceArea.tsx   # 右侧引用/参考面板
│   └── Mermaid.tsx         # Mermaid 图表组件
├── services/
│   └── api.ts              # 后端 API 调用 + SSE 流处理
├── App.tsx                 # 主应用、路由、会话状态管理
├── types.ts                # TypeScript 类型定义
├── constants.tsx           # 系统工具/Agent 常量
├── config.ts               # 静态资源路径配置
├── index.css               # 全局样式
└── index.html
```

---

## 本地开发

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173
```

构建生产版本：

```bash
npm run build
# 输出到 dist/
```

---

## 关键交互逻辑

### @技能 提及

在输入框键入 `@` 即触发技能选择菜单（从后端 `/api/v1/skills/` 加载）：

- 上下箭头或鼠标选择技能
- `Enter` / `Tab` 确认插入，格式为 `` `@技能名` ``
- `Esc` 关闭菜单

### 多技能流水线

单条消息中按文本顺序提及多个技能时，系统串行执行，每个技能独立输出一条 assistant 消息，前一步的输出通过 `context` 字段传递给下一步。

### 消息发送

- `Enter` — 发送消息
- `Shift + Enter` — 换行

### 会话标题

首条用户消息内容（剥离 @技能 标记后的前 24 字符）自动作为会话标题显示在历史记录中。

---

## 环境变量

在 `frontend/` 目录下创建 `.env.local`：

```bash
# 仅开发环境需要，生产环境通过 Nginx 代理
VITE_BACKEND_URL=http://localhost:8000
```

生产环境默认通过 `/ai-eido/api` 路径访问后端（见 `constants.tsx`）。
