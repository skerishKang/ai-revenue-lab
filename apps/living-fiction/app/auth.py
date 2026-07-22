"""Web authentication: invite codes, sessions, CSRF, and cookies.

Security properties:
- Invite codes are CSPRNG-generated and stored only as keyed HMAC digests.
- Invites are pre-bound to a reader; login reuses that reader and never
  creates one. Invites carry optional expiry and explicit revocation, and
  every invalid condition (unknown, expired, revoked, unbound, or bound to a
  missing/inactive reader) collapses to one privacy-safe failure.
- Session tokens are CSPRNG-generated and stored only as keyed HMAC digests.
- Reader and admin sessions use separate cookie names and tables, an absolute
  expiry, and explicit revocation.
- Raw tokens exist only in cookies, never in the database.
- All cookies are HttpOnly, SameSite=Lax, and Secure in production.
- CSRF tokens are purpose-bound keyed HMACs:
    * pre-auth forms use a signed nonce tied to a purpose-specific
      double-submit cookie;
    * authenticated forms derive the token from the raw session token and a
      purpose, so a reader token can never satisfy an admin form (or vice
      versa) and a token is meaningless without the matching session cookie.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app.utils import now_utc_iso, parse_iso_datetime


# ── Constants ──────────────────────────────────────────────────────────────

READER_COOKIE_NAME = "lf_reader_session"
ADMIN_COOKIE_NAME = "lf_admin_session"
READER_PREAUTH_COOKIE_NAME = "lf_reader_preauth"
ADMIN_PREAUTH_COOKIE_NAME = "lf_admin_preauth"
SESSION_TTL_HOURS = 24
INVITE_CODE_BYTES = 32  # 43-char urlsafe string
SESSION_TOKEN_BYTES = 32

# CSRF purposes — each derives an independent keyed MAC so a token minted for
# one surface cannot be replayed on another.
CSRF_READER_PREAUTH = "reader-preauth"
CSRF_ADMIN_PREAUTH = "admin-preauth"
CSRF_READER_SESSION = "reader-session"
CSRF_ADMIN_SESSION = "admin-session"

# Session-token HMAC purposes — reader and admin session digests use distinct
# purposes so the same raw token never yields the same stored digest across the
# two session tables (a reader token digest can never collide with an admin one).
SESSION_TOKEN_READER_PURPOSE = "reader-session-token"
SESSION_TOKEN_ADMIN_PURPOSE = "admin-session-token"

# Idle expiry: independent of the absolute ``expires_at``, a session is rejected
# once it has been unused for this long. ``last_seen_at`` is refreshed (throttled)
# on valid use but never extends the absolute expiry.
IDLE_TIMEOUT_SECONDS = 1800
IDLE_REFRESH_INTERVAL_SECONDS = 60

# Cookie paths. The reader session must span ``/read``, ``/read/*`` and
# ``/logout``, so it stays at ``/``. Admin surfaces are scoped under ``/admin``
# and each pre-auth cookie is scoped to the access route that sets it.
READER_SESSION_COOKIE_PATH = "/"
ADMIN_SESSION_COOKIE_PATH = "/admin"
READER_PREAUTH_COOKIE_PATH = "/access"
ADMIN_PREAUTH_COOKIE_PATH = "/admin/access"

_CSRF_KEY_PREFIX = "lf-csrf-v1:"


# ── HMAC helpers ───────────────────────────────────────────────────────────


def _hmac_digest(key: str, value: str) -> str:
    """Return a hex HMAC-SHA256 digest of *value* under *key*."""
    return hmac.new(
        key.encode("utf-8"), value.encode("utf-8"), "sha256"
    ).hexdigest()


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _derive_csrf_key(hmac_key: str, purpose: str) -> str:
    """Derive an independent keyed-MAC key for a CSRF *purpose*."""
    return _hmac_digest(hmac_key, _CSRF_KEY_PREFIX + purpose)


# ── CSRF: pre-auth (signed nonce + double-submit cookie) ───────────────────


def issue_preauth_csrf(hmac_key: str, purpose: str) -> str:
    """Return a signed pre-auth CSRF token of the form ``nonce.signature``."""
    nonce = secrets.token_urlsafe(32)
    sig = _hmac_digest(_derive_csrf_key(hmac_key, purpose), nonce)
    return f"{nonce}.{sig}"


def verify_preauth_csrf(
    hmac_key: str,
    purpose: str,
    cookie_value: str | None,
    form_value: str | None,
) -> bool:
    """Verify a pre-auth CSRF token.

    The submitted form value must be a valid signed nonce for *purpose* and
    must equal the double-submit cookie, binding the submission to the browser
    that received the form.
    """
    if not cookie_value or not form_value:
        return False
    if not _constant_time_compare(cookie_value, form_value):
        return False
    nonce, _, sig = form_value.partition(".")
    if not nonce or not sig:
        return False
    expected = _hmac_digest(_derive_csrf_key(hmac_key, purpose), nonce)
    return _constant_time_compare(expected, sig)


# ── CSRF: authenticated (derived from raw session token + purpose) ─────────


def compute_session_csrf(raw_token: str, hmac_key: str, purpose: str) -> str:
    """Derive the CSRF token rendered into an authenticated form."""
    return _hmac_digest(_derive_csrf_key(hmac_key, purpose), raw_token)


def verify_session_csrf(
    raw_token: str,
    hmac_key: str,
    purpose: str,
    provided: str | None,
) -> bool:
    """Verify an authenticated form's CSRF token against the session token."""
    if not raw_token or not provided:
        return False
    expected = compute_session_csrf(raw_token, hmac_key, purpose)
    return _constant_time_compare(expected, provided)


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
    *,
    bound_reader_id: str | None = None,
    expires_at: str | None = None,
    credential_id: str | None = None,
) -> str:
    """Store an invite credential digest, optionally bound to a reader.

    ``bound_reader_id`` is the reader a login will assume — login never creates
    a reader. ``expires_at`` (ISO-8601 UTC) optionally limits validity. Returns
    the credential ID.
    """
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    cred_id = credential_id or secrets.token_urlsafe(16)
    digest = hash_invite_code(code, hmac_key)
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO invite_credentials "
            "(id, code_digest, created_at, bound_reader_id, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cred_id, digest, now, bound_reader_id, expires_at),
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
) -> str | None:
    """Verify an invite code and return the bound reader ID if usable.

    Returns the bound ``reader_id`` only when the invite exists, is not
    revoked, is not expired, and is bound to a reader. Returns ``None`` for
    every other case so callers produce a single privacy-safe error without
    revealing which condition failed.
    """
    digest = hash_invite_code(code, hmac_key)
    row = conn.execute(
        "SELECT bound_reader_id, expires_at, revoked_at "
        "FROM invite_credentials WHERE code_digest = ?",
        (digest,),
    ).fetchone()
    if row is None:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] is not None and row["expires_at"] < now_utc_iso():
        return None
    if row["bound_reader_id"] is None:
        return None
    return row["bound_reader_id"]


def revoke_invite(conn: sqlite3.Connection, credential_id: str) -> bool:
    """Revoke an invite so it can no longer be used to log in."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE invite_credentials SET revoked_at = ? "
            "WHERE id = ? AND revoked_at IS NULL",
            (now, credential_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


# ── Session management ─────────────────────────────────────────────────────


def _hash_reader_token(token: str, hmac_key: str) -> str:
    """Keyed digest of a reader session token (reader-purpose bound)."""
    return _hmac_digest(hmac_key, SESSION_TOKEN_READER_PURPOSE + ":" + token)


def _hash_admin_token(token: str, hmac_key: str) -> str:
    """Keyed digest of an admin session token (admin-purpose bound)."""
    return _hmac_digest(hmac_key, SESSION_TOKEN_ADMIN_PURPOSE + ":" + token)


def _generate_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def _expiry(now: datetime, ttl_hours: int = SESSION_TTL_HOURS) -> str:
    return (now + timedelta(hours=ttl_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds_between(earlier_iso: str, later_iso: str) -> float | None:
    """Return ``later - earlier`` in seconds, or None if either is unparseable."""
    try:
        earlier = parse_iso_datetime(earlier_iso)
        later = parse_iso_datetime(later_iso)
    except (ValueError, TypeError):
        return None
    return (later - earlier).total_seconds()


def _idle_expired(last_seen_iso: str | None, now_iso: str) -> bool:
    """True when a session has been idle longer than ``IDLE_TIMEOUT_SECONDS``.

    A missing ``last_seen_at`` (e.g. a row created before migration 008) is
    treated as not idle-expired so the absolute ``expires_at`` remains the only
    cap for legacy rows.
    """
    if last_seen_iso is None:
        return False
    elapsed = _seconds_between(last_seen_iso, now_iso)
    if elapsed is None:
        return False
    return elapsed >= IDLE_TIMEOUT_SECONDS


def _touch_last_seen(
    conn: sqlite3.Connection,
    table: str,
    token_digest: str,
    last_seen_iso: str | None,
    now_iso: str,
) -> None:
    """Throttled ``last_seen_at`` refresh for idle-expiry tracking.

    Writes at most once per ``IDLE_REFRESH_INTERVAL_SECONDS`` to avoid a DB
    write on every request. Never touches ``expires_at`` (so the absolute
    expiry is never extended) and never revives a revoked/expired row. Skips
    silently when the connection is owned by a caller transaction so it never
    interferes with concurrent request handling.
    """
    if table not in ("reader_sessions", "admin_sessions"):
        raise ValueError(f"unexpected session table: {table}")
    if conn.in_transaction:
        return
    if last_seen_iso is not None:
        elapsed = _seconds_between(last_seen_iso, now_iso)
        if elapsed is not None and elapsed < IDLE_REFRESH_INTERVAL_SECONDS:
            return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE {table} SET last_seen_at = ? "
            "WHERE token_digest = ? AND revoked_at IS NULL AND expires_at > ?",
            (now_iso, token_digest, now_iso),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()


def create_reader_session(
    conn: sqlite3.Connection,
    reader_id: str,
    hmac_key: str,
) -> str:
    """Create a reader session. Returns the raw token (cookie value)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token = _generate_token()
    token_digest = _hash_reader_token(token, hmac_key)
    # Stored digest kept for schema compatibility; form CSRF is derived
    # statelessly from the raw token (see compute_session_csrf).
    csrf_digest = _hmac_digest(hmac_key, token)
    now = datetime.now(timezone.utc)
    expires = _expiry(now)
    now_iso = now_utc_iso()
    session_id = secrets.token_urlsafe(16)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO reader_sessions "
            "(id, reader_id, token_digest, csrf_token_digest, created_at, "
            "expires_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, reader_id, token_digest, csrf_digest, now_iso,
             expires, now_iso),
        )
        conn.commit()
        return token
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def create_admin_session(
    conn: sqlite3.Connection,
    hmac_key: str,
) -> str:
    """Create an admin session. Returns the raw token (cookie value)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token = _generate_token()
    token_digest = _hash_admin_token(token, hmac_key)
    csrf_digest = _hmac_digest(hmac_key, token)
    now = datetime.now(timezone.utc)
    expires = _expiry(now)
    now_iso = now_utc_iso()
    session_id = secrets.token_urlsafe(16)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO admin_sessions "
            "(id, token_digest, csrf_token_digest, created_at, expires_at, "
            "last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, token_digest, csrf_digest, now_iso, expires, now_iso),
        )
        conn.commit()
        return token
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_reader_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> str | None:
    """Return the reader ID if the session is valid.

    A session is valid only when it exists, is not revoked, is not past its
    absolute expiry, and has not been idle longer than ``IDLE_TIMEOUT_SECONDS``.
    A valid lookup throttled-refreshes ``last_seen_at`` (never extending the
    absolute expiry). Returns ``None`` otherwise.
    """
    token_digest = _hash_reader_token(token, hmac_key)
    now = now_utc_iso()
    row = conn.execute(
        "SELECT reader_id, expires_at, revoked_at, last_seen_at "
        "FROM reader_sessions WHERE token_digest = ?",
        (token_digest,),
    ).fetchone()
    if row is None:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] < now:
        return None
    if _idle_expired(row["last_seen_at"], now):
        return None
    _touch_last_seen(
        conn, "reader_sessions", token_digest, row["last_seen_at"], now
    )
    return row["reader_id"]


def get_admin_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> bool:
    """Return True if the admin session is valid.

    Valid means: exists, not revoked, not past absolute expiry, and not idle
    longer than ``IDLE_TIMEOUT_SECONDS``. A valid lookup throttled-refreshes
    ``last_seen_at`` (never extending the absolute expiry).
    """
    token_digest = _hash_admin_token(token, hmac_key)
    now = now_utc_iso()
    row = conn.execute(
        "SELECT expires_at, revoked_at, last_seen_at "
        "FROM admin_sessions WHERE token_digest = ?",
        (token_digest,),
    ).fetchone()
    if row is None:
        return False
    if row["revoked_at"] is not None:
        return False
    if row["expires_at"] < now:
        return False
    if _idle_expired(row["last_seen_at"], now):
        return False
    _touch_last_seen(
        conn, "admin_sessions", token_digest, row["last_seen_at"], now
    )
    return True


def delete_reader_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> None:
    """Delete a reader session by raw token (logout)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token_digest = _hash_reader_token(token, hmac_key)
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
    """Delete an admin session by raw token (logout)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token_digest = _hash_admin_token(token, hmac_key)
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


def revoke_reader_session(
    conn: sqlite3.Connection,
    token: str,
    hmac_key: str,
) -> None:
    """Soft-revoke a reader session by raw token."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    token_digest = _hash_reader_token(token, hmac_key)
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE reader_sessions SET revoked_at = ? "
            "WHERE token_digest = ? AND revoked_at IS NULL",
            (now, token_digest),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def revoke_all_reader_sessions(
    conn: sqlite3.Connection,
    reader_id: str,
) -> int:
    """Soft-revoke every session for a reader (e.g. on deactivation/deletion)."""
    if conn.in_transaction:
        raise RuntimeError("repository write requires an idle connection")
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "UPDATE reader_sessions SET revoked_at = ? "
            "WHERE reader_id = ? AND revoked_at IS NULL",
            (now, reader_id),
        )
        conn.commit()
        return cursor.rowcount
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


# ── Cookie helpers ─────────────────────────────────────────────────────────


def set_reader_cookie(response, token: str, is_production: bool) -> None:
    response.set_cookie(
        READER_COOKIE_NAME,
        token,
        path=READER_SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=is_production,
    )


def set_admin_cookie(response, token: str, is_production: bool) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        token,
        path=ADMIN_SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=is_production,
    )


def set_preauth_cookie(
    response, name: str, value: str, is_production: bool, path: str
) -> None:
    """Set a pre-auth double-submit CSRF cookie (HttpOnly; not JS-readable)."""
    response.set_cookie(
        name,
        value,
        path=path,
        httponly=True,
        samesite="lax",
        secure=is_production,
    )


def clear_reader_cookie(response) -> None:
    response.delete_cookie(READER_COOKIE_NAME, path=READER_SESSION_COOKIE_PATH)


def clear_admin_cookie(response) -> None:
    response.delete_cookie(ADMIN_COOKIE_NAME, path=ADMIN_SESSION_COOKIE_PATH)


def clear_preauth_cookie(response, name: str, path: str) -> None:
    response.delete_cookie(name, path=path)
