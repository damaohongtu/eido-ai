---
name: scheduled-tasks
description: 创建、查看、修改、删除、立即运行定时任务（定时对话/技能/脚本）。当用户说“定时任务/计划任务/每天/每周/每隔…自动执行/到点提醒/自动运行/取消定时”时使用。
---

# 定时任务（Eido 调度器）

在 Eido 对话里以当前登录用户身份管理定时任务。到点后调度器会新建一个名为
`[自动任务] <任务名>` 的对话并执行任务内容，执行过程可在“会话”列表里查看。

## 前置条件

必须运行在 Eido 沙箱的 Agent 模式中（脚本读取沙箱自动注入的
`EIDO_API_URL` / `EIDO_USER_ID` / `EIDO_USER_TOKEN_SECRET` 并在每次请求前
现场签发 280 秒有效的用户令牌）。问答模式、本地终端或缺少这些变量时会报
“缺少身份凭据”。

脚本位置（eido 沙箱内）：

```bash
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py list
```

若该路径不存在（例如用户私有版本），先 `ls .claude/skills/*/scripts/eido_task.py`
找到实际目录，再把下面示例里的绝对路径替换掉。所有操作都用脚本完成，
**不要手写 curl + HMAC 签名**。

## 命令

| 命令 | 作用 |
|------|------|
| `list [--json] [--enabled/--disabled]` | 列出当前用户的定时任务 |
| `show <task_id>` | 查看任务详情 |
| `create --name ... --type ... --schedule ...` | 创建任务 |
| `update <task_id> [--name] [--schedule] [--type] [--params] [--enabled/--disabled]` | 修改任务 |
| `delete <task_id> --yes` | 删除任务（不可恢复） |
| `run <task_id>` | 立即执行一次（不影响原定计划） |

## 调度格式（重要）

`--schedule` 只接受两种写法：

1. `interval:<秒>` — 固定间隔，从创建/修改时刻起算（例如 `interval:1800` 表示每 30 分钟）。
2. 5 段 cron：`分 时 日 月 周`。

注意：

- **调度按 UTC 解释**（服务端容器时区）。用户说的时间若是北京时间，必须加
  `--schedule-cst`，脚本会做 -8 小时换算；只有用户明确说 UTC 时才不加。
- 换算只支持“时”为固定值（可逗号分隔，如 `9,18`）；含 `*`、`/`、`-` 的小时
  或换算后跨 UTC 零点且“日/月/周”受限时，脚本会报错——此时直接向用户要 UTC 表达式。
- **周字段是 APScheduler 语义**：`0`=周一 … `6`=周日，**不是** Linux crontab 的
  `0`=周日。建议一律用 `mon/tue/wed/thu/fri/sat/sun` 避免歧义。
- 到点时间以调度器为准；创建后向用户报告“北京时间 + UTC”两种表述。

示例：

```bash
# 每天北京时间 9:00
--schedule-cst "0 9 * * *"      # 存为 0 1 * * *

# 每周一北京时间 10:30（每周一 02:30 UTC）
--schedule-cst "30 10 * * mon"

# 每 30 分钟
--schedule "interval:1800"
```

## 任务类型与参数

| 类型 | 参数 | 说明 |
|------|------|------|
| `chat` | `--prompt "完整指令"` | 最常见。到点新建对话，prompt 作为用户消息执行（默认 Agent 模式，可调用工具、联网、读写工作区） |
| `skill` | `--skill-id <技能目录名>` + 可选 `--extra-prompt` | 到点让 Agent 执行指定技能 |
| `script` | `--script-path <沙箱内路径>` + 可选 `--arg 值`（可重复） | 到点直接在沙箱内运行脚本 |

`--params '<JSON对象>'` 或 `--params-file <路径>` 可直接传原始参数（需符合上述结构，例如
`{"messages":[{"role":"user","content":"..."}]}`），不能与上面几种参数同时使用。

`chat` 任务的 prompt 必须写成**可独立执行的完整指令**——到点执行时没有当前对话的上下文，
也不会自动带上“用户是谁”等信息；需要联网就明确写“先联网检索”。

## 工作流程（必须遵守）

1. 只有用户明确要求“定时/定期/每天/到点自动执行”等才使用本技能。
2. 先收集：任务名、执行时间（确认是否北京时间）、执行内容、类型；缺什么问什么。
3. 创建/修改/删除/立即运行前，把“名称、时间（北京时间 + UTC）、执行内容”告知用户并征得
   同意；用户当轮已明确要求同一件事时可直接执行。
4. 删除必须带 `--yes`，且仅在用户确认后执行。
5. 完成后用返回的任务 ID + `list` 结果向用户报告；不要只说“已创建”。

## 示例

```bash
# 查看
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py list

# 每天北京时间 9:00 生成行业简报
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py create \
  --name "每日行业简报" --type chat --schedule-cst "0 9 * * *" \
  --prompt "先联网检索今天的行业新闻，挑 5 条最重要的，输出标题、要点和来源链接。"

# 每 30 分钟检查一次工作区里的 TODO
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py create \
  --name "TODO 巡检" --type chat --schedule "interval:1800" \
  --prompt "读取工作区的 TODO.md，列出未完成项并按优先级排序。"

# 暂停 / 恢复 / 删除
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py update <task_id> --disabled
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py update <task_id> --enabled
python3 /workspace/.claude/skills/system/scheduled-tasks/scripts/eido_task.py delete <task_id> --yes
```

## 安全与排错

- 不要回显、打印或写文件保存 `EIDO_USER_TOKEN` / `EIDO_USER_TOKEN_SECRET`；脚本只在内存里
  生成令牌并放进请求头。
- `HTTP 401 未登录`：说明不在沙箱 Agent 模式或令牌被拒；请用户从“对话”页的 Agent 模式重试。
- `HTTP 503 任务存储未初始化`：网关侧未启用定时任务，需管理员处理。
- `无法连接`：检查 `EIDO_API_URL` 是否存在且可访问。
- 不要为了“让任务跑起来”而缩短间隔（如 `interval:60`）做测试；验证创建用 `list` 即可，
  真要立即执行用 `run`，用完记得删除测试任务。
