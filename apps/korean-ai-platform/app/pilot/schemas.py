"""Request/response schemas for the BYOK Gateway Pilot.

All request schemas use extra="forbid" to reject unknown fields.
Message roles are restricted to system/user/assistant.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    """A single chat message with a restricted role."""

    role: Literal["system", "user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def _content_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message content must not be empty")
        if len(stripped) > 32000:
            raise ValueError("message content must not exceed 32000 characters")
        return stripped

    model_config = {"extra": "forbid"}


class PilotChatRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = 0.2
    max_tokens: int | None = 300
    stream: bool | None = False
    tools: list[dict[str, Any]] | None = None

    @field_validator("model")
    @classmethod
    def _model_valid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("model must not be empty")
        if len(stripped) > 200:
            raise ValueError("model must not exceed 200 characters")
        return stripped

    @field_validator("temperature")
    @classmethod
    def _temperature_range(cls, v: float | None) -> float | None:
        if v is not None and (v < 0.0 or v > 2.0):
            raise ValueError("temperature must be between 0.0 and 2.0")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _max_tokens_range(cls, v: int | None) -> int | None:
        if v is not None and (v < 1 or v > 4096):
            raise ValueError("max_tokens must be between 1 and 4096")
        return v

    @field_validator("messages")
    @classmethod
    def _messages_count(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if len(v) < 1:
            raise ValueError("at least one message is required")
        if len(v) > 100:
            raise ValueError("message count must not exceed 100")
        return v

    model_config = {"extra": "forbid"}


class PilotChatMessage(BaseModel):
    role: str
    content: str


class PilotChoice(BaseModel):
    index: int = 0
    message: PilotChatMessage
    finish_reason: str = "stop"


class PilotUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class PilotBusiness14Meta(BaseModel):
    mode: str = "byok-pilot"
    provider: str = ""
    latency_ms: int = 0
    estimated_krw: float | None = None
    request_id: str = ""


class PilotChatResponse(BaseModel):
    id: str = ""
    object: str = "chat.completion"
    model: str = ""
    choices: list[PilotChoice] = Field(default_factory=list)
    usage: PilotUsage | None = None
    business14: PilotBusiness14Meta = Field(default_factory=PilotBusiness14Meta)


class PilotError(BaseModel):
    error: dict[str, str]


class PilotModelInfo(BaseModel):
    id: str
    name: str
    provider_id: str
    provider_name: str
    pilot_available: bool = True
    input_krw_per_1k: float | None = None
    output_krw_per_1k: float | None = None
    tags: list[str] = Field(default_factory=list)


class PilotHealthResponse(BaseModel):
    status: str = "ok"
    mode: str = "byok-pilot"
    configured_providers: int = 0
