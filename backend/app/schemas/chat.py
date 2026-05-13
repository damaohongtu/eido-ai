"""
Chat-related Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class Message(BaseModel):
    """Single message in a conversation."""
    id: Optional[str] = Field(None, description="前端消息 ID；持久化时用于幂等写入")
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Request schema for chat completions."""
    messages: List[Message] = Field(..., description="Conversation history")
    context: Optional[str] = Field(None, description="Output from previous skill in a pipeline, injected into prompt")
    session_id: str = Field(..., description="会话 ID，agent 工作目录将切到该会话的 .eido/workspaces/<session_id>/")
    assistant_message_id: str = Field(..., description="前端 assistant 占位消息 ID；后端保存模型输出时使用")
    claude_session_id: Optional[str] = Field(None, description="复用已有的 Claude Code 内部会话 ID，首次不传，后续由后端返回")


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
