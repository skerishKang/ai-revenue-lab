"""Source-state derivation and validation for canonical events.

These helpers are pure and deterministic: the same inputs always produce the
same resolution, which is what allows the World Feed to turn shared facts into
different personal editions without changing the facts.
"""

from app.domain.enums import SourceState
from app.domain.models import SourceCard

_SELECTION_FORBIDDEN = (SourceState.WITHDRAWN, SourceState.SUPERSEDED)


def is_eligible(status: SourceState) -> bool:
    """Withdrawn and superseded cards must never be selected."""
    return status not in _SELECTION_FORBIDDEN


def requires_uncertainty(status: SourceState) -> bool:
    return status == SourceState.CONFLICTING


def derive_event_status(source_states: list[SourceState]) -> SourceState:
    """Resolve the canonical event status from its contributing source states.

    Priority (most authoritative / most restrictive first):
      withdrawn  -> the event is cancelled/withdrawn (never selected)
      superseded -> a newer record replaced it (never selected)
      conflicting-> sources disagree on a material fact
      multi      -> two+ independent sources agree
      single     -> one authoritative source
    """
    if not source_states:
        raise ValueError("cannot derive status from zero source states")
    if SourceState.WITHDRAWN in source_states:
        return SourceState.WITHDRAWN
    if SourceState.SUPERSEDED in source_states:
        return SourceState.SUPERSEDED
    if SourceState.CONFLICTING in source_states:
        return SourceState.CONFLICTING
    if len(source_states) > 1:
        return SourceState.MULTI_SOURCE
    return SourceState.SINGLE_SOURCE


def resolve_conflict_penalty(source_states: list[SourceState]) -> float:
    """A conflicting group carries an explicit uncertainty penalty."""
    if SourceState.CONFLICTING in source_states:
        return 0.5
    return 0.0


def _coerce_state(value):
    if isinstance(value, SourceState):
        return value
    return SourceState(value)


def summarize_source_states(sources) -> dict:
    """Build the resolved canonical-event view for one canonical_key group.

    Accepts either ``SourceCard`` (enum fields) or ``SourceRecord`` (string
    fields) so the service can resolve directly from stored rows.
    """
    states = [_coerce_state(s.source_state) for s in sources]
    status = derive_event_status(states)
    conflicting = [
        s.source_id
        for s in sources
        if _coerce_state(s.source_state) == SourceState.CONFLICTING
    ]
    primary = next(
        (s for s in sources if _coerce_state(s.source_state) != SourceState.CONFLICTING),
        sources[0],
    )
    return {
        "status": status,
        "eligible": is_eligible(status),
        "uncertainty_note": (
            "Sources disagree on a material fact; treat as unconfirmed."
            if requires_uncertainty(status)
            else None
        ),
        "conflicting_source_ids": conflicting,
        "primary_source": primary,
        "source_ids": [s.source_id for s in sources],
        "conflict_penalty": resolve_conflict_penalty(states),
    }
