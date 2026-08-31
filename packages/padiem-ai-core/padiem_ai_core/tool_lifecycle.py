"""Normalized Tool/Connector lifecycle event contract for P01.

The existing ToolEvent remains the execution result primitive. This module adds
an immutable lifecycle envelope suitable for orchestration/event consumers while
keeping raw arguments, outputs, credentials and hidden reasoning out of the
normalized public event.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOOL_ID_RE = re.compile(r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_CONNECTOR_ID_RE = re.compile(r"^connector:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$")
_SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_EVENT_METADATA_KEYS = 16
MAX_EVENT_STRING_CHARS = 1_000


class ToolLifecycleError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_IDENTIFIER_RE.fullmatch(code):
            raise ValueError("tool lifecycle error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class ToolLifecycleKind(str, Enum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"


class ConnectorLifecycleKind(str, Enum):
    RESOLVED = "resolved"
    AUTHORIZATION_REQUIRED = "authorization_required"
    AUTHORIZED = "authorized"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"
    TOOL_BOUND = "tool_bound"


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ToolLifecycleError("invalid_tool_lifecycle_event", f"{name} must be a string")
    if value.startswith("connector:") or ("connector" in name and "@" in value):
        if not _CONNECTOR_ID_RE.fullmatch(value):
            raise ToolLifecycleError("invalid_tool_lifecycle_event", f"{name} must match canonical Connector id grammar")
        return value
    if value.startswith("tool:") or ("tool" in name and "@" in value):
        if not _TOOL_ID_RE.fullmatch(value):
            raise ToolLifecycleError("invalid_tool_lifecycle_event", f"{name} must match canonical Tool id grammar")
        return value
    if not _SAFE_TAG_RE.fullmatch(value):
        raise ToolLifecycleError("invalid_tool_lifecycle_event", f"{name} must be a bounded safe identifier")
    return value


def _scalar_metadata(metadata: Mapping[str, object] | None) -> dict[str, str | int | float | bool | None]:
    values = {} if metadata is None else dict(metadata)
    if len(values) > MAX_EVENT_METADATA_KEYS:
        raise ToolLifecycleError("tool_event_budget_exceeded", "event metadata contains too many fields")
    result: dict[str, str | int | float | bool | None] = {}
    for key, value in values.items():
        safe_key = _identifier("metadata key", key)
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ToolLifecycleError("invalid_tool_lifecycle_event", "event metadata values must be scalar")
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ToolLifecycleError("invalid_tool_lifecycle_event", "event metadata floats must be finite")
        if isinstance(value, str) and len(value) > MAX_EVENT_STRING_CHARS:
            raise ToolLifecycleError("tool_event_budget_exceeded", "event metadata string exceeds the bounded event limit")
        result[safe_key] = value
    return result


@dataclass(frozen=True, slots=True)
class ToolLifecycleEvent:
    event_id: str
    run_id: str
    kind: ToolLifecycleKind
    tool_id: str
    sequence: int
    connector_id: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    metadata: Mapping[str, object] = ()

    def __post_init__(self) -> None:
        for name in ("event_id", "run_id", "tool_id"):
            object.__setattr__(self, name, _identifier(name, getattr(self, name)))
        if self.connector_id is not None:
            object.__setattr__(self, "connector_id", _identifier("connector_id", self.connector_id))
        if not isinstance(self.kind, ToolLifecycleKind):
            raise ToolLifecycleError("invalid_tool_lifecycle_event", "kind must be ToolLifecycleKind")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ToolLifecycleError("invalid_tool_lifecycle_event", "sequence must be a positive integer")
        if self.duration_ms is not None:
            if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
                raise ToolLifecycleError("invalid_tool_lifecycle_event", "duration_ms must be a non-negative integer")
        if self.error_code is not None:
            object.__setattr__(self, "error_code", _identifier("error_code", self.error_code))
        object.__setattr__(self, "metadata", _scalar_metadata(self.metadata if isinstance(self.metadata, Mapping) else None))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "kind": self.kind.value,
            "tool_id": self.tool_id,
            "sequence": self.sequence,
            "connector_id": self.connector_id,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ConnectorLifecycleEvent:
    event_id: str
    run_id: str
    kind: ConnectorLifecycleKind
    connector_id: str
    sequence: int
    tool_id: str | None = None
    metadata: Mapping[str, object] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier("event_id", self.event_id))
        object.__setattr__(self, "run_id", _identifier("run_id", self.run_id))
        object.__setattr__(self, "connector_id", _identifier("connector_id", self.connector_id))
        if self.tool_id is not None:
            object.__setattr__(self, "tool_id", _identifier("tool_id", self.tool_id))
        if not isinstance(self.kind, ConnectorLifecycleKind):
            raise ToolLifecycleError("invalid_connector_lifecycle_event", "kind must be ConnectorLifecycleKind")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ToolLifecycleError("invalid_connector_lifecycle_event", "sequence must be a positive integer")
        object.__setattr__(self, "metadata", _scalar_metadata(self.metadata if isinstance(self.metadata, Mapping) else None))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "kind": self.kind.value,
            "connector_id": self.connector_id,
            "tool_id": self.tool_id,
            "sequence": self.sequence,
            "metadata": dict(self.metadata),
        }
