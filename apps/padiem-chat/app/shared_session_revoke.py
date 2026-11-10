"""#7078: revoke a Chat user's padiem-auth sessions on credential change.

The password change/reset paths own the Chat credential. The shared login
surface (padiem-auth) owns the login sessions. When the credential changes, the
sessions that were minted by the shared surface must stop refreshing too.

The call is best-effort by product decision: a failed revocation never fails the
credential change. The failure is journaled and a durable pending row lets the
next login/refresh (or the next credential change) retry it. No user id, email
or session value is ever written to a log line.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

AUTH_SESSION_REVOKE_URL = "https://auth.padiem.net/internal/account-sessions/revoke"
AUTH_SESSION_REVOKE_PATH = "/internal/account-sessions/revoke"
_PRODUCT_ID = "b62"
_RPC_ATTEMPTS = 2
_RPC_RETRY_DELAY_SECONDS = 0.2
_SERVICE_AT = "x-padiem-service-at"
_SERVICE_ID = "x-padiem-service-id"
_SERVICE_PROOF = "x-padiem-service-proof"


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(("shared-session-revoke:" + user_id).encode("utf-8")).hexdigest()[:12]


def _journal(outcome: str, *, code: str = "none", user_id: str = "", revoked: int = 0) -> None:
    # Closed line: outcome, bounded code, count and a non-reversible user hash.
    print(
        "shared_session_revoke",
        f"outcome={outcome}",
        f"code={code}",
        f"revoked={revoked}",
        f"user_hash={_user_hash(user_id) if user_id else 'none'}",
    )


def _service_proof(secret: str, *, path: str, at: int, service_id: str, body: bytes) -> str:
    signed = b"\n".join(
        (
            b"v2",
            b"POST",
            path.encode("utf-8"),
            str(at).encode("ascii"),
            service_id.encode("utf-8"),
            body,
        )
    )
    return "v2=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


async def _post_revoke(request: Any, user_id: str) -> tuple[bool, int, str]:
    settings = getattr(request.app.state, "settings", None)
    secret = getattr(settings, "account_delete_rpc_secret", None)
    if not isinstance(secret, str) or len(secret) < 32:
        _journal("skipped", code="not_configured", user_id=user_id)
        return False, 0, "not_configured"
    body = json.dumps(
        {"product_id": _PRODUCT_ID, "product_user_id": user_id},
        separators=(",", ":"),
    ).encode("utf-8")
    at = int(time.time())
    service_id = str(uuid.uuid4())
    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        _SERVICE_AT: str(at),
        _SERVICE_ID: service_id,
        _SERVICE_PROOF: _service_proof(
            secret, path=AUTH_SESSION_REVOKE_PATH, at=at, service_id=service_id, body=body
        ),
    }
    try:
        transport = getattr(request.app.state, "account_delete_rpc_transport", None)
        if callable(transport):
            response = await transport(
                url=AUTH_SESSION_REVOKE_URL,
                method="POST",
                path=AUTH_SESSION_REVOKE_PATH,
                body=body,
                headers=headers,
            )
        else:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                response = await client.post(AUTH_SESSION_REVOKE_URL, content=body, headers=headers)
    except Exception:
        _journal("failed", code="transport", user_id=user_id)
        return False, 0, "transport"
    status = getattr(response, "status_code", None)
    data = None
    if status == 200:
        try:
            data = response.json()
        except Exception:
            data = None
    if status == 200 and isinstance(data, dict) and data.get("ok") is True:
        raw_count = data.get("revoked_sessions")
        count = raw_count if isinstance(raw_count, int) and raw_count >= 0 else 0
        _journal("ok", code="none", user_id=user_id, revoked=count)
        return True, count, "ok"
    code = "http_error"
    if isinstance(data, dict):
        candidate = data.get("error")
        if isinstance(candidate, dict) and isinstance(candidate.get("code"), str):
            code = candidate["code"]
    _journal("failed", code=code, user_id=user_id)
    return False, 0, code


async def _attempt(request: Any, user_id: str) -> tuple[bool, int, str]:
    last: tuple[bool, int, str] = (False, 0, "not_attempted")
    for attempt in range(_RPC_ATTEMPTS):
        if attempt:
            await asyncio.sleep(_RPC_RETRY_DELAY_SECONDS)
        last = await _post_revoke(request, user_id)
        if last[0]:
            return last
    return last


def _db(request: Any) -> Any:
    return getattr(request.app.state, "account_data_db", None)


async def _clear_pending(request: Any, user_id: str) -> None:
    db = _db(request)
    if db is None or not callable(getattr(db, "prepare", None)):
        return
    try:
        await db.prepare(
            "DELETE FROM shared_session_revoke_pending WHERE user_id=?"
        ).bind(user_id).run()
    except Exception:
        _journal("pending_clear_failed", user_id=user_id)


async def _remember_pending(request: Any, user_id: str) -> None:
    db = _db(request)
    if db is None or not callable(getattr(db, "prepare", None)):
        return
    try:
        await db.prepare(
            "INSERT INTO shared_session_revoke_pending (user_id, created_at, attempts) "
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
            "SELECT user_id FROM shared_session_revoke_pending WHERE user_id=?"
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
            "UPDATE shared_session_revoke_pending SET attempts=attempts+1 WHERE user_id=?"
        ).bind(user_id).run()
    except Exception:
        pass
    return False


__all__ = [
    "AUTH_SESSION_REVOKE_PATH",
    "AUTH_SESSION_REVOKE_URL",
    "flush_pending",
    "revoke_after_credential_change",
]
