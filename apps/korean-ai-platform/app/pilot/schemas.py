"""Request/response schemas for the BYOK Gateway Pilot."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PilotChatRequest(BaseModel):
    model: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    temperature: float | None = 0.2
    max_tokens: int | None = 300
    stream: bool | None = False
    tools: list[dict[str, Any]] | None = None


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
    estimated_krw: float = 0.0
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
    input_krw_per_1k: float = 0.0
    output_krw_per_1k: float = 0.0
    tags: list[str] = Field(default_factory=list)


class PilotHealthResponse(BaseModel):
    status: str = "ok"
    mode: str = "byok-pilot"
    configured_providers: int = 0
