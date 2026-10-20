"""#5015: a model-only Claw run is readable through its own stored message.

The owner-scoped lookup compares the stored completion record with the actual
assistant message of that run, inside the owner / run / conversation scope. It
never substitutes the run summary for the message, never turns an unverified
run into a success, and it labels a model reply as a model reply.
"""
import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from app.history import (
    D1HistoryStore,
    PRODUCT_SCOPE_CHAT,
    general_answer_message_id,
)
from app.claw_routes import claw_pending_result


OWNER = "owner"
CID = "chat_" + "a" * 24
RUN_ID = "run_" + "b" * 24
MESSAGE_ID = general_answer_message_id(RUN_ID)
ANSWER = "the verified model reply"


def _store(*, dispatch=None, run_row=None, messages=None, reads=None):
    """A D1HistoryStore whose three reads are answered from fixed evidence."""
    store = SimpleNamespace()
    store.get_claw_run_result_message = D1HistoryStore.get_claw_run_result_message.__get__(
        store
    )
    store.get_claw_run_result = D1HistoryStore.get_claw_run_result.__get__(store)

    async def first(sql, *args):
        if reads is not None:
            reads.append(("first", sql, args))
        if "oracle_mesh_dispatch" in sql:
            return dispatch
        if "claw_run_history" in sql:
            return run_row
        return None

    async def all_rows(sql, *args):
        if reads is not None:
            reads.append(("all", sql, args))
        return messages or []

    async def local_correlation(user_id, run_id):
        return None

    store._first = first
    store._all = all_rows
    store.get_local_task_correlation = local_correlation
    return store


def test_general_run_result_returns_the_actual_message_not_the_summary():
    run_row = {
        "id": RUN_ID, "status": "completed", "conversation_id": CID,
        "result_summary": ANSWER[:50],
    }
    store = _store(
        run_row=run_row,
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {"answer": ANSWER, "answer_source": "model_reply"}


def test_general_run_result_refuses_every_unverified_shape():
    completed = {
        "id": RUN_ID, "status": "completed", "conversation_id": CID,
    }
    # No stored completion record at all.
    store = _store(run_row=None, messages=[{"id": MESSAGE_ID, "content": ANSWER}])
    assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None
    # A run that the store never recorded as completed stays unverified.
    store = _store(
        run_row={**completed, "status": "running"},
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
    )
    assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None
    # A run whose conversation differs from the requested one never answers.
    store = _store(
        run_row={**completed, "conversation_id": "chat_other"},
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
    )
    assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None
    # A completed run without the correlated message stays unverified.
    store = _store(run_row=completed, messages=[])
    assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None


def test_general_run_result_is_scoped_to_the_owner_conversation_and_message():
    run_row = {
        "id": RUN_ID, "status": "completed", "conversation_id": CID,
    }
    reads = []
    store = _store(
        run_row=run_row,
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
        reads=reads,
    )
    asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    lookup = [entry for entry in reads if entry[0] == "all"][-1]
    sql, args = lookup[1], lookup[2]
    assert "JOIN conversations" in sql
    assert "c.user_id=?" in sql and "c.product_scope=?" in sql
    assert "m.role='assistant'" in sql
    assert args == (MESSAGE_ID, CID, OWNER, PRODUCT_SCOPE_CHAT)


def test_command_run_result_keeps_the_verified_pc_source():
    store = _store(
        dispatch={"command_id": "command_1", "revision_ref": "revision_1"},
        messages=[{"id": "msg_ltr_x", "content": "PC COMMAND OUTPUT"}],
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {
        "answer": "PC COMMAND OUTPUT", "answer_source": "pc_command_result",
    }


def _request(history):
    request = Request({
        "type": "http", "method": "GET",
        "path": "/api/claw/runs/run_abc123abc123/pending-result",
        "path_params": {"run_id": RUN_ID}, "headers": [],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(history_store=history)
    )
    return request


def test_pending_result_reports_the_model_reply_source(monkeypatch):
    import app.claw_routes as routes

    class History:
        async def get_claw_run(self, user_id, run_id):
            return {"run_id": run_id, "conversation_id": CID, "status": "completed"}

        async def get_claw_run_result(self, user_id, run_id, conversation_id):
            return {"answer": ANSWER, "answer_source": "model_reply"}

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    response = asyncio.run(claw_pending_result(_request(History())))
    assert response.status_code == 200
    body = json.loads(response.body)["result"]
    assert body["answer"] == ANSWER
    assert body["answer_source"] == "model_reply"


def test_pending_result_keeps_an_unverified_run_unavailable(monkeypatch):
    import app.claw_routes as routes

    class History:
        async def get_claw_run(self, user_id, run_id):
            return {"run_id": run_id, "conversation_id": CID, "status": "completed"}

        async def get_claw_run_result(self, user_id, run_id, conversation_id):
            return None

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    response = asyncio.run(claw_pending_result(_request(History())))
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "run_result_unavailable"


def test_browser_never_presents_a_model_reply_as_a_verified_pc_result():
    from pathlib import Path

    app_js = (
        Path(__file__).resolve().parents[1] / "static" / "app.js"
    ).read_text(encoding="utf-8")
    poll = app_js.split("async function waitForAcceptedPcRun(", 1)[1]
    poll = poll.split("async function requestStreamingAnswer(", 1)[0]
    assert 'result.answer_source !== "pc_command_result"' in poll
    # The model's own answer stays in place; only a verified PC command result
    # replaces the article content.
    assert poll.index('result.answer_source !== "pc_command_result"') < poll.index(
        "content.replaceChildren();"
    )
