"""Security utilities for Living Travel Phase 2.

Token generation, hashing, session management, CSRF protection, rate limiting.
All secrets are stored as one-way digests. Raw tokens are shown once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Protocol


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


# --- Rate Limiting for Operator Login ---

class _Clock(Protocol):
    """Protocol for testable clock."""
    def now(self) -> datetime: ...


class _SystemClock:
    """Default system clock."""
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class LoginRateLimiter:
    """In-memory rate limiter for operator login attempts."""

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300, lockout_seconds: int = 60, clock: _Clock | None = None) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._lockout_seconds = lockout_seconds
        self._clock = clock or _SystemClock()
        self._failures: dict[str, list[float]] = {}
        self._lockouts: dict[str, float] = {}
        self._lock = threading.Lock()

    def _cleanup_old_failures(self, key: str) -> None:
        now_ts = self._clock.now().timestamp()
        cutoff = now_ts - self._window_seconds
        self._failures[key] = [t for t in self._failures.get(key, []) if t > cutoff]

    def is_locked(self, key: str) -> bool:
        with self._lock:
            lockout_until = self._lockouts.get(key, 0)
            now_ts = self._clock.now().timestamp()
            if lockout_until > now_ts:
                return True
            if lockout_until > 0:
                self._lockouts.pop(key, None)
                self._failures.pop(key, None)
            return False

    def record_failure(self, key: str) -> None:
        with self._lock:
            now_ts = self._clock.now().timestamp()
            self._cleanup_old_failures(key)
            self._failures.setdefault(key, []).append(now_ts)
            if len(self._failures[key]) >= self._max_failures:
                self._lockouts[key] = now_ts + self._lockout_seconds

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._lockouts.pop(key, None)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._lockouts.pop(key, None)


_login_rate_limiter: LoginRateLimiter | None = None


def get_login_rate_limiter() -> LoginRateLimiter:
    global _login_rate_limiter
    if _login_rate_limiter is None:
        _login_rate_limiter = LoginRateLimiter()
    return _login_rate_limiter


def reset_login_rate_limiter() -> None:
    global _login_rate_limiter
    _login_rate_limiter = None


def generate_high_entropy_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure high-entropy token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """One-way SHA-256 hash of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_csrf_token() -> str:
    """Generate a CSRF token."""
    return secrets.token_urlsafe(24)


# --- Operator Session Management ---

def create_operator_session(conn: sqlite3.Connection, *, session_ttl_hours: int = 8) -> tuple[str, str, str]:
    now = _utcnow_dt()
    expires = now + timedelta(hours=session_ttl_hours)
    session_id = f"os_{secrets.token_urlsafe(16)}"
    raw_token = generate_high_entropy_token(32)
    token_hash = hash_token(raw_token)
    csrf = generate_csrf_token()
    conn.execute(
        "INSERT INTO operator_sessions (id, session_token, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, token_hash, csrf, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    return session_id, raw_token, csrf


def validate_operator_session(conn: sqlite3.Connection, raw_session_token: str) -> dict | None:
    if not raw_session_token:
        return None
    token_hash = hash_token(raw_session_token)
    row = conn.execute(
        "SELECT id, session_token, csrf_token, created_at, expires_at FROM operator_sessions WHERE session_token = ?",
        (token_hash,),
    ).fetchone()
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if _utcnow_dt() > expires:
        conn.execute("DELETE FROM operator_sessions WHERE id = ?", (row["id"],))
        conn.commit()
        return None
    return {"session_id": row["id"], "csrf_token": row["csrf_token"], "created_at": row["created_at"], "expires_at": row["expires_at"]}


def invalidate_operator_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM operator_sessions WHERE id = ?", (session_id,))
    conn.commit()


def rotate_operator_session(conn: sqlite3.Connection, session_id: str) -> tuple[str, str, str]:
    invalidate_operator_session(conn, session_id)
    return create_operator_session(conn)


# --- Traveler Token Management ---

def create_traveler_token(conn: sqlite3.Connection, traveler_id: str, *, commit: bool = True) -> tuple[str, str]:
    raw_token = generate_high_entropy_token(32)
    token_hash = hash_token(raw_token)
    token_id = f"tt_{secrets.token_urlsafe(16)}"
    now = _utcnow()
    conn.execute(
        "INSERT INTO traveler_tokens (id, traveler_id, token_hash, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
        (token_id, traveler_id, token_hash, now),
    )
    if commit:
        conn.commit()
    return token_id, raw_token


def rotate_traveler_token(conn: sqlite3.Connection, token_id: str) -> tuple[str, str]:
    conn.execute("UPDATE traveler_tokens SET is_active = 0, rotated_at = ? WHERE id = ?", (_utcnow(), token_id))
    conn.commit()
    row = conn.execute("SELECT traveler_id FROM traveler_tokens WHERE id = ?", (token_id,)).fetchone()
    if not row:
        raise ValueError("Token not found")
    return create_traveler_token(conn, row["traveler_id"])


def validate_traveler_token(conn: sqlite3.Connection, raw_token: str) -> str | None:
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    row = conn.execute(
        "SELECT tt.traveler_id, tt.is_active FROM traveler_tokens tt JOIN travelers t ON t.id = tt.traveler_id WHERE tt.token_hash = ? AND tt.is_active = 1 AND t.status = 'active'",
        (token_hash,),
    ).fetchone()
    if not row:
        return None
    return row["traveler_id"]


def deactivate_traveler_tokens(conn: sqlite3.Connection, traveler_id: str, *, commit: bool = True) -> None:
    conn.execute("UPDATE traveler_tokens SET is_active = 0, rotated_at = ? WHERE traveler_id = ?", (_utcnow(), traveler_id))
    if commit:
        conn.commit()


# --- Traveler Session Management ---

def create_traveler_session(conn: sqlite3.Connection, traveler_id: str, *, session_ttl_hours: int = 24) -> tuple[str, str, str]:
    now = _utcnow_dt()
    expires = now + timedelta(hours=session_ttl_hours)
    session_id = f"ts_{secrets.token_urlsafe(16)}"
    raw_token = generate_high_entropy_token(32)
    token_hash = hash_token(raw_token)
    csrf = generate_csrf_token()
    conn.execute(
        "INSERT INTO traveler_sessions (id, traveler_id, session_token, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, traveler_id, token_hash, csrf, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    return session_id, raw_token, csrf


def validate_traveler_session(conn: sqlite3.Connection, raw_session_token: str) -> dict | None:
    if not raw_session_token:
        return None
    token_hash = hash_token(raw_session_token)
    row = conn.execute(
        "SELECT id, traveler_id, csrf_token, created_at, expires_at FROM traveler_sessions WHERE session_token = ?",
        (token_hash,),
    ).fetchone()
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if _utcnow_dt() > expires:
        conn.execute("DELETE FROM traveler_sessions WHERE id = ?", (row["id"],))
        conn.commit()
        return None
    active = conn.execute("SELECT status FROM travelers WHERE id = ?", (row["traveler_id"],)).fetchone()
    if not active or active["status"] != "active":
        conn.execute("DELETE FROM traveler_sessions WHERE id = ?", (row["id"],))
        conn.commit()
        return None
    return {"session_id": row["id"], "traveler_id": row["traveler_id"], "csrf_token": row["csrf_token"], "created_at": row["created_at"], "expires_at": row["expires_at"]}


def invalidate_traveler_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM traveler_sessions WHERE id = ?", (session_id,))
    conn.commit()


def rotate_traveler_session(conn: sqlite3.Connection, session_id: str, traveler_id: str) -> tuple[str, str, str]:
    invalidate_traveler_session(conn, session_id)
    return create_traveler_session(conn, traveler_id)
