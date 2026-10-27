"""Durable one-time LoveTree sign-in handoff rows.

The store owns state transitions only. It never hashes or compares credentials, never
decides authentication, and never creates a session; the login routes own those steps
with the existing ``padiem_session`` authority, and the ``lovetree-auth-caller`` relay
owns issuance on the identity authority. Every transition is a single conditional
UPDATE so an expired or already claimed row cannot be advanced by a late or replayed
request — the same discipline as ``android_auth_store.py``.

What a row proves is narrow: the existing PADIEM login verified this identity in this
browser for this LoveTree login request (``state_sha256``) for this product and
recipient, until ``expires_at``. Nothing else in the system may treat a ticket id as
login evidence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Protocol

LOVETREE_HANDOFF_PRODUCT_ID = "lovetree-4-0"
LOVETREE_HANDOFF_RECIPIENT = "lovetree-auth-caller"

HANDOFF_STATUS_AWAITING_LOGIN = "awaiting_login"
HANDOFF_STATUS_READY = "ready"
HANDOFF_STATUS_CLAIMED = "claimed"

_LIVE_HANDOFF_STATUSES = frozenset({HANDOFF_STATUS_AWAITING_LOGIN, HANDOFF_STATUS_READY})
_AUTH_PROVIDERS = frozenset({"google", "password"})


@dataclass(frozen=True, slots=True)
class LoveTreeHandoffRecord:
    ticket_id: str
    product_id: str
    recipient: str
    state_sha256: str
    status: str
    pending_user_id: str | None
    auth_provider: str | None
    provider_subject: str | None
    created_at: str
    updated_at: str
    expires_at: str

    def is_expired(self, now_iso: str) -> bool:
        # Both timestamps come from the same fixed UTC format, so the lexicographic
        # comparison is a valid chronological comparison.
        return self.expires_at <= now_iso

    def is_live(self, now_iso: str) -> bool:
        return self.status in _LIVE_HANDOFF_STATUSES and not self.is_expired(now_iso)


class LoveTreeLoginHandoffStore(Protocol):
    async def create(
        self,
        *,
        ticket_id: str,
        state_sha256: str,
        now_iso: str,
        expires_at_iso: str,
    ) -> None: ...

    async def get(self, ticket_id: str) -> LoveTreeHandoffRecord | None: ...

    async def bind_verified_identity(
        self,
        ticket_id: str,
        *,
        user_id: str,
        auth_provider: str,
        provider_subject: str,
        state_sha256: str,
        now_iso: str,
    ) -> bool:
        ...

    async def claim(
        self,
        ticket_id: str,
        *,
        now_iso: str,
    ) -> LoveTreeHandoffRecord | None: ...


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


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _record(row: Any) -> LoveTreeHandoffRecord | None:
    values = _row_to_dict(row)
    if values is None:
        return None
    required = (
        "ticket_id",
        "product_id",
        "recipient",
        "state_sha256",
        "status",
        "created_at",
        "updated_at",
        "expires_at",
    )
    if not all(isinstance(values.get(key), str) and values.get(key) for key in required):
        return None
    if values["product_id"] != LOVETREE_HANDOFF_PRODUCT_ID or values["recipient"] != LOVETREE_HANDOFF_RECIPIENT:
        return None
    if values["status"] not in _LIVE_HANDOFF_STATUSES | {HANDOFF_STATUS_CLAIMED}:
        return None
    auth_provider = _optional_text(values.get("auth_provider"))
    provider_subject = _optional_text(values.get("provider_subject"))
    pending_user_id = _optional_text(values.get("pending_user_id"))
    if values["status"] != HANDOFF_STATUS_AWAITING_LOGIN:
        if not (pending_user_id and auth_provider in _AUTH_PROVIDERS and provider_subject):
            return None
    elif pending_user_id or auth_provider or provider_subject:
        return None
    return LoveTreeHandoffRecord(
        ticket_id=values["ticket_id"],
        product_id=values["product_id"],
        recipient=values["recipient"],
        state_sha256=values["state_sha256"],
        status=values["status"],
        pending_user_id=pending_user_id,
        auth_provider=auth_provider,
        provider_subject=provider_subject,
        created_at=values["created_at"],
        updated_at=values["updated_at"],
        expires_at=values["expires_at"],
    )


def _identity_arguments(user_id: str, auth_provider: str, provider_subject: str) -> None:
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("verified users.id is required")
    if auth_provider not in _AUTH_PROVIDERS:
        raise ValueError("auth_provider must be a reviewed provider")
    if not isinstance(provider_subject, str) or not provider_subject.strip() or len(provider_subject) > 255:
        raise ValueError("provider_subject must be a bounded verified subject")


class D1LoveTreeLoginHandoffStore:
    """D1 authority for migration 073. Missing table or binding fails closed."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.first()

    async def create(
        self,
        *,
        ticket_id: str,
        state_sha256: str,
        now_iso: str,
        expires_at_iso: str,
    ) -> None:
        if not isinstance(ticket_id, str) or not ticket_id:
            raise ValueError("ticket_id is required")
        if not isinstance(state_sha256, str) or len(state_sha256) != 64:
            raise ValueError("login request state must be a sha256 digest")
        if expires_at_iso <= now_iso:
            raise ValueError("handoff expiry must be in the future")
        await self._first(
            "INSERT INTO lovetree_login_handoffs "
            "(ticket_id, product_id, recipient, state_sha256, status, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, ?, 'awaiting_login', ?, ?, ?) RETURNING ticket_id",
            ticket_id,
            LOVETREE_HANDOFF_PRODUCT_ID,
            LOVETREE_HANDOFF_RECIPIENT,
            state_sha256,
            now_iso,
            now_iso,
            expires_at_iso,
        )

    async def get(self, ticket_id: str) -> LoveTreeHandoffRecord | None:
        row = await self._first(
            "SELECT ticket_id, product_id, recipient, state_sha256, status, pending_user_id, "
            "auth_provider, provider_subject, created_at, updated_at, expires_at "
            "FROM lovetree_login_handoffs WHERE ticket_id=?",
            ticket_id,
        )
        return _record(row)

    async def bind_verified_identity(
        self,
        ticket_id: str,
        *,
        user_id: str,
        auth_provider: str,
        provider_subject: str,
        state_sha256: str,
        now_iso: str,
    ) -> bool:
        _identity_arguments(user_id, auth_provider, provider_subject)
        if not isinstance(state_sha256, str) or len(state_sha256) != 64:
            raise ValueError("login request state must be a sha256 digest")
        row = await self._first(
            "UPDATE lovetree_login_handoffs "
            "SET status='ready', pending_user_id=?, auth_provider=?, provider_subject=?, bound_at=?, updated_at=? "
            "WHERE ticket_id=? AND product_id=? AND recipient=? AND state_sha256=? "
            "AND status='awaiting_login' AND expires_at > ? "
            "RETURNING ticket_id",
            user_id,
            auth_provider,
            provider_subject,
            now_iso,
            now_iso,
            ticket_id,
            LOVETREE_HANDOFF_PRODUCT_ID,
            LOVETREE_HANDOFF_RECIPIENT,
            state_sha256,
            now_iso,
        )
        return _row_to_dict(row) is not None

    async def claim(self, ticket_id: str, *, now_iso: str) -> LoveTreeHandoffRecord | None:
        row = await self._first(
            "UPDATE lovetree_login_handoffs "
            "SET status='claimed', claimed_at=?, updated_at=? "
            "WHERE ticket_id=? AND product_id=? AND recipient=? AND status='ready' AND expires_at > ? "
            "RETURNING ticket_id, product_id, recipient, state_sha256, status, pending_user_id, "
            "auth_provider, provider_subject, created_at, updated_at, expires_at",
            now_iso,
            now_iso,
            ticket_id,
            LOVETREE_HANDOFF_PRODUCT_ID,
            LOVETREE_HANDOFF_RECIPIENT,
            now_iso,
        )
        return _record(row)


class InMemoryLoveTreeLoginHandoffStore:
    """Network-free test oracle. Never composed as the production authority."""

    def __init__(self) -> None:
        self.records: dict[str, LoveTreeHandoffRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        ticket_id: str,
        state_sha256: str,
        now_iso: str,
        expires_at_iso: str,
    ) -> None:
        if not isinstance(ticket_id, str) or not ticket_id:
            raise ValueError("ticket_id is required")
        if not isinstance(state_sha256, str) or len(state_sha256) != 64:
            raise ValueError("login request state must be a sha256 digest")
        if expires_at_iso <= now_iso:
            raise ValueError("handoff expiry must be in the future")
        async with self._lock:
            self.records[ticket_id] = LoveTreeHandoffRecord(
                ticket_id=ticket_id,
                product_id=LOVETREE_HANDOFF_PRODUCT_ID,
                recipient=LOVETREE_HANDOFF_RECIPIENT,
                state_sha256=state_sha256,
                status=HANDOFF_STATUS_AWAITING_LOGIN,
                pending_user_id=None,
                auth_provider=None,
                provider_subject=None,
                created_at=now_iso,
                updated_at=now_iso,
                expires_at=expires_at_iso,
            )

    async def get(self, ticket_id: str) -> LoveTreeHandoffRecord | None:
        return self.records.get(ticket_id)

    async def bind_verified_identity(
        self,
        ticket_id: str,
        *,
        user_id: str,
        auth_provider: str,
        provider_subject: str,
        state_sha256: str,
        now_iso: str,
    ) -> bool:
        _identity_arguments(user_id, auth_provider, provider_subject)
        if not isinstance(state_sha256, str) or len(state_sha256) != 64:
            raise ValueError("login request state must be a sha256 digest")
        async with self._lock:
            record = self.records.get(ticket_id)
            if record is None or record.status != HANDOFF_STATUS_AWAITING_LOGIN:
                return False
            if record.is_expired(now_iso) or record.state_sha256 != state_sha256:
                return False
            self.records[ticket_id] = replace(
                record,
                status=HANDOFF_STATUS_READY,
                pending_user_id=user_id,
                auth_provider=auth_provider,
                provider_subject=provider_subject,
                updated_at=now_iso,
            )
            return True

    async def claim(self, ticket_id: str, *, now_iso: str) -> LoveTreeHandoffRecord | None:
        async with self._lock:
            record = self.records.get(ticket_id)
            if record is None or record.status != HANDOFF_STATUS_READY or record.is_expired(now_iso):
                return None
            claimed = replace(record, status=HANDOFF_STATUS_CLAIMED, updated_at=now_iso)
            self.records[ticket_id] = claimed
            return claimed


__all__ = [
    "D1LoveTreeLoginHandoffStore",
    "HANDOFF_STATUS_AWAITING_LOGIN",
    "HANDOFF_STATUS_CLAIMED",
    "HANDOFF_STATUS_READY",
    "InMemoryLoveTreeLoginHandoffStore",
    "LOVETREE_HANDOFF_PRODUCT_ID",
    "LOVETREE_HANDOFF_RECIPIENT",
    "LoveTreeHandoffRecord",
    "LoveTreeLoginHandoffStore",
]
