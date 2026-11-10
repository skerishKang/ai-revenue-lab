"""End a Chat user's external AI credentials on credential change.

A password change or reset already ends the Chat sessions and the shared
login sessions (#7078). The external AI personal tokens and OAuth grants
stored in Chat's own MCP database outlive that: a personal token is minted
without an expiry hole in the old flow, and an OAuth grant row carries both
the access hash and the rotating refresh hash. A password stolen earlier
therefore keeps reaching the PC after the victim changes it.

On a successful credential change this module revokes every live credential
row of that account in one owner-scoped UPDATE. The call is best-effort by
product decision: a failed revocation never fails the credential change. The
failure is journaled and a durable pending row lets the next login/refresh
(or the next credential change) retry it. No user id, email or token material
is ever written to a log line.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(("external-token-revoke:" + user_id).encode("utf-8")).hexdigest()[:12]


def _journal(outcome: str, *, code: str = "none", user_id: str = "", revoked: int = 0) -> None:
    # Closed line: outcome, bounded code, count and a non-reversible user hash.
    print(
        "external_token_revoke",
        f"outcome={outcome}",
        f"code={code}",
        f"revoked={revoked}",
        f"user_hash={_user_hash(user_id) if user_id else 'none'}",
    )


def _db(request: Any) -> Any:
    return getattr(request.app.state, "account_data_db", None)


def _store(request: Any) -> Any:
    return getattr(request.app.state, "mcp_gateway_store", None)


async def _attempt(request: Any, user_id: str) -> tuple[bool, int, str]:
    store = _store(request)
    if store is None or not callable(getattr(store, "revoke_all_tokens", None)):
        # No MCP store on this deployment: there is no external credential to
        # end, so there is nothing to retry either.
        _journal("skipped", code="not_configured", user_id=user_id)
        return True, 0, "not_configured"
    try:
        revoked = await store.revoke_all_tokens(user_id=user_id)
    except Exception:
        _journal("failed", code="store_error", user_id=user_id)
        return False, 0, "store_error"
    _journal("ok", code="none", user_id=user_id, revoked=revoked)
    return True, revoked, "ok"


async def _clear_pending(request: Any, user_id: str) -> None:
    db = _db(request)
    if db is None or not callable(getattr(db, "prepare", None)):
        return
    try:
        await db.prepare(
            "DELETE FROM external_token_revoke_pending WHERE user_id=?"
        ).bind(user_id).run()
    except Exception:
        _journal("pending_clear_failed", user_id=user_id)


async def _remember_pending(request: Any, user_id: str) -> None:
    db = _db(request)
    if db is None or not callable(getattr(db, "prepare", None)):
        return
    try:
        await db.prepare(
            "INSERT INTO external_token_revoke_pending (user_id, created_at, attempts) "
            "VALUES (?,?,1) "
            "ON CONFLICT(user_id) DO UPDATE SET attempts=attempts+1"
        ).bind(user_id, datetime.now(UTC).isoformat()).run()
        _journal("pending", code="retry_scheduled", user_id=user_id)
    except Exception:
        _journal("pending_write_failed", user_id=user_id)


async def revoke_after_credential_change(request: Any, user_id: str) -> bool:
    """Best-effort revocation. Never raises; leaves a durable retry on failure."""
    ok, _, _ = await _attempt(request, user_id)
    if ok:
        await _clear_pending(request, user_id)
        return True
    await _remember_pending(request, user_id)
    return False


async def flush_pending(request: Any, user_id: str) -> bool:
    """Retry one pending revocation for this user. Never raises."""
    db = _db(request)
    if db is None or not callable(getattr(db, "prepare", None)):
        return True
    try:
        row = await db.prepare(
            "SELECT user_id FROM external_token_revoke_pending WHERE user_id=?"
        ).bind(user_id).first()
    except Exception:
        return False
    if row is None:
        return True
    ok, _, _ = await _attempt(request, user_id)
    if ok:
        await _clear_pending(request, user_id)
        _journal("recovered", user_id=user_id)
        return True
    try:
        await db.prepare(
            "UPDATE external_token_revoke_pending SET attempts=attempts+1 WHERE user_id=?"
        ).bind(user_id).run()
    except Exception:
        pass
    return False


__all__ = [
    "flush_pending",
    "revoke_after_credential_change",
]
