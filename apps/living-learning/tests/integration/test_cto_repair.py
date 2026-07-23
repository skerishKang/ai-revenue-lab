import pytest
import sqlite3
from typing import Any
from fastapi.testclient import TestClient

from app.factory import create_app
from app.db import apply_migrations
from app.pipeline.service import LessonPipeline
from app.ai.mock import MockProvider
from app.pipeline.errors import (
    GenerationError,
    RetryExhaustedError,
    NonRetryableError,
    AdaptationNotChangedError,
)

@pytest.fixture
def temp_db_url(tmp_path):
    db_path = tmp_path / "test.db"
    return str(db_path)

@pytest.fixture
def test_app(temp_db_url):
    from app.config import Settings
    settings = Settings(
        database_url=temp_db_url,
        provider_type="mock",
        provider_model="mock-fixture"
    )
    app = create_app(settings)
    return app

@pytest.fixture
def pipeline(test_app, temp_db_url):
    apply_migrations(temp_db_url)
    conn = sqlite3.connect(temp_db_url)
    conn.row_factory = sqlite3.Row
    provider = MockProvider()
    pl = LessonPipeline(conn, provider, test_app.state.settings)
    yield pl
    conn.close()

def test_duplicate_second_request_returns_original_lesson(pipeline, monkeypatch):
    # Setup learner
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]

    # Get a concept
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]

    # Start first lesson
    lesson1_id = pipeline.start_first_lesson(learner_id, concept_id)

    # Comprehension
    comp = pipeline.record_comprehension(lesson1_id, learner_id, understood=False, free_text="hard")

    # Feedback
    fb = pipeline.record_feedback(lesson1_id, learner_id, ["more_examples"])

    # Mock adaptation check so mock provider identical returns don't fail
    monkeypatch.setattr(pipeline, "_verify_adaptation_changes", lambda *args, **kwargs: None)

    # First second lesson call
    res1 = pipeline.process_feedback_and_generate_second_lesson(
        lesson1_id, learner_id, comp["response_id"], fb["feedback_id"], "idem_key_1"
    )

    # Duplicate second request
    res2 = pipeline.process_feedback_and_generate_second_lesson(
        lesson1_id, learner_id, comp["response_id"], fb["feedback_id"], "idem_key_1"
    )

    assert res1["lesson_id"] == res2["lesson_id"]

def test_feedback_from_another_lesson_rejected(pipeline):
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id1 = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]
    concept_id2 = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'values'").fetchone()[0]

    lesson1_id = pipeline.start_first_lesson(learner_id, concept_id1)
    lesson2_id = pipeline.start_first_lesson(learner_id, concept_id2)

    comp1 = pipeline.record_comprehension(lesson1_id, learner_id, understood=False, free_text="hard")
    fb1 = pipeline.record_feedback(lesson1_id, learner_id, ["more_examples"])

    # Try to use fb1 on lesson2
    with pytest.raises(Exception):
        pipeline.process_feedback_and_generate_second_lesson(lesson2_id, learner_id, comp1["response_id"], fb1["feedback_id"])

def test_first_lesson_failure_injection(pipeline, monkeypatch):
    # Contract (no skeleton): a failure while persisting the first lesson must
    # roll back the whole transaction, leaving ZERO lesson rows. We inject the
    # failure at the persist step (create_lesson) inside the service module.
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]

    import app.pipeline.service as service_module

    def failing_create_lesson(*args, **kwargs):
        raise sqlite3.OperationalError("Injected persist failure")

    monkeypatch.setattr(service_module, "create_lesson", failing_create_lesson)

    with pytest.raises(Exception):
        pipeline.start_first_lesson(learner_id, concept_id)

    cursor = pipeline.conn.cursor()
    count = cursor.execute(
        "SELECT count(*) AS c FROM lessons WHERE learner_id = ?", (learner_id,)
    ).fetchone()["c"]
    assert count == 0

def test_second_lesson_failure_injection(pipeline, monkeypatch):
    # Contract (single transaction): if any persist step of the second lesson
    # fails, the whole transaction rolls back — no new lesson, feedback stays
    # unapplied, mastery unchanged, and no adaptation decision is recorded.
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]

    lesson1_id = pipeline.start_first_lesson(learner_id, concept_id)
    comp1 = pipeline.record_comprehension(lesson1_id, learner_id, understood=False, free_text="hard")
    fb1 = pipeline.record_feedback(lesson1_id, learner_id, ["more_examples"])

    import app.pipeline.service as service_module

    def failing_exercise(*args, **kwargs):
        raise sqlite3.OperationalError("Injected failure")

    monkeypatch.setattr(service_module, "create_exercise", failing_exercise)

    with pytest.raises(Exception):
        pipeline.process_feedback_and_generate_second_lesson(
            lesson1_id, learner_id, comp1["response_id"], fb1["feedback_id"]
        )

    cursor = pipeline.conn.cursor()
    fb = cursor.execute("SELECT applied_status FROM feedback WHERE id = ?", (fb1["feedback_id"],)).fetchone()
    assert fb["applied_status"] == "not_applied"

    # Only the original lesson remains — the failed second lesson rolled back.
    lessons = cursor.execute(
        "SELECT * FROM lessons WHERE learner_id = ? ORDER BY created_at DESC", (learner_id,)
    ).fetchall()
    assert len(lessons) == 1
    assert lessons[0]["generation_status"] == "pending_review"

    # No adaptation decision was persisted.
    adapt_count = cursor.execute(
        "SELECT count(*) AS c FROM adaptation_decisions WHERE learner_id = ?", (learner_id,)
    ).fetchone()["c"]
    assert adapt_count == 0

def test_unsupported_create_app_fails_closed(temp_db_url):
    from app.config import Settings
    settings = Settings(
        database_url=temp_db_url,
        provider_type="invalid_type"
    )
    with pytest.raises(ValueError):
        create_app(settings)

def test_provider_none_api_route_fails_closed(temp_db_url):
    from app.config import Settings
    settings = Settings(
        database_url=temp_db_url,
        provider_type="mock"
    )
    app = create_app(settings)
    app.state.provider = None # Simulate missing provider
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 503

def test_migration_004_integrity(temp_db_url):
    apply_migrations(temp_db_url)
    conn = sqlite3.connect(temp_db_url)

    # Insert a learner and concept
    conn.execute("INSERT INTO learners (id, topic, status) VALUES ('L1', 'T1', 'active')")
    conn.execute("INSERT INTO curricula (id, topic) VALUES ('C1', 'T1')")
    conn.execute("INSERT INTO concepts (id, curriculum_id, name) VALUES ('C1', 'C1', 'N1')")

    # Insert first active lesson
    conn.execute(
        "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, generation_status) VALUES ('Lsn1', 'L1', 'C1', 1, 'pending_review')"
    )

    # Insert second active lesson with same number -> should fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, generation_status) VALUES ('Lsn2', 'L1', 'C1', 1, 'pending_review')"
        )

    # Insert failed lesson with same number -> should pass
    conn.execute(
        "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, generation_status) VALUES ('Lsn3', 'L1', 'C1', 1, 'generation_failed')"
    )

    conn.commit()
    conn.close()

def test_six_direction_adaptation_rejection(pipeline):
    orig_plan = {"sections": [{"title": "T1"}]}
    orig_content = {"sections": [{"title": "T1", "content": "Theory"}]}

    with pytest.raises(AdaptationNotChangedError):
        pipeline._verify_adaptation_changes(
            orig_plan, orig_content, orig_plan, orig_content, {"reduce_theory"}
        )

def test_first_lesson_failure_persists_no_skeleton(pipeline, monkeypatch):
    # Contract (no skeleton): when generation fails terminally, zero lesson rows
    # are created, but the failed provider call IS recorded for accounting.
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]

    def mock_generate(*args, **kwargs):
        raise ValueError("Arbitrary error")

    monkeypatch.setattr(pipeline.provider, "generate_structured", mock_generate)

    with pytest.raises(NonRetryableError):
        pipeline.start_first_lesson(learner_id, concept_id)

    cursor = pipeline.conn.cursor()
    lesson_count = cursor.execute(
        "SELECT count(*) AS c FROM lessons WHERE learner_id = ?", (learner_id,)
    ).fetchone()["c"]
    assert lesson_count == 0

    # The failed provider call is still accounted for.
    failed_runs = cursor.execute(
        "SELECT count(*) AS c FROM generation_runs WHERE success = 0"
    ).fetchone()["c"]
    assert failed_runs >= 1

def test_retry_matrix(pipeline, monkeypatch):
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]

    # 1. A timeout is retryable and maps to the "timeout" category (not a
    #    collapsed transient bucket). It retries MAX_RETRIES times.
    call_count = 0

    def mock_transient(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Timeout")

    monkeypatch.setattr(pipeline.provider, "generate_structured", mock_transient)

    with pytest.raises(RetryExhaustedError):
        pipeline.start_first_lesson(learner_id, concept_id)
    assert call_count == 3

    # Generation runs are keyed by the candidate lesson id (no lesson row is
    # persisted on failure), so query by task type + category.
    runs = pipeline.conn.execute(
        "SELECT attempt_number, error_category FROM generation_runs "
        "WHERE task_type = 'lesson_plan' AND error_category = 'timeout' "
        "ORDER BY attempt_number"
    ).fetchall()
    assert len(runs) == 3
    assert [r[0] for r in runs] == [1, 2, 3]
    assert all(r[1] == "timeout" for r in runs)

    # 2. A non-retryable error aborts immediately after a single call.
    call_count = 0

    def mock_fatal(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        class AuthError(Exception):
            error_category = "authentication_error"

        raise AuthError("auth failed")

    monkeypatch.setattr(pipeline.provider, "generate_structured", mock_fatal)

    with pytest.raises(NonRetryableError):
        pipeline.start_first_lesson(learner_id, concept_id)
    assert call_count == 1

    auth_runs = pipeline.conn.execute(
        "SELECT count(*) AS c FROM generation_runs WHERE error_category = 'authentication_error'"
    ).fetchone()["c"]
    assert auth_runs == 1

def test_privacy_safe_accounting(pipeline, monkeypatch):
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]

    def mock_generate(*args, **kwargs):
        raise ValueError("Arbitrary error with API_KEY=secret_12345")
    monkeypatch.setattr(pipeline.provider, "generate_structured", mock_generate)

    with pytest.raises(NonRetryableError):
        pipeline.start_first_lesson(learner_id, concept_id)

    runs = pipeline.conn.execute("SELECT error_message FROM generation_runs ORDER BY created_at DESC LIMIT 1").fetchall()
    assert "secret_12345" not in runs[0][0]
    assert runs[0][0] == "unknown_exception"

def test_app_isolation(tmp_path):
    from app.config import Settings
    from fastapi.testclient import TestClient
    import uuid

    db1_path = str(tmp_path / "db1.sqlite")
    db2_path = str(tmp_path / "db2.sqlite")

    set1 = Settings(database_url=db1_path, provider_type="mock", provider_model="mock-1")
    set2 = Settings(database_url=db2_path, provider_type="mock", provider_model="mock-2")

    apply_migrations(db1_path)
    apply_migrations(db2_path)

    app1 = create_app(set1)
    app2 = create_app(set2)

    # App1 setup
    client1 = TestClient(app1)
    client2 = TestClient(app2)

    res1 = client1.post("/api/v1/learners", json={"display_name": "L1", "topic": "Python"})
    assert res1.status_code == 200
    learner1_id = res1.json()["learner_id"]

    # Check health and model
    h1 = client1.get("/health").json()
    assert h1["provider"] == "mock"
    assert h1["model"] == "mock-1"

    h2 = client2.get("/health").json()
    assert h2["provider"] == "mock"
    assert h2["model"] == "mock-2"

    # Verify isolation
    res2 = client2.get(f"/api/v1/learners/{learner1_id}/progress")
    assert res2.status_code == 422

    # App2 setup
    res2_create = client2.post("/api/v1/learners", json={"display_name": "L2", "topic": "Java"})
    assert res2_create.status_code == 200
    learner2_id = res2_create.json()["learner_id"]

    res1_check = client1.get(f"/api/v1/learners/{learner2_id}/progress")
    # Cross-app access maps to "learner not found" (422) — consistent with the
    # reverse direction above. Isolation holds: app1 never sees app2's data.
    assert res1_check.status_code == 422
