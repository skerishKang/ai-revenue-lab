from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _text(value: str, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or _CONTROL_RE.search(value):
        raise ContractError(f"{field_name} must be bounded non-empty text")
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain raw credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ClawUiEventKind(str, Enum):
    RUN_STATUS_CHANGED = "run_status_changed"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    HUMAN_TAKEOVER_REQUIRED = "human_takeover_required"
    HUMAN_TAKEOVER_RESOLVED = "human_takeover_resolved"
    ARTIFACT_READY = "artifact_ready"
    VERIFIED_DIFF_READY = "verified_diff_ready"
    DRAFT_PR_READY = "draft_pr_ready"
    USER_VISIBLE_ERROR = "user_visible_error"


@dataclass(frozen=True, slots=True)
class ClawUiEvent:
    event_id: str
    stream_id: str
    sequence: int
    run_id: str
    kind: ClawUiEventKind
    occurred_at: datetime
    summary: str
    subject_ref: str | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("event_id", "stream_id", "run_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or not 1 <= self.sequence <= 10_000_000:
            raise ContractError("sequence must be a positive bounded integer")
        if not isinstance(self.kind, ClawUiEventKind):
            try:
                object.__setattr__(self, "kind", ClawUiEventKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid UI event kind") from exc
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "summary", _text(self.summary, "summary", limit=1000))
        if self.subject_ref is not None:
            object.__setattr__(self, "subject_ref", _id(self.subject_ref, "subject_ref"))
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", _id(self.trace_id, "trace_id"))

    @property
    def fingerprint(self) -> str:
        payload = "|".join(
            (
                self.event_id,
                self.stream_id,
                str(self.sequence),
                self.run_id,
                self.kind.value,
                self.occurred_at.isoformat(),
                self.summary,
                self.subject_ref or "",
                self.trace_id or "",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ui-event.v1",
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "run_id": self.run_id,
            "kind": self.kind.value,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "summary": self.summary,
            "subject_ref": self.subject_ref,
            "trace_id": self.trace_id,
            "event_fingerprint": self.fingerprint,
            "hidden_reasoning": False,
            "tool_arguments": False,
            "tool_results": False,
            "raw_diff": False,
            "raw_terminal_output": False,
            "credential_values": False,
            "execution_authority": False,
        }


class ClawUiEventStream:
    def __init__(self) -> None:
        self._events: dict[str, list[ClawUiEvent]] = {}
        self._by_id: dict[tuple[str, str], ClawUiEvent] = {}

    def append(self, event: ClawUiEvent) -> None:
        if not isinstance(event, ClawUiEvent):
            raise ContractError("event must be ClawUiEvent")
        id_key = (event.stream_id, event.event_id)
        existing = self._by_id.get(id_key)
        if existing is not None:
            if existing == event:
                return
            raise ContractError("UI event ID replay conflicts with existing event")
        stream = self._events.setdefault(event.stream_id, [])
        expected = len(stream) + 1
        if event.sequence != expected:
            raise ContractError("UI event sequence must be contiguous")
        if stream and event.run_id != stream[0].run_id:
            raise ContractError("UI stream cannot mix run identities")
        if stream and event.occurred_at < stream[-1].occurred_at:
            raise ContractError("UI event time cannot regress")
        stream.append(event)
        self._by_id[id_key] = event

    def events(self, stream_id: str) -> tuple[ClawUiEvent, ...]:
        stream_id = _id(stream_id, "stream_id")
        return tuple(self._events.get(stream_id, ()))

    def safe_export(self, stream_id: str) -> dict[str, Any]:
        events = self.events(stream_id)
        return {
            "contract_version": "claw-ui-event-stream.v1",
            "stream_id": stream_id,
            "events": [event.safe_dict() for event in events],
            "ag_ui_canonical_authority": False,
            "b62_execution_authority": False,
        }


AG_UI_RUNTIME_DEPENDENCY_CONFIGURED = False
B62_EXECUTION_AUTHORITY = False
UI_STREAM_CONTAINS_HIDDEN_RUNTIME_STATE = False
