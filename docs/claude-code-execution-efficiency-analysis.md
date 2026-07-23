# Claude Code 执行效率分析与优化报告

> 分析与实施日期：2026-07-23  
> 范围：Eido 后端 Claude Code harness、Claude Agent SDK、技能发现、会话续接、提示词、进程生命周期、依赖与可观测性

## 1. 结论摘要

本次效率问题不是单一的“模型慢”，而是应用层同时存在四类重复开销：

1. 后端每轮使用一次性 `query()`，即使传入 `resume`，仍要重新启动 Claude Code 子进程并初始化工具与文件系统配置。
2. Eido 手工扫描技能、把完整技能索引拼入首轮提示词，再要求模型调用 `Read` 重读 `SKILL.md`，绕过了新版 Agent SDK 的原生 Skills 渐进式加载。
3. 技能列表接口在页面初始化时会被密集调用，每次都遍历目录、读取并解析所有 `SKILL.md`。
4. 已 `resume` 的每一轮仍重复注入项目说明和共享文件列表；项目说明上限为 20,000 字符，这部分已经存在于 Claude 原生会话中。

本次已完成版本升级和代码优化：

- 本机 Claude Code：`2.1.90 → 2.1.218`。
- Conda `eido` 环境 Claude Agent SDK：`0.1.44 → 0.2.126`。
- Docker 构建统一固定 Claude Code `2.1.218`，Node.js `20 → 22`；新版 CLI 的 npm 包要求 Node.js 22 及以上。
- 同一 Eido session 改用长生命周期 `ClaudeSDKClient`，在短期身份令牌有效期内复用 Claude Code 子进程；进程回收、项目切换和异常重建均有兜底。
- session 可见技能映射到原生 `.claude/skills/<id>`，使用 `skills="all"` 和 `Skill` 工具按需加载正文。
- 技能元数据增加 TTL 缓存、stat 指纹校验和 CRUD 主动失效。
- `resume` 提示词不再重复项目上下文；原生 session 失效时才用持久化历史和最新项目上下文重建。
- 禁用未被消费的 partial-message 流；限定实际可见工具集合；关闭跨租户的 Claude auto-memory。
- 日志新增 warm/cold、连接耗时、首消息耗时、提示词字符数、技能数、token/cache token、terminal reason 和 API 状态。
- 修复升级后的认证回归：`backend/.env` 中的 provider 配置现在由 `Settings`
  显式传给 SDK 内置 CLI；缺少非交互式凭据时在启动模型前返回可操作的中文错误，
  不再透传具有误导性的 `Please run /login`。

## 2. 基线与证据

### 2.1 版本基线

| 组件 | 优化前 | 优化后 | 说明 |
|---|---:|---:|---|
| 本机 Claude Code | 2.1.90 | 2.1.218 | 已执行官方 updater |
| Python Agent SDK | 0.1.44 | 0.2.126 | 在 Conda `eido` 环境安装并验证 |
| SDK 内置 Claude CLI | 旧版随 0.1.44 | 2.1.218 | 0.2.126 changelog 明确记录 |
| Docker Node.js | 20.x | 22.x | 满足 Claude Code 2.1.218 npm `engines` |
| Docker Claude Code | 浮动 latest | 固定 2.1.218 | 构建可复现 |

官方资料：

- [Claude Agent SDK Python changelog](https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md)
- [Claude Agent SDK Python reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Agent Skills in the SDK](https://code.claude.com/docs/en/agent-sdk/skills)
- [Use Claude Code features in the SDK](https://code.claude.com/docs/en/agent-sdk/claude-code-features)
- [Claude Code npm package](https://www.npmjs.com/package/@anthropic-ai/claude-code)

### 2.2 生产日志观察

对 `backend/logs/app.log` 的现有记录做只读统计：

| 指标 | 观察值 |
|---|---:|
| Claude 执行次数 | 9 |
| 技能全量扫描日志 | 277 次 |
| 同一秒技能扫描峰值 | 13 次 |
| 明确的手工 `Read .../SKILL.md` | 2 次 |
| 首轮提示词样本 | 3,135–3,229 字符 |
| 最长任务样本 | 86 轮 / 971.6 秒 / 约 $2.5208 |

277 次技能扫描远高于 9 次 Claude 执行，说明主要重复扫描来自技能列表/界面请求，而不只是模型执行。日志还显示：会话已成功 `resume` 后，Claude 仍再次调用 `Read` 加载 `scheduled-tasks/SKILL.md`；这正是旧版手工技能路由造成的重复模型轮次。

## 3. 原执行链路与瓶颈

### 3.1 优化前

```text
HTTP chat request
  → 服务端加载最近 80 条消息
  → 每次请求扫描 system/user 技能目录
  → 首轮拼接完整技能索引和绝对路径
  → query() 启动新的 Claude Code 进程
  → 模型判断技能
  → 模型调用 Read 再读 SKILL.md
  → 执行工具
  → ResultMessage 保存 claude_session_id

后续轮次
  → 再次 query() 启动进程
  → resume 原生 transcript
  → 再次注入项目上下文
  → 必要时再次 Read SKILL.md
```

### 3.2 瓶颈分级

| 优先级 | 瓶颈 | 直接影响 | 根因 | 本次处理 |
|---|---|---|---|---|
| P0 | 每轮启动一次性 SDK/CLI | 增加首 token 延迟、重复初始化 | 对交互会话使用了适合一次性任务的 `query()` | 改为 session 级 `ClaudeSDKClient` 池 |
| P0 | 手工技能索引 + 模型 `Read` | 增加提示词、模型判断和工具轮次 | 未使用新版原生 Skills | 原生 `skills="all"` + session 技能视图 |
| P0 | resume 重复项目上下文 | 最坏每轮重复 20k+ 字符 | 未区分“冷重建”和“正常续接” | 正常续接只发送本轮输入 |
| P1 | 技能接口重复全量解析 | 文件 I/O、YAML 解析、日志噪声 | 无缓存/失效协议 | TTL + 指纹 + CRUD 失效 |
| P1 | 工具面过宽、partial 事件未消费 | system/tool schema 变大、IPC 浪费 | `allowed_tools` 不等于隐藏工具；partial 开启但转换器忽略 | 使用 `tools` 限定集合并关闭 partial |
| P1 | 版本与运行时漂移 | 新特性不可用、容器构建不稳定 | CLI 浮动安装、Node 20 与最新 CLI 不兼容 | 精确锁定版本并升 Node 22 |
| P1 | 缺少 warm/TTFT/token 指标 | 无法证明优化或定位供应商延迟 | 只记录总时长、费用、轮次 | 增加结构化运行日志 |
| P2 | 长任务缺少分技能预算 | 可能出现 80+ 轮长循环 | 全局硬限制会误伤复杂技能 | 本次先补 `terminal_reason`/usage；建议后续按技能设置预算 |

## 4. 已实施设计

### 4.1 原生 Skills 与多租户隔离

新版 SDK 会在启动时发现技能元数据，只有技能命中时才加载完整正文。Eido 的物理目录是：

```text
SKILLS_DIR/system/<id>/SKILL.md
SKILLS_DIR/users/<uid>/<id>/SKILL.md
```

Claude Code 原生布局要求：

```text
<cwd>/.claude/skills/<id>/SKILL.md
```

因此每个 session 工作区生成一层只包含当前用户可见技能的符号链接视图：

```text
.eido/workspaces/<session>/.claude/skills/<id>
  → SKILLS_DIR/system/<id>
  或 SKILLS_DIR/users/<uid>/<id>
```

映射仍遵循“用户私有同 ID 覆盖系统技能”。manifest 只管理 Eido 自己创建的符号链接，不删除普通目录。相同技能 revision 的后续轮次直接复用视图，不重复改写 manifest 或检查每个链接。

无 `session_id` 的历史后台任务暂时保留旧式绝对路径索引，以避免改变其全局 workspace 行为。

### 4.2 ClaudeSDKClient 连接池

连接池键为 `(user_id, session_id)`，签名包含：

- session cwd；
- Project ID 与 `context_revision`；
- 当前用户技能 revision。

签名不变时复用已连接的 Claude Code 子进程。以下情况会驱逐：

- Project 切换、删除或 context revision 更新；
- 技能新增、编辑、删除或外部文件指纹变化；
- session 删除；
- CLI/SDK 异常或未收到完整 `ResultMessage`；
- 空闲超过 15 分钟；
- 达到短期 `EIDO_USER_TOKEN` 到期前 30 秒；
- 连接池超过 32 个，淘汰最久未使用的空闲连接；
- 应用 shutdown。

如果冷启动 `resume` 在产生本轮输出前失败，会清理旧 SID，并使用 Eido 持久化历史、最新 Project 上下文和原生技能重新建会话。已经产生工具/模型输出后不自动重放，避免重复副作用。

### 4.3 提示词去重

正常 resume 现在只包含：

```text
## 用户最新请求
<本轮输入>

可选：多技能流水线的上一步结果（最多 4,000 字符）
```

Project 说明、共享文件清单和历史只在新会话或失效重建时注入。Project revision 改变时数据库会先清空 provider SID，因此不会错误沿用旧项目上下文。

### 4.4 缓存策略

技能缓存分两层：

1. 5 秒内直接返回解析后的 `SkillMeta`。
2. TTL 到期后只遍历目录并比较 `(路径, mtime_ns, size)`；指纹未变时不读取或解析 Markdown/YAML。

应用内技能 CRUD 会主动失效相关用户缓存；系统技能变化失效所有用户视图。外部直接修改文件最多在 5 秒后被发现。

### 4.5 安全与上下文卫生

- `setting_sources` 只启用 session 的 project source，不加载用户级配置。
- 注入 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`，防止多租户进程读取宿主机 `~/.claude/projects/.../memory`，同时减少冷启动 system prompt 的无关动态内容。
- 原生 Skills 只映射该用户可见的 system/private 合并结果。
- session 并发仍由原有 single-flight guard 控制。

## 5. 微基准结果

以下结果为本机 Conda `eido` 环境、12 个可见技能下的确定性应用层微基准，不包含模型网络延迟：

| 项目 | 优化前路径 | 优化后路径 | 变化 |
|---|---:|---:|---:|
| 首轮提示词 | 3,160 字符 | 716 字符 | -77.3% |
| 含 20k Project 说明的重复轮次 | 22,326 字符 | 13 字符 | -99.9% |
| 200 次技能列表解析 | 485.24 ms | 0.03 ms | >99.9% |

未给出“模型响应时间降低 X%”的虚假结论。真实收益还取决于模型供应商、网络、任务是否命中技能和工具执行时间。长连接对首消息耗时的收益应通过新增的 `warm=true/false` 日志做线上 A/B 统计。

## 6. 新增可观测指标

每轮会输出两类结构化日志：

```text
[ClaudeRun] mode=resume warm=true connect_ms=0.0 prompt_chars=... skills=... tools=...
[ClaudeRun] first_message_ms=... warm=true session=...
[Result/OK] ... terminal=completed api_status=- input=... cache_read=... cache_create=... output=...
```

建议按日聚合：

- warm 命中率；
- cold/warm 的 P50、P95 `first_message_ms`；
- fresh/resume 的 `prompt_chars`；
- 每任务 `num_turns`、`duration_ms`、`total_cost_usd`；
- `cache_read_input_tokens / input_tokens`；
- `terminal_reason != completed` 比例；
- resume 重建次数；
- 每技能的工具失败率和任务完成率。

## 7. 兼容性、风险与回滚

### 7.0 Agent SDK 认证边界

新版 Agent SDK 会以 `CLAUDE_CODE_ENTRYPOINT=sdk-py` 启动自带 CLI。即使全局
`claude auth status` 显示 Claude.ai OAuth 已登录，该登录也不能作为 Eido 这类
第三方 Agent SDK 应用的模型凭据。官方推荐 Claude Console 的
`ANTHROPIC_API_KEY`，也支持文档列出的云平台认证；项目既有的 Anthropic 兼容
网关仍可通过 `ANTHROPIC_BASE_URL` 配合 API Key/Auth Token 使用。

此前 `backend/.env` 虽有 provider 配置，但 `Settings` 未声明这些字段，配置被
Pydantic 作为 extra 忽略，且 `.env` 不会自动导出到 `os.environ`，导致 SDK 子进程
看到所有认证变量均为空。现在凭据使用 `SecretStr` 保存，并仅通过
`ClaudeAgentOptions.env` 注入；日志只记录认证类型与 provider，不输出密钥。

### 7.1 已验证

- Conda `eido`：Claude Agent SDK 0.2.126，原生 `skills` 选项存在。
- `pip check`：无破损依赖。
- 后端测试：121 passed，2 skipped。
- 新增技能缓存/映射/提示词/连接池测试：5 passed。
- Python 语法检查与 Ruff `E9,F`：通过。

升级过程中还修复了完整锁文件中的既有冲突：`fastapi 0.115.0` 与 `sse-starlette 3.2.0 / starlette 0.51.0` 无法同时满足约束。现对齐为 `fastapi 0.120.1 + starlette 0.49.3 + python-multipart 0.0.22`，与主 requirements 一致。

### 7.2 风险

- 本地文件系统必须支持目录符号链接；失败时自动回退到旧式技能索引。
- Agent SDK 官方说明：SDK 模式下 `SKILL.md` 的 `allowed-tools` 不直接限制工具权限；Eido 仍在顶层 options 统一审批工具。
- 长连接保留子进程会增加常驻内存，因此设置 32 个上限、空闲 TTL 和 token TTL 上限。
- 直接在文件系统外部修改技能存在最多 5 秒可见延迟；通过 API 修改会立即失效。
- 真实模型端到端测试会产生费用，本次自动测试未发送真实模型请求。

### 7.3 回滚点

如果原生 Skills 在特定部署文件系统上不可用，可只回滚 session 技能映射和 `skills="all"`，保留以下低风险收益：

- Agent SDK / Claude Code 版本升级；
- `ClaudeSDKClient` 长连接；
- resume 项目上下文去重；
- 技能元数据缓存；
- 日志与 auto-memory 隔离。

## 8. 后续建议

1. 运行 3–7 天线上观测，按 warm/cold 比较首消息 P50/P95，而不是只看整轮时长。
2. 为高成本技能定义 `max_turns`、预算、超时和可重试阶段；不要用一个全局硬限制覆盖所有技能。
3. 把技能执行结果分为“可重试读操作”和“不可自动重放副作用”，进一步细化 resume 故障恢复。
4. 对高频 API 增加 Prometheus 指标，减少依赖日志文本聚合。
5. 当任务明确指定一个技能时，将 `skills="all"` 收窄为该技能及其依赖，继续降低元数据上下文。
6. 定期自动核对 PyPI、npm 最新版与 changelog；生产镜像继续使用精确版本，由依赖更新 PR 显式升级，而不是构建时浮动 latest。
