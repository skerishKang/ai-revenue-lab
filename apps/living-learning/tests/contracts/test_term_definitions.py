"""P1: term_definitions schema consistency.

``LessonContent`` has a validated ``term_definitions`` field shared by the mock
fixture, validation, learner response, and operator response.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.db import apply_migrations
from app.domain.models import LessonContent, TermDefinition
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


def test_valid_term_definitions_preserved():
    content = LessonContent.model_validate(
        {
            "title": "t",
            "sections": [{"section_id": "s1", "title": "섹션", "content": "내용"}],
            "term_definitions": [{"term": "변수", "definition": "값을 담는 이름"}],
        }
    )
    assert len(content.term_definitions) == 1
    assert content.term_definitions[0].term == "변수"
    assert content.term_definitions[0].definition == "값을 담는 이름"


def test_empty_term_rejected():
    with pytest.raises(ValidationError):
        TermDefinition.model_validate({"term": "", "definition": "정의"})


def test_empty_definition_rejected():
    with pytest.raises(ValidationError):
        TermDefinition.model_validate({"term": "변수", "definition": ""})


def _publish_lesson_with_terms(path, learner_id, concept_id, extra_field=None):
    content = {
        "content_version": "1.0",
        "title": "변수",
        "sections": [{"section_id": "s1", "title": "섹션", "content": "변수 설명", "includes_code": True, "code_snippet": "x = 1"}],
        "review_questions": [{"question": "Q?", "correct_answer": "설명", "explanation": "이유"}],
        "code_examples": [{"example_id": "ex1", "language": "python", "code": "x = 10\nprint(x)", "explanation": "할당", "expected_output": "10"}],
        "term_definitions": [{"term": "변수", "definition": "값을 담는 이름"}],
    }
    if extra_field is not None:
        content["secret_internal"] = extra_field
    plan = {"title": "변수", "sections": [{"section_id": "s1", "title": "섹션"}]}
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, prior_lesson_id, generation_status, "
        "publication_state, lesson_plan_json, lesson_content_json, adaptation_summary, created_at, updated_at) "
        "VALUES ('les_terms', ?, ?, 1, NULL, 'pending_review', 'published', ?, ?, '', datetime('now'), datetime('now'))",
        (learner_id, concept_id, json.dumps(plan), json.dumps(content)),
    )
    conn.commit()
    conn.close()


def test_learner_response_includes_term_definitions(portal_app):
    app, learner_id, concept_id, path = portal_app
    _publish_lesson_with_terms(path, learner_id, concept_id)
    client = TestClient(app)
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    terms = resp.json()["term_definitions"]
    assert {"term": "변수", "definition": "값을 담는 이름"} in terms


def test_operator_response_includes_term_definitions(portal_app):
    app, learner_id, concept_id, path = portal_app
    _publish_lesson_with_terms(path, learner_id, concept_id)
    client = TestClient(app)
    resp = client.get("/api/v1/operator/review/les_terms", headers=_auth(OPERATOR_TOKEN))
    assert resp.status_code == 200
    terms = resp.json()["lesson_content"]["term_definitions"]
    assert {"term": "변수", "definition": "값을 담는 이름"} in terms


def test_unexpected_raw_extra_field_not_exposed_to_learner(portal_app):
    app, learner_id, concept_id, path = portal_app
    _publish_lesson_with_terms(path, learner_id, concept_id, extra_field="INTERNAL_SECRET")
    client = TestClient(app)
    resp = client.get("/api/v1/lessons/1", headers=_auth(LEARNER_TOKEN))
    assert resp.status_code == 200
    assert "secret_internal" not in resp.text
    assert "INTERNAL_SECRET" not in resp.text
