"""P0: publication lineage integrity.

The lesson's stored provenance must be internally consistent. First lessons have
no lineage; second+ lessons must reference a valid prior lesson, feedback (applied
to THIS lesson), and comprehension response. No fallback to a prior lesson's
signal is permitted.
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

_VALID_PLAN = {"title": "변수", "sections": [{"section_id": "s1", "title": "섹션", "description": "설명", "emphasis": ""}]}
_VALID_CONTENT = {
    "content_version": "1.0",
    "title": "변수 컨텐츠",
    "sections": [{"section_id": "s1", "title": "섹션", "content": "변수는 값을 담는 이름 설명", "includes_code": True, "code_snippet": "x = 1"}],
    "review_questions": [{"question": "Q?", "correct_answer": "설명", "explanation": "이유"}],
    "code_examples": [{"example_id": "ex1", "language": "python", "code": "x = 10\nprint(x)", "explanation": "할당", "expected_output": "10"}],
    "term_definitions": [{"term": "변수", "definition": "값을 담는 이름"}],
}
# Materially adapted content (more examples) for a valid second lesson.
_ADAPTED_CONTENT = json.loads(json.dumps(_VALID_CONTENT))
_ADAPTED_CONTENT["code_examples"].append({"example_id": "ex2", "language": "python", "code": "y = 2\nprint(y)", "explanation": "두번째", "expected_output": "2"})


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
    set_identity_verifier(FakeIdentityVerifier({LEARNER_TOKEN: _principal("learner-sub"), OPERATOR_TOKEN: _principal("operator-sub")}))
    app = create_app(Settings(database_url=path, provider_type="mock", provider_model="mock-fixture"))
    yield app, learner_id, concept_id, path
    reset_identity_verifier()
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _insert_lesson(path, *, lesson_id, learner_id, concept_id, lesson_number, prior_lesson_id=None, content=None, publication_state="pending", generation_status="pending_review", source_feedback_id=None, source_comprehension_response_id=None, source_diagnostic_snapshot_id=None):
    conn = _conn(path)
    conn.execute(
        "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status, "
        "publication_state, lesson_plan_json, lesson_content_json, adaptation_summary, source_feedback_id, "
        "source_comprehension_response_id, source_diagnostic_snapshot_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, datetime('now'), datetime('now'))",
        (lesson_id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status, publication_state,
         json.dumps(_VALID_PLAN), json.dumps(content if content is not None else _VALID_CONTENT),
         source_feedback_id, source_comprehension_response_id, source_diagnostic_snapshot_id),
    )
    conn.commit()
    conn.close()


def _insert_comprehension(path, comp_id, lesson_id, learner_id):
    conn = _conn(path)
    conn.execute(
        "INSERT INTO comprehension_responses (id, lesson_id, learner_id, understood, difficulty_rating, free_text, response_id, responded_at) "
        "VALUES (?, ?, ?, 0, 3, '응답', ?, datetime('now'))",
        (comp_id, lesson_id, learner_id, comp_id),
    )
    conn.commit()
    conn.close()


def _insert_feedback(path, fb_id, lesson_id, learner_id, applied_to_lesson_id, *, directions=None, lesson_generation=1, applied_status="applied_to_second"):
    conn = _conn(path)
    conn.execute(
        "INSERT INTO feedback (id, lesson_id, learner_id, lesson_generation, direction_choices, free_text, applied_status, applied_to_lesson_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, '', ?, ?, datetime('now'))",
        (fb_id, lesson_id, learner_id, lesson_generation, json.dumps(directions if directions is not None else ["more_examples"]), applied_status, applied_to_lesson_id),
    )
    conn.commit()
    conn.close()


def _build_valid_second_lesson(path, learner_id, concept_id, *, second_id="les2", first_id="les1", fb_id="fb1", comp_id="comp1", second_content=None):
    """Build a fully valid second-lesson lineage; return the second lesson id."""
    _insert_lesson(path, lesson_id=first_id, learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id=second_id, learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id=first_id, content=second_content or _ADAPTED_CONTENT)
    _insert_comprehension(path, comp_id, first_id, learner_id)
    _insert_feedback(path, fb_id, first_id, learner_id, second_id)
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id=?, source_comprehension_response_id=? WHERE id=?", (fb_id, comp_id, second_id))
    conn.commit()
    conn.close()
    return second_id


def _approve(client, lesson_id):
    return client.post(f"/api/v1/operator/review/{lesson_id}/approve", json={"reason": "ok"}, headers=_auth(OPERATOR_TOKEN))


def _state(path, lesson_id):
    conn = _conn(path)
    row = conn.execute("SELECT publication_state FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    audit = conn.execute("SELECT count(*) AS c FROM lesson_review_events WHERE lesson_id = ?", (lesson_id,)).fetchone()["c"]
    conn.close()
    return row["publication_state"], audit


def _assert_rejected(client, path, lesson_id):
    resp = _approve(client, lesson_id)
    assert resp.status_code == 422
    state, audit = _state(path, lesson_id)
    assert state == "pending"
    assert audit == 0


# ---------------------------------------------------------------------------
# First lesson lineage
# ---------------------------------------------------------------------------
def test_first_lesson_no_source_ids_approve_succeeds(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les_f1", learner_id=learner_id, concept_id=concept_id, lesson_number=1)
    resp = _approve(client, "les_f1")
    assert resp.status_code == 200
    state, audit = _state(path, "les_f1")
    assert state == "published"
    assert audit == 1


def test_first_lesson_with_feedback_source_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les_f2", learner_id=learner_id, concept_id=concept_id, lesson_number=1)
    _insert_feedback(path, "fb_f2", "les_f2", learner_id, "les_f2")
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb_f2' WHERE id='les_f2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les_f2")


# ---------------------------------------------------------------------------
# Second lesson lineage
# ---------------------------------------------------------------------------
def test_valid_second_lesson_approve_succeeds(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    second_id = _build_valid_second_lesson(path, learner_id, concept_id)
    resp = _approve(client, second_id)
    assert resp.status_code == 200
    state, audit = _state(path, second_id)
    assert state == "published"
    assert audit == 1


def test_second_lesson_no_prior_lesson_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les_n2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id=None)
    _assert_rejected(client, path, "les_n2")


def test_second_lesson_no_source_feedback_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1", source_feedback_id=None, source_comprehension_response_id=None)
    _insert_comprehension(path, "comp1", "les1", learner_id)
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_second_lesson_no_source_comprehension_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_feedback(path, "fb1", "les1", learner_id, "les2")
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1' WHERE id='les2'")  # no comprehension
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_feedback_belongs_to_another_lesson_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les_other", learner_id=learner_id, concept_id=concept_id, lesson_number=1, generation_status="generation_failed")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_comprehension(path, "comp1", "les1", learner_id)
    # Feedback belongs to les_other, not the prior lesson les1.
    _insert_feedback(path, "fb1", "les_other", learner_id, "les2")
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_feedback_belongs_to_another_learner_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    # Another learner.
    other_learner, _ = bootstrap_learner(path)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_comprehension(path, "comp1", "les1", learner_id)
    # Feedback owned by another learner.
    _insert_feedback(path, "fb1", "les1", other_learner, "les2")
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_feedback_lesson_generation_mismatch_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_comprehension(path, "comp1", "les1", learner_id)
    # lesson_generation=2 but prior lesson_number=1 -> mismatch.
    _insert_feedback(path, "fb1", "les1", learner_id, "les2", lesson_generation=2)
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_feedback_not_applied_to_current_lesson_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_comprehension(path, "comp1", "les1", learner_id)
    # applied_to_lesson_id points elsewhere.
    _insert_feedback(path, "fb1", "les1", learner_id, "les1")
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_comprehension_belongs_to_another_lesson_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les_other", learner_id=learner_id, concept_id=concept_id, lesson_number=1, generation_status="generation_failed")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_feedback(path, "fb1", "les1", learner_id, "les2")
    # Comprehension belongs to les_other, not prior lesson les1.
    _insert_comprehension(path, "comp1", "les_other", learner_id)
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_comprehension_belongs_to_another_learner_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    other_learner, _ = bootstrap_learner(path)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1")
    _insert_feedback(path, "fb1", "les1", learner_id, "les2")
    _insert_comprehension(path, "comp1", "les1", other_learner)
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


def test_diagnostic_snapshot_belongs_to_another_learner_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    other_learner, _ = bootstrap_learner(path)
    conn = _conn(path)
    conn.execute(
        "INSERT INTO diagnostic_snapshots (id, learner_id, coding_experience, explanation_preference, theory_practice_balance, derived_difficulty, created_at) "
        "VALUES ('snap_other', ?, 'none', 'balanced', 'balanced', 'intro_1', datetime('now'))",
        (other_learner,),
    )
    conn.commit(); conn.close()
    _insert_lesson(path, lesson_id="les_f3", learner_id=learner_id, concept_id=concept_id, lesson_number=1, source_diagnostic_snapshot_id="snap_other")
    _assert_rejected(client, path, "les_f3")


def test_no_fallback_to_prior_lesson_signal(portal_app):
    """Current lesson has no source_feedback_id; prior lesson has one. The old
    fallback is removed, so this must be rejected (not substituted)."""
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1", content=_ADAPTED_CONTENT)
    _insert_comprehension(path, "comp1", "les1", learner_id)
    # Prior lesson has a feedback signal; current lesson references comprehension only.
    _insert_feedback(path, "fb_prior", "les1", learner_id, "les2")
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb_prior' WHERE id='les1'")
    conn.execute("UPDATE lessons SET source_feedback_id=NULL, source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


# ---------------------------------------------------------------------------
# Empty feedback directions
# ---------------------------------------------------------------------------
def test_second_lesson_empty_directions_rejected(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    _insert_lesson(path, lesson_id="les1", learner_id=learner_id, concept_id=concept_id, lesson_number=1, publication_state="published")
    _insert_lesson(path, lesson_id="les2", learner_id=learner_id, concept_id=concept_id, lesson_number=2, prior_lesson_id="les1", content=_ADAPTED_CONTENT)
    _insert_comprehension(path, "comp1", "les1", learner_id)
    _insert_feedback(path, "fb1", "les1", learner_id, "les2", directions=[])
    conn = _conn(path)
    conn.execute("UPDATE lessons SET source_feedback_id='fb1', source_comprehension_response_id='comp1' WHERE id='les2'")
    conn.commit(); conn.close()
    _assert_rejected(client, path, "les2")


# ---------------------------------------------------------------------------
# Review payload validation fields
# ---------------------------------------------------------------------------
def test_valid_second_lesson_review_payload(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    second_id = _build_valid_second_lesson(path, learner_id, concept_id)
    resp = client.get(f"/api/v1/operator/review/{second_id}", headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    # Exact source IDs maintained.
    assert body["source_feedback_id"] == "fb1"
    assert body["source_comprehension_response_id"] == "comp1"
    # Structured signals reflect the exact rows.
    assert body["adaptation"]["feedback_signal"]["feedback_id"] == "fb1"
    assert body["adaptation"]["feedback_signal"]["direction_choices"] == ["more_examples"]
    assert body["adaptation"]["comprehension_signal"]["response_id"] == "comp1"
    # Validation: lineage passed and lesson is publishable.
    assert body["validation"]["lineage_integrity"] == "passed"
    assert body["validation"]["adaptation_materiality"] == "passed"
    assert body["validation"]["publishable"] is True
