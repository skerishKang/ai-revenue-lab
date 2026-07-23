"""Pre-PR integrity: review queue, operator review payload, read-time validation,
diagnostic provenance, and review-audit identity FK."""

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
from app.review_service import approve_lesson

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
    yield app, learner_id, path
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


def _review_queue(client) -> list:
    return client.get("/api/v1/operator/review", headers=_auth(OPERATOR_TOKEN)).json()["pending"]


# ---------------------------------------------------------------------------
# Review queue + progress
# ---------------------------------------------------------------------------
def test_review_queue_generate_then_approve(portal_app):
    app, learner_id, _ = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "q-1")
    assert len(_review_queue(client)) == 1

    approve = client.post(
        f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN)
    )
    assert approve.status_code == 200
    assert len(_review_queue(client)) == 0


def test_review_queue_generate_then_reject(portal_app):
    app, learner_id, _ = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "q-2")
    assert len(_review_queue(client)) == 1

    reject = client.post(
        f"/api/v1/operator/review/{lesson_id}/reject", json={"reason": "no"}, headers=_auth(OPERATOR_TOKEN)
    )
    assert reject.status_code == 200
    assert len(_review_queue(client)) == 0


def test_published_not_in_pending_review_lessons(portal_app):
    app, learner_id, _ = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "q-3")
    # Before approval: pending_review_lessons == 1.
    progress = client.get("/api/v1/progress", headers=_auth(LEARNER_TOKEN)).json()
    assert progress["pending_review_lessons"] == 1

    client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))
    # After approval (published): not counted.
    progress = client.get("/api/v1/progress", headers=_auth(LEARNER_TOKEN)).json()
    assert progress["pending_review_lessons"] == 0


def test_rejected_not_in_pending_review_lessons(portal_app):
    app, learner_id, _ = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "q-4")
    client.post(f"/api/v1/operator/review/{lesson_id}/reject", json={"reason": "no"}, headers=_auth(OPERATOR_TOKEN))
    progress = client.get("/api/v1/progress", headers=_auth(LEARNER_TOKEN)).json()
    assert progress["pending_review_lessons"] == 0


# ---------------------------------------------------------------------------
# Operator review detail payload
# ---------------------------------------------------------------------------
def test_operator_review_detail_payload(portal_app):
    app, learner_id, _ = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "detail-1")

    resp = client.get(f"/api/v1/operator/review/{lesson_id}", headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    # Metadata.
    for field in ("lesson_id", "learner_id", "concept_id", "lesson_number", "generation_status", "publication_state"):
        assert field in body
    # Structured sub-objects.
    plan = body["instructional_plan"]
    for field in ("objective", "section_order", "difficulty", "example_count", "review_question_count", "feedback_actions"):
        assert field in plan
    content = body["lesson_content"]
    for field in ("sections", "code_examples", "term_definitions", "review_questions"):
        assert field in content
    # Operator view includes expected answers/rationale and expected output.
    if content["review_questions"]:
        assert "correct_answer" in content["review_questions"][0]
        assert "explanation" in content["review_questions"][0]
    if content["code_examples"]:
        assert "expected_output" in content["code_examples"][0]
    # Adaptation, validation, generation evidence present.
    for field in ("prior_lesson_id", "feedback_signal", "comprehension_signal", "material_changes"):
        assert field in body["adaptation"]
    for field in ("content_schema", "ast_safety", "answer_grounding", "adaptation_materiality", "privacy_markup"):
        assert field in body["validation"]
    for field in ("provider", "model", "attempts", "retries", "latency_ms_total", "input_tokens_total", "output_tokens_total"):
        assert field in body["generation_evidence"]
    # No raw prompt / secret leakage.
    assert "system_prompt" not in resp.text
    assert "Bearer" not in resp.text


def test_learner_cannot_access_operator_review_detail(portal_app):
    app, learner_id, _ = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "detail-2")
    resp = client.get(f"/api/v1/operator/review/{lesson_id}", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Published content read-time validation (fail-closed)
# ---------------------------------------------------------------------------
def _publish_with_content(path, lesson_id, content_json):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("UPDATE lessons SET lesson_content_json = ? WHERE id = ?", (content_json, lesson_id))
    conn.commit()
    conn.close()


def test_invalid_published_json_not_200(portal_app):
    app, learner_id, path = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "rv-1")
    _publish_with_content(path, lesson_id, "{not valid json")
    client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code != 200


def test_schema_invalid_published_content_not_200(portal_app):
    app, learner_id, path = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "rv-2")
    # Valid JSON but violates the LessonContent schema (sections not a list).
    _publish_with_content(path, lesson_id, '{"content_version": "1.0", "title": "t", "sections": "not-a-list"}')
    client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code != 200


def test_valid_content_structured_response_excludes_answers(portal_app):
    app, learner_id, path = portal_app
    client = TestClient(app)
    lesson_id = _generate_first(client, learner_id, "rv-3")
    client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    for field in ("lesson_id", "lesson_number", "objective", "sections", "code_examples", "term_definitions", "exercises", "adaptation_note"):
        assert field in body
    # Learner-facing response excludes expected answers and internal payloads.
    assert "correct_answer" not in resp.text
    assert "expected_output" not in resp.text
    assert "lesson_content_json" not in resp.text


# ---------------------------------------------------------------------------
# Diagnostic provenance
# ---------------------------------------------------------------------------
def test_diagnostic_provenance_first_lesson(portal_app):
    app, learner_id, path = portal_app
    client = TestClient(app)
    diag = client.post(
        "/api/v1/diagnostics",
        json={"coding_experience": "none", "explanation_preference": "example", "theory_practice_balance": "practice"},
        headers=_auth(LEARNER_TOKEN),
    )
    assert diag.status_code == 200
    snapshot_id = diag.json()["snapshot_id"]

    lesson_id = _generate_first(client, learner_id, "prov-1")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT source_diagnostic_snapshot_id FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    conn.close()
    assert row["source_diagnostic_snapshot_id"] == snapshot_id


def test_diagnostic_provenance_next_lesson_and_prior_unchanged(portal_app):
    app, learner_id, path = portal_app
    client = TestClient(app)

    # First diagnostic -> first lesson references it.
    diag1 = client.post(
        "/api/v1/diagnostics",
        json={"coding_experience": "none", "explanation_preference": "example", "theory_practice_balance": "practice"},
        headers=_auth(LEARNER_TOKEN),
    ).json()
    first_lesson_id = _generate_first(client, learner_id, "prov-2")

    # Publish + respond + feedback so a next lesson can be generated.
    client.post(f"/api/v1/operator/review/{first_lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))
    client.post("/api/v1/lessons/1/responses", json={"understood": False, "free_text": "hard"}, headers=_auth(LEARNER_TOKEN))
    fb = client.post("/api/v1/lessons/1/feedback", json={"direction_choices": ["more_examples"]}, headers=_auth(LEARNER_TOKEN)).json()

    # New diagnostic snapshot.
    diag2 = client.post(
        "/api/v1/diagnostics",
        json={"coding_experience": "some", "explanation_preference": "concept", "theory_practice_balance": "balanced"},
        headers=_auth(LEARNER_TOKEN),
    ).json()
    assert diag2["snapshot_id"] != diag1["snapshot_id"]

    # Comprehension response id.
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    comp_id = conn.execute(
        "SELECT id FROM comprehension_responses WHERE lesson_id = ? ORDER BY responded_at DESC LIMIT 1",
        (first_lesson_id,),
    ).fetchone()["id"]
    conn.close()

    next_resp = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/1/next/generate",
        json={"comprehension_response_id": comp_id, "feedback_id": fb["feedback_id"], "idempotency_key": "prov-2-next"},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert next_resp.status_code == 200
    next_lesson_id = next_resp.json()["lesson_id"]

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    first_snap = conn.execute("SELECT source_diagnostic_snapshot_id FROM lessons WHERE id = ?", (first_lesson_id,)).fetchone()[0]
    next_snap = conn.execute("SELECT source_diagnostic_snapshot_id FROM lessons WHERE id = ?", (next_lesson_id,)).fetchone()[0]
    conn.close()

    # Next lesson references the NEW snapshot; the first lesson's provenance is unchanged.
    assert next_snap == diag2["snapshot_id"]
    assert first_snap == diag1["snapshot_id"]


# ---------------------------------------------------------------------------
# Review-audit identity FK
# ---------------------------------------------------------------------------
def test_audit_requires_real_identity(file_db):
    """An audit insert with a non-existent external identity must fail (FK)."""
    learner_id, concept_id = bootstrap_learner(file_db)
    pipeline = make_pipeline(file_db)
    try:
        lesson_id = pipeline.start_first_lesson(learner_id, concept_id)
    finally:
        pipeline.conn.close()

    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            approve_lesson(conn, lesson_id, external_identity_id="ghost-identity", reason="ok")
        # The state transition rolled back too: still pending.
        conn.rollback()
        row = conn.execute("SELECT publication_state FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        assert row["publication_state"] == "pending"
    finally:
        conn.close()
