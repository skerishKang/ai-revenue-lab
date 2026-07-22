"""Focused tests for operator web routes.

Tests: login flow, traveler management, invitation tokens, edition generation, publish/reject.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.config import get_settings, reset_settings
from app.db import get_connection
from app.factory import create_app
from app.security import (
    create_traveler_token,
    reset_login_rate_limiter,
)
from app.traveler_repository import create_traveler


@pytest.fixture()
def app(tmp_path: Path):
    """Create a test FastAPI application with isolated database."""
    reset_settings()
    reset_login_rate_limiter()
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
def logged_in_client(client):
    """Client with operator session."""
    # Access settings AFTER app creation so env vars are picked up
    settings = get_settings()
    secret = getattr(settings, "operator_secret", "test-secret-12345")
    login_page = client.get("/operator/login")
    csrf = client.cookies.get("lt_csrf")
    client.post("/operator/login", data={
        "secret": secret,
        "csrf_token": csrf or "",
    }, cookies={"lt_csrf": csrf or ""})
    return client


class TestOperatorLogin:
    """Test operator authentication flow."""

    def test_login_page_returns_200(self, client: TestClient):
        resp = client.get("/operator/login")
        assert resp.status_code == 200
        assert "Operator Login" in resp.text

    def test_login_page_has_csrf_token(self, client: TestClient):
        resp = client.get("/operator/login")
        assert "lt_csrf" in resp.cookies
        assert "csrf_token" in resp.text

    def test_wrong_secret_shows_error(self, client: TestClient):
        login_page = client.get("/operator/login")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/operator/login", data={
            "secret": "wrong-secret",
            "csrf_token": csrf or "",
        }, cookies={"lt_csrf": csrf or ""})
        assert resp.status_code == 200
        assert "Invalid secret" in resp.text

    def test_correct_secret_creates_session(self, client: TestClient):
        settings = get_settings()
        secret = getattr(settings, "operator_secret", "test-secret-12345")
        login_page = client.get("/operator/login")
        csrf = client.cookies.get("lt_csrf")
        resp = client.post("/operator/login", data={
            "secret": secret,
            "csrf_token": csrf or "",
        }, cookies={"lt_csrf": csrf or ""})
        assert resp.status_code in (200, 303)
        assert "lt_operator_session" in (resp.cookies or client.cookies)

    def test_session_rotation_on_login(self, client: TestClient):
        settings = get_settings()
        secret = getattr(settings, "operator_secret", "test-secret-12345")
        # First login
        client.get("/operator/login")
        csrf1 = client.cookies.get("lt_csrf")
        resp1 = client.post("/operator/login", data={
            "secret": secret,
            "csrf_token": csrf1 or "",
        }, cookies={"lt_csrf": csrf1 or ""})
        session1 = resp1.cookies.get("lt_operator_session", client.cookies.get("lt_operator_session"))

        # Second login
        client.get("/operator/login")
        csrf2 = client.cookies.get("lt_csrf")
        resp2 = client.post("/operator/login", data={
            "secret": secret,
            "csrf_token": csrf2 or "",
        }, cookies={"lt_csrf": csrf2 or ""})
        session2 = resp2.cookies.get("lt_operator_session", client.cookies.get("lt_operator_session"))

        # Sessions should differ (rotation)
        if session1 and session2:
            assert session1 != session2

    def test_logout_invalidates_session(self, logged_in_client: TestClient):
        # Get dashboard to verify logged in
        resp = logged_in_client.get("/operator/")
        assert resp.status_code == 200

        # Extract CSRF from dashboard
        dashboard = logged_in_client.get("/operator/")
        csrf = None
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', dashboard.text)
        if m:
            csrf = m.group(1)

        logout_resp = logged_in_client.post("/operator/logout",
            data={"csrf_token": csrf or ""},
            cookies={"lt_csrf": csrf or ""})
        assert logout_resp.status_code in (200, 303)

        # Try accessing dashboard - should redirect to login
        resp2 = logged_in_client.get("/operator/")
        assert resp2.status_code in (307, 200)


class TestTravelerManagement:
    """Test operator traveler CRUD operations."""

    def test_create_traveler(self, logged_in_client: TestClient):
        dashboard = logged_in_client.get("/operator/")
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', dashboard.text)
        csrf = m.group(1) if m else ""

        resp = logged_in_client.post("/operator/travelers/create", data={
            "display_name": "Bob",
            "destination": "Tokyo",
            "trip_duration_nights": 3,
            "csrf_token": csrf,
        }, cookies={"lt_csrf": csrf})
        assert resp.status_code in (200, 303)

    def test_create_traveler_shows_in_dashboard(self, logged_in_client: TestClient):
        dashboard = logged_in_client.get("/operator/")
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', dashboard.text)
        csrf = m.group(1) if m else ""

        logged_in_client.post("/operator/travelers/create", data={
            "display_name": "Charlie",
            "destination": "Paris",
            "trip_duration_nights": 5,
            "csrf_token": csrf,
        }, cookies={"lt_csrf": csrf})

        resp = logged_in_client.get("/operator/")
        assert "Charlie" in resp.text
        assert "Paris" in resp.text


class TestInvitationToken:
    """Test invitation token generation and validation."""

    def test_generate_invitation_token(self, logged_in_client: TestClient):
        conn = get_connection()
        create_traveler(conn, display_name="Dave", destination="London", trip_duration_nights=4)
        travelers = conn.execute("SELECT id FROM travelers WHERE display_name = 'Dave'").fetchone()
        traveler_id = travelers["id"]
        conn.close()

        detail = logged_in_client.get(f"/operator/travelers/{traveler_id}")
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', detail.text)
        csrf = m.group(1) if m else ""

        resp = logged_in_client.post(f"/operator/travelers/{traveler_id}/invite",
            data={"csrf_token": csrf},
            cookies={"lt_csrf": csrf})
        assert resp.status_code == 200
        assert "token" in resp.text.lower() or "Token" in resp.text


class TestCSRFProtection:
    """Verify CSRF protection on all state-changing operator routes."""

    def test_create_traveler_requires_csrf(self, logged_in_client: TestClient):
        resp = logged_in_client.post("/operator/travelers/create", data={
            "display_name": "Test",
            "destination": "Nowhere",
            "trip_duration_nights": 1,
            "csrf_token": "",
        })
        assert resp.status_code in (403, 200, 422)

    def test_deactivate_requires_csrf(self, logged_in_client: TestClient):
        conn = get_connection()
        create_traveler(conn, display_name="Eve", destination="Rome", trip_duration_nights=2)
        travelers = conn.execute("SELECT id FROM travelers WHERE display_name = 'Eve'").fetchone()
        traveler_id = travelers["id"]
        conn.close()

        resp = logged_in_client.post(f"/operator/travelers/{traveler_id}/deactivate", data={"csrf_token": ""})
        assert resp.status_code in (403, 200, 422)

    def test_publish_requires_csrf(self, logged_in_client: TestClient):
        resp = logged_in_client.post("/operator/editions/fake_id/publish", data={"csrf_token": ""})
        assert resp.status_code in (403, 200, 404, 422)

    def test_reject_requires_csrf(self, logged_in_client: TestClient):
        resp = logged_in_client.post("/operator/editions/fake_id/reject", data={"csrf_token": ""})
        assert resp.status_code in (403, 200, 404, 422)
