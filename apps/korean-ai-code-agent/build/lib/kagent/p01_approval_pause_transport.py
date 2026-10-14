"""#2946: Bounded Engine approval-pause wire projection for the P01 port.

The Engine remains the sole continuation authority. This module never
reconstructs ``ApprovalPause``, never mints a ``continuation_ref``, and never
opens a second continuation store or approval verifier. It only:

* fail-closes an Engine-issued pause wire against a closed public shape;
* strips ``approval_pause`` / ``continuation_state`` / ``continuation_ref`` so
  the generic Core public parser can reconstruct the orchestration result
  (that parser intentionally refuses those keys and must not be weakened);
* returns the opaque Engine ``continuation_ref`` for B54 WAITING_APPROVAL
  projection only.

Stripped keys never re-enter a reconstructed ``OrchestrationResult``. Resume,
cancel, and any owner-scoped decision surface remain later children.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

_ENGINE_CONTINUATION_REF_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")

# ApprovalPause.to_public_dict() closed shape. Extra keys are authority the
# public projection does not carry and must not be accepted or forwarded.
_APPROVAL_PAUSE_PUBLIC_KEYS = frozenset(
    {
        "status",
        "continuation_id",
        "run_id",
        "trace_id",
        "step_index",
        "agent_id",
        "tool_id",
        "requirement",
        "approval_scope",
        "created_at",
        "expires_at",
    }
)

# OrchestrationResult.to_public_dict().continuation_state closed shape.
_CONTINUATION_STATE_PUBLIC_KEYS = frozenset({"status", "decision_id"})

_APPROVAL_PAUSED_EVENT_KIND = "approval_paused"


class EngineApprovalPauseWireError(ValueError):
    """Fail-closed rejection of an unusable Engine approval-pause wire."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class EngineApprovalPauseWire:
    """Engine-issued opaque continuation identity plus safe public pause metadata.

    B54 only carries what the Engine already issued. ``continuation_ref`` is
    opaque and is never parsed into authority, stored locally, or rewritten.
    """

    approval_pause: Mapping[str, Any]
    continuation_ref: str
    continuation_state: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class P01PausedWireResult:
    """Port result when the Engine wire carried an approval pause (#2946)."""

    result: Any
    wire: EngineApprovalPauseWire


def _has_approval_paused_event(events: Any) -> bool:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)):
        return False
    for item in events:
        if isinstance(item, Mapping) and item.get("kind") == _APPROVAL_PAUSED_EVENT_KIND:
            return True
    return False


def _approval_paused_event_run_ids(events: Sequence[Any]) -> frozenset[str]:
    run_ids: set[str] = set()
    for item in events:
        if not isinstance(item, Mapping) or item.get("kind") != _APPROVAL_PAUSED_EVENT_KIND:
            continue
        run_id = item.get("run_id")
        if isinstance(run_id, str) and run_id:
            run_ids.add(run_id)
    return frozenset(run_ids)


def split_engine_approval_pause_wire(
    payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any], EngineApprovalPauseWire | None]:
    """Split an Engine orchestration payload into a Core-parseable body and wire.

    Returns ``(payload, None)`` unchanged when no pause wire is present so the
    completed-result path stays byte/contract compatible. A present pause wire
    is validated fail-closed and every pause/continuation key is removed from a
    shallow copy before the generic Core public parser runs.
    """
    if not isinstance(payload, Mapping):
        raise EngineApprovalPauseWireError(
            "invalid_engine_result",
            "Engine orchestration result must be a mapping.",
        )

    pause = payload.get("approval_pause")
    continuation_ref = payload.get("continuation_ref")
    continuation_state = payload.get("continuation_state")
    has_pause = pause is not None
    has_ref = continuation_ref is not None
    has_state = continuation_state is not None

    if not (has_pause or has_ref or has_state):
        return payload, None

    if (has_ref or has_state) and not has_pause:
        raise EngineApprovalPauseWireError(
            "continuation_without_pause",
            "Engine result carries continuation identity without an approval pause.",
        )
    if has_pause and not has_ref:
        raise EngineApprovalPauseWireError(
            "missing_continuation_ref",
            "Engine approval pause arrived without an Engine-issued continuation reference.",
        )
    if has_ref and (
        not isinstance(continuation_ref, str)
        or not _ENGINE_CONTINUATION_REF_RE.fullmatch(continuation_ref)
    ):
        raise EngineApprovalPauseWireError(
            "malformed_continuation_ref",
            "Engine continuation reference is not a bounded opaque identifier.",
        )
    if not isinstance(pause, Mapping):
        raise EngineApprovalPauseWireError(
            "invalid_engine_result",
            "Engine approval pause block must be an object.",
        )
    unknown_pause_keys = set(pause) - _APPROVAL_PAUSE_PUBLIC_KEYS
    if unknown_pause_keys:
        raise EngineApprovalPauseWireError(
            "unknown_extra_authority_fields",
            "Engine approval pause carries fields outside the public pause projection.",
        )
    if has_state:
        if not isinstance(continuation_state, Mapping):
            raise EngineApprovalPauseWireError(
                "invalid_engine_result",
                "Engine continuation state block must be an object.",
            )
        unknown_state_keys = set(continuation_state) - _CONTINUATION_STATE_PUBLIC_KEYS
        if unknown_state_keys:
            raise EngineApprovalPauseWireError(
                "unknown_extra_authority_fields",
                "Engine continuation state carries fields outside the public projection.",
            )

    events = payload.get("events")
    if not _has_approval_paused_event(events):
        raise EngineApprovalPauseWireError(
            "pause_without_lifecycle_evidence",
            "Engine approval pause has no APPROVAL_PAUSED lifecycle event.",
        )
    pause_run_id = pause.get("run_id")
    if isinstance(pause_run_id, str) and pause_run_id:
        if pause_run_id not in _approval_paused_event_run_ids(events):
            raise EngineApprovalPauseWireError(
                "correlation_mismatch",
                "Engine approval pause run identity does not match its lifecycle event.",
            )

    wire = EngineApprovalPauseWire(
        approval_pause=MappingProxyType(dict(pause)),
        continuation_ref=continuation_ref,
        continuation_state=(
            MappingProxyType(dict(continuation_state)) if has_state else None
        ),
    )
    stripped = dict(payload)
    stripped.pop("approval_pause", None)
    stripped.pop("continuation_ref", None)
    stripped.pop("continuation_state", None)
    return stripped, wire


__all__ = [
    "EngineApprovalPauseWire",
    "EngineApprovalPauseWireError",
    "P01PausedWireResult",
    "split_engine_approval_pause_wire",
]
