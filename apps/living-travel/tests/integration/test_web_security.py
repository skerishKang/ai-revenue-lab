"""Focused security tests for Living Travel Phase 2 web layer.

Tests: token security, session management, CSRF, XSS, rate limiting, privacy.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from app.security import (
    LoginRateLimiter,
    constant_time_compare,
    create_operator_session,
    create_traveler_session,
    create_traveler_token,
    deactivate_traveler_tokens,
    generate_csrf_token,
    generate_high_entropy_token,
    get_login_rate_limiter,
    hash_token,
    invalidate_operator_session,
    invalidate_traveler_session,
    rotate_traveler_token,
    validate_operator_session,
    validate_traveler_session,
    validate_traveler_token,
)


# ── Token Security ─────────────────────────────────────────────────

class TestTokenSecurity:
    """Verify token generation is cryptographically secure."""

    def test_high_entropy_token_has_sufficient_length(self):
        token = generate_high_entropy_token(32)
        assert len(token) >= 40  # urlsafe encoding expands bytes

    def test_tokens_are_unique(self):
        tokens = {generate_high_entropy_token(32) for _ in range(100)}
        assert len(tokens) == 100

    def test_token_is_urlsafe(self):
        token = generate_high_entropy_token(32)
        # urlsafe uses A-Z, a-z, 0-9, -, _
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in token)

    def test_csrf_token_is_unique(self):
        tokens = {generate_csrf_token() for _ in range(100)}
        assert len(tokens) == 100


class TestTokenStorage:
    """Verify tokens are stored as digests, not raw values."""

    def test_raw_token_not_in_db(self, seeded_db: sqlite3.Connection):
        token_id, raw_token = create_traveler_token(seeded_db, "travel_test_001")
        # Check that raw token does not appear in DB
        cursor = seeded_db.execute("SELECT * FROM traveler_tokens WHERE id = ?", (token_id,))
        row = cursor.fetchone()
        assert raw_token not in str(row["token_hash"])
        # Verify it's a SHA-256 hash
        assert len(row["token_hash"]) == 64  # hex-encoded SHA-256

    def test_token_hash_is_sha256(self):
        token = "test-token-123"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert hash_token(token) == expected

    def test_constant_time_comparison(self):
        a = "abc123"
        b = "abc123"
        c = "abc124"
        assert constant_time_compare(a, b) is True
        assert constant_time_compare(a, c) is False


class TestTokenRotation:
    """Verify token rotation invalidates old token."""

    def test_rotation_invalidates_old_token(self, seeded_db: sqlite3.Connection):
        token_id, raw_token = create_traveler_token(seeded_db, "travel_test_001")
        # Old token should work
        assert validate_traveler_token(seeded_db, raw_token) == "travel_test_001"
        # Rotate
        new_token_id, new_raw_token = rotate_traveler_token(seeded_db, token_id)
        # Old token should fail
        assert validate_traveler_token(seeded_db, raw_token) is None
        # New token should work
        assert validate_traveler_token(seeded_db, new_raw_token) == "travel_test_001"

    def test_deactivated_traveler_token_fails(self, seeded_db: sqlite3.Connection):
        token_id, raw_token = create_traveler_token(seeded_db, "travel_test_001")
        # Deactivate traveler
        seeded_db.execute("UPDATE travelers SET status = 'deleted' WHERE id = ?", ("travel_test_001",))
        seeded_db.commit()
        # Token should fail
        assert validate_traveler_token(seeded_db, raw_token) is None


class TestDeactivatedTokens:
    """Verify deactivated token batch works."""

    def test_deactivate_all_tokens(self, seeded_db: sqlite3.Connection):
        token_id1, raw1 = create_traveler_token(seeded_db, "travel_test_001")
        token_id2, raw2 = create_traveler_token(seeded_db, "travel_test_001")
        deactivate_traveler_tokens(seeded_db, "travel_test_001")
        assert validate_traveler_token(seeded_db, raw1) is None
        assert validate_traveler_token(seeded_db, raw2) is None


# ── Session Management ─────────────────────────────────────────────

class TestOperatorSession:
    """Verify operator session creation, validation, and rotation."""

    def test_create_and_validate_session(self, temp_db: sqlite3.Connection):
        session_id, raw_token, csrf = create_operator_session(temp_db)
        assert session_id.startswith("os_")
        result = validate_operator_session(temp_db, raw_token)
        assert result is not None
        assert result["session_id"] == session_id
        assert result["csrf_token"] == csrf

    def test_invalid_token_returns_none(self, temp_db: sqlite3.Connection):
        assert validate_operator_session(temp_db, "nonexistent") is None

    def test_empty_token_returns_none(self, temp_db: sqlite3.Connection):
        assert validate_operator_session(temp_db, "") is None

    def test_invalidate_session(self, temp_db: sqlite3.Connection):
        session_id, raw_token, _ = create_operator_session(temp_db)
        invalidate_operator_session(temp_db, session_id)
        assert validate_operator_session(temp_db, raw_token) is None

    def test_session_rotation(self, temp_db: sqlite3.Connection):
        session_id, raw_old, csrf_old = create_operator_session(temp_db)
        new_id, raw_new, csrf_new = create_operator_session(temp_db)
        invalidate_operator_session(temp_db, session_id)
        assert validate_operator_session(temp_db, raw_old) is None
        assert validate_operator_session(temp_db, raw_new) is not None


class TestTravelerSession:
    """Verify traveler session creation, validation, and deactivation."""

    def test_create_and_validate_session(self, seeded_db: sqlite3.Connection):
        session_id, raw_token, csrf = create_traveler_session(seeded_db, "travel_test_001")
        assert session_id.startswith("ts_")
        result = validate_traveler_session(seeded_db, raw_token)
        assert result is not None
        assert result["session_id"] == session_id
        assert result["traveler_id"] == "travel_test_001"

    def test_invalid_token_returns_none(self, seeded_db: sqlite3.Connection):
        assert validate_traveler_session(seeded_db, "nonexistent") is None

    def test_deactivated_traveler_session_rejected(self, seeded_db: sqlite3.Connection):
        session_id, raw_token, _ = create_traveler_session(seeded_db, "travel_test_001")
        seeded_db.execute("UPDATE travelers SET status = 'deleted' WHERE id = ?", ("travel_test_001",))
        seeded_db.commit()
        assert validate_traveler_session(seeded_db, raw_token) is None

    def test_invalidate_session(self, seeded_db: sqlite3.Connection):
        session_id, raw_token, _ = create_traveler_session(seeded_db, "travel_test_001")
        invalidate_traveler_session(seeded_db, session_id)
        assert validate_traveler_session(seeded_db, raw_token) is None


# ── CSRF Protection ────────────────────────────────────────────────

class TestCSRF:
    """Verify CSRF token generation and comparison."""

    def test_csrf_tokens_differ(self):
        assert generate_csrf_token() != generate_csrf_token()

    def test_csrf_token_is_sufficient_entropy(self):
        token = generate_csrf_token()
        # 24 bytes urlsafe -> ~32 chars, should be enough
        assert len(token) >= 20


class TestLoginCSRF:
    """Verify CSRF protection on login routes."""

    def test_operator_login_requires_csrf(self, sync_client: TestClient):
        # Try login without CSRF cookie - include form field but no cookie match
        resp = sync_client.post("/operator/login", data={"secret": "test-secret-12345", "csrf_token": "x"})
        assert resp.status_code in (200, 422)
        assert "Invalid CSRF" in resp.text or resp.status_code == 422

    def test_traveler_enter_requires_csrf(self, sync_client: TestClient):
        resp = sync_client.post("/traveler/enter", data={"token": "some-token"})
        
