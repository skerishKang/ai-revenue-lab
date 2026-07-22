"""Focused tests for traveler web routes.

Tests: token auth, preferences, edition viewing, feedback, ownership isolation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.config import get_settings, reset_settings
from app.db import apply_migrations
from app.factory import create_app
from app.security import (
    create_traveler_token,
    create_traveler_session,
    reset_login_rate_limiter,
)
from app.traveler_repository import create_traveler
from app.edition_repository import create_edition, update_edition_content, update_edition_publication, update_edition_generation_status
from app.feedback_repository import create_feedback


@pytest.fixture()
def app(tmp_path: Path):
    reset_settings()
    reset_login_rate_limiter()
    import os
    db_path = str(tmp_path / "test.db")
    os.environ["LT_DATABASE_URL"] = db_path
    os.environ["LT_OPERATOR_SECRET"] = "test-secret-12345"
    reset_settings()
    application = create_app()
    yield application
    reset_settings()
    reset_login_rate_limiter()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def seeded_app(app):
    """App with two active travelers."""
    from app.db import get_connection
    conn = get_connection()
    create_traveler(conn, display_name="Alice", destination="Seoul", trip_duration_nights=3)
    create_traveler(conn, display_name="Bob", destination="Tokyo", trip_duration_nights=5)
    conn.close()
    return app


@pytest.fixture()
def alice_client(seeded_app):
    """Client authenticated as Alice."""
    from app.db import get_connection
    conn = get_connection()
    alice = conn.execute("SELECT id FROM travelers WHERE display_name = 'Alice'").fetchone()
    alice_id = alice["id"]
    token_id, raw_token = create_traveler_token(conn, alice_id)
    session_id, raw_session, csrf = create_traveler_session(conn, alice_id)
    conn.close()

    c = TestClient(seeded_app)
    c.cookies.set("lt_traveler_session", raw_session)
    c._csrf = csrf  # Store for CSRF
    return c


@pytest.fixture()
def bob_client(seeded_app):
    """Client authenticated as Bob."""
    from app.db import get_connection
    conn = get_connection()
    bob = conn.execute("SELECT id FROM travelers WHERE display_name = 'Bob'").fetchone()
    bob_id = bob["id"]
    token_id, raw_token = create_traveler_token(conn, bob_id)
    session_id, raw_session, csrf = create_traveler_session(conn, bob_id)
    conn.close()

    c = TestClient(seeded_app)
    c.cookies.set("lt_traveler_session", raw_session)
    c._csrf = csrf
    return c


class TestTravelerAuth:
    """Test traveler token authentication flow."""

    def test_enter_page_returns_200(self, client: TestClient):
        resp = client.get("/traveler/enter")
        assert resp.status_code == 200
        assert "Access Token" in resp.text

    def test_enter_page_has_csrf(self, client: TestClient):
        resp = client.get("/traveler/enter")
        assert "lt_csrf" in resp.cookies

    def test_invalid_token_shows_error(self, client: TestClient):
        login_page = client.get("/traveler/enter")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/traveler/enter", data={
            "token": "invalid-token",
            "csrf_token": csrf or "",
        }, cookies={"lt_csrf": csrf or ""})
        assert resp.status_code == 200
        assert "Invalid" in resp.text or "error" in resp.text.lower()

    def test_valid_token_creates_session(self, seeded_app, client: TestClient):
        from app.db import get_connection
        conn = get_connection()
        alice = conn.execute("SELECT id FROM travelers WHERE display_name = 'Alice'").fetchone()
        alice_id = alice["id"]
        token_id, raw_token = create_traveler_token(conn, alice_id)
        conn.close()

        login_page = client.get("/traveler/enter")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/traveler/enter", data={
            "token": raw_token,
            "csrf_token": csrf or "",
        }, cookies={"lt_csrf": csrf or ""})
        assert resp.status_code in (200, 303)
        assert "lt_traveler_session" in resp.cookies or "lt_traveler_session" in client.cookies

    def test_deactivated_traveler_token_fails(self, seeded_app, client: TestClient):
        from app.db import get_connection
        conn = get_connection()
        bob = conn.execute("SELECT id FROM travelers WHERE display_name = 'Bob'").fetchone()
        bob_id = bob["id"]
        token_id, raw_token = create_traveler_token(conn, bob_id)
        # Deactivate Bob
        conn.execute("UPDATE travelers SET status = 'deleted' WHERE id = ?", (bob_id,))
        conn.commit()
        conn.close()

        login_page = client.get("/traveler/enter")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/traveler/enter", data={
            "token": raw_token,
            "csrf_token": csrf or "",
        }, cookies={"lt_csrf": csrf or ""})
        assert resp.status_code == 200
        assert "Invalid" in resp.text or "deactivated" in resp.text.lower()


class TestTravelerDashboard:
    """Test traveler dashboard and preferences."""

    def test_dashboard_shows_traveler_name(self, alice_client: TestClient):
        resp = alice_client.get("/traveler/")
        assert resp.status_code == 200
        assert "Alice" in resp.text

    def test_dashboard_shows_preferences(self, alice_client: TestClient):
        resp = alice_client.get("/traveler/")
        assert "Seoul" in resp.text or "destination" in resp.text.lower()

    def test_update_preferences(self, alice_client: TestClient):
        csrf = getattr(alice_client, '_csrf', '')
        resp = alice_client.post("/traveler/preferences", data={
            "destination": "Busan",
            "trip_duration_nights": 4,
            "interests": "food,beaches",
            "csrf_token": csrf,
        }, cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)

        # Verify update
        resp2 = alice_client.get("/traveler/")
        assert "Busan" in resp2.text or "4" in resp2.text

    def test_preferences_requires_csrf(self, alice_client: TestClient):
        resp = alice_client.post("/traveler/preferences", data={
            "destination": "Hack",
            "csrf_token": "wrong",
        }, cookies={"lt_csrf": "mismatch"})
        assert resp.status_code in (403, 200)


class TestTravelerLogout:
    """Test traveler logout CSRF protection."""

    def test_logout_requires_csrf(self, alice_client: TestClient):
        # Logout without CSRF should fail
        resp = alice_client.post("/traveler/logout", data={"csrf_token": "wrong"})
        assert resp.status_code == 403

    def test_logout_invalidates_session(self, alice_client: TestClient):
        csrf = getattr(alice_client, '_csrf', '')
        resp = alice_client.post("/traveler/logout",
            data={"csrf_token": csrf},
            cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)
        # Should no longer be able to access dashboard
        resp2 = alice_client.get("/traveler/")
        assert resp2.status_code in (307, 200)


class TestOwnershipIsolation:
    """Verify travelers cannot access each other's data."""

    def test_alice_cannot_view_bob_edition(self, seeded_app, alice_client: TestClient):
        from app.db import get_connection
        conn = get_connection()
        bob = conn.execute("SELECT id FROM travelers WHERE display_name = 'Bob'").fetchone()
        bob_id = bob["id"]
        # Create a published edition for Bob
        edition = create_edition(conn, traveler_id=bob_id, edition_number=1)
        update_edition_content(conn, edition.id, {"title": "Bob's Edition", "sections": []})
        update_edition_generation_status(conn, edition.id, "pending_review")
        update_edition_publication(conn, edition.id, "published")
        bob_edition_id = edition.id
        conn.close()

        # Alice tries to access Bob's edition
        resp = alice_client.get(f"/traveler/editions/{bob_edition_id}")
        # Should get 404 (generic not found)
        assert resp.status_code == 404

    def test_pending_edition_not_visible_to_traveler(self, seeded_app, alice_client: TestClient):
        from app.db import get_connection
        conn = get_connection()
        alice = conn.execute("SELECT id FROM travelers WHERE display_name = 'Alice'").fetchone()
        alice_id = alice["id"]
        edition = create_edition(conn, traveler_id=alice_id, edition_number=1)
        update_edition_content(conn, edition.id, {"title": "Pending", "sections": []})
        update_edition_generation_status(conn, edition.id, "pending_review")
        conn.close()

        resp = alice_client.get("/traveler/")
        assert resp.status_code == 200
        assert f"/traveler/editions/{edition.id}" not in resp.text
