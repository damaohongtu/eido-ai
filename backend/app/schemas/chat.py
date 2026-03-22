"""
Chat-related Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class Message(BaseModel):
    """Single message in a conversation."""
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Request schema for chat completions."""
    messages: List[Message] = Field(..., description="Conversation history")
    context: Optional[str] = Field(None, description="Output from previous skill in a pipeline, injected into prompt")


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
