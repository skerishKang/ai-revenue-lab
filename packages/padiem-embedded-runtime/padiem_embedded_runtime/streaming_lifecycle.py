"""Display-only streaming lifecycle/error/retry presentation for IP-SIDECAR (S7).

Canonical public event issuance, execution truth, sequence authority, and
retry/cancel semantics belong to Core/Engine/P01 (#1490 promoted boundary:
``padiem_ai_core.public_ui_events`` kinds and ``execution_state_machine``
run states). This module only projects already-public event facts into
bounded, deterministic, display-only views: it never transports, never
executes retries or cancellation, owns no clock, enforces no transition
table, and never turns a failure into a success.

Pipeline:

    public-safe upstream/host-relayed event facts
      -> bounded allowlisted normalization
      -> display-only projection (no execution side effects)
      -> duplicate-tolerant, conflict-degrading feed ordering
      -> host-safe unavailable/degraded/rejected states
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from .errors import SidecarContractError

# ---------------------------------------------------------------------------
# Display-only projection of the #1490 public event vocabulary. These are
# presentation strings; the issuing/sequencing authority stays in Core/Engine.
# ---------------------------------------------------------------------------

STREAM_EVENT_KINDS = frozenset(
    {
        "run_status_changed",
        "approval_required",
        "approval_resolved",
        "human_takeover_required",
        "human_takeover_resolved",
        "artifact_ready",
        "verified_diff_ready",
        "draft_pr_ready",
        "user_visible_error",
    }
)

STREAM_RUN_STATUSES = frozenset(
    {
        "created",
        "running",
        "recovering",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "expired",
    }
)

PHASE_UNAVAILABLE = "unavailable"

STATUS_STAGED = "staged"
STATUS_REJECTED = "rejected"
STATUS_PRESENTED = "presented"

ORDER_FRESH = "fresh"
ORDER_DUPLICATE = "duplicate"
ORDER_CONFLICT = "conflict"

REASON_INVALID_HOST_INPUT = "INVALID_HOST_INPUT"
REASON_OUT_OF_ORDER_REPLAY = "OUT_OF_ORDER_REPLAY"
_LIFECYCLE_REASONS = frozenset({"", REASON_INVALID_HOST_INPUT, REASON_OUT_OF_ORDER_REPLAY})

ERROR_REJECTION_REASONS = frozenset(
    {
        "MALFORMED_INPUT",
        "UNKNOWN_FIELDS",
        "INVALID_REASON_CODE",
        "INVALID_RUN_ID",
        "INVALID_SUMMARY",
    }
)

AFFORDANCE_REJECTION_REASONS = frozenset(
    {
        "MALFORMED_INPUT",
        "UNKNOWN_FIELDS",
        "INVALID_AFFORDANCE",
        "INVALID_RUN_ID",
        "INVALID_RUN_STATUS",
        "STATE_DOES_NOT_PERMIT",
    }
)

MAX_EVENT_SEQUENCE = 10_000_000  # mirrors the canonical public event bound
MAX_STREAM_SUMMARY_CHARS = 280
MAX_IDENTIFIER_CHARS = 128

PUBLIC_ERROR_REASON_CODES = frozenset(
    {
        "RUN_FAILED",
        "RUN_TIMED_OUT",
        "RUN_CANCELLED",
        "STREAM_INTERRUPTED",
        "UPSTREAM_UNAVAILABLE",
    }
)

RETRY_AFFORDANCES = frozenset({"retry", "reconnect", "cancel"})
AFFORDANCE_PERMITTED_STATUSES: Mapping[str, frozenset[str]] = {
    "retry": frozenset({"failed", "timed_out"}),
    "reconnect": frozenset({"failed", "timed_out", "cancelled"}),
    "cancel": frozenset({"created", "running", "recovering", "waiting_approval"}),
}

ALLOWED_LIFECYCLE_FIELDS = frozenset(
    {
        "kind",
        "run_status",
        "stream_id",
        "run_id",
        "event_id",
        "trace_id",
        "subject_ref",
        "sequence",
        "summary",
    }
)
ALLOWED_ERROR_FIELDS = frozenset({"reason_code", "run_id", "summary"})
ALLOWED_AFFORDANCE_FIELDS = frozenset({"affordance", "run_id", "run_status"})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_URL_SHAPE_RE = re.compile(r"://")
_GUARDED_VALUE_RE = re.compile(
    r"secret|passwd|password|credential|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization|"
    r"reasoning|chain[_-]of[_-]thought|tool[_-]?arg|stdout|stderr|traceback|"
    r"diff --git|unified diff|<\s*/?\s*[a-z]",
    re.IGNORECASE,
)


def _valid_identifier(value: object, limit: int = MAX_IDENTIFIER_CHARS) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= limit
        and _IDENTIFIER_RE.fullmatch(value) is not None
        and _GUARDED_VALUE_RE.search(value) is None
    )


def _valid_summary(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_STREAM_SUMMARY_CHARS
        and _GUARDED_VALUE_RE.search(value) is None
        and _URL_SHAPE_RE.search(value) is None
    )


def _unavailable(reason: str) -> "StreamLifecyclePresentation":
    return StreamLifecyclePresentation(
        run_status=PHASE_UNAVAILABLE, sequence=None, degraded=True, reason_code=reason
    )


@dataclass(frozen=True)
class StreamLifecyclePresentation:
    """Display-only projection of one public-safe stream/run event fact.

    ``run_status`` is the projected upstream state string (or
    ``unavailable``); this view never enforces transitions and never derives
    execution truth.
    """

    kind: str = ""
    run_status: str = PHASE_UNAVAILABLE
    stream_id: str = ""
    run_id: str = ""
    event_id: str = ""
    trace_id: str = ""
    subject_ref: str = ""
    sequence: int | None = None
    summary: str = ""
    degraded: bool = False
    reason_code: str = ""

    def __post_init__(self) -> None:
        if self.kind not in STREAM_EVENT_KINDS and self.kind != "":
            raise SidecarContractError("event kind is not an allowlisted kind")
        if self.run_status not in STREAM_RUN_STATUSES | {PHASE_UNAVAILABLE}:
            raise SidecarContractError("run status is not an allowlisted display state")
        if self.reason_code not in _LIFECYCLE_REASONS:
            raise SidecarContractError("lifecycle reason is not an allowlisted code")
        if self.degraded:
            if self.run_status != PHASE_UNAVAILABLE:
                raise SidecarContractError("degraded lifecycle views are unavailable")
            if not self.reason_code:
                raise SidecarContractError("degraded lifecycle views carry a reason code")
        elif not self.kind:
            raise SidecarContractError("presented lifecycle views carry an allowlisted kind")
        if self.sequence is not None and (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
            or self.sequence > MAX_EVENT_SEQUENCE
        ):
            raise SidecarContractError("sequence exceeds the canonical public bound")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "run_status": self.run_status,
            "stream_id": self.stream_id,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "subject_ref": self.subject_ref,
            "sequence": self.sequence,
            "summary": self.summary,
            "degraded": self.degraded,
            "reason_code": self.reason_code,
        }


def present_stream_lifecycle(raw: Mapping[str, object]) -> StreamLifecyclePresentation:
    """Project one untrusted public-safe event fact into a display view.

    Only allowlisted kinds/run-states and bounded identifier/sequence/summary
    fields pass. Raw provider/tool/terminal/diff/URL/secret-shaped material
    can never pass; any malformed input degrades to
    ``unavailable``/``INVALID_HOST_INPUT`` instead of raising.
    """
    if not isinstance(raw, Mapping):
        return _unavailable(REASON_INVALID_HOST_INPUT)
    if any(k not in ALLOWED_LIFECYCLE_FIELDS for k in raw):
        return _unavailable(REASON_INVALID_HOST_INPUT)

    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in STREAM_EVENT_KINDS:
        return _unavailable(REASON_INVALID_HOST_INPUT)

    run_status_raw = raw.get("run_status", "")
    if kind == "run_status_changed":
        if (
            not isinstance(run_status_raw, str)
            or run_status_raw not in STREAM_RUN_STATUSES
        ):
            return _unavailable(REASON_INVALID_HOST_INPUT)
        run_status = run_status_raw
    else:
        if run_status_raw != "" and (
            not isinstance(run_status_raw, str)
            or run_status_raw not in STREAM_RUN_STATUSES
        ):
            return _unavailable(REASON_INVALID_HOST_INPUT)
        run_status = run_status_raw if isinstance(run_status_raw, str) else ""
        if not run_status:
            run_status = PHASE_UNAVAILABLE

    refs: dict[str, str] = {}
    for name in ("stream_id", "run_id", "event_id", "trace_id", "subject_ref"):
        value = raw.get(name, "")
        if value == "":
            refs[name] = ""
            continue
        if not _valid_identifier(value):
            return _unavailable(REASON_INVALID_HOST_INPUT)
        refs[name] = value  # type: ignore[assignment]

    sequence = raw.get("sequence")
    if sequence is not None and (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 0
        or sequence > MAX_EVENT_SEQUENCE
    ):
        return _unavailable(REASON_INVALID_HOST_INPUT)

    summary = raw.get("summary", "")
    if summary != "" and not _valid_summary(summary):
        return _unavailable(REASON_INVALID_HOST_INPUT)

    return StreamLifecyclePresentation(
        kind=kind,
        run_status=run_status,
        stream_id=refs["stream_id"],
        run_id=refs["run_id"],
        event_id=refs["event_id"],
        trace_id=refs["trace_id"],
        subject_ref=refs["subject_ref"],
        sequence=sequence,
        summary=summary if isinstance(summary, str) else "",
        degraded=False,
        reason_code="",
    )


@dataclass(frozen=True)
class _FeedState:
    stream_id: str = ""
    last_sequence: int | None = None
    last_event_id: str = ""


class StreamFeedGuard:
    """Per-instance display-ordering guard for one stream feed.

    Duplicate replays of the same bounded event are display-idempotent;
    backward or same-sequence-different-event input conflicts and degrades to
    an ``unavailable``/``OUT_OF_ORDER_REPLAY`` view without advancing state.
    It never fabricates continuity and never re-implements #1490 canonical
    stream sequencing: forward jumps are passed through unmodified.
    """

    def __init__(self) -> None:
        self._state: _FeedState | None = None

    def observe(
        self, presentation: StreamLifecyclePresentation
    ) -> tuple[StreamLifecyclePresentation, str]:
        if not isinstance(presentation, StreamLifecyclePresentation):
            raise SidecarContractError("guard observes only lifecycle presentations")
        if presentation.degraded or presentation.sequence is None:
            return presentation, ORDER_FRESH

        state = self._state
        if state is not None:
            if (
                state.stream_id
                and presentation.stream_id
                and state.stream_id != presentation.stream_id
            ):
                return _unavailable(REASON_OUT_OF_ORDER_REPLAY), ORDER_CONFLICT
            if presentation.sequence < state.last_sequence or (
                presentation.sequence == state.last_sequence
                and presentation.event_id != state.last_event_id
            ):
                return _unavailable(REASON_OUT_OF_ORDER_REPLAY), ORDER_CONFLICT
            if presentation.sequence == state.last_sequence:
                return presentation, ORDER_DUPLICATE

        self._state = _FeedState(
            stream_id=presentation.stream_id,
            last_sequence=presentation.sequence,
            last_event_id=presentation.event_id,
        )
        return presentation, ORDER_FRESH


@dataclass(frozen=True)
class PublicErrorPresentation:
    """Bounded public-safe error display; never carries raw upstream bodies."""

    status: str
    reason_code: str = ""
    run_id: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if self.status not in (STATUS_PRESENTED, STATUS_REJECTED):
            raise SidecarContractError("error status is not an allowlisted code")
        if self.status == STATUS_PRESENTED:
            if self.reason_code not in PUBLIC_ERROR_REASON_CODES:
                raise SidecarContractError("presented error reason is not allowlisted")
        else:
            if self.reason_code not in ERROR_REJECTION_REASONS:
                raise SidecarContractError("error rejection reason is not allowlisted")
            if self.run_id or self.summary:
                raise SidecarContractError("rejected errors never echo values")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "run_id": self.run_id,
            "summary": self.summary,
        }


def present_public_error(raw: Mapping[str, object]) -> PublicErrorPresentation:
    """Project one ``user_visible_error``-style fact into a safe display view.

    Only allowlisted public reason codes pass; the bounded summary is
    optional display text, never an error authority. Raw provider/model
    responses, HTTP bodies, stack traces, tool args/results, terminal output,
    diffs, URLs, paths, and credentials fail closed without retention.
    """
    if not isinstance(raw, Mapping):
        return PublicErrorPresentation(status=STATUS_REJECTED, reason_code="MALFORMED_INPUT")
    if any(k not in ALLOWED_ERROR_FIELDS for k in raw):
        return PublicErrorPresentation(status=STATUS_REJECTED, reason_code="UNKNOWN_FIELDS")
    reason = raw.get("reason_code")
    if not isinstance(reason, str) or reason not in PUBLIC_ERROR_REASON_CODES:
        return PublicErrorPresentation(
            status=STATUS_REJECTED, reason_code="INVALID_REASON_CODE"
        )
    run_id = raw.get("run_id", "")
    if run_id != "" and not _valid_identifier(run_id):
        return PublicErrorPresentation(status=STATUS_REJECTED, reason_code="INVALID_RUN_ID")
    summary = raw.get("summary", "")
    if summary != "" and not _valid_summary(summary):
        return PublicErrorPresentation(
            status=STATUS_REJECTED, reason_code="INVALID_SUMMARY"
        )
    return PublicErrorPresentation(
        status=STATUS_PRESENTED,
        reason_code=reason,
        run_id=run_id if isinstance(run_id, str) else "",
        summary=summary if isinstance(summary, str) else "",
    )


@dataclass(frozen=True)
class RetryAffordancePresentation:
    """Display-only staged retry/reconnect/cancel affordance.

    Staging is a host-handoff presentation state only: no retry execution,
    no backoff timer, no automatic loop, no cancellation, no transport, and
    no clock ownership.
    """

    status: str
    affordance: str = ""
    run_id: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        if self.status not in (STATUS_STAGED, STATUS_REJECTED):
            raise SidecarContractError("affordance status is not an allowlisted code")
        if self.status == STATUS_STAGED:
            if self.affordance not in RETRY_AFFORDANCES:
                raise SidecarContractError("staged affordance must be allowlisted")
            if not _valid_identifier(self.run_id):
                raise SidecarContractError("staged affordance requires a bounded run_id")
            if self.reason_code:
                raise SidecarContractError("staged affordances carry no reason code")
        else:
            if self.affordance or self.run_id:
                raise SidecarContractError("rejected affordances never echo values")
            if self.reason_code not in AFFORDANCE_REJECTION_REASONS:
                raise SidecarContractError("affordance reason is not allowlisted")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "affordance": self.affordance,
            "run_id": self.run_id,
            "reason_code": self.reason_code,
        }


def present_retry_affordance(raw: Mapping[str, object]) -> RetryAffordancePresentation:
    """Stage one affordance only when the projected public state permits it.

    The sidecar never converts a failure into success and never acts on the
    affordance itself; permitted staging is handed back for the product
    adapter's authenticated delivery path.
    """
    if not isinstance(raw, Mapping):
        return RetryAffordancePresentation(
            status=STATUS_REJECTED, reason_code="MALFORMED_INPUT"
        )
    if any(k not in ALLOWED_AFFORDANCE_FIELDS for k in raw):
        return RetryAffordancePresentation(
            status=STATUS_REJECTED, reason_code="UNKNOWN_FIELDS"
        )
    affordance = raw.get("affordance")
    if not isinstance(affordance, str) or affordance not in RETRY_AFFORDANCES:
        return RetryAffordancePresentation(
            status=STATUS_REJECTED, reason_code="INVALID_AFFORDANCE"
        )
    run_id = raw.get("run_id")
    if not _valid_identifier(run_id):
        return RetryAffordancePresentation(
            status=STATUS_REJECTED, reason_code="INVALID_RUN_ID"
        )
    run_status = raw.get("run_status")
    if not isinstance(run_status, str) or run_status not in STREAM_RUN_STATUSES:
        return RetryAffordancePresentation(
            status=STATUS_REJECTED, reason_code="INVALID_RUN_STATUS"
        )
    if run_status not in AFFORDANCE_PERMITTED_STATUSES[affordance]:
        return RetryAffordancePresentation(
            status=STATUS_REJECTED, reason_code="STATE_DOES_NOT_PERMIT"
        )
    return RetryAffordancePresentation(
        status=STATUS_STAGED, affordance=affordance, run_id=run_id
    )
