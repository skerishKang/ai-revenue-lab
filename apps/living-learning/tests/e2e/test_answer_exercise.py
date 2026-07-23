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
async def test_answer_exercise_mastery(app_instance, sync_db):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as async_client:
        resp = await async_client.post("/api/v1/learners", json={"topic": "Python", "example_preference": "balanced", "theory_density": "standard", "jargon_level": "standard", "review_question_count": 2})
        learner_id = resp.json()["learner_id"]

        curriculum_id = resp.json()["curriculum_id"]
        cur = sync_db.cursor()
        cur.execute("SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order LIMIT 1", (curriculum_id,))
        concept_id = cur.fetchone()[0]

        resp = await async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id})
        assert resp.status_code == 200
        lesson_id = resp.json()["lesson_id"]

        cur = sync_db.cursor()
        cur.execute("SELECT id, correct_answer FROM exercises WHERE lesson_id = ?", (lesson_id,))
        ex = cur.fetchone()
        ex_id = ex["id"]
        ans = ex["correct_answer"]

        resp = await async_client.post("/api/v1/exercises/answer", json={
            "exercise_id": ex_id,
            "learner_id": learner_id,
            "answer": ans,
            "idempotency_key": "ans1"
        })
        assert resp.status_code == 200
        assert resp.json()["is_correct"] == True
        assert resp.json()["is_duplicate"] == False

        cur.execute("SELECT practice_count, correct_count FROM learner_mastery WHERE learner_id = ?", (learner_id,))
        m = cur.fetchone()
        assert m["practice_count"] == 1
        assert m["correct_count"] == 1

        resp = await async_client.post("/api/v1/exercises/answer", json={
            "exercise_id": ex_id,
            "learner_id": learner_id,
            "answer": ans,
            "idempotency_key": "ans1"
        })
        assert resp.status_code == 200
        assert resp.json()["is_duplicate"] == True

        cur.execute("SELECT practice_count, correct_count FROM learner_mastery WHERE learner_id = ?", (learner_id,))
        m2 = cur.fetchone()
        assert m2["practice_count"] == 1
        assert m2["correct_count"] == 1

        resp = await async_client.post("/api/v1/exercises/answer", json={
            "exercise_id": ex_id,
            "learner_id": learner_id,
            "answer": "wrong",
        })
        assert resp.status_code == 409

        cur.execute("SELECT practice_count, correct_count FROM learner_mastery WHERE learner_id = ?", (learner_id,))
        m3 = cur.fetchone()
        assert m3["practice_count"] == 1
        assert m3["correct_count"] == 1
