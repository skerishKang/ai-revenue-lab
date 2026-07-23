import pytest
import httpx
from app.factory import create_app
from app.config import Settings
import sqlite3

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture
def app_instance(temp_db_path):
    settings = Settings(database_url=temp_db_path, environment="testing")
    return create_app(settings)

@pytest.fixture
def sync_db(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

@pytest.mark.anyio
async def test_generation_idempotency_rollback_on_unsafe_content(app_instance, sync_db, mock_settings):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as async_client:
        resp = await async_client.post("/api/v1/learners", json={"topic": "Python", "example_preference": "balanced", "theory_density": "standard", "jargon_level": "standard", "review_question_count": 2})
        assert resp.status_code == 200
        learner_id = resp.json()["learner_id"]

        curriculum_id = resp.json()["curriculum_id"]
        cur = sync_db.cursor()
        cur.execute("SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order LIMIT 1", (curriculum_id,))
        concept_id = cur.fetchone()[0]
        
        app_instance.state.provider.task_payloads = {"lesson_plan": {"title": "t", "sections": [{"section_id": "s1", "title": "test", "description": "import os", "emphasis": "t"}]}}
        resp = await async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id})
        assert resp.status_code == 422
        
        cur = sync_db.cursor()
        cur.execute("SELECT count(*) FROM lessons WHERE learner_id = ?", (learner_id,))
        assert cur.fetchone()[0] == 0
        
        cur.execute("SELECT success, error_category FROM generation_runs")
        rows = cur.fetchall()
        assert len(rows) > 0
        assert rows[0]["success"] == 0
        assert rows[0]["error_category"] == "unsafe_code: unsafe_module_import"

@pytest.mark.anyio
async def test_review_answer_cannot_ground_itself(app_instance, sync_db):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as async_client:
        resp = await async_client.post("/api/v1/learners", json={"topic": "Python", "example_preference": "balanced", "theory_density": "standard", "jargon_level": "standard", "review_question_count": 2})
        learner_id = resp.json()["learner_id"]

        curriculum_id = resp.json()["curriculum_id"]
        cur = sync_db.cursor()
        cur.execute("SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order LIMIT 1", (curriculum_id,))
        concept_id = cur.fetchone()[0]
        
        app_instance.state.provider.task_payloads = {
            "lesson_plan": {"sections": [{"section_id": "s1", "title": "t", "description": "d", "emphasis": "t"}]},
            "lesson_content": {
                "content_version": "1.0",
                "title": "t",
                "sections": [{"section_id": "s1", "title": "t", "content": "not grounding", "includes_code": False}],
                "review_questions": [{"question": "q", "correct_answer": "ungrounded", "explanation": "e"}]
            }
        }
        
        resp = await async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id})
        assert resp.status_code == 422

@pytest.mark.anyio
async def test_review_answer_must_exist_in_lesson_evidence(app_instance, sync_db):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as async_client:
        resp = await async_client.post("/api/v1/learners", json={"topic": "Python", "example_preference": "balanced", "theory_density": "standard", "jargon_level": "standard", "review_question_count": 2})
        learner_id = resp.json()["learner_id"]

        curriculum_id = resp.json()["curriculum_id"]
        cur = sync_db.cursor()
        cur.execute("SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order LIMIT 1", (curriculum_id,))
        concept_id = cur.fetchone()[0]
        
        app_instance.state.provider.task_payloads = {
            "lesson_plan": {"title": "t", "sections": [{"section_id": "s1", "title": "t", "description": "d", "emphasis": "t"}]},
            "lesson_content": {
                "content_version": "1.0",
                "title": "t",
                "sections": [{"section_id": "s1", "title": "t", "content": "this has the grounded_answer", "includes_code": False}],
                "review_questions": [{"question": "q", "correct_answer": "grounded_answer", "explanation": "e"}]
            }
        }
        
        resp = await async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id})
        assert resp.status_code == 200

@pytest.mark.anyio
async def test_code_output_can_ground_review_answer(app_instance, sync_db):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as async_client:
        resp = await async_client.post("/api/v1/learners", json={"topic": "Python", "example_preference": "balanced", "theory_density": "standard", "jargon_level": "standard", "review_question_count": 2})
        learner_id = resp.json()["learner_id"]

        curriculum_id = resp.json()["curriculum_id"]
        cur = sync_db.cursor()
        cur.execute("SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order LIMIT 1", (curriculum_id,))
        concept_id = cur.fetchone()[0]
        
        app_instance.state.provider.task_payloads = {
            "lesson_plan": {"title": "t", "sections": [{"section_id": "s1", "title": "t", "description": "d", "emphasis": "t"}]},
            "lesson_content": {
                "content_version": "1.0",
                "title": "t",
                "sections": [{"section_id": "s1", "title": "t", "content": "not grounding", "includes_code": False}],
                "code_examples": [{"example_id": "e", "language": "python", "explanation": "e", "code": "print(42)", "expected_output": "42"}],
                "review_questions": [{"question": "q", "correct_answer": "42", "explanation": "e"}]
            }
        }
        
        resp = await async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id})
        assert resp.status_code == 200
