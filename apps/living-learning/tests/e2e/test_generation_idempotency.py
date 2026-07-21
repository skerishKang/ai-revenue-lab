import pytest
import httpx
from app.factory import create_app
from app.config import Settings
import sqlite3
import asyncio

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
async def test_generation_idempotency(app_instance, sync_db, mock_settings):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_instance), base_url="http://test") as async_client:
        resp = await async_client.post("/api/v1/learners", json={"topic": "Python", "example_preference": "balanced", "theory_density": "standard", "jargon_level": "standard", "review_question_count": 2})
        learner_id = resp.json()["learner_id"]

        curriculum_id = resp.json()["curriculum_id"]
        cur = sync_db.cursor()
        cur.execute("SELECT id FROM concepts WHERE curriculum_id = ? ORDER BY sequence_order LIMIT 1", (curriculum_id,))
        concept_id = cur.fetchone()[0]
        
        key = "idem-1"
        req1 = async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id, "idempotency_key": key})
        req2 = async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id, "idempotency_key": key})
        results = await asyncio.gather(req1, req2)
        
        # One should succeed, one should fail with 422 concurrent request in progress
        status_codes = {r.status_code for r in results}
        assert 200 in status_codes
        assert 422 in status_codes
        
        successful_resp = next(r for r in results if r.status_code == 200)
        
        # Then an idempotency retry after completion should succeed and return same lesson_id
        req3 = await async_client.post("/api/v1/lessons", json={"learner_id": learner_id, "concept_id": concept_id, "idempotency_key": key})
        assert req3.status_code == 200
        assert req3.json()["lesson_id"] == successful_resp.json()["lesson_id"]
        
        cur = sync_db.cursor()
        cur.execute("SELECT count(*) FROM lessons WHERE learner_id = ?", (learner_id,))
        assert cur.fetchone()[0] == 1
        
        cur.execute("SELECT count(*) FROM generation_runs WHERE success = 1 AND task_type = 'lesson_plan'")
        assert cur.fetchone()[0] == 1
