"""Normalized event contracts for the P01 Unified Orchestration Pipeline.

This module provides an immutable, product-neutral lifecycle event envelope
that unifies Agent, Memory, Skill, Tool, Evidence, and Execution events while
strictly forbidding raw credentials, tokens, secrets, hidden reasoning, and
unbounded payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SENSITIVE_KEY_RE = re.compile(r"(secret|token|credential|password|key|auth)", re.IGNORECASE)

MAX_ORCHESTRATION_EVENT_KEYS = 32
MAX_ORCHESTRATION_EVENT_STRING_CHARS = 1_000
MAX_ORCHESTRATION_EVENT_MESSAGE_CHARS = 2_000


class OrchestrationEventError(ValueError):
    """Raised when an orchestration event contract is violated."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("orchestration event error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class OrchestrationEventKind(str, Enum):
    """Frozen lifecycle states emitted by the P01 Orchestration Pipeline."""

    RUN_STARTED = "run_started"
    CONTEXT_PREPARED = "context_prepared"
    MEMORY_READ = "memory_read"
    PLAN_CREATED = "plan_created"
    SKILL_RESOLVED = "skill_resolved"
    TOOL_RESOLUTION = "tool_resolution"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    EVIDENCE_ATTACHED = "evidence_attached"
    VERIFICATION_COMPLETED = "verification_completed"
    APPROVAL_PAUSED = "approval_paused"
    RUN_CANCELLED = "run_cancelled"
    RUN_FAILED = "run_failed"
    RUN_COMPLETED = "run_completed"


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise OrchestrationEventError(
            "invalid_event_identifier",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _bounded_message(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OrchestrationEventError(
            "invalid_event_message",
            "event message must be a string",
        )
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_ORCHESTRATION_EVENT_MESSAGE_CHARS:
        raise OrchestrationEventError(
            "event_budget_exceeded",
            f"event message exceeds {MAX_ORCHESTRATION_EVENT_MESSAGE_CHARS} characters",
        )
    return normalized


def _sanitize_scalar_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, str | int | float | bool | None]:
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise OrchestrationEventError(
            "invalid_event_metadata",
            "metadata must be a mapping",
        )
    if len(metadata) > MAX_ORCHESTRATION_EVENT_KEYS:
        raise OrchestrationEventError(
            "event_budget_exceeded",
            f"metadata contains more than {MAX_ORCHESTRATION_EVENT_KEYS} entries",
        )

    sanitized: dict[str, str | int | float | bool | None] = {}
    for raw_key, raw_val in metadata.items():
        if not isinstance(raw_key, str) or not _SAFE_ID_RE.fullmatch(raw_key):
            raise OrchestrationEventError(
                "invalid_event_metadata",
                "metadata keys must be bounded safe identifiers",
            )
        if _SENSITIVE_KEY_RE.search(raw_key):
            raise OrchestrationEventError(
                "sensitive_metadata_key_rejected",
                f"metadata key '{raw_key}' contains prohibited sensitive pattern",
            )

        if raw_val is None or isinstance(raw_val, (bool, int, float)):
            sanitized[raw_key] = raw_val
        elif isinstance(raw_val, str):
            if len(raw_val) > MAX_ORCHESTRATION_EVENT_STRING_CHARS:
                raise OrchestrationEventError(
                    "event_budget_exceeded",
                    f"metadata string value for '{raw_key}' exceeds {MAX_ORCHESTRATION_EVENT_STRING_CHARS} characters",
                )
            sanitized[raw_key] = raw_val
        else:
            raise OrchestrationEventError(
                "non_scalar_metadata_rejected",
                f"metadata value for '{raw_key}' must be scalar (str, int, float, bool, None); nested structures are prohibited",
            )

    return sanitized


@dataclass(frozen=True, slots=True)
class OrchestrationEvent:
    """Immutable, bounded lifecycle event for the P01 Orchestration Pipeline."""

    event_id: str
    run_id: str
    trace_id: str
    app_id: str
    kind: OrchestrationEventKind
    sequence: int
    timestamp_iso: str
    message: str | None = None
    metadata: Mapping[str, str | int | float | bool | None] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_identifier("event_id", self.event_id))
        object.__setattr__(self, "run_id", _safe_identifier("run_id", self.run_id))
        object.__setattr__(self, "trace_id", _safe_identifier("trace_id", self.trace_id))
        object.__setattr__(self, "app_id", _safe_identifier("app_id", self.app_id))
        if not isinstance(self.kind, OrchestrationEventKind):
            raise OrchestrationEventError(
                "invalid_event_kind",
                "kind must be an OrchestrationEventKind enum value",
            )
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise OrchestrationEventError(
                "invalid_event_sequence",
                "sequence must be a positive integer (1-based monotonic)",
            )
        if not isinstance(self.timestamp_iso, str) or not self.timestamp_iso.strip():
            raise OrchestrationEventError(
                "invalid_event_timestamp",
                "timestamp_iso must be a non-empty ISO-8601 string",
            )
        object.__setattr__(self, "message", _bounded_message(self.message))
        sanitized = _sanitize_scalar_metadata(self.metadata)
        object.__setattr__(self, "metadata", MappingProxyType(sanitized))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "app_id": self.app_id,
            "kind": self.kind.value,
            "sequence": self.sequence,
            "timestamp_iso": self.timestamp_iso,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


def public_orchestration_event(
    *,
    event_id: str,
    run_id: str,
    trace_id: str,
    app_id: str,
    kind: OrchestrationEventKind,
    sequence: int,
    message: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    timestamp_iso: str | None = None,
) -> OrchestrationEvent:
    """Construct an immutable, validated OrchestrationEvent."""
    ts = timestamp_iso or datetime.now(timezone.utc).isoformat()
    return OrchestrationEvent(
        event_id=event_id,
        run_id=run_id,
        trace_id=trace_id,
        app_id=app_id,
        kind=kind,
        sequence=sequence,
        timestamp_iso=ts,
        message=message,
        metadata=metadata or {},
    )
