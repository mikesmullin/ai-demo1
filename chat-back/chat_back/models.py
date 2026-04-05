"""OpenAI Chat Completions compatible request/response models."""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, Field


# --- Request models ---


class FunctionDefinition(BaseModel):
    name: str
    description: str = ""
    parameters: dict = {}


class ToolDefinition(BaseModel):
    type: str = "function"
    function: FunctionDefinition


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: list[ToolDefinition] | None = None
    tool_choice: str | dict | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: list[str] | str | None = None


# --- Response models ---


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:24]}")
    type: str = "function"
    function: FunctionCall


class ResponseMessage(BaseModel):
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class Choice(BaseModel):
    index: int = 0
    message: ResponseMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[Choice]
    usage: Usage = Usage()


# Update forward refs
ChatMessage.model_rebuild()
