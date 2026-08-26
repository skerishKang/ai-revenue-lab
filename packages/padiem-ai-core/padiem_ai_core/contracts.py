from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ToolSideEffect(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    HIGH_RISK = "high_risk"


class ApprovalPolicy(str, Enum):
    NOT_REQUIRED = "not_required"
    USER_CONFIRMATION = "user_confirmation"
    EXTERNAL_AUTHORIZATION = "external_authorization"


class RunStatus(str, Enum):
    RECEIVED = "received"
    AUTHORIZED = "authorized"
    CONTEXT_READY = "context_ready"
    MODEL_SELECTED = "model_selected"
    MODEL_RUNNING = "model_running"
    TOOL_REQUIRED = "tool_required"
    TOOL_RUNNING = "tool_running"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    POLICY_BLOCKED = "policy_blocked"
    TIMEOUT = "timeout"


class ErrorClass(str, Enum):
    INPUT_ERROR = "input_error"
    AUTH_ERROR = "auth_error"
    POLICY_BLOCKED = "policy_blocked"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_BAD_RESPONSE = "provider_bad_response"
    TOOL_VALIDATION_ERROR = "tool_validation_error"
    TOOL_RUNTIME_ERROR = "tool_runtime_error"
    BROWSER_ERROR = "browser_error"
    CONTEXT_ERROR = "context_error"
    INTERNAL_ERROR = "internal_error"


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty safe identifier")
    return value


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _tuple_of_identifiers(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        values = tuple(values)
    checked = tuple(_identifier(name, value) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{name} must not contain duplicates")
    return checked


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((_thaw(item) for item in value), key=repr)
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    title: str
    snippet: str
    retrieved_at: str
    provider: str
    source_type: str
    url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier("evidence id", self.id))
        object.__setattr__(self, "title", _non_empty("title", self.title))
        object.__setattr__(self, "retrieved_at", _non_empty("retrieved_at", self.retrieved_at))
        object.__setattr__(self, "provider", _identifier("provider", self.provider))
        object.__setattr__(self, "source_type", _identifier("source_type", self.source_type))
        if self.url is not None and not isinstance(self.url, str):
            raise ValueError("url must be a string or None")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "retrieved_at": self.retrieved_at,
            "provider": self.provider,
            "source_type": self.source_type,
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    id: str
    title: str
    description: str
    owner: str
    side_effect: ToolSideEffect
    approval_policy: ApprovalPolicy
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_contract: Mapping[str, Any] = field(default_factory=dict)
    auth_scope: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    user_visible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier("tool id", self.id))
        object.__setattr__(self, "title", _non_empty("title", self.title))
        object.__setattr__(self, "description", _non_empty("description", self.description))
        object.__setattr__(self, "owner", _identifier("owner", self.owner))
        if not isinstance(self.side_effect, ToolSideEffect):
            raise ValueError("side_effect must be ToolSideEffect")
        if not isinstance(self.approval_policy, ApprovalPolicy):
            raise ValueError("approval_policy must be ApprovalPolicy")
        if self.side_effect in {ToolSideEffect.WRITE, ToolSideEffect.HIGH_RISK} and self.approval_policy is ApprovalPolicy.NOT_REQUIRED:
            raise ValueError("write/high-risk tools require an approval policy")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not 0 < self.timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be > 0 and <= 300")
        object.__setattr__(self, "auth_scope", _tuple_of_identifiers("auth_scope", self.auth_scope))
        object.__setattr__(self, "input_schema", _freeze(self.input_schema))
        object.__setattr__(self, "output_contract", _freeze(self.output_contract))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "owner": self.owner,
            "side_effect": self.side_effect.value,
            "approval_policy": self.approval_policy.value,
            "input_schema": _thaw(self.input_schema),
            "output_contract": _thaw(self.output_contract),
            "auth_scope": list(self.auth_scope),
            "timeout_seconds": self.timeout_seconds,
            "user_visible": self.user_visible,
        }


@dataclass(frozen=True, slots=True)
class AgentProfile:
    id: str
    title: str
    description: str
    system_instruction: str
    task_type: str
    optimize_for: str
    max_tokens: int
    allowed_tools: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    context_policy: Mapping[str, Any] = field(default_factory=dict)
    model_policy: Mapping[str, Any] = field(default_factory=dict)
    max_steps: int = 1
    output_contract: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier("agent id", self.id))
        object.__setattr__(self, "title", _non_empty("title", self.title))
        object.__setattr__(self, "description", _non_empty("description", self.description))
        object.__setattr__(self, "system_instruction", _non_empty("system_instruction", self.system_instruction))
        object.__setattr__(self, "task_type", _identifier("task_type", self.task_type))
        object.__setattr__(self, "optimize_for", _identifier("optimize_for", self.optimize_for))
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or not 1 <= self.max_steps <= 100:
            raise ValueError("max_steps must be between 1 and 100")
        object.__setattr__(self, "allowed_tools", _tuple_of_identifiers("allowed_tools", self.allowed_tools))
        object.__setattr__(self, "required_capabilities", _tuple_of_identifiers("required_capabilities", self.required_capabilities))
        object.__setattr__(self, "context_policy", _freeze(self.context_policy))
        object.__setattr__(self, "model_policy", _freeze(self.model_policy))
        object.__setattr__(self, "output_contract", _freeze(self.output_contract))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "task_type": self.task_type,
            "optimize_for": self.optimize_for,
            "max_tokens": self.max_tokens,
            "allowed_tools": list(self.allowed_tools),
            "required_capabilities": list(self.required_capabilities),
            "context_policy": _thaw(self.context_policy),
            "model_policy": _thaw(self.model_policy),
            "max_steps": self.max_steps,
            "output_contract": _thaw(self.output_contract),
        }


@dataclass(frozen=True, slots=True)
class UsageMetadata:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")

    def to_public_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class ToolEvent:
    tool_id: str
    status: RunStatus
    duration_ms: int | None = None
    error_class: ErrorClass | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _identifier("tool_id", self.tool_id))
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be RunStatus")
        if self.duration_ms is not None and (isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0):
            raise ValueError("duration_ms must be a non-negative integer or None")
        if self.error_class is not None and not isinstance(self.error_class, ErrorClass):
            raise ValueError("error_class must be ErrorClass or None")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "error_class": self.error_class.value if self.error_class is not None else None,
        }


@dataclass(frozen=True, slots=True)
class RunMetadata:
    trace_id: str
    app_id: str
    agent_id: str
    status: RunStatus
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    duration_ms: int | None = None
    usage: UsageMetadata = field(default_factory=UsageMetadata)
    tool_events: tuple[ToolEvent, ...] = ()
    error_class: ErrorClass | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier("trace_id", self.trace_id))
        object.__setattr__(self, "app_id", _identifier("app_id", self.app_id))
        object.__setattr__(self, "agent_id", _identifier("agent_id", self.agent_id))
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be RunStatus")
        if self.session_id is not None:
            object.__setattr__(self, "session_id", _identifier("session_id", self.session_id))
        if self.provider is not None:
            object.__setattr__(self, "provider", _identifier("provider", self.provider))
        if self.model is not None:
            object.__setattr__(self, "model", _non_empty("model", self.model))
        if self.duration_ms is not None and (isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0):
            raise ValueError("duration_ms must be a non-negative integer or None")
        if not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata")
        if not isinstance(self.tool_events, tuple):
            object.__setattr__(self, "tool_events", tuple(self.tool_events))
        if any(not isinstance(event, ToolEvent) for event in self.tool_events):
            raise ValueError("tool_events must contain ToolEvent values")
        if self.error_class is not None and not isinstance(self.error_class, ErrorClass):
            raise ValueError("error_class must be ErrorClass or None")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "app_id": self.app_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "provider": self.provider,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "usage": self.usage.to_public_dict(),
            "tool_events": [event.to_public_dict() for event in self.tool_events],
            "error_class": self.error_class.value if self.error_class is not None else None,
        }
