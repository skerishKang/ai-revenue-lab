"""#4072/#3928: real B54 general P01 result → existing owner run-history port.

Real TestClient route with provider-fake adapter; no Production D1, model,
Drive, Office, secrets, or external network activity.
"""
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

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
    assert "conversation_id=conversation_id" in text
    assert "artifact_document_id=None" in text
    assert "except Exception:" in text
    for forbidden in ("wrangler", "drive.files", "file_modified", "pdf_exported", "localStorage", "subprocess"):
        assert forbidden not in text

# #3929: the optional canonical conversation is no longer ignored when
# explicitly supplied. It is OWNER-checked before dispatch, then projected
# with the server-resolved canonical CP tenant, never browser workspace_id.

_OWNED_THREAD_3929 = "chat_" + "4" * 32
_TENANT_3929 = "tenant_3929_cp"


class _OwnedConversationStore(OwnerStore):
    async def get_conversation(self, user_id, conversation_id):
        if user_id == base.SIGNED_IN_USER_ID and conversation_id == _OWNED_THREAD_3929:
            return {"id": conversation_id}
        return None


def test_explicit_owned_general_conversation_links_completed_run_and_canonical_tenant():
    store = _OwnedConversationStore()
    adapter = base._make_adapter(
        subject_lane=True,
        outcome=base._make_outcome(answer="?? ??"),
    )
    bridge = SimpleNamespace(auth_session=SimpleNamespace(
        subject=SimpleNamespace(subject_id="subject_3929_test"),
        tenant_id=_TENANT_3929,
    ))
    with patch(
        "app.b54_canonical_session.resolve_current_b54_canonical_session",
        new_callable=AsyncMock, return_value=bridge,
    ):
        with owner_client(store, adapter) as client:
            response = client.post(base.GENERAL_ROUTE_PATH, json=base._payload(
                conversation_id=_OWNED_THREAD_3929,
                workspace_id="fake_browser_workspace",
                user_id="usr_foreign",
            ))
    assert response.status_code == 200, response.text
    adapter.execute.assert_awaited_once()
    assert len(store.calls) == 1
    row = store.calls[0]
    assert row["conversation_id"] == _OWNED_THREAD_3929
    assert row["workspace_id"] == _TENANT_3929
    assert row["user_id"] == base.SIGNED_IN_USER_ID
    assert "fake_browser_workspace" not in str(row)


def test_explicit_foreign_or_malformed_conversation_denied_before_quota_p01():
    store = _OwnedConversationStore()
    adapter = base._make_adapter(subject_lane=True)
    with owner_client(store, adapter) as client:
        invalid = client.post(base.GENERAL_ROUTE_PATH, json=base._payload(
            conversation_id="not_a_canonical_conversation",
        ))
        foreign = client.post(base.GENERAL_ROUTE_PATH, json=base._payload(
            conversation_id="chat_" + "f" * 32,
        ))
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_conversation_id"
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "conversation_not_found"
    adapter.execute.assert_not_called()
    assert store.calls == []



# #3936 Tabbit regression: a completed generic Claw reply becomes a real owner
# conversation. Continuation MUST use server-stored turns, not forged browser
# history, and saving may never turn a completed P01 into a retryable failure.

class _ClawThreadStore(OwnerStore):
    THREAD_ID = "chat_" + "b" * 32

    def __init__(self, *, fail_write=False):
        super().__init__()
        self.fail_write = fail_write
        self.saved = {}

    async def append_exchange(self, user_id, conversation_id, user_text, answer, project_id=None):
        if self.fail_write:
            raise RuntimeError("synthetic history store unavailable")
        assert user_id == base.SIGNED_IN_USER_ID
        cid = conversation_id or self.THREAD_ID
        assert cid == self.THREAD_ID
        if cid not in self.saved:
            self.saved[cid] = {"id": cid, "project_id": project_id, "messages": []}
        thread = self.saved[cid]
        thread["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer},
        ])
        return cid

    async def get_conversation(self, user_id, conversation_id):
        if user_id != base.SIGNED_IN_USER_ID:
            return None
        return self.saved.get(conversation_id)


def test_general_signup_claw_saved_thread_sse_done_id_is_real():
    store = _ClawThreadStore()
    adapter = base._make_adapter(outcome=base._make_outcome(answer="verified test answer"))
    with owner_client(store, adapter) as client:
        result = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
        owned = client.get("/api/conversations/" + store.THREAD_ID)
    assert result.status_code == 200
    assert '"conversation_id":"' + store.THREAD_ID + '"' in result.text
    assert owned.status_code == 200
    assert len(owned.json()["conversation"]["messages"]) == 2
    assert store.saved[store.THREAD_ID]["messages"][1]["content"] == "verified test answer"
    adapter.execute.assert_awaited_once()


def test_same_owner_claw_followup_uses_persisted_context_and_same_thread():
    store = _ClawThreadStore()
    store.saved[store.THREAD_ID] = {
        "id": store.THREAD_ID, "project_id": None,
        "messages": [
            {"role": "user", "content": "previous-owner-unique-context"},
            {"role": "assistant", "content": "previous-verified-answer"},
        ],
    }
    adapter = base._make_adapter(outcome=base._make_outcome(answer="second answer"))
    bridge = SimpleNamespace(auth_session=SimpleNamespace(
        subject=SimpleNamespace(subject_id="owner-subject"), tenant_id="tenant_claw_test",
    ))
    adapter.subject_identity_lane = True
    with patch(
        "app.b54_canonical_session.resolve_current_b54_canonical_session",
        new_callable=AsyncMock, return_value=bridge,
    ):
        with owner_client(store, adapter) as client:
            result = client.post(
                base.GENERAL_ROUTE_PATH,
                json=base._payload(
                    conversation_id=store.THREAD_ID,
                    messages=[{"role": "user", "content": "current-followup-question"}],
                ),
            )
    assert result.status_code == 200, result.text
    assert '"conversation_id":"' + store.THREAD_ID + '"' in result.text
    run = adapter.execute.await_args.args[0]
    assert "previous-owner-unique-context" in run.intent.task
    assert "previous-verified-answer" in run.intent.task
    assert "current-followup-question" in run.intent.task
    assert len(store.saved[store.THREAD_ID]["messages"]) == 4
    assert store.saved[store.THREAD_ID]["messages"][-2]["content"] == "current-followup-question"
    assert store.calls[0]["conversation_id"] == store.THREAD_ID
    assert store.calls[0]["workspace_id"] == "tenant_claw_test"


def test_history_write_failure_preserves_answer_without_forged_thread_receipt():
    store = _ClawThreadStore(fail_write=True)
    adapter = base._make_adapter(outcome=base._make_outcome(answer="still-completed"))
    with owner_client(store, adapter) as client:
        result = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
    assert result.status_code == 200
    assert "still-completed" in result.text
    assert '"conversation_id"' not in result.text
    adapter.execute.assert_awaited_once()


def test_browser_history_bridge_requires_owner_run_link_not_title():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "static/app.js").read_text(encoding="utf-8")
    assert "const clawConversationIds = new Set();" in app
    assert 'run?.action === "general"' in app
    assert "run?.session?.conversation_id" in app
    assert "openClawWorkspace();" in app
    assert "showConversation({ preserveClaw: isVerifiedClawThread });" in app


def test_real_d1_owner_conversation_created_only_after_completed_claw():
    """SQLite executes the same owner-scoped D1 SQL as Production history."""
    import json
    import sqlite3
    from app.history import D1HistoryStore

    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT, "
        "project_id TEXT, title TEXT, created_at TEXT, updated_at TEXT);"
        "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT, "
        "sequence_number INTEGER, role TEXT, content TEXT, created_at TEXT);"
    )

    class Statement:
        def __init__(self, sql):
            self.sql = sql
            self.values = ()

        def bind(self, *values):
            self.values = values
            return self

        async def run(self):
            cursor = db.execute(self.sql, self.values)
            if self.sql.lstrip().upper().startswith("SELECT"):
                return {"success": True, "results": [dict(row) for row in cursor.fetchall()]}
            db.commit()
            return {"success": True}

        async def first(self):
            found = db.execute(self.sql, self.values).fetchone()
            return dict(found) if found else None

        async def all(self):
            return [dict(row) for row in db.execute(self.sql, self.values).fetchall()]

    class SQLiteD1:
        def prepare(self, sql):
            return Statement(sql)

    store = D1HistoryStore(SQLiteD1())
    adapter = base._make_adapter(outcome=base._make_outcome(answer="persisted on D1"))
    with owner_client(store, adapter) as client:
        completed = client.post(base.GENERAL_ROUTE_PATH, json=base._payload())
        done_payload = json.loads(completed.text.rsplit("data: ", 1)[1].strip())
        cid = done_payload.get("conversation_id")
        listed = client.get("/api/conversations")
        detail = client.get("/api/conversations/" + cid) if cid else None
    assert completed.status_code == 200
    assert isinstance(cid, str) and cid.startswith("chat_")
    assert listed.status_code == 200
    assert any(row["id"] == cid for row in listed.json()["conversations"])
    assert detail is not None and detail.status_code == 200
    assert detail.json()["conversation"]["messages"] == [
        {"role": "user", "content": base._payload()["messages"][-1]["content"]},
        {"role": "assistant", "content": "persisted on D1"},
    ]
    db.close()
