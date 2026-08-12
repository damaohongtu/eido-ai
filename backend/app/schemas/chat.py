"""
Chat-related Pydantic schemas for request/response validation.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Single message in a conversation."""

    id: Optional[str] = Field(None, description="前端消息 ID；持久化时用于幂等写入")
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Request schema for chat completions."""

    messages: List[Message] = Field(..., description="Conversation history")
    context: Optional[str] = Field(
        None, description="Output from previous skill in a pipeline, injected into prompt"
    )
    session_id: str = Field(
        ..., description="会话 ID，agent 工作目录将切到该会话的 .eido/workspaces/<session_id>/"
    )
    assistant_message_id: str = Field(
        ..., description="前端 assistant 占位消息 ID；后端保存模型输出时使用"
    )
    harness: Optional[str] = Field(
        None, description="AI 后端选择: claude_code | opencode（不传则使用 AGENT_HARNESS 配置）"
    )


class ChatControlRequest(BaseModel):
    """Additional input submitted while a session is already executing."""

    mode: Literal["queue", "steer"]
    session_id: str
    message: Message
    assistant_message_id: str = Field(..., description="排队执行时使用的 assistant 消息 ID")
    context: Optional[str] = None
    harness: Optional[str] = Field(None, description="AI 后端选择")


class ChatResponse(BaseModel):
    """Response schema for non-streaming chat completions."""

    content: str
    role: Literal["assistant"] = "assistant"
    model: str = "unknown"
    usage: Optional[dict] = None


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: str
    detail: Optional[str] = None
