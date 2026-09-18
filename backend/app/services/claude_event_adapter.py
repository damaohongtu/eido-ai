"""Translate Claude SDK events into the application's SSE contract."""

import json
import logging
from typing import List

logger = logging.getLogger(__name__)


def _serialize_log_value(value):
    return json.dumps(value, ensure_ascii=False, default=str)


class ClaudeEventAdapter:
    def __init__(self):
        self.streamed_text = False

    def _log_message(self, message: object) -> None:
        """将完整 SDK 消息写入日志，便于按 traceId 追踪执行过程。"""
        if not logger.isEnabledFor(logging.DEBUG) and type(message).__name__ != "ResultMessage":
            return
        try:
            from claude_agent_sdk.types import (  # type: ignore
                AssistantMessage,
                ResultMessage,
                SystemMessage,
                TextBlock,
                ThinkingBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except ImportError:
            return

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    logger.debug(
                        "  [Assistant/Text] %s",
                        _serialize_log_value(block.text),
                    )
                elif isinstance(block, ThinkingBlock):
                    logger.debug(
                        "  [Assistant/Thinking] %s",
                        _serialize_log_value(block.thinking),
                    )
                elif isinstance(block, ToolUseBlock):
                    logger.debug(
                        "  [Tool/Call] %s | 参数: %s",
                        block.name,
                        _serialize_log_value(block.input),
                    )

        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        raw = block.content
                        content_str = raw if isinstance(raw, str) else str(raw or "")
                        status = "ERROR" if block.is_error else "OK"
                        logger.debug(
                            "  [Tool/Result:%s] %s",
                            status,
                            _serialize_log_value(content_str),
                        )

        elif isinstance(message, SystemMessage):
            logger.debug(
                "  [System/%s] %s",
                message.subtype,
                _serialize_log_value(message.data),
            )

        elif isinstance(message, ResultMessage):
            cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "N/A"
            duration = f"{message.duration_ms / 1000:.1f}s"
            api_duration = f"{message.duration_api_ms / 1000:.1f}s"
            status = "ERROR" if message.is_error else "OK"
            usage = message.usage or {}
            models = ",".join((message.model_usage or {}).keys()) or "-"
            logger.info(
                f"  [Result/{status}] 总用时={duration} | API用时={api_duration} | 费用={cost} | "
                f"轮次={message.num_turns} | session={message.session_id} | "
                f"models={models} | "
                f"terminal={getattr(message, 'terminal_reason', None) or '-'} | "
                f"api_status={getattr(message, 'api_error_status', None) or '-'} | "
                f"input={usage.get('input_tokens', 0)} | "
                f"cache_read={usage.get('cache_read_input_tokens', 0)} | "
                f"cache_create={usage.get('cache_creation_input_tokens', 0)} | "
                f"output={usage.get('output_tokens', 0)}"
            )

    def _convert_message(self, message: object) -> List[str]:
        """将 claude_agent_sdk 消息转换为前端 SSE 事件列表。

        SDK 返回强类型 dataclass，必须用 isinstance 判断，不能依赖 type 属性。
        消息类型：AssistantMessage / UserMessage / SystemMessage / ResultMessage / StreamEvent
        """
        try:
            from claude_agent_sdk.types import (  # type: ignore
                AssistantMessage,
                ResultMessage,
                StreamEvent,
                SystemMessage,
                TextBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except ImportError:
            return []

        events: List[str] = []
        # Subagent deltas are not the top-level answer.
        if getattr(message, "parent_tool_use_id", None):
            return events
        if isinstance(message, StreamEvent):
            event = message.event
            if event.get("type") == "message_start":
                self.streamed_text = False
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    self.streamed_text = True
                    events.append(self._sse({"type": "content", "content": delta["text"]}))
            return events
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text and not self.streamed_text:
                    events.append(self._sse({"type": "content", "content": block.text}))
                elif isinstance(block, ToolUseBlock):
                    events.append(
                        self._sse(
                            {
                                "type": "thinking",
                                "content": self._tool_hint(block.name, block.input),
                            }
                        )
                    )
            self.streamed_text = False
        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        raw = block.content
                        content_str = (
                            raw if isinstance(raw, str) else (str(raw) if raw is not None else "")
                        )
                        preview = content_str[:200].strip()
                        status = "✗ 工具出错" if block.is_error else "✓ 工具完成"
                        hint = f"{status}: {preview}" if preview else status
                        events.append(self._sse({"type": "thinking", "content": hint}))

        elif isinstance(message, SystemMessage):
            if message.subtype == "compact_boundary":
                events.append(
                    self._sse({"type": "thinking", "content": "上下文已压缩，继续当前任务…"})
                )
            if message.subtype == "status" and message.data.get("status") == "compacting":
                events.append(
                    self._sse({"type": "thinking", "content": "正在压缩上下文并保留任务进度…"})
                )
            if message.subtype == "init":
                tools = message.data.get("tools", [])
                if tools:
                    tool_list = ", ".join(tools[:6]) + ("…" if len(tools) > 6 else "")
                    events.append(
                        self._sse({"type": "thinking", "content": f"已加载工具: {tool_list}"})
                    )

        elif isinstance(message, ResultMessage):
            if message.is_error or getattr(message, "terminal_reason", None) in {
                "aborted_streaming",
                "aborted_tools",
                "max_turns",
                "max_budget_usd",
            }:
                events.append(
                    self._sse(
                        {
                            "type": "error",
                            "message": message.result
                            or "; ".join(getattr(message, "errors", None) or [])
                            or "执行未完成",
                        }
                    )
                )
                return events
            # 不重复发送 result：AssistantMessage 的 TextBlock 已包含完整回复，
            # ResultMessage.result 与之相同，再发会导致前端显示重复内容
            cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "N/A"
            duration = f"{message.duration_ms / 1000:.1f}s"
            api_duration = f"{message.duration_api_ms / 1000:.1f}s"
            usage = message.usage or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
            cache_create = int(usage.get("cache_creation_input_tokens", 0) or 0)
            events.append(
                self._sse(
                    {
                        "type": "thinking",
                        "content": (
                            f"执行完成 | 总用时: {duration} | 模型 API: {api_duration} | "
                            f"费用: {cost} | 轮次: {message.num_turns} | "
                            f"输入: {input_tokens} | 缓存读取: {cache_read} | 缓存写入: {cache_create}"
                            + (" | ⚠️ 出错" if message.is_error else "")
                        ),
                    }
                )
            )

        return events

    def _tool_hint(self, tool_name: str, tool_input: dict) -> str:
        """根据工具名称和参数生成人类可读的思考提示"""
        hints = {
            "Read": lambda i: f"读取文件: {i.get('file_path', '')}",
            "Bash": lambda i: f"执行命令: {str(i.get('command', ''))[:120]}",
            "Glob": lambda i: f"查找文件: {i.get('pattern', '')}",
            "WebFetch": lambda i: f"获取网页: {i.get('url', '')}",
            "WebSearch": lambda i: f"搜索: {i.get('query', '')}",
            "Write": lambda i: f"写入文件: {i.get('file_path', '')}",
            "Edit": lambda i: f"编辑文件: {i.get('file_path', '')}",
            "Grep": lambda i: f"搜索内容: {i.get('pattern', '')}",
            "MultiEdit": lambda i: f"批量编辑: {i.get('file_path', '')}",
            "Agent": lambda i: f"子任务: {i.get('description', '')}",
            "TaskCreate": lambda i: f"记录任务: {i.get('subject', '')}",
            "TaskUpdate": lambda i: f"更新任务进度: {i.get('status', '')}",
            "TaskList": lambda i: "查看任务进度",
            "TodoWrite": lambda i: "更新任务清单",
            "Skill": lambda i: f"加载技能: {i.get('skill', i.get('name', ''))}",
        }
        fn = hints.get(tool_name)
        if fn:
            try:
                return fn(tool_input)
            except Exception:
                pass
        return f"正在调用工具: {tool_name}..."

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #

    def _sse(self, data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
