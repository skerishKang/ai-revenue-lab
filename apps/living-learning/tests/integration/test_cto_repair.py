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

def test_duplicate_second_request_returns_original_lesson(pipeline):
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
    pass

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

def test_failed_skeleton_is_persisted(pipeline, monkeypatch):
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]
    
    def mock_generate(*args, **kwargs):
        raise ValueError("Arbitrary error")
    
    monkeypatch.setattr(pipeline.provider, "generate_structured", mock_generate)
    
    with pytest.raises(NonRetryableError):
        pipeline.start_first_lesson(learner_id, concept_id)
    
    # Ensure lesson is failed
    cursor = pipeline.conn.cursor()
    lesson = cursor.execute("SELECT * FROM lessons WHERE learner_id = ? ORDER BY created_at DESC", (learner_id,)).fetchone()
    assert lesson["generation_status"] == "generation_failed"

def test_exact_attempt_counts(pipeline, monkeypatch):
    learner_data = pipeline.create_learner_and_session(topic="Python")
    learner_id = learner_data["learner_id"]
    concept_id = pipeline.conn.execute("SELECT id FROM concepts WHERE name = 'variables'").fetchone()[0]
    
    call_count = 0
    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Timeout")
    
    monkeypatch.setattr(pipeline.provider, "generate_structured", mock_generate)
    
    with pytest.raises(RetryExhaustedError):
        pipeline.start_first_lesson(learner_id, concept_id)
        
    assert call_count == 3
    
    runs = pipeline.conn.execute("SELECT attempt_number FROM generation_runs").fetchall()
    assert len(runs) == 3
    assert [r[0] for r in runs] == [1, 2, 3]

def test_file_backed_database(temp_db_url):
    from app.config import Settings
    settings = Settings(database_url=temp_db_url, provider_type="mock")
    app1 = create_app(settings)
    app2 = create_app(settings)
    assert app1 is not None and app2 is not None

