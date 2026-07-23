"""Tests for inactive traveler API access suspension (Task D).

Verifies that a deactivated traveler is blocked from all traveler API routes
while operator routes remain accessible, and that re-activation restores access.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.api.auth import Principal
from app.config import reset_settings
from app.db import apply_migrations, get_connection
from app.factory import create_app
from app.firebase import PROVIDER_FIREBASE, FakeTokenVerifier, TokenClaims, reset_token_verifier, set_token_verifier
from app.security import reset_login_rate_limiter
from app.traveler_repository import create_traveler, delete_traveler, activate_traveler
from app import external_identity_repository as eid_repo


@pytest.fixture()
def firebase_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LT_ENVIRONMENT", "testing")
    monkeypatch.setenv("LT_AUTH_MODE", "firebase")
    monkeypatch.setenv("LT_FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("LT_DATABASE_URL", db_path)
    reset_settings()
    reset_login_rate_limiter()
    reset_token_verifier()

    app = create_app()

    fake = FakeTokenVerifier()
    set_token_verifier(fake)

    yield app, fake, db_path

    reset_token_verifier()
    reset_settings()
    reset_login_rate_limiter()


def _seed_traveler_with_identity(db_path: str, subject: str) -> str:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    traveler = create_traveler(conn, display_name="TestTraveler", destination="Seoul")
    identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, subject)
    eid_repo.link_traveler(conn, identity.id, traveler.id)
    conn.close()
    return traveler.id


def _seed_operator(db_path: str, subject: str) -> str:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    identity = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, subject)
    eid_repo.link_operator(conn, identity.id, "op_test_operator")
    conn.close()
    return identity.id


class TestInactiveTravelerAccess:
    def test_active_traveler_can_access_preferences(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-active")
        fake.add("tok-active", TokenClaims(PROVIDER_FIREBASE, "uid-active"))

        client = TestClient(app)
        resp = client.get(
            "/api/v1/traveler/preferences",
            headers={"Authorization": "Bearer tok-active"},
        )
        assert resp.status_code == 200

    def test_deactivated_traveler_blocked_from_preferences(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-deact")
        fake.add("tok-deact", TokenClaims(PROVIDER_FIREBASE, "uid-deact"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.get(
            "/api/v1/traveler/preferences",
            headers={"Authorization": "Bearer tok-deact"},
        )
        assert resp.status_code == 401

    def test_deactivated_traveler_blocked_from_editions(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-deact2")
        fake.add("tok-deact2", TokenClaims(PROVIDER_FIREBASE, "uid-deact2"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.get(
            "/api/v1/traveler/editions",
            headers={"Authorization": "Bearer tok-deact2"},
        )
        assert resp.status_code == 401

    def test_deactivated_traveler_blocked_from_feedback(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-deact3")
        fake.add("tok-deact3", TokenClaims(PROVIDER_FIREBASE, "uid-deact3"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.post(
            "/api/v1/traveler/feedback",
            headers={"Authorization": "Bearer tok-deact3"},
            json={"edition_id": "ed_fake", "direction_choices": ["continue_direction"]},
        )
        assert resp.status_code == 401

    def test_deactivated_traveler_blocked_from_deactivation_request(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-deact4")
        fake.add("tok-deact4", TokenClaims(PROVIDER_FIREBASE, "uid-deact4"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.post(
            "/api/v1/traveler/deactivation-request",
            headers={"Authorization": "Bearer tok-deact4"},
        )
        assert resp.status_code == 401

    def test_operator_route_accessible_after_traveler_deactivation(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-op-test")
        _seed_operator(db_path, "uid-operator")
        fake.add("tok-op", TokenClaims(PROVIDER_FIREBASE, "uid-operator"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.get(
            "/api/v1/operator/travelers",
            headers={"Authorization": "Bearer tok-op"},
        )
        assert resp.status_code == 200

    def test_reactivated_traveler_regains_access(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-reactivate")
        fake.add("tok-react", TokenClaims(PROVIDER_FIREBASE, "uid-reactivate"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.get(
            "/api/v1/traveler/preferences",
            headers={"Authorization": "Bearer tok-react"},
        )
        assert resp.status_code == 401

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        activate_traveler(conn, traveler_id)
        conn.close()

        resp = client.get(
            "/api/v1/traveler/preferences",
            headers={"Authorization": "Bearer tok-react"},
        )
        assert resp.status_code == 200


class TestMeEndpointSuspension:
    def test_active_traveler_me_returns_traveler(self, firebase_app):
        app, fake, db_path = firebase_app
        _seed_traveler_with_identity(db_path, "uid-me-active")
        fake.add("tok-me-active", TokenClaims(PROVIDER_FIREBASE, "uid-me-active"))

        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-active"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "traveler"
        assert data["traveler_id"] is not None

    def test_deactivated_traveler_me_returns_none(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-me-deact")
        fake.add("tok-me-deact", TokenClaims(PROVIDER_FIREBASE, "uid-me-deact"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-deact"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "none"
        assert data["traveler_id"] is None

    def test_reactivated_traveler_me_restores_traveler(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-me-react")
        fake.add("tok-me-react", TokenClaims(PROVIDER_FIREBASE, "uid-me-react"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        delete_traveler(conn, traveler_id)
        conn.close()

        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-react"})
        assert resp.json()["role"] == "none"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        activate_traveler(conn, traveler_id)
        conn.close()

        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-react"})
        assert resp.json()["role"] == "traveler"
        assert resp.json()["traveler_id"] == traveler_id

    def test_operator_me_returns_operator(self, firebase_app):
        app, fake, db_path = firebase_app
        _seed_operator(db_path, "uid-me-op")
        fake.add("tok-me-op", TokenClaims(PROVIDER_FIREBASE, "uid-me-op"))

        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-op"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "operator"

    def test_revoked_identity_me_returns_none(self, firebase_app):
        app, fake, db_path = firebase_app
        traveler_id = _seed_traveler_with_identity(db_path, "uid-me-revoked")
        fake.add("tok-me-revoked", TokenClaims(PROVIDER_FIREBASE, "uid-me-revoked"))

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        identity = eid_repo.get_identity(conn, PROVIDER_FIREBASE, "uid-me-revoked")
        eid_repo.revoke_identity(conn, identity.id)
        conn.close()

        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-revoked"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "none"
        assert data["traveler_id"] is None
        assert data["revoked"] is True

    def test_unmapped_identity_me_returns_none(self, firebase_app):
        app, fake, db_path = firebase_app
        fake.add("tok-me-unmapped", TokenClaims(PROVIDER_FIREBASE, "uid-me-unmapped"))

        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer tok-me-unmapped"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "none"
        assert data["traveler_id"] is None
