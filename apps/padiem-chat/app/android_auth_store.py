"""Durable one-time handoff rows for the Android 1.0.1 sign-in return contract.

The store owns state transitions only. It never hashes or compares credentials,
never decides authentication, and never creates a session; routes own those
steps with the existing `padiem_session` authority. Every transition is a
single conditional UPDATE so an expired, already claimed, or already confirmed
row cannot be advanced by a late request.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any, Protocol

HANDOFF_STATUS_AWAITING_LOGIN = "awaiting_login"
HANDOFF_STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
HANDOFF_STATUS_READY = "ready"
HANDOFF_STATUS_CLAIMED = "claimed"
HANDOFF_STATUS_CANCELLED = "cancelled"

TERMINAL_HANDOFF_STATUSES = frozenset({HANDOFF_STATUS_CLAIMED, HANDOFF_STATUS_CANCELLED})
_LIVE_HANDOFF_STATUSES = frozenset(
    {
        HANDOFF_STATUS_AWAITING_LOGIN,
        HANDOFF_STATUS_AWAITING_CONFIRMATION,
        HANDOFF_STATUS_READY,
    }
)


@dataclass(frozen=True, slots=True)
class AndroidHandoffRecord:
    handoff_id: str
    status: str
    secret_hash: str
    code_hash: str
    pending_user_id: str | None
    attempts: int
    expires_at: str

    def is_expired(self, now_iso: str) -> bool:
        # Both timestamps are produced by the same fixed UTC format, so the
        # lexicographic comparison is a valid chronological comparison.
        return self.expires_at <= now_iso

    def is_live(self, now_iso: str) -> bool:
        return self.status in _LIVE_HANDOFF_STATUSES and not self.is_expired(now_iso)


class AndroidAuthHandoffStore(Protocol):
    async def create(
        self,
        *,
        handoff_id: str,
        secret_hash: str,
        code_hash: str,
        now_iso: str,
        expires_at_iso: str,
    ) -> None: ...

    async def get(self, handoff_id: str) -> AndroidHandoffRecord | None: ...

    async def bind_user(self, handoff_id: str, *, user_id: str, now_iso: str) -> bool: ...

    async def confirm(self, handoff_id: str, *, code_hash: str, now_iso: str) -> bool: ...

    async def record_failed_attempt(
        self, handoff_id: str, *, maximum: int, now_iso: str
    ) -> int: ...

    async def claim(self, handoff_id: str, *, secret_hash: str, now_iso: str) -> str | None: ...


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


def _record(row: Any) -> AndroidHandoffRecord | None:
    values = _row_to_dict(row)
    if values is None:
        return None
    handoff_id = values.get("handoff_id")
    status = values.get("status")
    secret_hash = values.get("secret_hash")
    code_hash = values.get("code_hash")
    expires_at = values.get("expires_at")
    if not all(isinstance(item, str) and item for item in (handoff_id, status, secret_hash, code_hash, expires_at)):
        return None
    pending_user_id = values.get("pending_user_id")
    try:
        attempts = int(values.get("attempts") or 0)
    except (TypeError, ValueError):
        attempts = 0
    return AndroidHandoffRecord(
        handoff_id=handoff_id,
        status=status,
        secret_hash=secret_hash,
        code_hash=code_hash,
        pending_user_id=pending_user_id if isinstance(pending_user_id, str) and pending_user_id else None,
        attempts=attempts,
        expires_at=expires_at,
    )


class D1AndroidAuthHandoffStore:
    """D1 authority for migration 055. Missing table/binding fails closed."""

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
        handoff_id: str,
        secret_hash: str,
        code_hash: str,
        now_iso: str,
        expires_at_iso: str,
    ) -> None:
        await self._first(
            "INSERT INTO padiem_android_auth_handoffs "
            "(handoff_id, secret_hash, code_hash, status, attempts, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, 'awaiting_login', 0, ?, ?, ?) RETURNING handoff_id",
            handoff_id,
            secret_hash,
            code_hash,
            now_iso,
            now_iso,
            expires_at_iso,
        )

    async def get(self, handoff_id: str) -> AndroidHandoffRecord | None:
        row = await self._first(
            "SELECT handoff_id, status, secret_hash, code_hash, pending_user_id, attempts, expires_at "
            "FROM padiem_android_auth_handoffs WHERE handoff_id=?",
            handoff_id,
        )
        return _record(row)

    async def bind_user(self, handoff_id: str, *, user_id: str, now_iso: str) -> bool:
        row = await self._first(
            "UPDATE padiem_android_auth_handoffs "
            "SET status='awaiting_confirmation', pending_user_id=?, pending_at=?, updated_at=? "
            "WHERE handoff_id=? AND status='awaiting_login' AND expires_at > ? "
            "RETURNING handoff_id",
            user_id,
            now_iso,
            now_iso,
            handoff_id,
            now_iso,
        )
        return _row_to_dict(row) is not None

    async def confirm(self, handoff_id: str, *, code_hash: str, now_iso: str) -> bool:
        row = await self._first(
            "UPDATE padiem_android_auth_handoffs "
            "SET status='ready', confirmed_at=?, updated_at=? "
            "WHERE handoff_id=? AND status='awaiting_confirmation' AND code_hash=? "
            "AND pending_user_id IS NOT NULL AND expires_at > ? "
            "RETURNING handoff_id",
            now_iso,
            now_iso,
            handoff_id,
            code_hash,
            now_iso,
        )
        return _row_to_dict(row) is not None

    async def record_failed_attempt(
        self, handoff_id: str, *, maximum: int, now_iso: str
    ) -> int:
        row = await self._first(
            "UPDATE padiem_android_auth_handoffs "
            "SET attempts=attempts + 1, "
            "status=CASE WHEN attempts + 1 >= ? THEN 'cancelled' ELSE status END, "
            "updated_at=? "
            "WHERE handoff_id=? AND status='awaiting_confirmation' AND expires_at > ? "
            "RETURNING attempts",
            maximum,
            now_iso,
            handoff_id,
            now_iso,
        )
        values = _row_to_dict(row)
        if values is None:
            return 0
        try:
            return int(values.get("attempts") or 0)
        except (TypeError, ValueError):
            return 0

    async def claim(self, handoff_id: str, *, secret_hash: str, now_iso: str) -> str | None:
        row = await self._first(
            "UPDATE padiem_android_auth_handoffs "
            "SET status='claimed', claimed_at=?, updated_at=? "
            "WHERE handoff_id=? AND status='ready' AND secret_hash=? "
            "AND pending_user_id IS NOT NULL AND expires_at > ? "
            "RETURNING pending_user_id",
            now_iso,
            now_iso,
            handoff_id,
            secret_hash,
            now_iso,
        )
        values = _row_to_dict(row)
        if values is None:
            return None
        user_id = values.get("pending_user_id")
        return user_id if isinstance(user_id, str) and user_id else None


class InMemoryAndroidAuthHandoffStore:
    """Network-free test oracle. Never composed as the Production authority."""

    def __init__(self) -> None:
        self.records: dict[str, AndroidHandoffRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        handoff_id: str,
        secret_hash: str,
        code_hash: str,
        now_iso: str,
        expires_at_iso: str,
    ) -> None:
        async with self._lock:
            self.records[handoff_id] = AndroidHandoffRecord(
                handoff_id=handoff_id,
                status=HANDOFF_STATUS_AWAITING_LOGIN,
                secret_hash=secret_hash,
                code_hash=code_hash,
                pending_user_id=None,
                attempts=0,
                expires_at=expires_at_iso,
            )

    async def get(self, handoff_id: str) -> AndroidHandoffRecord | None:
        return self.records.get(handoff_id)

    async def bind_user(self, handoff_id: str, *, user_id: str, now_iso: str) -> bool:
        async with self._lock:
            record = self.records.get(handoff_id)
            if record is None or record.status != HANDOFF_STATUS_AWAITING_LOGIN:
                return False
            if record.is_expired(now_iso):
                return False
            self.records[handoff_id] = replace(
                record,
                status=HANDOFF_STATUS_AWAITING_CONFIRMATION,
                pending_user_id=user_id,
            )
            return True

    async def confirm(self, handoff_id: str, *, code_hash: str, now_iso: str) -> bool:
        async with self._lock:
            record = self.records.get(handoff_id)
            if (
                record is None
                or record.status != HANDOFF_STATUS_AWAITING_CONFIRMATION
                or record.pending_user_id is None
                or record.is_expired(now_iso)
                or record.code_hash != code_hash
            ):
                return False
            self.records[handoff_id] = replace(record, status=HANDOFF_STATUS_READY)
            return True

    async def record_failed_attempt(
        self, handoff_id: str, *, maximum: int, now_iso: str
    ) -> int:
        async with self._lock:
            record = self.records.get(handoff_id)
            if (
                record is None
                or record.status != HANDOFF_STATUS_AWAITING_CONFIRMATION
                or record.is_expired(now_iso)
            ):
                return 0
            attempts = record.attempts + 1
            self.records[handoff_id] = replace(
                record,
                attempts=attempts,
                status=HANDOFF_STATUS_CANCELLED if attempts >= maximum else record.status,
            )
            return attempts

    async def claim(self, handoff_id: str, *, secret_hash: str, now_iso: str) -> str | None:
        async with self._lock:
            record = self.records.get(handoff_id)
            if (
                record is None
                or record.status != HANDOFF_STATUS_READY
                or record.pending_user_id is None
                or record.is_expired(now_iso)
                or record.secret_hash != secret_hash
            ):
                return None
            self.records[handoff_id] = replace(record, status=HANDOFF_STATUS_CLAIMED)
            return record.pending_user_id


__all__ = [
    "AndroidAuthHandoffStore",
    "AndroidHandoffRecord",
    "D1AndroidAuthHandoffStore",
    "HANDOFF_STATUS_AWAITING_CONFIRMATION",
    "HANDOFF_STATUS_AWAITING_LOGIN",
    "HANDOFF_STATUS_CANCELLED",
    "HANDOFF_STATUS_CLAIMED",
    "HANDOFF_STATUS_READY",
    "InMemoryAndroidAuthHandoffStore",
    "TERMINAL_HANDOFF_STATUSES",
]
