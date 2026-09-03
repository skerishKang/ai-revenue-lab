"""Product-local shadow/read-through bridge for Shared Control Plane identity.

The D1 row in this module is deliberately non-authoritative. It stores only a
bounded pointer/projection last issued by the trusted Control Plane authority.
Before a shared-authority operation uses a canonical subject, the current auth
session is re-read from that authority and validated fail-closed.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from padiem_control_plane import AuthSessionSnapshot, AuthSessionState, SubjectType

from .control_plane_identity import (
    BridgedIdentitySession,
    IdentityBridgeError,
    PADIEM_CHAT_PRODUCT_ID,
)


@dataclass(frozen=True, slots=True)
class IdentityShadowRecord:
    product_user_id: str
    canonical_subject_id: str
    auth_session_id: str
    session_revision: int
    session_state: str
    session_expires_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.product_user_id, str) or not self.product_user_id.startswith("usr_"):
            raise ValueError("product_user_id is invalid")
        for name in ("canonical_subject_id", "auth_session_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(f"{name} is invalid")
        if isinstance(self.session_revision, bool) or not isinstance(self.session_revision, int) or self.session_revision < 1:
            raise ValueError("session_revision is invalid")
        if self.session_state not in {"active", "revoked", "expired"}:
            raise ValueError("session_state is invalid")
        for name in ("session_expires_at", "observed_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")


class IdentityShadowStore(Protocol):
    async def save_projection(self, bridged: BridgedIdentitySession) -> None: ...

    async def load_projection(self, product_user_id: str) -> IdentityShadowRecord | None: ...


class CurrentCanonicalSessionAuthority(Protocol):
    def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot: ...


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _parse_aware(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


class D1IdentityShadowStore:
    """Non-authoritative B62 D1 projection of authority-issued canonical pointers."""

    def __init__(self, db: Any) -> None:
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("D1 binding is required")
        self._db = db

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self._db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await _maybe_await(statement.run())

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self._db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await _maybe_await(statement.first()))

    async def save_projection(self, bridged: BridgedIdentitySession) -> None:
        if not isinstance(bridged, BridgedIdentitySession):
            raise ValueError("bridged identity is invalid")
        session = bridged.auth_session
        now = datetime.now(timezone.utc).isoformat()
        await self._run(
            "INSERT INTO control_plane_identity_shadow "
            "(product_user_id, canonical_subject_id, auth_session_id, session_revision, session_state, session_expires_at, observed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(product_user_id) DO UPDATE SET "
            "canonical_subject_id=excluded.canonical_subject_id, "
            "auth_session_id=excluded.auth_session_id, "
            "session_revision=excluded.session_revision, "
            "session_state=excluded.session_state, "
            "session_expires_at=excluded.session_expires_at, "
            "observed_at=excluded.observed_at",
            bridged.product_user_id,
            bridged.canonical_subject.subject_id,
            session.session_id,
            session.revision,
            session.state.value,
            session.expires_at.isoformat(),
            now,
        )

    async def load_projection(self, product_user_id: str) -> IdentityShadowRecord | None:
        row = await self._first(
            "SELECT product_user_id, canonical_subject_id, auth_session_id, session_revision, "
            "session_state, session_expires_at, observed_at "
            "FROM control_plane_identity_shadow WHERE product_user_id=?",
            product_user_id,
        )
        if row is None:
            return None
        try:
            return IdentityShadowRecord(
                product_user_id=str(row["product_user_id"]),
                canonical_subject_id=str(row["canonical_subject_id"]),
                auth_session_id=str(row["auth_session_id"]),
                session_revision=int(row["session_revision"]),
                session_state=str(row["session_state"]),
                session_expires_at=_parse_aware(row["session_expires_at"]),
                observed_at=_parse_aware(row["observed_at"]),
            )
        except (KeyError, TypeError, ValueError):
            raise IdentityBridgeError(
                503,
                "control_plane_shadow_invalid",
                "Canonical identity shadow state is invalid.",
            ) from None


class RefreshingCanonicalSubjectResolver:
    """Resolve canonical subject only after refreshing current session authority."""

    def __init__(self, *, authority: CurrentCanonicalSessionAuthority, store: IdentityShadowStore) -> None:
        if authority is None or store is None:
            raise ValueError("authority and shadow store are required")
        self._authority = authority
        self._store = store

    async def resolve_subject_id(
        self,
        *,
        product_user_id: str,
        now: datetime | None = None,
    ) -> str:
        shadow = await self._store.load_projection(product_user_id)
        if shadow is None:
            raise IdentityBridgeError(
                503,
                "control_plane_identity_not_linked",
                "Canonical identity is not linked for this product session.",
            )
        try:
            current = await _maybe_await(
                self._authority.resolve_auth_session(session_id=shadow.auth_session_id)
            )
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "control_plane_session_unavailable",
                "Canonical auth session is unavailable.",
            ) from exc
        if not isinstance(current, AuthSessionSnapshot):
            raise IdentityBridgeError(
                503,
                "control_plane_session_invalid",
                "Canonical auth authority returned an invalid session.",
            )
        if (
            current.session_id != shadow.auth_session_id
            or current.product_id != PADIEM_CHAT_PRODUCT_ID
            or current.subject.subject_type is not SubjectType.USER
            or current.subject.subject_id != shadow.canonical_subject_id
            or current.revision < shadow.session_revision
        ):
            raise IdentityBridgeError(
                403,
                "control_plane_session_mismatch",
                "Canonical auth session does not match the linked product identity.",
            )
        effective_now = now if now is not None else datetime.now(timezone.utc)
        if effective_now.tzinfo is None or effective_now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if current.effective_state(now=effective_now) is not AuthSessionState.ACTIVE:
            raise IdentityBridgeError(
                401,
                "control_plane_session_inactive",
                "Canonical auth session is expired or revoked.",
            )
        return current.subject.subject_id
