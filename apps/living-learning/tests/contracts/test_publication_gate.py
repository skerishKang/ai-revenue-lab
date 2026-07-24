"""P0: validation-before-publication gate.

Invalid content must never reach ``publication_state='published'``. Approve runs
the canonical publication validation inside its transaction; on failure the state
stays ``pending`` and no audit row is written.
"""

from __future__ import annotations

import json
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
        FakeIdentityVerifier({LEARNER_TOKEN: _principal("learner-sub"), OPERATOR_TOKEN: _principal("operator-sub")})
    )
    settings = Settings(database_url=path, provider_type="mock", provider_model="mock-fixture")
    app = create_app(settings)
    yield app, learner_id, concept_id, path
    reset_identity_verifier()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


_VALID_PLAN = {"title": "변수", "sections": [{"section_id": "s1", "title": "섹션", "description": "설명", "emphasis": ""}]}
_VALID_CONTENT = {
    "content_version": "1.0",
    "title": "변수 컨텐츠",
    "sections": [{"section_id": "s1", "title": "섹션", "content": "변수는 값을 담는 이름 설명", "includes_code": True, "code_snippet": "x = 1"}],
    "review_questions": [{"question": "Q?", "correct_answer": "설명", "explanation": "이유"}],
    "code_examples": [{"example_id": "ex1", "language": "python", "code": "x = 10\nprint(x)", "explanation": "할당", "expected_output": "10"}],
    "term_definitions": [{"term": "변수", "definition": "값을 담는 이름"}],
}


def _create_pending_lesson(path, learner_id, concept_id, plan, content, *, lesson_number=1, prior_lesson_id=None, source_feedback_id=None, source_comprehension_response_id=None, lesson_id=None, publication_state="pending", generation_status="pending_review"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if lesson_id is None:
        lesson_id = f"les_{lesson_number}_{os.urandom(4).hex()}"
    conn.execute(
        "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status, "
        "publication_state, lesson_plan_json, lesson_content_json, adaptation_summary, source_feedback_id, "
        "source_comprehension_response_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, datetime('now'), datetime('now'))",
        (lesson_id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status, publication_state, json.dumps(plan), json.dumps(content), source_feedback_id, source_comprehension_response_id),
    )
    conn.commit()
    conn.close()
    return lesson_id


def _setup_second_lesson_lineage(path, learner_id, concept_id, second_content, *, second_id="les_2_fixed", fb_id="fb_fixed", comp_id="comp_fixed", directions=None, first_publication="published"):
    """Create a fully consistent second-lesson lineage and return (first_id, second_id).

    first lesson (published/closed) -> comprehension + feedback (applied to the
    second lesson) -> second lesson referencing the exact feedback/comprehension.

    The lesson<->feedback reference is circular (lesson.source_feedback_id ->
    feedback.id and feedback.applied_to_lesson_id -> lesson.id), so the second
    lesson is created first with a NULL feedback ref, the feedback is inserted,
    then the lesson's feedback ref is set.
    """
    if directions is None:
        directions = ["more_examples"]
    first_id = _create_pending_lesson(
        path, learner_id, concept_id, _VALID_PLAN, _VALID_CONTENT,
        lesson_number=1, lesson_id="les_1_fixed", publication_state=first_publication,
    )
    # Second lesson first (feedback ref NULL for now).
    _create_pending_lesson(
        path, learner_id, concept_id, _VALID_PLAN, second_content,
        lesson_number=2, prior_lesson_id=first_id, source_feedback_id=None,
        source_comprehension_response_id=None, lesson_id=second_id,
    )
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO comprehension_responses (id, lesson_id, learner_id, understood, difficulty_rating, free_text, response_id, responded_at) "
        "VALUES (?, ?, ?, 0, 3, '어려워요', ?, datetime('now'))",
        (comp_id, first_id, learner_id, comp_id),
    )
    conn.execute(
        "INSERT INTO feedback (id, lesson_id, learner_id, lesson_generation, direction_choices, free_text, applied_status, applied_to_lesson_id, created_at) "
        "VALUES (?, ?, ?, 1, ?, '', 'applied_to_second', ?, datetime('now'))",
        (fb_id, first_id, learner_id, json.dumps(directions), second_id),
    )
    # Now set the second lesson's exact provenance (feedback + comprehension).
    conn.execute(
        "UPDATE lessons SET source_feedback_id = ?, source_comprehension_response_id = ? WHERE id = ?",
        (fb_id, comp_id, second_id),
    )
    conn.commit()
    conn.close()
    return first_id, second_id


def _approve(client, lesson_id):
    return client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))


def _state(path, lesson_id):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT publication_state FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    audit = conn.execute("SELECT count(*) AS c FROM lesson_review_events WHERE lesson_id = ?", (lesson_id,)).fetchone()["c"]
    conn.close()
    return row["publication_state"], audit


def test_invalid_json_lesson_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, _VALID_CONTENT)
    # Corrupt to invalid JSON.
    conn = sqlite3.connect(path); conn.execute("UPDATE lessons SET lesson_content_json='{bad' WHERE id=?", (lesson_id,)); conn.commit(); conn.close()
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, audit = _state(path, lesson_id)
    assert state == "pending"
    assert audit == 0


def test_plan_schema_invalid_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    bad_plan = {"sections": "not-a-list"}  # missing required title
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, bad_plan, _VALID_CONTENT)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, audit = _state(path, lesson_id)
    assert state == "pending"
    assert audit == 0


def test_content_schema_invalid_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    bad_content = {"content_version": "1.0", "title": "t", "sections": "not-a-list"}
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, bad_content)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, _ = _state(path, lesson_id)
    assert state == "pending"


def test_unsafe_ast_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    content = json.loads(json.dumps(_VALID_CONTENT))
    content["code_examples"][0]["code"] = "import os\nos.system('ls')"
    content["code_examples"][0]["expected_output"] = "x"
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, content)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, _ = _state(path, lesson_id)
    assert state == "pending"


def test_expected_output_mismatch_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    content = json.loads(json.dumps(_VALID_CONTENT))
    content["code_examples"][0]["expected_output"] = "999"  # actual output is "10"
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, content)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, _ = _state(path, lesson_id)
    assert state == "pending"


def test_ungrounded_answer_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    content = json.loads(json.dumps(_VALID_CONTENT))
    content["review_questions"][0]["correct_answer"] = "근거없는정답"
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, content)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, _ = _state(path, lesson_id)
    assert state == "pending"


def test_privacy_markup_violation_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    content = json.loads(json.dumps(_VALID_CONTENT))
    content["sections"][0]["content"] = "변수 설명 <script>alert(1)</script>"
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, content)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, _ = _state(path, lesson_id)
    assert state == "pending"


def test_metadata_only_second_lesson_approve_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    # Second lesson with IDENTICAL content (metadata-only change) -> not material.
    _, second_id = _setup_second_lesson_lineage(path, learner_id, concept_id, _VALID_CONTENT)
    resp = _approve(client, second_id)
    assert resp.status_code == 422
    state, audit = _state(path, second_id)
    assert state == "pending"
    assert audit == 0


def test_valid_first_lesson_approve_succeeds(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, _VALID_CONTENT)
    resp = _approve(client, lesson_id)
    assert resp.status_code == 200
    state, audit = _state(path, lesson_id)
    assert state == "published"
    assert audit == 1


def test_valid_materially_adapted_second_lesson_approve_succeeds(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    # Second lesson with a materially adapted content (more code examples).
    adapted = json.loads(json.dumps(_VALID_CONTENT))
    adapted["code_examples"].append({"example_id": "ex2", "language": "python", "code": "y = 2\nprint(y)", "explanation": "두번째", "expected_output": "2"})
    _, second_id = _setup_second_lesson_lineage(path, learner_id, concept_id, adapted)
    resp = _approve(client, second_id)
    assert resp.status_code == 200
    state, audit = _state(path, second_id)
    assert state == "published"
    assert audit == 1


def test_reject_allowed_for_invalid_content(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    bad_content = {"content_version": "1.0", "title": "t", "sections": "not-a-list"}
    lesson_id = _create_pending_lesson(path, learner_id, concept_id, _VALID_PLAN, bad_content)
    resp = client.post(f"/api/v1/operator/review/{lesson_id}/reject", json={"reason": "invalid"}, headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 200
    state, audit = _state(path, lesson_id)
    assert state == "rejected"
    assert audit == 1
