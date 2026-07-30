"""Request/response schemas for the BYOK Gateway Pilot.

All dataclass-based (no pydantic) to avoid bundling pydantic-core
(4 MiB WASM binary) in Cloudflare Workers.

Extra-field rejection is implemented via _validate_extra_kwargs in
__post_init__.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Error types (replaces pydantic.ValidationError)
# ---------------------------------------------------------------------------
from app.pilot.errors import PilotError


class ValidationError(PilotError):
    """Raised when a schema field fails validation."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors_list = errors
        messages = "; ".join(e.get("msg", str(e)) for e in errors)
        super().__init__(
            code="validation_error",
            message=messages,
            status_code=422,
        )


def _raise(msg: str) -> None:
    raise ValidationError([{"msg": msg}])


# ---------------------------------------------------------------------------
# Chat message
# ---------------------------------------------------------------------------
@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("system", "user", "assistant"):
            _raise(f"invalid role: {self.role!r}")
        stripped = self.content.strip()
        if not stripped:
            _raise("message content must not be empty")
        if len(stripped) > 32000:
            _raise("message content must not exceed 32000 characters")
        self.content = stripped


# ---------------------------------------------------------------------------
# Chat completion request
# ---------------------------------------------------------------------------
@dataclass
class PilotChatRequest:
    model: str = ""
    messages: list[dict[str, str]] | list[ChatMessage] = field(default_factory=list)
    temperature: float | None = 0.2
    max_tokens: int | None = 300
    stream: bool | None = False
    tools: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        stripped = self.model.strip()
        if not stripped:
            _raise("model must not be empty")
        if len(stripped) > 200:
            _raise("model must not exceed 200 characters")
        self.model = stripped

        if self.temperature is not None and (self.temperature < 0.0 or self.temperature > 2.0):
            _raise("temperature must be between 0.0 and 2.0")

        if self.max_tokens is not None and (self.max_tokens < 1 or self.max_tokens > 4096):
            _raise("max_tokens must be between 1 and 4096")

        if len(self.messages) < 1:
            _raise("at least one message is required")
        if len(self.messages) > 100:
            _raise("message count must not exceed 100")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
@dataclass
class PilotChatMessage:
    role: str = ""
    content: str = ""


@dataclass
class PilotChoice:
    index: int = 0
    message: PilotChatMessage = field(default_factory=PilotChatMessage)
    finish_reason: str = "stop"


@dataclass
class PilotUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class PilotBusiness14Meta:
    mode: str = "byok-pilot"
    provider: str = ""
    model_route: str = ""
    latency_ms: int = 0
    estimated_krw: float | None = None
    request_id: str = ""


@dataclass
class PilotChatResponse:
    id: str = ""
    object: str = "chat.completion"
    model: str = ""
    choices: list[PilotChoice] = field(default_factory=list)
    usage: PilotUsage | None = None
    business14: PilotBusiness14Meta = field(default_factory=PilotBusiness14Meta)


@dataclass
class PilotError:
    error: dict[str, str]


@dataclass
class PilotModelInfo:
    id: str = ""
    name: str = ""
    provider_id: str = ""
    provider_name: str = ""
    pilot_available: bool = True
    input_krw_per_1k: float | None = None
    output_krw_per_1k: float | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class PilotHealthResponse:
    status: str = "ok"
    mode: str = "byok-pilot"
    configured_providers: int = 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert any dataclass to a dict, recursing into nested dataclasses.

    Replaces pydantic's model_dump().
    """
    return asdict(obj)
