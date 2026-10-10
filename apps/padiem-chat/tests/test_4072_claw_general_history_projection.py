"""#4072/#3928: real B54 general P01 result → existing owner run-history port.

Real TestClient route with provider-fake adapter; no Production D1, model,
Drive, Office, secrets, or external network activity.
"""
from contextlib import contextmanager
from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_general_run_history import project_completed_general_run

import test_b54_claw_general_p01_routing as base


class OwnerStore:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id):
        return None

    async def record_claw_run(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("private store failure must not leak")


@contextmanager
def owner_client(store, adapter):
    settings = base._settings()
    app = create_app(
        settings=settings, history_store=store, claw_p01_adapter=adapter
    )
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, base.SIGNED_IN_USER_ID),
            domain="chat.example.test", path="/",
        )
        yield client


def test_real_completed_p01_answer_written_once_to_existing_owner_history():
    store = OwnerStore()
    adapter = base._make_adapter(outcome=base._make_outcome(answer="정상 완료된 사용자 결과"))
    payload = base._payload(
        conversation_id="conv_untrusted_browser",
        workspace_id="another-tenant",
        user_id="usr_forged",
        run_id="run_forged",
    )
    with owner_client(store, adapter) as client:
        response = client.post(base.GENERAL_ROUTE_PATH, json=payload)
    assert response.status_code == 200, response.text
    assert "event: done" in response.text
    adapter.execute.assert_awaited_once()
    assert len(store.calls) == 1
    saved = store.calls[0]
    assert saved["user_id"] == base.SIGNED_IN_USER_ID
    assert saved["run_id"].startswith("run_") and len(saved["run_id"]) == 28
    assert saved["channel"] == "web"
    assert saved["action"] == "general"
    assert saved["status"] == "completed"
    assert saved["title"].startswith("Claw: ")
    assert saved["result_summary"] == "정상 완료된 사용자 결과"
    assert saved["artifact_document_id"] is None
    assert saved["artifact_filename"] is None
    assert saved["artifact_media_type"] is None
    assert saved["conversation_id"] is None
    # No client-supplied owner, workspace, conversation, artifact or forged run
    # has been accepted as authority.
    assert "usr_forged" not in str(saved)
    assert "another-tenant" not in str(saved)
    assert "conv_untrusted_browser" not in str(saved)


def test_record_failure_does_not_mask_answer_or_repeat_irreversible_p01_run():
    store = OwnerStore(fail=True)
    adapter = base._make_adapter(outcome=base._make_outcome(answer="확정된 답변"))
    with owner_client(store, adapter) as client:
        response = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
    assert response.status_code == 200
    assert "확정된 답변" in response.text
    assert "private store failure" not in response.text
    adapter.execute.assert_awaited_once()
    assert len(store.calls) == 1


def test_incomplete_or_approval_required_is_never_recorded_as_completed():
    for status, expected in (("waiting_approval", 409), ("failed", 502)):
        store = OwnerStore()
        adapter = base._make_adapter(outcome=base._make_outcome(status=status, answer=None))
        with owner_client(store, adapter) as client:
            response = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
        assert response.status_code == expected
        adapter.execute.assert_awaited_once()
        assert store.calls == []


def test_no_record_for_unbound_p01_route_or_bad_request():
    store = OwnerStore()
    with owner_client(store, None) as client:
        bad = client.post(base.GENERAL_ROUTE_PATH, json={"messages": []})
        unavailable = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
    assert bad.status_code == 400
    assert unavailable.status_code == 503
    assert store.calls == []





def test_real_d1_history_store_owner_read_after_general_p01_execution():
    # Reuse the canonical store with its SQL-accurate in-memory D1 statement
    # port, rather than replacing the read side with an unrelated fake API.
    import asyncio
    import test_history_workspace_linkage as d1_fixture

    store = d1_fixture._store()
    adapter = base._make_adapter(outcome=base._make_outcome(answer="완료 후 기록 조회"))
    with owner_client(store, adapter) as client:
        completed = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
        history = client.get("/api/claw/runs?limit=10")
    assert completed.status_code == 200
    assert history.status_code == 200, history.text
    payload = history.json()
    assert payload["ok"] is True
    assert len(payload["runs"]) == 1
    row = payload["runs"][0]
    assert row["run_id"].startswith("run_")
    assert row["status"] == "completed"
    assert row["action"] == "general"
    assert row["result_summary"] == "완료 후 기록 조회"
    assert row["artifact"] is None
    # Canonical D1 is the single owner filter; no browser-supplied identity.
    foreign = asyncio.run(
        store.list_recent_claw_runs("usr_" + "8" * 32, limit=10)
    )
    assert foreign == []


def test_storage_projection_has_no_fake_lineage_or_private_details():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "app/claw_general_run_history.py").read_text(encoding="utf-8")
    assert 'action="general"' in text
    assert 'channel="web"' in text
    assert 'status="completed"' in text
    assert "conversation_id=None" in text
    assert "artifact_document_id=None" in text
    assert "except Exception:" in text
    for forbidden in ("wrangler", "drive.files", "file_modified", "pdf_exported", "localStorage", "subprocess"):
        assert forbidden not in text
