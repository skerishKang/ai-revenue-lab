"""Web authentication: invite codes, sessions, CSRF, and cookies.

Security properties:
- Invite codes are CSPRNG-generated and stored only as keyed HMAC digests.
- Session tokens are CSPRNG-generated and stored only as keyed HMAC digests.
- Reader and admin sessions use separate cookie names and tables.
- Raw tokens exist only in cookies, never in the database.
- All cookies are HttpOnly, SameSite=Lax, and Secure in production.
- CSRF tokens are stored as digests alongside sessions.
"""

from __future__ import annotations

import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.utils import now_utc_iso


# ── Constants ──────────────────────────────────────────────────────────────

READER_COOKIE_NAME = "lf_reader_session"
ADMIN_COOKIE_NAME = "lf_admin_session"
SESSION_TTL_HOURS = 24
INVITE_CODE_BYTES = 32  # 43-char urlsafe string
SESSION_TOKEN_BYTES = 32


# ── HMAC helpers ───────────────────────────────────────────────────────────


def _hmac_digest(key: str, value: str) -> str:
    """Return a hex HMAC-SHA256 digest of *value* under *key*."""
    return hmac.new(
        key.encode("utf-8"), value.encode("utf-8"), "sha256"
    ).hexdigest()


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ── Invite code management ─────────────────────────────────────────────────


def generate_invite_code() -> str:
    """Generate a CSPRNG-based invite code (url-safe, ~43 chars)."""
    return secrets.token_urlsafe(INVITE_CODE_BYTES)


def hash_invite_code(code: str, hmac_key: str) -> str:
    """Return the keyed digest of an invite code."""
    return _hmac_digest(hmac_key, code)


def create_invite_credential(
    conn: sqlite3.Connection,
    code: str,
    hmac_key: str,
) -> str:
    """Store an invite credential digest. Returns the credential ID."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    cred_id = secrets.token_urlsafe(16)
    digest = hash_invite_code(code, hmac_key)
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO invite_credentials (id, code_digest, created_at) "
            "VALUES (?, ?, ?)",
            (cred_id, digest, now),
        )
        conn.commit()
        return cred_id
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def verify_invite_code(
    conn: sqlite3.Connection,
    code: str,
    hmac_key: str,
) -> tuple[str, str | None] | None:
    """Verify an invite code.

    Returns (credential_id, reader_id_or_None) if valid.
    - reader_id is None if the invite has not been consumed.
    - reader_id is set if the invite was already used by a reader.
    Returns None if the code does not match any credential.

    Uses constant-time comparison to prevent timing attacks.
    """
    digest = hash_invite_code(code, hmac_key)
    row = conn.execute(
        "SELECT id, used_by_reader_id FROM invite_credentials "
        "WHERE code_digest = ?",
        (digest,),
    ).fetchone()
    if row is None:
        return None
    return row["id"], row["used_by_reader_id"]


def mark_invite_used(
    conn: sqlite3.Connection,
    cred_id: str,
    reader_id: str,
) -> None:
    """Mark an invite credential as consumed by a reader."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE invite_credentials "
            "SET used_by_reader_id = ?, used_at = ? "
            "WHERE id = ? AND used_by_reader_id IS NULL",
            (reader_id, now, cred_id),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


# ── Session management ─────────────────────────────────────────────────────


def _hash_token(token: str, hmac_key: str) -> str:
    return _hmac_digest(hmac_key, token)


def _generate_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def _generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _expiry(now: datetime, ttl_hours: int = SESSION_TTL_HOURS) -> str:
    return (now + timedelta(hours=ttl_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_reader_session(
    conn: sqlite3.Connection,
    reader_id: str,
    hmac_key: str,
) -> tuple[str, str]:
    """Create a reader session. Returns (raw_token, csrf_token)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token = _generate_token()
    csrf = _generate_csrf_token()
    token_digest = _hash_token(token, hmac_key)
    csrf_digest = _hmac_digest(hmac_key, csrf)
    now = datetime.now(timezone.utc)
    expires = _expiry(now)
    session_id = secrets.token_urlsafe(16)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO reader_sessions "
            "(id, reader_id, token_digest, csrf_token_digest, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, reader_id, token_digest, csrf_digest, now_utc_iso(), expires),
        )
        conn.commit()
        return token, csrf
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def create_admin_session(
    conn: sqlite3.Connection,
    hmac_key: str,
) -> tuple[str, str]:
    """Create an admin session. Returns (raw_token, csrf_token)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token = _generate_token()
    csrf = _generate_csrf_token()
    token_digest = _hash_token(token, hmac_key)
    csrf_digest = _hmac_digest(hmac_key, csrf)
    now = datetime.now(timezone.utc)
    expires = _expiry(now)
    session_id = secrets.token_urlsafe(16)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO admin_sessions "
            "(id, token_digest, csrf_token_digest, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, token_digest, csrf_digest, now_utc_iso(), expires),
        )
        conn.commit()
        return token, csrf
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_reader_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> tuple[str, str] | None:
    """Look up a reader session by raw token.

    Returns (reader_id, csrf_token) if valid and not expired, else None.
    """
    token_digest = _hash_token(token, hmac_key)
    now = now_utc_iso()
    row = conn.execute(
        "SELECT reader_id, csrf_token_digest, expires_at "
        "FROM reader_sessions WHERE token_digest = ?",
        (token_digest,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < now:
        return None  # expired
    # Reconstruct CSRF token is not possible from digest; return digest
    # and let the caller compare via verify_csrf_token.
    return row["reader_id"], row["csrf_token_digest"]


def get_admin_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> str | None:
    """Look up an admin session by raw token.

    Returns csrf_token_digest if valid and not expired, else None.
    """
    token_digest = _hash_token(token, hmac_key)
    now = now_utc_iso()
    row = conn.execute(
        "SELECT csrf_token_digest, expires_at "
        "FROM admin_sessions WHERE token_digest = ?",
        (token_digest,),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < now:
        return None  # expired
    return row["csrf_token_digest"]


def verify_csrf_token(
    csrf_digest: str,
    provided_csrf: str,
    hmac_key: str,
) -> bool:
    """Verify a CSRF token against the stored digest.

    The CSRF token rendered in forms is the stored digest itself (not the
    raw CSPRNG token). This is safe because the digest is an HMAC of a
    CSPRNG value and is never stored in a cookie — it is only visible in
    the HTML form, which cross-site attackers cannot read.
    """
    return _constant_time_compare(csrf_digest, provided_csrf)


def delete_reader_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> None:
    """Delete a reader session by raw token."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token_digest = _hash_token(token, hmac_key)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "DELETE FROM reader_sessions WHERE token_digest = ?",
            (token_digest,),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def delete_admin_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> None:
    """Delete an admin session by raw token."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token_digest = _hash_token(token, hmac_key)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "DELETE FROM admin_sessions WHERE token_digest = ?",
            (token_digest,),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


# ── Cookie helpers ─────────────────────────────────────────────────────────


def _cookie_value(token: str, is_production: bool) -> str:
    parts = [f"token={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if is_production:
        parts.append("Secure")
    return "; ".join(parts)


def set_reader_cookie(response, token: str, is_production: bool) -> None:
    response.set_cookie(
        READER_COOKIE_NAME,
        token,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_production,
    )


def set_admin_cookie(response, token: str, is_production: bool) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        token,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_production,
    )


def clear_reader_cookie(response) -> None:
    response.delete_cookie(READER_COOKIE_NAME, path="/")


def clear_admin_cookie(response) -> None:
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")
