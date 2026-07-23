"""End-to-end production foundation workflow test.

Exercises the full operator→traveler pipeline through the authenticated JSON
API: create traveler, invite, claim, generate first edition, publish, traveler
views + gives feedback, generate second edition, publish again.

Runs with FakeTokenVerifier (no live Firebase) and SQLite (no network).
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
from app.security import reset_login_rate_limiter

ALLOWED_ORIGIN = "https://ai-revenue-living-travel.pages.dev"


@pytest.fixture()
def workflow(tmp_path, monkeypatch):
    reset_settings()
    reset_login_rate_limiter()
    reset_token_verifier()
    monkeypatch.setenv("LT_DATABASE_URL", str(tmp_path / "wf.db"))
    monkeypatch.setenv("LT_ENVIRONMENT", "testing")
    monkeypatch.setenv("LT_AUTH_MODE", "firebase")
    monkeypatch.setenv("LT_FIREBASE_PROJECT_ID", "ai-revenue-lab-identity")
    monkeypatch.setenv("LT_ALLOWED_ORIGINS", ALLOWED_ORIGIN)
    monkeypatch.setenv("LT_OPERATOR_SECRET", "wf-test-secret-99")
    reset_settings()

    fake = FakeTokenVerifier()
    fake.add("op-tok", TokenClaims(PROVIDER_FIREBASE, "uid-op"))
    fake.add("user-tok", TokenClaims(PROVIDER_FIREBASE, "uid-newuser"))
    set_token_verifier(fake)

    application = create_app()

    conn = get_connection()
    oid = eid_repo.ensure_identity(conn, PROVIDER_FIREBASE, "uid-op")
    eid_repo.link_operator(conn, oid.id, "op_uid-op")
    conn.close()

    yield {"app": application}

    reset_token_verifier()
    reset_settings()
    reset_login_rate_limiter()


def _c(wf) -> TestClient:
    return TestClient(wf["app"])


def _op() -> dict:
    return {"Authorization": "Bearer op-tok"}


def _user() -> dict:
    return {"Authorization": "Bearer user-tok"}


class TestProductionWorkflow:
    def test_full_operator_traveler_pipeline(self, workflow):
        client = _c(workflow)

        resp = client.post(
            "/api/v1/operator/travelers",
            headers=_op(),
            json={
                "display_name": "Workflow Traveler",
                "destination": "Jeju",
                "trip_duration_nights": 3,
            },
        )
        assert resp.status_code == 200
        traveler_id = resp.json()["id"]

        resp = client.post(
            f"/api/v1/operator/travelers/{traveler_id}/invite", headers=_op()
        )
        assert resp.status_code == 200
        invitation_code = resp.json()["invitation_code"]
        assert invitation_code

        resp = client.post(
            "/api/v1/invitations/claim",
            headers=_user(),
            json={"invitation_code": invitation_code},
        )
        assert resp.status_code == 200
        assert resp.json()["traveler_id"] == traveler_id

        resp = client.get("/api/v1/me", headers=_user())
        assert resp.status_code == 200
        assert resp.json()["traveler_id"] == traveler_id

        resp = client.put(
            "/api/v1/traveler/preferences",
            headers=_user(),
            json={"interests": ["hiking", "seafood"], "pace_preference": "relaxed"},
        )
        assert resp.status_code == 200

        resp = client.post(
            f"/api/v1/operator/travelers/{traveler_id}/generate-first", headers=_op()
        )
        assert resp.status_code == 200
        edition_1 = resp.json()["edition"]
        assert edition_1["generation_status"] == "pending_review"

        resp = client.post(
            f"/api/v1/operator/editions/{edition_1['id']}/publish", headers=_op()
        )
        assert resp.status_code == 200
        assert resp.json()["publication_state"] == "published"

        resp = client.get("/api/v1/traveler/editions", headers=_user())
        assert resp.status_code == 200
        editions = resp.json()["editions"]
        assert len(editions) == 1
        assert editions[0]["publication_state"] == "published"

        resp = client.get(
            f"/api/v1/traveler/editions/{edition_1['id']}", headers=_user()
        )
        assert resp.status_code == 200
        assert resp.json()["structured_content"]

        resp = client.post(
            "/api/v1/traveler/feedback",
            headers=_user(),
            json={
                "edition_id": edition_1["id"],
                "direction_choices": ["quieter_places"],
                "free_text": "조용한 장소를 더 원합니다",
            },
        )
        assert resp.status_code == 200

        resp = client.post(
            f"/api/v1/operator/travelers/{traveler_id}/generate-second", headers=_op()
        )
        assert resp.status_code == 200
        edition_2 = resp.json()["edition"]
        assert edition_2["generation_status"] == "pending_review"
        assert edition_2["id"] != edition_1["id"]

        resp = client.post(
            f"/api/v1/operator/editions/{edition_2['id']}/publish", headers=_op()
        )
        assert resp.status_code == 200

        resp = client.get("/api/v1/traveler/editions", headers=_user())
        assert resp.status_code == 200
        editions = resp.json()["editions"]
        assert len(editions) == 2
        assert all(e["publication_state"] == "published" for e in editions)

    def test_replay_invitation_rejected(self, workflow):
        client = _c(workflow)

        resp = client.post(
            "/api/v1/operator/travelers",
            headers=_op(),
            json={
                "display_name": "Replay Test",
                "destination": "Busan",
                "trip_duration_nights": 2,
            },
        )
        traveler_id = resp.json()["id"]

        resp = client.post(
            f"/api/v1/operator/travelers/{traveler_id}/invite", headers=_op()
        )
        code = resp.json()["invitation_code"]

        resp = client.post(
            "/api/v1/invitations/claim",
            headers=_user(),
            json={"invitation_code": code},
        )
        assert resp.status_code == 200

        resp = client.post(
            "/api/v1/invitations/claim",
            headers=_user(),
            json={"invitation_code": code},
        )
        assert resp.status_code == 400

    def test_operator_cannot_claim_own_invitation(self, workflow):
        client = _c(workflow)

        resp = client.post(
            "/api/v1/operator/travelers",
            headers=_op(),
            json={
                "display_name": "Self Claim",
                "destination": "Seoul",
                "trip_duration_nights": 1,
            },
        )
        traveler_id = resp.json()["id"]

        resp = client.post(
            f"/api/v1/operator/travelers/{traveler_id}/invite", headers=_op()
        )
        code = resp.json()["invitation_code"]

        resp = client.post(
            "/api/v1/invitations/claim",
            headers=_op(),
            json={"invitation_code": code},
        )
        assert resp.status_code == 400
