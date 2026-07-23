"""Integration tests for the authenticated JSON API (/api/v1).

Runs without live Firebase credentials by injecting a FakeTokenVerifier. Covers
bearer enforcement, identity mapping, authorization, foreign-access denial,
invitation claim/replay, revocation, CORS, and no-store.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app import external_identity_repository as eid_repo
from app.config import reset_settings
from app.db import get_connection
from app.factory import create_app
from app.firebase import (
    PROVIDER_FIREBASE,
    FakeTokenVerifier,
    TokenClaims,
    reset_token_verifier,
    set_token_verifier,
)
from app.security import create_traveler_token, reset_login_rate_limiter
from app.traveler_repository import create_traveler

ALLOWED_ORIGIN = "https://ai-revenue-living-travel.pages.dev"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    reset_settings()
    reset_login_rate_limiter()
    reset_token_verifier()
    db_path = str(tmp_path / "api.db")
    monkeypatch.setenv("LT_DATABASE_URL", db_path)
    monkeypatch.setenv("LT_ENVIRONMENT", "testing")
    monkeypatch.setenv("LT_AUTH_MODE", "firebase")
    monkeypatch.setenv("LT_FIREBASE_PROJECT_ID", "ai-revenue-lab-identity")
    monkeypatch.setenv("LT_ALLOWED_ORIGINS", ALLOWED_ORIGIN)
    monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
    reset_settings()

    fake = FakeTokenVerifier()
    fake.add("traveler-token", TokenClaims(PROVIDER_FIREBASE, "uid-traveler"))
    fake.add("operator-token", TokenClaims(PROVIDER_FIREBASE, "uid-operator"))
    fake.add("newuser-token", TokenClaims(PROVIDER_FIREBASE, "uid-newuser"))
    fake.add("revoked-token", TokenClaims(PROVIDER_FIREBASE, "uid-revoked"))
    set_token_verifier(fake)

    application = create_app()

    conn = get_connection()
    traveler = create_traveler(conn, display_name="API Traveler", destination="Seoul")
    tid = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-traveler")
    eid_repo.link_traveler(conn, tid.id, traveler.id)
    oid = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-operator")
    eid_repo.link_operator(conn, oid.id, "op_uid-operator")
    rid = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-revoked")
    eid_repo.revoke_identity(conn, rid.id)
    conn.close()

    yield {"app": application, "traveler_id": traveler.id}

    reset_token_verifier()
    reset_settings()
    reset_login_rate_limiter()


def _client(api) -> TestClient:
    return TestClient(api["app"])


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestBearerEnforcement:
    def test_missing_bearer(self, api):
        resp = _client(api).get("/api/v1/me")
        assert resp.status_code == 401

    def test_malformed_bearer(self, api):
        resp = _client(api).get("/api/v1/me", headers={"Authorization": "Token x"})
        assert resp.status_code == 401

    def test_invalid_token(self, api):
        resp = _client(api).get("/api/v1/me", headers=_auth("bogus"))
        assert resp.status_code == 401

    def test_unmapped_identity_denied_on_protected(self, api):
        resp = _client(api).get("/api/v1/traveler/preferences", headers=_auth("newuser-token"))
        assert resp.status_code == 401

    def test_revoked_identity_denied(self, api):
        resp = _client(api).get("/api/v1/traveler/preferences", headers=_auth("revoked-token"))
        assert resp.status_code == 401


class TestIdentityAndRole:
    def test_me_traveler(self, api):
        resp = _client(api).get("/api/v1/me", headers=_auth("traveler-token"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "traveler"
        assert body["traveler_id"] == api["traveler_id"]

    def test_me_operator(self, api):
        resp = _client(api).get("/api/v1/me", headers=_auth("operator-token"))
        assert resp.status_code == 200
        assert resp.json()["role"] == "operator"

    def test_me_unmapped(self, api):
        resp = _client(api).get("/api/v1/me", headers=_auth("newuser-token"))
        assert resp.status_code == 200
        assert resp.json()["role"] == "none"

    def test_health_public(self, api):
        resp = _client(api).get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestAuthorization:
    def test_traveler_cannot_access_operator_endpoint(self, api):
        resp = _client(api).get("/api/v1/operator/travelers", headers=_auth("traveler-token"))
        assert resp.status_code == 403

    def test_operator_cannot_access_traveler_endpoint(self, api):
        resp = _client(api).get("/api/v1/traveler/preferences", headers=_auth("operator-token"))
        assert resp.status_code == 403

    def test_operator_lists_travelers(self, api):
        resp = _client(api).get("/api/v1/operator/travelers", headers=_auth("operator-token"))
        assert resp.status_code == 200
        ids = [t["id"] for t in resp.json()["travelers"]]
        assert api["traveler_id"] in ids


class TestTravelerFlow:
    def test_preferences_get_put(self, api):
        c = _client(api)
        got = c.get("/api/v1/traveler/preferences", headers=_auth("traveler-token"))
        assert got.status_code == 200
        assert got.json()["destination"] == "Seoul"
        put = c.put(
            "/api/v1/traveler/preferences",
            headers=_auth("traveler-token"),
            json={"destination": "Busan", "trip_duration_nights": 4},
        )
        assert put.status_code == 200
        assert put.json()["destination"] == "Busan"
        assert put.json()["trip_duration_nights"] == 4

    def test_foreign_edition_access_denied(self, api):
        # Operator creates a second traveler + edition; the first traveler must
        # not be able to read it.
        c = _client(api)
        create = c.post(
            "/api/v1/operator/travelers",
            headers=_auth("operator-token"),
            json={"display_name": "Other", "destination": "Seoul"},
        )
        other_id = create.json()["id"]
        gen = c.post(
            f"/api/v1/operator/travelers/{other_id}/generate-first",
            headers=_auth("operator-token"),
        )
        assert gen.status_code == 200
        edition_id = gen.json()["edition"]["id"]
        # First traveler tries to read the other traveler's edition.
        resp = c.get(
            f"/api/v1/traveler/editions/{edition_id}",
            headers=_auth("traveler-token"),
        )
        assert resp.status_code == 404

    def test_deactivation_request_idempotent(self, api):
        c = _client(api)
        r1 = c.post("/api/v1/traveler/deactivation-request", headers=_auth("traveler-token"))
        r2 = c.post("/api/v1/traveler/deactivation-request", headers=_auth("traveler-token"))
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestInvitationClaim:
    def test_claim_and_replay(self, api):
        c = _client(api)
        # Create a fresh, unclaimed traveler and issue an invitation code.
        created = c.post(
            "/api/v1/operator/travelers",
            headers=_auth("operator-token"),
            json={"display_name": "Claimable", "destination": "Seoul"},
        )
        fresh_id = created.json()["id"]
        inv = c.post(
            f"/api/v1/operator/travelers/{fresh_id}/invite",
            headers=_auth("operator-token"),
        )
        code = inv.json()["invitation_code"]
        # A fresh Firebase user claims it.
        claim = c.post(
            "/api/v1/invitations/claim",
            headers=_auth("newuser-token"),
            json={"invitation_code": code},
        )
        assert claim.status_code == 200
        assert claim.json()["traveler_id"] == fresh_id
        # The new user is now a traveler.
        me = c.get("/api/v1/me", headers=_auth("newuser-token"))
        assert me.json()["role"] == "traveler"
        assert me.json()["traveler_id"] == fresh_id
        # Replay of the consumed code fails.
        replay = c.post(
            "/api/v1/invitations/claim",
            headers=_auth("newuser-token"),
            json={"invitation_code": code},
        )
        assert replay.status_code == 400

    def test_invalid_code_generic(self, api):
        c = _client(api)
        resp = c.post(
            "/api/v1/invitations/claim",
            headers=_auth("newuser-token"),
            json={"invitation_code": "wrong"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invitation_claim_failed"


class TestOperatorGenerationAndPublication:
    def test_generate_publish_traveler_reads(self, api):
        c = _client(api)
        gen = c.post(
            f"/api/v1/operator/travelers/{api['traveler_id']}/generate-first",
            headers=_auth("operator-token"),
        )
        assert gen.status_code == 200
        edition = gen.json()["edition"]
        assert edition["generation_status"] == "pending_review"
        # Traveler cannot see it before publication.
        before = c.get(
            f"/api/v1/traveler/editions/{edition['id']}", headers=_auth("traveler-token")
        )
        assert before.status_code == 404
        # Operator publishes.
        pub = c.post(
            f"/api/v1/operator/editions/{edition['id']}/publish",
            headers=_auth("operator-token"),
        )
        assert pub.status_code == 200
        # Now the traveler can read it.
        after = c.get(
            f"/api/v1/traveler/editions/{edition['id']}", headers=_auth("traveler-token")
        )
        assert after.status_code == 200

    def test_reject(self, api):
        c = _client(api)
        gen = c.post(
            f"/api/v1/operator/travelers/{api['traveler_id']}/generate-first",
            headers=_auth("operator-token"),
        )
        edition_id = gen.json()["edition"]["id"]
        rej = c.post(
            f"/api/v1/operator/editions/{edition_id}/reject",
            headers=_auth("operator-token"),
        )
        assert rej.status_code == 200
        assert rej.json()["publication_state"] == "rejected"


class TestSecurityHeadersAndCors:
    def test_no_store_on_private_api(self, api):
        resp = _client(api).get("/api/v1/me", headers=_auth("traveler-token"))
        assert resp.headers.get("Cache-Control") == "no-store"

    def test_cors_allowed_origin(self, api):
        resp = _client(api).get(
            "/api/v1/health", headers={"Origin": ALLOWED_ORIGIN}
        )
        assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN

    def test_cors_rejected_origin(self, api):
        resp = _client(api).get(
            "/api/v1/health", headers={"Origin": "https://evil.example.com"}
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_legacy_routes_disabled_in_firebase_mode(self, api):
        resp = _client(api).get("/operator/login")
        assert resp.status_code == 404
