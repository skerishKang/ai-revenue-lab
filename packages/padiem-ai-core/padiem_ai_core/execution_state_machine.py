"""Product-neutral deterministic execution state machine for Padiem AI Core (P01).

Unifies recovery, retry, approval-pause, resume, timeout, cancellation, and
idempotency replay into a bounded, deterministic lifecycle state machine.

Invariants:
- retry != provider fallback: Core recovery is step-level retry only; B14 owns Provider routing.
- resume != retry: Resume continues an existing paused continuation; retry creates a new attempt.
- approval != permission expansion: Approval verifies a specific action within existing bounds.
- timeout != cancellation: Timeout is budget exhaustion; cancellation is explicit abort.
- idempotency replay != rerun: Replaying a cached result skips pipeline execution entirely.
- Terminal states reject all subsequent transitions (fail closed).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Callable

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_STATE_TRANSITIONS = 64
MAX_METADATA_KEYS = 32
MAX_REASON_CHARS = 500


class ExecutionStateMachineError(ValueError):
    """Base error for execution state machine contract violations."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class InvalidTransitionError(ExecutionStateMachineError):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, from_state: ExecutionState, to_state: ExecutionState, reason: str = "") -> None:
        msg = f"Invalid state transition from '{from_state.value}' to '{to_state.value}'"
        if reason:
            msg += f": {reason}"
        super().__init__("invalid_transition", msg)
        self.from_state = from_state
        self.to_state = to_state


class ExecutionState(str, Enum):
    """Discrete, deterministic lifecycle states for P01 execution."""

    CREATED = "created"
    RUNNING = "running"
    RECOVERING = "recovering"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    EXPIRED = "expired"


# Canonical valid transition graph
_VALID_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.CREATED: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
    }),
    ExecutionState.RUNNING: frozenset({
        ExecutionState.RECOVERING,
        ExecutionState.WAITING_APPROVAL,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT,
    }),
    ExecutionState.RECOVERING: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.WAITING_APPROVAL,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT,
    }),
    ExecutionState.WAITING_APPROVAL: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.CANCELLED,
        ExecutionState.EXPIRED,
        ExecutionState.FAILED,
    }),
    # Terminal states have no valid outgoing transitions
    ExecutionState.COMPLETED: frozenset(),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.TIMED_OUT: frozenset(),
    ExecutionState.EXPIRED: frozenset(),
}

_TERMINAL_STATES = frozenset({
    ExecutionState.COMPLETED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
    ExecutionState.TIMED_OUT,
    ExecutionState.EXPIRED,
})


def is_terminal_state(state: ExecutionState) -> bool:
    """Return True if the state is an immutable terminal state."""
    return state in _TERMINAL_STATES


def is_valid_transition(from_state: ExecutionState, to_state: ExecutionState) -> bool:
    """Return True if transitioning from from_state to to_state is permitted."""
    allowed = _VALID_TRANSITIONS.get(from_state, frozenset())
    return to_state in allowed


def _sanitize_metadata(metadata: Mapping[str, Any] | None) -> MappingProxyType[str, Any]:
    if metadata is None:
        return MappingProxyType({})
    if not isinstance(metadata, Mapping):
        raise ExecutionStateMachineError("invalid_metadata", "metadata must be a mapping")
    if len(metadata) > MAX_METADATA_KEYS:
        raise ExecutionStateMachineError("metadata_budget_exceeded", f"metadata exceeds {MAX_METADATA_KEYS} keys")
    sanitized: dict[str, Any] = {}
    for k, v in metadata.items():
        if not isinstance(k, str) or not _IDENTIFIER_RE.fullmatch(k):
            raise ExecutionStateMachineError("invalid_metadata_key", f"key '{k}' must be a safe identifier")
        if isinstance(v, (str, int, float, bool)) or v is None:
            sanitized[k] = v
        else:
            sanitized[k] = str(v)
    return MappingProxyType(sanitized)


@dataclass(frozen=True, slots=True)
class ExecutionTransition:
    """Immutable record of an authorized state transition."""

    sequence: int
    from_state: ExecutionState
    to_state: ExecutionState
    reason: str
    timestamp_iso: str
    attempt_number: int = 1
    metadata: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.from_state, ExecutionState):
            raise ExecutionStateMachineError("invalid_transition", "from_state must be ExecutionState")
        if not isinstance(self.to_state, ExecutionState):
            raise ExecutionStateMachineError("invalid_transition", "to_state must be ExecutionState")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ExecutionStateMachineError("invalid_transition", "reason must be a non-empty string")
        if len(self.reason) > MAX_REASON_CHARS:
            raise ExecutionStateMachineError("reason_budget_exceeded", f"reason exceeds {MAX_REASON_CHARS} chars")
        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int) or self.attempt_number < 1:
            raise ExecutionStateMachineError("invalid_attempt", "attempt_number must be an integer >= 1")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ExecutionStateMachineError("invalid_sequence", "sequence must be an integer >= 1")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
            "timestamp": self.timestamp_iso,
            "attempt_number": self.attempt_number,
            "metadata": dict(self.metadata),
        }


class ExecutionStateMachine:
    """Bounded, deterministic state machine governing pipeline execution."""

    def __init__(
        self,
        *,
        initial_state: ExecutionState = ExecutionState.CREATED,
        max_retries: int = 3,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(initial_state, ExecutionState):
            raise ExecutionStateMachineError("invalid_initial_state", "initial_state must be ExecutionState")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ExecutionStateMachineError("invalid_max_retries", "max_retries must be an integer >= 0")

        self._state = initial_state
        self._max_retries = max_retries
        self._retries_used = 0
        self._attempt_number = 1
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._transitions: list[ExecutionTransition] = []
        self._seq = 1

    @property
    def state(self) -> ExecutionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return is_terminal_state(self._state)

    @property
    def attempt_number(self) -> int:
        return self._attempt_number

    @property
    def retries_used(self) -> int:
        return self._retries_used

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def remaining_retries(self) -> int:
        return max(0, self._max_retries - self._retries_used)

    @property
    def transitions(self) -> tuple[ExecutionTransition, ...]:
        return tuple(self._transitions)

    def _now_iso(self) -> str:
        dt = self._clock()
        if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
            raise ExecutionStateMachineError("invalid_clock", "clock must return a timezone-aware datetime")
        return dt.isoformat()

    def transition_to(
        self,
        target_state: ExecutionState,
        reason: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionTransition:
        """Execute a validated transition to target_state."""
        if not isinstance(target_state, ExecutionState):
            raise ExecutionStateMachineError("invalid_target_state", "target_state must be ExecutionState")
        if not isinstance(reason, str) or not reason.strip():
            raise ExecutionStateMachineError("invalid_reason", "reason must be a non-empty string")

        if len(self._transitions) >= MAX_STATE_TRANSITIONS:
            raise ExecutionStateMachineError("transition_budget_exceeded", f"exceeded maximum {MAX_STATE_TRANSITIONS} transitions")

        if not is_valid_transition(self._state, target_state):
            raise InvalidTransitionError(self._state, target_state, reason)

        sanitized_meta = _sanitize_metadata(metadata)
        transition = ExecutionTransition(
            sequence=self._seq,
            from_state=self._state,
            to_state=target_state,
            reason=reason.strip(),
            timestamp_iso=self._now_iso(),
            attempt_number=self._attempt_number,
            metadata=sanitized_meta,
        )

        self._state = target_state
        self._transitions.append(transition)
        self._seq += 1
        return transition

    # Convenience Transition Operations

    def start(self, reason: str = "run_started", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.RUNNING, reason, metadata=metadata)

    def start_recovery(self, reason: str = "failure_encountered", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.RECOVERING, reason, metadata=metadata)

    def retry(self, reason: str = "retry_step", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        """Execute a step retry attempt within the bounded retry budget."""
        if self._state is not ExecutionState.RECOVERING:
            raise InvalidTransitionError(self._state, ExecutionState.RUNNING, "retry is only allowed from RECOVERING")
        if self._retries_used >= self._max_retries:
            raise ExecutionStateMachineError("retry_budget_exhausted", f"max retries ({self._max_retries}) exhausted")

        self._retries_used += 1
        self._attempt_number += 1
        return self.transition_to(ExecutionState.RUNNING, reason, metadata=metadata)

    def pause_for_approval(self, reason: str = "approval_required", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.WAITING_APPROVAL, reason, metadata=metadata)

    def resume(self, reason: str = "explicit_resume", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        """Resume a paused continuation. Does not consume retry budget or increment attempt."""
        if self._state is not ExecutionState.WAITING_APPROVAL:
            raise InvalidTransitionError(self._state, ExecutionState.RUNNING, "resume is only allowed from WAITING_APPROVAL")
        return self.transition_to(ExecutionState.RUNNING, reason, metadata=metadata)

    def complete(self, reason: str = "run_completed", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.COMPLETED, reason, metadata=metadata)

    def fail(self, reason: str = "run_failed", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.FAILED, reason, metadata=metadata)

    def cancel(self, reason: str = "run_cancelled", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.CANCELLED, reason, metadata=metadata)

    def timeout(self, reason: str = "run_timed_out", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.TIMED_OUT, reason, metadata=metadata)

    def expire(self, reason: str = "continuation_expired", metadata: Mapping[str, Any] | None = None) -> ExecutionTransition:
        return self.transition_to(ExecutionState.EXPIRED, reason, metadata=metadata)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "current_state": self._state.value,
            "is_terminal": self.is_terminal,
            "attempt_number": self._attempt_number,
            "retries_used": self._retries_used,
            "max_retries": self._max_retries,
            "remaining_retries": self.remaining_retries,
            "transitions": [t.to_public_dict() for t in self._transitions],
        }
