"""Provider/framework-neutral public-safe UI event contract (#1490, promoted Core slice).

Defines the shared event boundary that web/chat/mobile surfaces may consume for
run state, approvals, human takeover, artifacts, verified diffs and Draft-PR
readiness — without ever exposing P01 hidden state, model messages, tool
arguments/results, raw diffs, raw terminal output or credential values.

This module is the promoted, product-neutral equivalent of the accepted B54
compatibility contract (``apps/korean-ai-code-agent`` ``ui_events.py``). It
carries no provider, transport, or product-specific semantics and performs no
I/O; sequencing/replay enforcement is deterministic and in-memory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any

MAX_PUBLIC_UI_EVENT_SUMMARY_CHARS = 1_000
MAX_PUBLIC_UI_EVENT_SEQUENCE = 10_000_000

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Conservative credential-material guard. Text containing obvious secret
# assignments, bearer/JWT shapes, or well-known token prefixes is rejected
# outright instead of being redacted, so raw credential values can never enter
# the public-safe projection.
_CREDENTIAL_MATERIAL_RE = re.compile(
    r"(?is)("
    r"\b(api[_-]?key|apikey|auth[_-]?token|access[_-]?token|refresh[_-]?token"
    r"|secret|password|passwd|pwd|client[_-]?secret|private[_-]?key)\b\s*[:=]"
    r"|\bbearer\s+[A-Za-z0-9._-]{8,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\bghp_[A-Za-z0-9]{20,}"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r")"
)


class PublicUiEventError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("public UI event error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise PublicUiEventError(
            "invalid_public_ui_event", f"{field_name} must be a bounded safe identifier"
        )
    return value.strip()


def _text(value: str, field_name: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise PublicUiEventError(
            "invalid_public_ui_event", f"{field_name} must be a string"
        )
    value = value.strip()
    if not value or len(value) > limit or _CONTROL_RE.search(value):
        raise PublicUiEventError(
            "invalid_public_ui_event", f"{field_name} must be bounded non-empty text"
        )
    if _CREDENTIAL_MATERIAL_RE.search(value):
        raise PublicUiEventError(
            "credential_material_rejected",
            f"{field_name} must not contain credential material",
        )
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PublicUiEventError(
            "invalid_public_ui_event", f"{field_name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


class PublicUiEventKind(str, Enum):
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
class PublicUiEvent:
    """One bounded, public-safe UI event.

    Only run/trace/subject references and a bounded user-visible summary are
    carried. There is intentionally no arbitrary payload mapping field.
    """

    event_id: str
    stream_id: str
    sequence: int
    run_id: str
    kind: PublicUiEventKind
    occurred_at: datetime
    summary: str
    subject_ref: str | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("event_id", "stream_id", "run_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or not 1 <= self.sequence <= MAX_PUBLIC_UI_EVENT_SEQUENCE
        ):
            raise PublicUiEventError(
                "invalid_public_ui_event",
                "sequence must be a positive bounded integer",
            )
        if not isinstance(self.kind, PublicUiEventKind):
            try:
                object.__setattr__(self, "kind", PublicUiEventKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise PublicUiEventError(
                    "invalid_public_ui_event", "kind must be PublicUiEventKind"
                ) from exc
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", limit=MAX_PUBLIC_UI_EVENT_SUMMARY_CHARS)
        )
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
            "contract_version": "padiem-public-ui-event.v1",
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
            "model_messages": False,
            "tool_arguments": False,
            "tool_results": False,
            "raw_diff": False,
            "raw_terminal_output": False,
            "credential_values": False,
            "execution_authority": False,
        }


class PublicUiEventStream:
    """In-memory, per-stream event log with deterministic sequencing rules.

    - sequences must be contiguous per stream (1, 2, 3, ...);
    - replaying an identical event is idempotent;
    - replaying the same event ID with different content is rejected;
    - one stream can never mix run identities;
    - event time can never regress within a stream.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[PublicUiEvent]] = {}
        self._by_id: dict[tuple[str, str], PublicUiEvent] = {}

    def append(self, event: PublicUiEvent) -> None:
        if not isinstance(event, PublicUiEvent):
            raise PublicUiEventError(
                "invalid_public_ui_event", "event must be PublicUiEvent"
            )
        id_key = (event.stream_id, event.event_id)
        existing = self._by_id.get(id_key)
        if existing is not None:
            if existing == event:
                return
            raise PublicUiEventError(
                "public_ui_event_id_conflict",
                "UI event ID replay conflicts with existing event",
            )
        stream = self._events.setdefault(event.stream_id, [])
        expected = len(stream) + 1
        if event.sequence != expected:
            raise PublicUiEventError(
                "public_ui_sequence_not_contiguous",
                "UI event sequence must be contiguous",
            )
        if stream and event.run_id != stream[0].run_id:
            raise PublicUiEventError(
                "public_ui_stream_run_mismatch",
                "UI stream cannot mix run identities",
            )
        if stream and event.occurred_at < stream[-1].occurred_at:
            raise PublicUiEventError(
                "public_ui_time_regression",
                "UI event time cannot regress",
            )
        stream.append(event)
        self._by_id[id_key] = event

    def events(self, stream_id: str) -> tuple[PublicUiEvent, ...]:
        stream_id = _id(stream_id, "stream_id")
        return tuple(self._events.get(stream_id, ()))

    def safe_export(self, stream_id: str) -> dict[str, Any]:
        events = self.events(stream_id)
        return {
            "contract_version": "padiem-public-ui-event-stream.v1",
            "stream_id": stream_id,
            "events": [event.safe_dict() for event in events],
            "ag_ui_canonical_authority": False,
            "b62_execution_authority": False,
        }


AG_UI_RUNTIME_DEPENDENCY_CONFIGURED = False
B62_EXECUTION_AUTHORITY = False
PUBLIC_UI_STREAM_CONTAINS_HIDDEN_RUNTIME_STATE = False

__all__ = [
    "MAX_PUBLIC_UI_EVENT_SUMMARY_CHARS",
    "MAX_PUBLIC_UI_EVENT_SEQUENCE",
    "PublicUiEventError",
    "PublicUiEventKind",
    "PublicUiEvent",
    "PublicUiEventStream",
    "AG_UI_RUNTIME_DEPENDENCY_CONFIGURED",
    "B62_EXECUTION_AUTHORITY",
    "PUBLIC_UI_STREAM_CONTAINS_HIDDEN_RUNTIME_STATE",
]
