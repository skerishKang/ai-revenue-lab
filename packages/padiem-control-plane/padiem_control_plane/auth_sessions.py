"""Canonical server-trusted auth-session lifecycle for Padiem Control Plane.

This contract does not implement cookies, OAuth, password verification, token
minting, or product login UI. It records only the bounded canonical session
facts that downstream Padiem products may trust after their own authentication
adapter has established identity.

Security invariants:
- browser/client state is never the authority for canonical subject identity;
- no bearer token, cookie value, refresh token, password, or OAuth credential is
  carried by this contract;
- expiry and revocation are explicit and monotonic;
- terminal revoked/expired sessions cannot reactivate in place;
- product-owned auth persistence is not migrated by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re

from .contracts import CanonicalSubjectRef, ControlPlaneContractError


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_SESSION_REASON_CHARS = 128


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_auth_session",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _aware_datetime(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_auth_session",
            f"{name} must be timezone-aware",
        )
    return value


class AuthSessionState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AuthSessionTransitionKind(str, Enum):
    REVOKE = "revoke"
    EXPIRE = "expire"


@dataclass(frozen=True, slots=True)
class AuthSessionSnapshot:
    """Immutable canonical session state after trusted authentication resolution."""

    session_id: str
    product_id: str
    subject: CanonicalSubjectRef
    issued_at: datetime
    expires_at: datetime
    state: AuthSessionState = AuthSessionState.ACTIVE
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _safe_identifier("session_id", self.session_id))
        object.__setattr__(self, "product_id", _safe_identifier("product_id", self.product_id))
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise ControlPlaneContractError(
                "invalid_auth_session",
                "subject must be CanonicalSubjectRef",
            )
        object.__setattr__(self, "issued_at", _aware_datetime("issued_at", self.issued_at))
        object.__setattr__(self, "expires_at", _aware_datetime("expires_at", self.expires_at))
        if self.expires_at <= self.issued_at:
            raise ControlPlaneContractError(
                "invalid_auth_session",
                "expires_at must be later than issued_at",
            )
        if not isinstance(self.state, AuthSessionState):
            raise ControlPlaneContractError(
                "invalid_auth_session",
                "state must be AuthSessionState",
            )
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ControlPlaneContractError(
                "invalid_auth_session",
                "revision must be a positive integer",
            )

    def effective_state(self, *, now: datetime) -> AuthSessionState:
        now = _aware_datetime("now", now)
        if self.state is AuthSessionState.REVOKED:
            return AuthSessionState.REVOKED
        if self.state is AuthSessionState.EXPIRED or now >= self.expires_at:
            return AuthSessionState.EXPIRED
        return AuthSessionState.ACTIVE

    def is_active(self, *, now: datetime) -> bool:
        return self.effective_state(now=now) is AuthSessionState.ACTIVE

    def to_public_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "product_id": self.product_id,
            "subject": self.subject.to_public_dict(),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "state": self.state.value,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class AuthSessionTransition:
    """Immutable server-side transition event for revocation/expiry materialization."""

    event_id: str
    session_id: str
    kind: AuthSessionTransitionKind
    occurred_at: datetime
    from_revision: int
    reason_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_identifier("event_id", self.event_id))
        object.__setattr__(self, "session_id", _safe_identifier("session_id", self.session_id))
        if not isinstance(self.kind, AuthSessionTransitionKind):
            raise ControlPlaneContractError(
                "invalid_auth_session_transition",
                "kind must be AuthSessionTransitionKind",
            )
        object.__setattr__(self, "occurred_at", _aware_datetime("occurred_at", self.occurred_at))
        if isinstance(self.from_revision, bool) or not isinstance(self.from_revision, int) or self.from_revision < 1:
            raise ControlPlaneContractError(
                "invalid_auth_session_transition",
                "from_revision must be a positive integer",
            )
        if self.reason_code is not None:
            if (
                not isinstance(self.reason_code, str)
                or not _IDENTIFIER_RE.fullmatch(self.reason_code)
                or len(self.reason_code) > MAX_SESSION_REASON_CHARS
            ):
                raise ControlPlaneContractError(
                    "invalid_auth_session_transition",
                    "reason_code must be a bounded safe identifier",
                )


@dataclass(frozen=True, slots=True)
class AppliedAuthSessionTransition:
    previous: AuthSessionSnapshot
    transition: AuthSessionTransition
    current: AuthSessionSnapshot


def apply_auth_session_transition(
    snapshot: AuthSessionSnapshot,
    transition: AuthSessionTransition,
) -> AppliedAuthSessionTransition:
    """Apply one exact-revision terminal transition to a canonical session."""

    if not isinstance(snapshot, AuthSessionSnapshot):
        raise ControlPlaneContractError(
            "invalid_auth_session",
            "snapshot must be AuthSessionSnapshot",
        )
    if not isinstance(transition, AuthSessionTransition):
        raise ControlPlaneContractError(
            "invalid_auth_session_transition",
            "transition must be AuthSessionTransition",
        )
    if transition.session_id != snapshot.session_id:
        raise ControlPlaneContractError(
            "auth_session_mismatch",
            "transition does not belong to the supplied session",
        )
    if transition.from_revision != snapshot.revision:
        raise ControlPlaneContractError(
            "stale_auth_session_transition",
            "transition revision does not match the current session revision",
        )
    if snapshot.state is not AuthSessionState.ACTIVE:
        raise ControlPlaneContractError(
            "terminal_auth_session",
            "revoked or expired sessions cannot transition again",
        )
    if transition.occurred_at < snapshot.issued_at:
        raise ControlPlaneContractError(
            "invalid_auth_session_transition",
            "transition cannot occur before session issuance",
        )

    if transition.kind is AuthSessionTransitionKind.EXPIRE:
        if transition.occurred_at < snapshot.expires_at:
            raise ControlPlaneContractError(
                "premature_auth_session_expiry",
                "expiry transition cannot be materialized before expires_at",
            )
        next_state = AuthSessionState.EXPIRED
    else:
        next_state = AuthSessionState.REVOKED

    current = AuthSessionSnapshot(
        session_id=snapshot.session_id,
        product_id=snapshot.product_id,
        subject=snapshot.subject,
        issued_at=snapshot.issued_at,
        expires_at=snapshot.expires_at,
        state=next_state,
        revision=snapshot.revision + 1,
    )
    return AppliedAuthSessionTransition(
        previous=snapshot,
        transition=transition,
        current=current,
    )


def validate_auth_session_transition_batch(
    snapshot: AuthSessionSnapshot,
    transitions: tuple[AuthSessionTransition, ...],
) -> AuthSessionSnapshot:
    """Apply a bounded exact-order transition batch and reject replayed event IDs."""

    if not isinstance(transitions, tuple):
        raise ControlPlaneContractError(
            "invalid_auth_session_transition",
            "transitions must be a tuple",
        )
    if len(transitions) > 16:
        raise ControlPlaneContractError(
            "auth_session_transition_budget_exceeded",
            "too many auth session transitions in one batch",
        )
    event_ids = tuple(item.event_id for item in transitions if isinstance(item, AuthSessionTransition))
    if len(event_ids) != len(transitions):
        raise ControlPlaneContractError(
            "invalid_auth_session_transition",
            "transitions must contain AuthSessionTransition values",
        )
    if len(set(event_ids)) != len(event_ids):
        raise ControlPlaneContractError(
            "duplicate_auth_session_event",
            "auth session transition event IDs must be unique",
        )

    current = snapshot
    for transition in transitions:
        current = apply_auth_session_transition(current, transition).current
    return current
