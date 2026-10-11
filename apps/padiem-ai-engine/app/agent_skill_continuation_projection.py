"""Product-safe Agent/Skill continuation projection for Engine (#2786 S13-4 Phase 1).

The execution lifecycle contract for an approval continuation.  It is a pure
projection: it names facts the coordinator already established (the server-issued
continuation reference, the paused run identity, the trusted owner, the state
before and after the resume, whether the verified approval delta was applied).

It never invents state, never widens authority and never exposes authority
material: approval decisions, claim tokens, store-internal fingerprints and the
transport caller identity stay inside the Engine.

S13-4 Phase 3 adds a continuation **lifecycle** projection next to the run event
plane.  The lifecycle stream is derived from transitions the coordinator already
performed; it is never a second state machine.  See ``project_agent_lifecycle_events``.
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
from typing import Any

from padiem_ai_core.orchestration import OrchestrationResult

from app.agent_skill_authority import TrustedAgentSkillSelection
from app.orchestration_continuation import ContinuationRecord

ENGINE_AGENT_CONTINUATION_CONTRACT_FAMILY = "padiem.engine.agent-continuation"
ENGINE_AGENT_CONTINUATION_CONTRACT_MAJOR = 1
ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION = (
    f"{ENGINE_AGENT_CONTINUATION_CONTRACT_FAMILY}/{ENGINE_AGENT_CONTINUATION_CONTRACT_MAJOR}.0"
)

# ---------------------------------------------------------------------------
# S13-4 Phase 3: continuation lifecycle events
# ---------------------------------------------------------------------------
#
# Two planes, deliberately separate:
#
#   events               the frozen core run event plane (20 OrchestrationEventKind
#                        values).  Untouched, so existing consumers keep behaving.
#   lifecycle_events     the continuation transitions, projected from the record and
#                        the run events that evidence them.
#
# Ordering: every lifecycle event carries its own 1-based ``sequence`` because the
# core sequence restarts at 1 on the cancel path (``cancel_pause`` emits a single
# event with ``sequence=1``).  ``timestamp_iso`` comes from the run event that
# evidences the transition, so a request/state pair may share one timestamp;
# ``sequence`` -- not the timestamp -- establishes order.
#
# Expiry stays lazy: nothing is swept in the background, so an expiry is only
# observed when a read observes it.  ``transition="expired"`` therefore projects a
# single ``expiration_observed`` event and no run event backs it.

ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION = (
    f"{ENGINE_AGENT_CONTINUATION_CONTRACT_FAMILY}-lifecycle/"
    f"{ENGINE_AGENT_CONTINUATION_CONTRACT_MAJOR}.0"
)

_LIFECYCLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "resume": ("resume_requested", "resumed"),
    "cancel": ("cancel_requested", "cancelled"),
    "expired": ("expiration_observed",),
}
_LIFECYCLE_REQUEST_KINDS = frozenset({"resume_requested", "cancel_requested"})
_TERMINAL_LIFECYCLE_KINDS = frozenset({"resumed", "cancelled", "expiration_observed"})
_LIFECYCLE_BACKING_EVENT_KINDS = {"resume": "run_resumed", "cancel": "run_cancelled"}


def _lifecycle_event_id(*, continuation_id: str, kind: str, sequence: int) -> str:
    """Deterministic, non-secret event id for one continuation transition step."""

    digest = hashlib.sha256(f"{continuation_id}|{kind}|{sequence}".encode("utf-8")).hexdigest()
    return f"lce_{digest[:12]}"


def _lifecycle_backing_event(
    transition: str, public_events: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the run event that evidences the transition, if one is available."""

    expected = _LIFECYCLE_BACKING_EVENT_KINDS.get(transition)
    if expected is not None:
        for event in reversed(public_events):
            if event.get("kind") == expected:
                return event
    return public_events[-1] if public_events else None


def project_agent_lifecycle_events(
    *,
    continuation_id: str,
    transition: str,
    task_id: str | None = None,
    trace_id: str | None = None,
    events: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    """Return the bounded, ordered lifecycle events for one continuation transition.

    ``transition`` is one of ``resume``, ``cancel`` or ``expired``.  The projection
    names facts the coordinator already established; it never invents a timestamp,
    a subject or a state.  ``task_id`` and ``trace_id`` stay ``None`` when the caller
    has no trusted source for them (the engine does not synthesise them).
    """

    kinds = _LIFECYCLE_TRANSITIONS.get(transition)
    if kinds is None:
        raise ValueError("unknown lifecycle transition")
    if not isinstance(continuation_id, str) or not continuation_id:
        raise TypeError("continuation_id must be a non-empty string")

    backing: dict[str, Any] | None = None
    if transition != "expired":
        public_events = [event.to_public_dict() for event in events]
        backing = _lifecycle_backing_event(transition, public_events)

    projected: list[dict[str, Any]] = []
    for index, kind in enumerate(kinds, start=1):
        if kind in _LIFECYCLE_REQUEST_KINDS:
            derived_from = "store_transition"
            source_event_id: str | None = None
        elif transition == "expired":
            derived_from = "read_observation"
            source_event_id = None
        else:
            derived_from = "run_events" if backing is not None else "store_record"
            source_event_id = backing.get("event_id") if backing is not None else None
        projected.append(
            {
                "event_id": _lifecycle_event_id(
                    continuation_id=continuation_id, kind=kind, sequence=index
                ),
                "continuation_id": continuation_id,
                "task_id": task_id,
                "trace_id": trace_id,
                "sequence": index,
                "kind": kind,
                "terminal": kind in _TERMINAL_LIFECYCLE_KINDS,
                "timestamp_iso": backing.get("timestamp_iso") if backing is not None else None,
                "derived_from": derived_from,
                "source_event_id": source_event_id,
            }
        )
    return projected


def project_agent_continuation_result(
    result: OrchestrationResult,
    *,
    selection: TrustedAgentSkillSelection,
    record: ContinuationRecord,
    approval_delta_applied: bool,
) -> dict[str, Any]:
    """Return the bounded continuation block for a resumed run.

    ``approval_delta_applied`` is asserted by the caller: the Engine only reaches
    this projection after a verified approval decision was applied to the paused
    run, so it is recorded rather than derived from request input.
    """

    if not isinstance(result, OrchestrationResult):
        raise TypeError("result must be OrchestrationResult")
    if not isinstance(selection, TrustedAgentSkillSelection):
        raise TypeError("selection must be TrustedAgentSkillSelection")
    if not isinstance(record, ContinuationRecord):
        raise TypeError("record must be ContinuationRecord")

    execution = result.execution_result
    public_events = [event.to_public_dict() for event in result.events]
    resumed_state = (
        result.execution_state.value
        if result.execution_state is not None
        else execution.metadata.status.value
    )
    task_id = record.pause.run_id or (
        public_events[0].get("run_id") if public_events else None
    )
    trace_id = record.pause.trace_id or (
        public_events[0].get("trace_id") if public_events else None
    )
    definition = selection.authority.definition

    return {
        "continuation_contract_version": ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION,
        # CONTINUATION_ID: the server-issued continuation reference.  Phase 1 keeps
        # it on the continuation responses only (no run-response exposure).
        "continuation_id": record.continuation_ref,
        # TASK_ID: canonical alias of the paused run id, same rule as the task contract.
        "task_id": task_id,
        # OWNER_IDENTITY: trusted binding state; the transport caller is not projected.
        "owner_identity": {"subject_id": selection.subject_id},
        "current_state": record.state,
        "resume_target_state": resumed_state,
        # RESUME_AUTHORITY: a summary only.  The authority material itself (the
        # decided delta, its references and the verified decision) never crosses.
        "resume_authority": {
            "approval_delta_applied": bool(approval_delta_applied),
            "capability_required": list(definition.required_capabilities),
        },
        # S13-4 Phase 3: the continuation transition stream.  Exposed for internal
        # consumption only -- no compatibility guarantee (see the contract doc).
        "lifecycle_contract_version": ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION,
        "lifecycle_events": project_agent_lifecycle_events(
            continuation_id=record.continuation_ref,
            transition="resume",
            task_id=task_id,
            trace_id=trace_id,
            events=result.events,
        ),
        "audit_event": {
            "trace_id": trace_id,
            "event_count": len(public_events),
            "terminal_kind": public_events[-1].get("kind") if public_events else None,
        },
    }


def project_agent_cancellation_result(
    *,
    record: ContinuationRecord,
    committed: ContinuationRecord,
    events: Sequence[Any],
    reason: str,
) -> dict[str, Any]:
    """Return the bounded continuation block for a cancelled continuation.

    No owner identity is projected here: the cancel path has no trusted execution
    selection, so the Engine has no trusted source for a subject on this route.
    Recording that gap is deliberate (S13-4 Phase 2 decision) — the alternative
    would be to invent one or to add a runtime lookup to the cancel path.
    """

    if not isinstance(record, ContinuationRecord):
        raise TypeError("record must be ContinuationRecord")
    if not isinstance(committed, ContinuationRecord):
        raise TypeError("committed must be ContinuationRecord")
    if not isinstance(reason, str) or not reason:
        raise TypeError("reason must be a non-empty string")

    public_events = [event.to_public_dict() for event in events]
    task_id = record.pause.run_id or (
        public_events[0].get("run_id") if public_events else None
    )
    trace_id = record.pause.trace_id or (
        public_events[0].get("trace_id") if public_events else None
    )

    return {
        "continuation_contract_version": ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION,
        "continuation_id": record.continuation_ref,
        "task_id": task_id,
        "current_state": record.state,
        "terminal_state": committed.state,
        "cancel_reason": committed.cancel_reason or reason,
        # S13-4 Phase 3: the continuation transition stream.  Exposed for internal
        # consumption only -- no compatibility guarantee (see the contract doc).
        "lifecycle_contract_version": ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION,
        "lifecycle_events": project_agent_lifecycle_events(
            continuation_id=record.continuation_ref,
            transition="cancel",
            task_id=task_id,
            trace_id=trace_id,
            events=events,
        ),
        "audit_event": {
            "trace_id": trace_id,
            "event_count": len(public_events),
            "terminal_kind": public_events[-1].get("kind") if public_events else None,
        },
    }
