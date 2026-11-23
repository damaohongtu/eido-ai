#!/usr/bin/env python3
"""Eido 定时任务命令行（沙箱内以当前登录用户身份操作）。

依赖：仅 Python 标准库。
身份：读取沙箱注入的 EIDO_USER_ID + EIDO_USER_TOKEN_SECRET，每次请求现场签发
      280 秒有效的 X-Eido-User-Token；令牌只出现在请求头里，不打印、不落盘。
接口：EIDO_API_URL（例如 http://eido-gateway/ai-eido）+ /api/v1/tasks/。

调度：
  interval:<秒>       固定间隔，从创建/修改时刻起算
  5 段 cron           分 时 日 月 周；按 UTC 解释（--schedule-cst 时按北京时间换算）
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

TASKS_PATH = "/api/v1/tasks/"
TOKEN_TTL_SEC = 280
HTTP_TIMEOUT_SEC = 20

EXIT_API_ERROR = 1
EXIT_USAGE_ERROR = 2

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class CliError(Exception):
    """可预期的使用/环境/接口错误。"""


# --------------------------------------------------------------------- #
#  身份与 HTTP                                                           #
# --------------------------------------------------------------------- #


def mint_user_token(user_id: str, secret: str) -> str:
    """与后端 app/core/user_token.py 完全一致的令牌格式。"""
    if not user_id or ":" in user_id:
        raise CliError("EIDO_USER_ID 非法，无法签发令牌")
    expiry = int(time.time()) + TOKEN_TTL_SEC
    payload = f"{user_id}:{expiry}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def auth_headers() -> dict[str, str]:
    secret = (os.environ.get("EIDO_USER_TOKEN_SECRET") or "").strip()
    user_id = (os.environ.get("EIDO_USER_ID") or "").strip()
    if secret and user_id:
        return {"X-Eido-User-Token": mint_user_token(user_id, secret)}
    token = (os.environ.get("EIDO_USER_TOKEN") or "").strip()
    if token:
        return {"X-Eido-User-Token": token}
    raise CliError(
        "缺少身份凭据：请在 Eido 对话的 Agent 模式中运行本脚本"
        "（需要 EIDO_USER_ID 与 EIDO_USER_TOKEN_SECRET，或 EIDO_USER_TOKEN）"
    )


def api_base() -> str:
    base = (os.environ.get("EIDO_API_URL") or "").strip().rstrip("/")
    if not base:
        raise CliError("缺少环境变量 EIDO_API_URL（Eido 沙箱内会自动注入）")
    return base


def _error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return " ".join(str(text).split())[:300]


def request(method: str, path: str, body: dict | None = None) -> Any:
    url = f"{api_base()}{path}"
    data = None
    headers = {"Accept": "application/json", **auth_headers()}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise CliError(f"无法连接定时任务接口 {url}：{exc.reason}") from exc

    try:
        payload: Any = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        payload = raw

    if status in (301, 302, 307, 308):
        raise CliError(
            f"接口返回 HTTP {status} 重定向，请检查 EIDO_API_URL 是否包含正确的前缀（如 /ai-eido）"
        )
    if status in (401, 403):
        raise CliError(
            f"未登录或令牌被拒（HTTP {status}）：{_error_detail(payload)}；"
            "请确认在 Eido 沙箱的 Agent 模式中运行"
        )
    if status >= 400:
        raise CliError(f"接口返回 HTTP {status}：{_error_detail(payload)}")
    return payload


# --------------------------------------------------------------------- #
#  调度换算                                                              #
# --------------------------------------------------------------------- #


def _cst_hour_to_utc(hour_field: str) -> tuple[str, bool]:
    shifted: list[str] = []
    crosses_midnight = False
    for item in hour_field.split(","):
        if not (item.isdigit() and 0 <= int(item) <= 23):
            raise CliError(
                "北京时间换算要求“时”字段为固定值（可逗号分隔，如 9,18）；"
                "含 *、/、- 时请直接提供 UTC cron"
            )
        hour = int(item) - 8
        if hour < 0:
            hour += 24
            crosses_midnight = True
        shifted.append(str(hour))
    return ",".join(shifted), crosses_midnight


def normalize_schedule(expr: str, *, cst: bool) -> str:
    value = " ".join((expr or "").split())
    if not value:
        raise CliError("调度表达式不能为空")
    if value.startswith("interval:"):
        seconds = value.split(":", 1)[1].strip()
        if not (seconds.isdigit() and int(seconds) > 0):
            raise CliError("interval 格式应为 interval:<正整数秒>，例如 interval:1800")
        return f"interval:{int(seconds)}"

    parts = value.split(" ")
    if len(parts) != 5:
        raise CliError("调度格式只支持 5 段 cron（分 时 日 月 周）或 interval:<秒>")
    if not cst:
        return " ".join(parts)

    minute, hour, day, month, weekday = parts
    if hour == "*":
        return " ".join(parts)
    utc_hour, crosses_midnight = _cst_hour_to_utc(hour)
    if crosses_midnight and not (
        day == "*" and month == "*" and weekday == "*"
    ):
        raise CliError(
            "换算后跨越 UTC 零点，且“日/月/周”字段受限会导致错位；请直接提供 UTC cron"
        )
    return " ".join([minute, utc_hour, day, month, weekday])


# --------------------------------------------------------------------- #
#  参数组装                                                              #
# --------------------------------------------------------------------- #


def _read_params_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except OSError as exc:
        raise CliError(f"读取 --params-file 失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"--params-file 不是合法 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise CliError("--params-file 内容必须是 JSON 对象")
    return value


def build_params(args: argparse.Namespace) -> dict | None:
    raw = getattr(args, "params", None)
    params_file = getattr(args, "params_file", None)
    if raw and params_file:
        raise CliError("--params 与 --params-file 只能二选一")
    type_options = [
        value
        for value in (
            getattr(args, "prompt", None),
            getattr(args, "skill_id", None),
            getattr(args, "script_path", None),
            getattr(args, "arg", None),
        )
        if value
    ]
    if (raw or params_file) and type_options:
        raise CliError(
            "--params/--params-file 不能与 --prompt/--skill-id/--script-path/--arg 同时使用"
        )

    if raw:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError(f"--params 不是合法 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise CliError("--params 必须是 JSON 对象")
        return value
    if params_file:
        return _read_params_file(params_file)

    prompt = getattr(args, "prompt", None)
    if prompt:
        return {"messages": [{"role": "user", "content": prompt}]}
    skill_id = getattr(args, "skill_id", None)
    extra_prompt = getattr(args, "extra_prompt", None)
    if extra_prompt and not skill_id:
        raise CliError("--extra-prompt 需要与 --skill-id 一起使用")
    if skill_id:
        params: dict = {"skill_id": skill_id}
        if extra_prompt:
            params["extra_prompt"] = extra_prompt
        return params
    script_path = getattr(args, "script_path", None)
    if getattr(args, "arg", None) and not script_path:
        raise CliError("--arg 需要与 --script-path 一起使用")
    if script_path:
        params = {"script_path": script_path}
        arg_values = getattr(args, "arg", None)
        if arg_values:
            params["args"] = arg_values
        return params
    return None


def _validate_type_params(task_type: str, params: dict) -> None:
    if task_type == "chat":
        messages = params.get("messages")
        if not isinstance(messages, list) or not messages:
            raise CliError("chat 任务的 params 需要 --prompt，或 messages 消息数组")
    elif task_type == "skill":
        if not str(params.get("skill_id") or "").strip():
            raise CliError("skill 任务需要 --skill-id")
    elif task_type == "script":
        if not str(params.get("script_path") or "").strip():
            raise CliError("script 任务需要 --script-path")


# --------------------------------------------------------------------- #
#  子命令                                                                #
# --------------------------------------------------------------------- #


def _task_summary(task: dict) -> str:
    params = task.get("params") or {}
    if task.get("type") == "chat":
        messages = params.get("messages") or []
        if messages and isinstance(messages[0], dict):
            text = str(messages[0].get("content") or "")
            return " ".join(text.split())[:40]
    if task.get("type") == "skill":
        return str(params.get("skill_id") or "")
    if task.get("type") == "script":
        return str(params.get("script_path") or "")
    return ""


def cmd_list(args: argparse.Namespace) -> int:
    query = ""
    if args.enabled is not None:
        query = "?enabled=true" if args.enabled else "?enabled=false"
    data = request("GET", TASKS_PATH + query)
    if args.json or not isinstance(data, list):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if not data:
        print("（暂无定时任务）")
        return 0
    print(f"共 {len(data)} 个任务（调度按 UTC 解释）：")
    for task in data:
        state = "启用" if task.get("enabled") else "停用"
        task_id = str(task.get("id") or "")
        name = " ".join(str(task.get("name") or "").split())[:20]
        schedule = str(task.get("schedule") or "")
        task_type = str(task.get("type") or "")
        summary = _task_summary(task)
        line = f"- {task_id} | {name} | {task_type} | {schedule} | {state}"
        if summary:
            line += f" | {summary}"
        print(line)
    return 0


def _schedule_from_args(args: argparse.Namespace, *, required: bool) -> str | None:
    plain = getattr(args, "schedule", None)
    cst = getattr(args, "schedule_cst", None)
    if plain and cst:
        raise CliError("--schedule 与 --schedule-cst 只能二选一")
    if cst:
        return normalize_schedule(cst, cst=True)
    if plain:
        return normalize_schedule(plain, cst=False)
    if required:
        raise CliError("缺少调度表达式：--schedule（UTC）或 --schedule-cst（北京时间）")
    return None


def cmd_show(args: argparse.Namespace) -> int:
    data = request("GET", f"{TASKS_PATH}{args.task_id}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    params = build_params(args)
    if params is None:
        raise CliError(
            "创建任务需要执行内容：--prompt（chat）/ --skill-id（skill）/ "
            "--script-path（script）/ --params"
        )
    _validate_type_params(args.type, params)
    schedule = _schedule_from_args(args, required=True)
    body = {
        "name": args.name,
        "schedule": schedule,
        "type": args.type,
        "params": params,
    }
    data = request("POST", TASKS_PATH, body)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    body: dict = {}
    if args.name is not None:
        body["name"] = args.name
    schedule = _schedule_from_args(args, required=False)
    if schedule is not None:
        body["schedule"] = schedule
    if args.type is not None:
        body["type"] = args.type
    params = build_params(args)
    if params is not None:
        body["params"] = params
    if args.enable is not None:
        body["enabled"] = args.enable
    if not body:
        raise CliError("没有需要更新的字段")
    if "type" in body and "params" in body:
        _validate_type_params(body["type"], body["params"])
    data = request("PATCH", f"{TASKS_PATH}{args.task_id}", body)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        raise CliError("删除任务不可恢复；请先与用户确认，然后加 --yes 重新执行")
    data = request("DELETE", f"{TASKS_PATH}{args.task_id}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    data = request("POST", f"{TASKS_PATH}{args.task_id}/run")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------- #
#  入口                                                                  #
# --------------------------------------------------------------------- #


def _add_type_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", help="chat 任务内容：作为到点时对话的首条用户消息")
    parser.add_argument("--skill-id", help="skill 任务：技能目录名")
    parser.add_argument("--extra-prompt", help="skill 任务的附加说明")
    parser.add_argument("--script-path", help="script 任务：沙箱内脚本路径")
    parser.add_argument("--arg", action="append", help="script 任务参数，可重复")
    parser.add_argument("--params", help="原始参数 JSON 对象")
    parser.add_argument("--params-file", help="原始参数 JSON 文件路径")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eido_task.py",
        description="Eido 定时任务管理（沙箱内以当前用户身份操作）",
        epilog=(
            "调度按 UTC 解释；北京时间用 --schedule-cst 自动换算。"
            "cron 周字段为 APScheduler 语义（0=周一 … 6=周日），建议用 mon…sun。"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出定时任务")
    p_list.add_argument("--json", action="store_true", help="输出原始 JSON")
    state = p_list.add_mutually_exclusive_group()
    state.add_argument("--enabled", dest="enabled", action="store_true", default=None)
    state.add_argument("--disabled", dest="enabled", action="store_false")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="查看任务详情")
    p_show.add_argument("task_id")
    p_show.set_defaults(func=cmd_show)

    p_create = sub.add_parser("create", help="创建任务")
    p_create.add_argument("--name", required=True, help="任务名称")
    schedule = p_create.add_mutually_exclusive_group()
    schedule.add_argument("--schedule", help="UTC 调度：interval:<秒> 或 5 段 cron")
    schedule.add_argument("--schedule-cst", metavar="EXPR", help="北京时间调度，自动换算为 UTC")
    p_create.add_argument("--type", required=True, choices=("chat", "skill", "script"))
    _add_type_options(p_create)
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="修改任务")
    p_update.add_argument("task_id")
    p_update.add_argument("--name")
    schedule = p_update.add_mutually_exclusive_group()
    schedule.add_argument("--schedule", help="UTC 调度：interval:<秒> 或 5 段 cron")
    schedule.add_argument("--schedule-cst", metavar="EXPR", help="北京时间调度，自动换算为 UTC")
    p_update.add_argument("--type", choices=("chat", "skill", "script"))
    _add_type_options(p_update)
    state = p_update.add_mutually_exclusive_group()
    state.add_argument("--enabled", dest="enable", action="store_true", default=None)
    state.add_argument("--disabled", dest="enable", action="store_false")
    p_update.set_defaults(func=cmd_update)

    p_delete = sub.add_parser("delete", help="删除任务")
    p_delete.add_argument("task_id")
    p_delete.add_argument("--yes", action="store_true", help="确认删除（必须）")
    p_delete.set_defaults(func=cmd_delete)

    p_run = sub.add_parser("run", help="立即执行一次任务")
    p_run.add_argument("task_id")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
