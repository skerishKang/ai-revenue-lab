"""P0: review-before-delivery workflow.

Learners cannot access lessons until an operator approves (publishes) them.
Operator generation always yields pending_review/pending. Approve/reject are
atomic CAS transitions with an audit trail; concurrent approve/reject has exactly
one winner.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import apply_migrations
from app.factory import create_app
from app.identity import FakeIdentityVerifier, IdentityPrincipal, reset_identity_verifier, set_identity_verifier
from app.pipeline.errors import ReviewStateConflictError
from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    ensure_external_identity,
    grant_membership,
)
from app.review_service import approve_lesson, get_review_events, reject_lesson

from tests.contracts.conftest import bootstrap_learner, make_pipeline

LEARNER_TOKEN = "learner-token"
OPERATOR_TOKEN = "operator-token"


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
    li = ensure_external_identity(conn, provider="firebase", issuer="ai-revenue-lab-identity", subject="learner-sub", commit=True)
    grant_membership(conn, external_identity_id=li.id, role=ROLE_LEARNER, learner_id=learner_id, commit=True)
    oi = ensure_external_identity(conn, provider="firebase", issuer="ai-revenue-lab-identity", subject="operator-sub", commit=True)
    grant_membership(conn, external_identity_id=oi.id, role=ROLE_OPERATOR, commit=True)
    conn.close()

    set_identity_verifier(
        FakeIdentityVerifier(
            {LEARNER_TOKEN: _principal("learner-sub"), OPERATOR_TOKEN: _principal("operator-sub")}
        )
    )
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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _generate_first(client, learner_id: str, key: str) -> str:
    resp = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/first/generate",
        json={"idempotency_key": key},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert resp.status_code == 200
    return resp.json()["lesson_id"]


def test_operator_generation_creates_pending_review(portal_app):
    app, learner_id = portal_app
    client = TestClient(app)
    resp = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/first/generate",
        json={"idempotency_key": "gen-1"},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generation_status"] == "pending_review"
    assert body["publication_state"] == "pending"


def test_learner_cannot_fetch_pending_review_lesson(portal_app):
    app, learner_id = portal_app
    client = TestClient(app)
    _generate_first(client, learner_id, "gen-2")
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 404


def test_learner_cannot_respond_to_pending_review_lesson(portal_app):
    app, learner_id = portal_app
    client = TestClient(app)
    _generate_first(client, learner_id, "gen-3")
    resp = client.post(
        "/api/v1/lessons/1/responses",
        json={"understood": True},
        headers=_auth(LEARNER_TOKEN),
    )
    assert resp.status_code == 404
    fb = client.post(
        "/api/v1/lessons/1/feedback",
        json={"direction_choices": ["more_examples"]},
        headers=_auth(LEARNER_TOKEN),
    )
    assert fb.status_code == 404


def test_operator_approve_publishes_once(portal_app):
    app, learner_id = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "gen-4")

    first = client.post(
        f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN)
    )
    assert first.status_code == 200
    assert first.json()["publication_state"] == "published"

    # Re-approve (published -> published) is rejected as a state conflict.
    second = client.post(
        f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "again"}, headers=_auth(OPERATOR_TOKEN)
    )
    assert second.status_code == 409

    # Reject after publish is also rejected.
    reject = client.post(
        f"/api/v1/operator/review/{lesson_id}/reject", json={"reason": "no"}, headers=_auth(OPERATOR_TOKEN)
    )
    assert reject.status_code == 409


def test_published_lesson_returns_validated_content(portal_app):
    app, learner_id = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "gen-5")
    client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))

    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    # Validated structured fields are present.
    for field in ("lesson_id", "lesson_number", "objective", "sections", "code_examples", "term_definitions", "exercises", "adaptation_note"):
        assert field in body
    # No raw answers or internal payloads leak.
    assert "correct_answer" not in resp.text
    assert "expected_output" not in resp.text
    assert "lesson_content_json" not in resp.text


def test_concurrent_approve_reject_has_one_winner(file_db):
    """Two concurrent reviewers: exactly one transition wins, one audit row."""
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
    finally:
        pipeline.conn.close()

    # Create two real operator identities (the audit FK requires real rows).
    setup = sqlite3.connect(file_db)
    setup.row_factory = sqlite3.Row
    setup.execute("PRAGMA foreign_keys=ON")
    setup.execute(
        "INSERT INTO external_identities (id, provider, issuer, subject, status) "
        "VALUES ('op-1', 'firebase', 'ai-revenue-lab-identity', 'op1-sub', 'active')"
    )
    setup.execute(
        "INSERT INTO external_identities (id, provider, issuer, subject, status) "
        "VALUES ('op-2', 'firebase', 'ai-revenue-lab-identity', 'op2-sub', 'active')"
    )
    setup.commit()
    setup.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(action):
        conn = sqlite3.connect(file_db, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            barrier.wait()
            if action == "approve":
                approve_lesson(conn, lesson_id, external_identity_id="op-1", reason="ok")
            else:
                reject_lesson(conn, lesson_id, external_identity_id="op-2", reason="no")
            with lock:
                outcomes.append(f"{action}:ok")
        except ReviewStateConflictError:
            with lock:
                outcomes.append(f"{action}:conflict")
        finally:
            conn.close()

    threads = [threading.Thread(target=run, args=("approve",)), threading.Thread(target=run, args=("reject",))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [o for o in outcomes if o.endswith(":ok")]
    conflicts = [o for o in outcomes if o.endswith(":conflict")]
    assert len(winners) == 1, f"outcomes={outcomes}"
    assert len(conflicts) == 1, f"outcomes={outcomes}"

    # Exactly one audit row, matching the final publication_state.
    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    try:
        events = get_review_events(conn, lesson_id)
        assert len(events) == 1
        lesson = conn.execute("SELECT publication_state FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        expected_action = "approved" if lesson["publication_state"] == "published" else "rejected"
        assert events[0]["action"] == expected_action
    finally:
        conn.close()
