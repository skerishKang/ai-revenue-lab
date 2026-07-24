"""P0: exact generation-input provenance.

The review payload shows the EXACT feedback and comprehension response used in
generation (stored on the lesson), never an arbitrary "latest row". First lessons
have NULL feedback/comprehension signals. Provenance is immutable once stored.
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


def _generate_first(client, learner_id, key):
    resp = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/first/generate",
        json={"idempotency_key": key},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert resp.status_code == 200
    return resp.json()["lesson_id"]


def _add_comprehension(path, lesson_id, learner_id, comp_id, understood, free_text):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO comprehension_responses (id, lesson_id, learner_id, understood, difficulty_rating, free_text, response_id, responded_at) "
        "VALUES (?, ?, ?, ?, 3, ?, ?, datetime('now'))",
        (comp_id, lesson_id, learner_id, int(understood), free_text, comp_id),
    )
    conn.commit()
    conn.close()


def _add_feedback(path, lesson_id, learner_id, fb_id, directions):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO feedback (id, lesson_id, learner_id, lesson_generation, direction_choices, free_text, applied_status, created_at) "
        "VALUES (?, ?, ?, 1, ?, '', 'not_applied', datetime('now'))",
        (fb_id, lesson_id, learner_id, json.dumps(directions)),
    )
    conn.commit()
    conn.close()


def test_first_lesson_signals_are_null(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    first_id = _generate_first(client, learner_id, "prov-first")
    resp = client.get(f"/api/v1/operator/review/{first_id}", headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 200
    body = resp.json()
    assert body["adaptation"]["feedback_signal"] is None
    assert body["adaptation"]["comprehension_signal"] is None
    assert body["source_feedback_id"] is None
    assert body["source_comprehension_response_id"] is None


def test_exact_feedback_and_comprehension_used(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    first_id = _generate_first(client, learner_id, "prov-exact")

    # Multiple comprehension responses and feedback exist for the first lesson.
    _add_comprehension(path, first_id, learner_id, "comp_USED", False, "사용된 응답")
    _add_comprehension(path, first_id, learner_id, "comp_LATER", True, "나중 응답")
    _add_feedback(path, first_id, learner_id, "fb_USED", ["more_examples"])
    _add_feedback(path, first_id, learner_id, "fb_LATER", ["code_first"])

    # Generate the second lesson with the SPECIFIC (first) ids.
    resp = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/1/next/generate",
        json={"comprehension_response_id": "comp_USED", "feedback_id": "fb_USED", "idempotency_key": "prov-exact-next"},
        headers=_auth(OPERATOR_TOKEN),
    )
    assert resp.status_code == 200
    second_id = resp.json()["lesson_id"]

    detail = client.get(f"/api/v1/operator/review/{second_id}", headers=_auth(OPERATOR_TOKEN)).json()
    # Exact ids stored on the lesson.
    assert detail["source_feedback_id"] == "fb_USED"
    assert detail["source_comprehension_response_id"] == "comp_USED"
    # Structured signals reflect the exact rows used (not the later ones).
    assert detail["adaptation"]["feedback_signal"]["feedback_id"] == "fb_USED"
    assert detail["adaptation"]["feedback_signal"]["direction_choices"] == ["more_examples"]
    assert detail["adaptation"]["comprehension_signal"]["response_id"] == "comp_USED"
    assert detail["adaptation"]["comprehension_signal"]["understood"] is False
    assert detail["adaptation"]["comprehension_signal"]["free_text"] == "사용된 응답"


def test_provenance_immutable_after_later_responses(portal_app):
    app, learner_id, concept_id, path = portal_app
    client = TestClient(app)
    first_id = _generate_first(client, learner_id, "prov-immut")
    _add_comprehension(path, first_id, learner_id, "comp_A", False, "응답 A")
    _add_feedback(path, first_id, learner_id, "fb_A", ["more_examples"])

    resp = client.post(
        f"/api/v1/operator/learners/{learner_id}/lessons/1/next/generate",
        json={"comprehension_response_id": "comp_A", "feedback_id": "fb_A", "idempotency_key": "prov-immut-next"},
        headers=_auth(OPERATOR_TOKEN),
    )
    second_id = resp.json()["lesson_id"]

    # Add more responses AFTER the second lesson was generated.
    _add_comprehension(path, first_id, learner_id, "comp_B", True, "응답 B")
    _add_feedback(path, first_id, learner_id, "fb_B", ["code_first"])

    # The second lesson's provenance is unchanged.
    detail = client.get(f"/api/v1/operator/review/{second_id}", headers=_auth(OPERATOR_TOKEN)).json()
    assert detail["source_feedback_id"] == "fb_A"
    assert detail["source_comprehension_response_id"] == "comp_A"
    assert detail["adaptation"]["feedback_signal"]["feedback_id"] == "fb_A"
    assert detail["adaptation"]["comprehension_signal"]["response_id"] == "comp_A"
