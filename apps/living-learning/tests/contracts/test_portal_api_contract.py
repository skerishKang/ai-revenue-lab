"""Portal /api/v1 contract: auth enforcement, role gates, health, privacy headers.

Uses the network-free FakeIdentityVerifier. Verifies that Firebase auth alone is
insufficient (no membership => 401), learner/operator role gates return generic
403, the health endpoint exposes no secrets, and private responses are no-store.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import apply_migrations
from app.factory import create_app
from app.identity import FakeIdentityVerifier, IdentityPrincipal, reset_identity_verifier, set_identity_verifier
from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    ensure_external_identity,
    grant_membership,
)

from tests.contracts.conftest import bootstrap_learner

LEARNER_TOKEN = "learner-token"
OPERATOR_TOKEN = "operator-token"
NOMEMBER_TOKEN = "nomember-token"


def _principal(subject: str) -> IdentityPrincipal:
    return IdentityPrincipal(issuer="ai-revenue-lab-identity", subject=subject, email_verified=True)


@pytest.fixture
def portal_app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    apply_migrations(path)

    learner_id, concept_id = bootstrap_learner(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Learner identity + membership.
    learner_identity = ensure_external_identity(
        conn, provider="firebase", issuer="ai-revenue-lab-identity", subject="learner-sub", commit=True
    )
    grant_membership(conn, external_identity_id=learner_identity.id, role=ROLE_LEARNER, learner_id=learner_id, commit=True)
    # Operator identity + membership.
    operator_identity = ensure_external_identity(
        conn, provider="firebase", issuer="ai-revenue-lab-identity", subject="operator-sub", commit=True
    )
    grant_membership(conn, external_identity_id=operator_identity.id, role=ROLE_OPERATOR, commit=True)
    # An identity with NO membership.
    ensure_external_identity(
        conn, provider="firebase", issuer="ai-revenue-lab-identity", subject="nomember-sub", commit=True
    )
    conn.close()

    verifier = FakeIdentityVerifier(
        {
            LEARNER_TOKEN: _principal("learner-sub"),
            OPERATOR_TOKEN: _principal("operator-sub"),
            NOMEMBER_TOKEN: _principal("nomember-sub"),
        }
    )
    set_identity_verifier(verifier)

    settings = Settings(database_url=path, provider_type="mock", provider_model="mock-fixture")
    app = create_app(settings)
    yield app, learner_id

    reset_identity_verifier()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass


def _client(portal_app):
    app, _ = portal_app
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public_and_secret_free(portal_app):
    client = _client(portal_app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database_backend"] == "sqlite"
    assert body["identity_provider"] == "fake"
    assert body["portal_contract_version"] == "v1"
    # No secrets leaked.
    text = resp.text.lower()
    for forbidden in ("api_key", "secret", "token", "password", ".db"):
        assert forbidden not in text


def test_missing_token_is_401(portal_app):
    client = _client(portal_app)
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/progress").status_code == 401


def test_invalid_token_is_401(portal_app):
    client = _client(portal_app)
    assert client.get("/api/v1/me", headers=_auth("garbage")).status_code == 401


def test_verified_identity_without_membership_is_401(portal_app):
    # Firebase auth succeeded but there is no product membership => fail-closed.
    client = _client(portal_app)
    assert client.get("/api/v1/me", headers=_auth(NOMEMBER_TOKEN)).status_code == 401


def test_me_returns_role_for_learner(portal_app):
    client = _client(portal_app)
    resp = client.get("/api/v1/me", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "learner"
    assert body["learner_id"]
    # The raw subject is never exposed.
    assert "learner-sub" not in resp.text


def test_learner_cannot_access_operator_routes(portal_app):
    client = _client(portal_app)
    resp = client.get("/api/v1/operator/review", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 403


def test_operator_can_access_review_list(portal_app):
    client = _client(portal_app)
    resp = client.get("/api/v1/operator/review", headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 200
    assert "pending" in resp.json()


def test_operator_without_learner_role_cannot_access_learner_routes(portal_app):
    client = _client(portal_app)
    resp = client.get("/api/v1/progress", headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 403


def test_learner_progress_uses_membership_learner_id(portal_app):
    app, learner_id = portal_app
    client = TestClient(app)
    resp = client.get("/api/v1/progress", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    assert resp.json()["learner_id"] == learner_id


def test_private_response_is_no_store(portal_app):
    client = _client(portal_app)
    resp = client.get("/api/v1/me", headers=_auth(LEARNER_TOKEN))
    assert resp.headers.get("Cache-Control") == "no-store"
    assert "noindex" in resp.headers.get("X-Robots-Tag", "")


def test_learner_can_fetch_first_lesson(portal_app):
    """Review-before-delivery: operator generates -> learner denied while
    pending_review -> operator approves -> learner can fetch the published
    lesson as validated structured content."""
    app, learner_id = portal_app
    client = TestClient(app)

    # Operator generates the first lesson (pending_review, not published).
    gen = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/first/generate",
        json={"idempotency_key": "portal-first"},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert gen.status_code == 200
    assert gen.json()["generation_status"] == "pending_review"
    assert gen.json()["publication_state"] == "pending"
    lesson_id = gen.json()["lesson_id"]

    # Learner cannot fetch it before approval.
    denied = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert denied.status_code == 404

    # Operator approves (publishes).
    approve = client.post(
        f"/api/v1/operator/review/{lesson_id}/approve",
        json={"reason": "looks good"},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert approve.status_code == 200
    assert approve.json()["publication_state"] == "published"

    # Now the learner can fetch the published lesson.
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    assert body["lesson_number"] == 1
    assert "sections" in body
    assert "exercises" in body
    # No expected answers / internal fields are exposed.
    assert "correct_answer" not in resp.text
    assert "lesson_plan_json" not in resp.text
