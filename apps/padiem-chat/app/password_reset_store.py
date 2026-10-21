"""Cloudflare D1 adapter for the #5441 lost-password reset ledger.

Every dynamic value is a prepared-statement bind. The raw reset token is never
written here: only its keyed digest is persisted, and the identifier column of
the audit ledger holds a keyed digest as well.
"""

from __future__ import annotations

import secrets
from typing import Any

from .password_reset import PasswordResetToken


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


class D1PasswordResetStore:
    """Durable reset tokens plus the reset audit ledger."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    @staticmethod
    def _token_from_row(row: dict[str, Any] | None) -> PasswordResetToken | None:
        if not row:
            return None
        try:
            return PasswordResetToken(
                token_id=str(row["token_id"]),
                user_id=str(row["user_id"]),
                issued_at=str(row["issued_at"]),
                expires_at=str(row["expires_at"]),
                attempts=int(row.get("attempts") or 0),
                consumed_at=(
                    str(row["consumed_at"]) if row.get("consumed_at") else None
                ),
                revoked_at=(str(row["revoked_at"]) if row.get("revoked_at") else None),
            )
        except (KeyError, TypeError, ValueError):
            return None

    _TOKEN_COLUMNS = (
        "token_id, user_id, issued_at, expires_at, attempts, consumed_at, revoked_at"
    )

    async def issue_token(
        self, *, user_id: str, token_digest: str, issued_at: str, expires_at: str
    ) -> PasswordResetToken:
        token_id = "prst_" + secrets.token_hex(16)
        await self._run(
            "INSERT INTO password_reset_tokens "
            "(token_id, user_id, token_digest, issued_at, expires_at, attempts, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            token_id,
            user_id,
            token_digest,
            issued_at,
            expires_at,
            issued_at,
        )
        return PasswordResetToken(
            token_id=token_id,
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expires_at,
            attempts=0,
        )

    async def find_token(self, *, token_digest: str) -> PasswordResetToken | None:
        row = await self._first(
            f"SELECT {self._TOKEN_COLUMNS} FROM password_reset_tokens "
            "WHERE token_digest=?",
            token_digest,
        )
        return self._token_from_row(row)

    async def consume_token(
        self, *, token_digest: str, consumed_at: str, max_attempts: int
    ) -> PasswordResetToken | None:
        """Atomically consume one open token.

        The single conditional UPDATE is the compare-and-set: exactly one
        caller can move the row out of the open state, so a token can never be
        redeemed twice even across concurrent Workers.
        """

        row = await self._first(
            "UPDATE password_reset_tokens SET consumed_at=?, attempts=attempts+1 "
            "WHERE token_digest=? AND consumed_at IS NULL AND revoked_at IS NULL "
            "AND expires_at > ? AND attempts < ? "
            f"RETURNING {self._TOKEN_COLUMNS}",
            consumed_at,
            token_digest,
            consumed_at,
            int(max_attempts),
        )
        return self._token_from_row(row)

    async def revoke_tokens_for_user(self, *, user_id: str, revoked_at: str) -> int:
        result = await self._run(
            "UPDATE password_reset_tokens SET revoked_at=? "
            "WHERE user_id=? AND consumed_at IS NULL AND revoked_at IS NULL",
            revoked_at,
            user_id,
        )
        changes = getattr(getattr(result, "meta", None), "changes", None)
        return int(changes) if isinstance(changes, int) else 0

    async def record_audit(
        self,
        *,
        event: str,
        user_id: str | None,
        identifier_digest: str,
        reason_code: str | None,
        occurred_at: str,
    ) -> None:
        await self._run(
            "INSERT INTO password_reset_audit "
            "(event, user_id, identifier_digest, reason_code, occurred_at) "
            "VALUES (?, ?, ?, ?, ?)",
            event,
            user_id,
            identifier_digest,
            reason_code,
            occurred_at,
        )

    async def count_audit_events(
        self, *, event: str, identifier_digest: str, since: str
    ) -> int:
        row = await self._first(
            "SELECT COUNT(*) AS total FROM password_reset_audit "
            "WHERE event=? AND identifier_digest=? AND occurred_at >= ?",
            event,
            identifier_digest,
            since,
        )
        if not row:
            return 0
        try:
            return int(row.get("total") or 0)
        except (TypeError, ValueError):
            return 0

    async def latest_audit_at(self, *, event: str, identifier_digest: str) -> str | None:
        row = await self._first(
            "SELECT MAX(occurred_at) AS latest FROM password_reset_audit "
            "WHERE event=? AND identifier_digest=?",
            event,
            identifier_digest,
        )
        if not row:
            return None
        latest = row.get("latest")
        return str(latest) if latest else None

    async def count_audit_events_since(self, *, event: str, since: str) -> int:
        row = await self._first(
            "SELECT COUNT(*) AS total FROM password_reset_audit "
            "WHERE event=? AND occurred_at >= ?",
            event,
            since,
        )
        if not row:
            return 0
        try:
            return int(row.get("total") or 0)
        except (TypeError, ValueError):
            return 0


__all__ = ["D1PasswordResetStore"]
