"""Product-neutral execution cancellation teardown barrier for Padiem AI Core.

Promoted generic slice of the cancellation -> teardown barrier contract: a
trusted cancellation intent binds exactly one execution, prohibits every
forward/output transition afterwards, and admits teardown/cleanup as the
only permitted next transition. Attested successful cleanup reaches
``CANCELLED_CLEANED_UP``; attested failed cleanup reaches
``TEARDOWN_FAILED``.

Deliberately NOT modelled here (stays with product-local ledgers, which
remain reference/compat evidence only):

- stage receipt history, plan binding, or fingerprinting;
- temporal staleness of a cancellation against upstream receipts;
- pre-existing execution failure terminals (see
  ``ExecutionStateMachine.FAILED``);
- canonical P01 cancellation authority (this module mints no P01 event);
- resume / retry / redispatch affordances (none exist on this barrier).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Any

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_REASON_CHARS = 500

#: The only transition kind permitted after a cancellation is recorded.
TEARDOWN_TRANSITION = "teardown"


class CancellationBarrierError(ValueError):
    """Base error for cancellation teardown barrier contract violations."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class CancellationBarrierState(str, Enum):
    """Discrete barrier states for one bound execution."""

    ACTIVE = "active"
    AWAITING_TEARDOWN = "awaiting_teardown"
    CANCELLED_CLEANED_UP = "cancelled_cleaned_up"
    TEARDOWN_FAILED = "teardown_failed"


_TERMINAL_STATES = frozenset({
    CancellationBarrierState.CANCELLED_CLEANED_UP,
    CancellationBarrierState.TEARDOWN_FAILED,
})


def is_terminal_barrier_state(state: CancellationBarrierState) -> bool:
    """Return True if the barrier state is an immutable terminal state."""
    return state in _TERMINAL_STATES


def _safe_reference(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise CancellationBarrierError(
            f"invalid_{field_name}",
            f"{field_name} must be a bounded safe identifier",
        )
    return value


def _aware_moment(value: Any, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CancellationBarrierError(
            f"invalid_{field_name}",
            f"{field_name} must be a timezone-aware datetime",
        )
    return value


@dataclass(frozen=True, slots=True)
class CancellationProjection:
    """Immutable public view of a cancellation barrier."""

    execution_key: str
    state: CancellationBarrierState
    next_transition: str | None
    cancellation_ref: str | None
    terminal: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "execution_key": self.execution_key,
            "state": self.state.value,
            "next_transition": self.next_transition,
            "cancellation_ref": self.cancellation_ref,
            "terminal": self.terminal,
            "post_cancellation_output_supported": False,
            "p01_cancellation_authority": False,
            "automatic_resume": False,
            "automatic_retry": False,
            "automatic_redispatch": False,
        }


class CancellationBarrier:
    """Guard binding one execution to at most one trusted cancellation.

    Lifecycle: ``ACTIVE`` -> ``AWAITING_TEARDOWN`` -> exactly one of
    ``CANCELLED_CLEANED_UP`` / ``TEARDOWN_FAILED``. Terminal states reject
    every subsequent operation (fail closed).
    """

    def __init__(self, *, execution_key: str) -> None:
        self._execution_key = _safe_reference(execution_key, "execution_key")
        self._state = CancellationBarrierState.ACTIVE
        self._cancellation: tuple[str, datetime] | None = None

    @property
    def execution_key(self) -> str:
        return self._execution_key

    @property
    def state(self) -> CancellationBarrierState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return is_terminal_barrier_state(self._state)

    @property
    def cancellation_ref(self) -> str | None:
        return self._cancellation[0] if self._cancellation is not None else None

    def projection(self) -> CancellationProjection:
        """Return the current immutable public view of this barrier."""
        if self._state is CancellationBarrierState.AWAITING_TEARDOWN:
            next_transition: str | None = TEARDOWN_TRANSITION
        else:
            next_transition = None
        terminal = self._state.value if self.is_terminal else None
        return CancellationProjection(
            execution_key=self._execution_key,
            state=self._state,
            next_transition=next_transition,
            cancellation_ref=self.cancellation_ref,
            terminal=terminal,
        )

    def request_cancellation(
        self,
        *,
        cancellation_ref: str,
        execution_key: str,
        observed_at: datetime,
    ) -> CancellationProjection:
        """Record a trusted cancellation intent for the bound execution.

        An exact replay (same reference and same observation moment) returns
        the current projection unchanged. Anything else conflicting is
        rejected, as is any cancellation for a terminal execution.
        """
        candidate_ref = _safe_reference(cancellation_ref, "cancellation_ref")
        moment = _aware_moment(observed_at, "observed_at")
        if self.is_terminal:
            raise CancellationBarrierError(
                "terminal_cancellation_rejected",
                "terminal execution cannot accept cancellation",
            )
        if execution_key != self._execution_key:
            raise CancellationBarrierError(
                "cancellation_correlation_mismatch",
                "cancellation does not belong to the bound execution",
            )
        candidate = (candidate_ref, moment)
        if self._cancellation is not None:
            if self._cancellation != candidate:
                raise CancellationBarrierError(
                    "conflicting_cancellation",
                    "conflicting cancellation replay rejected",
                )
            return self.projection()
        self._cancellation = candidate
        self._state = CancellationBarrierState.AWAITING_TEARDOWN
        return self.projection()

    def guard_transition(self, *, kind: str) -> None:
        """Reject any post-cancellation transition except teardown/cleanup.

        Before a cancellation is recorded the barrier does not govern flow.
        After cancellation only the teardown transition is permitted; once
        terminal, every transition is rejected.
        """
        transition = _safe_reference(kind, "transition_kind")
        if self.is_terminal:
            raise CancellationBarrierError(
                "terminal_transition_rejected",
                "terminal execution accepts no further transitions",
            )
        if self._cancellation is not None and transition != TEARDOWN_TRANSITION:
            raise CancellationBarrierError(
                "post_cancel_output_prohibited",
                "only the teardown transition is permitted after cancellation",
            )

    def record_teardown(self, *, succeeded: bool) -> CancellationProjection:
        """Record the attested cleanup outcome; teardown cannot be skipped.

        Callers must verify cleanup before attesting success. A successful
        attestation reaches ``CANCELLED_CLEANED_UP``; a failed attestation
        reaches ``TEARDOWN_FAILED``.
        """
        if not isinstance(succeeded, bool):
            raise CancellationBarrierError(
                "invalid_teardown_outcome",
                "teardown outcome must be a boolean",
            )
        if self._state is not CancellationBarrierState.AWAITING_TEARDOWN:
            raise CancellationBarrierError(
                "teardown_without_cancellation",
                "teardown is only permitted while a cancellation is pending",
            )
        if succeeded:
            self._state = CancellationBarrierState.CANCELLED_CLEANED_UP
        else:
            self._state = CancellationBarrierState.TEARDOWN_FAILED
        return self.projection()
