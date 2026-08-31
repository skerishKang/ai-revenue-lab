"""Normalized, bounded Agent orchestration events for P01."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

MAX_AGENT_EVENT_MESSAGE_CHARS = 1_000
MAX_AGENT_EVENT_METADATA_KEYS = 16
MAX_AGENT_EVENT_ID_CHARS = 128
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AgentEventError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("agent event error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class AgentEventKind(str, Enum):
    RUN_PLANNED = "run_planned"
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    TOOL_REQUESTED = "tool_requested"
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_PAUSED = "approval_paused"
    RETRY_DECIDED = "retry_decided"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_id: str
    run_id: str
    kind: AgentEventKind
    sequence: int
    message: str | None = None
    metadata: Mapping[str, str | int | bool | None] = ()

    def __post_init__(self) -> None:
        for name in ("event_id", "run_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
                raise AgentEventError("invalid_agent_event", f"{name} must be a bounded safe identifier")
        if len(self.event_id) > MAX_AGENT_EVENT_ID_CHARS:
            raise AgentEventError("invalid_agent_event", "event_id exceeds the bounded event limit")
        if not isinstance(self.kind, AgentEventKind):
            raise AgentEventError("invalid_agent_event", "kind must be AgentEventKind")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise AgentEventError("invalid_agent_event", "sequence must be a positive integer")
        if self.message is not None:
            if not isinstance(self.message, str) or not self.message.strip():
                raise AgentEventError("invalid_agent_event", "message must be a non-empty string or None")
            message = self.message.strip()
            if len(message) > MAX_AGENT_EVENT_MESSAGE_CHARS:
                raise AgentEventError("invalid_agent_event", "message exceeds the bounded event limit")
            object.__setattr__(self, "message", message)

        if isinstance(self.metadata, (str, bytes)) or not isinstance(self.metadata, Mapping):
            raise AgentEventError("invalid_agent_event", "metadata must be a mapping")
        metadata = dict(self.metadata)
        if len(metadata) > MAX_AGENT_EVENT_METADATA_KEYS:
            raise AgentEventError("agent_event_budget_exceeded", "metadata contains too many fields")
        safe: dict[str, str | int | bool | None] = {}
        for key, value in metadata.items():
            if not isinstance(key, str) or not _IDENTIFIER_RE.fullmatch(key):
                raise AgentEventError("invalid_agent_event", "metadata keys must be bounded safe identifiers")
            if isinstance(value, (dict, list, tuple, set, bytes)):
                raise AgentEventError("invalid_agent_event", "metadata values must be scalar")
            if not isinstance(value, (str, int, bool)) and value is not None:
                raise AgentEventError("invalid_agent_event", "metadata values must be scalar")
            if isinstance(value, str) and len(value) > MAX_AGENT_EVENT_MESSAGE_CHARS:
                raise AgentEventError("agent_event_budget_exceeded", "metadata string exceeds the bounded event limit")
            safe[key] = value
        object.__setattr__(self, "metadata", safe)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "kind": self.kind.value,
            "sequence": self.sequence,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


def public_agent_event(
    *,
    event_id: str,
    run_id: str,
    kind: AgentEventKind,
    sequence: int,
    message: str | None = None,
    metadata: Mapping[str, str | int | bool | None] | None = None,
) -> AgentEvent:
    """Create a normalized event; callers should never attach raw arguments/results."""
    return AgentEvent(
        event_id=event_id,
        run_id=run_id,
        kind=kind,
        sequence=sequence,
        message=message,
        metadata=metadata or {},
    )
