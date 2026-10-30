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


def _store(*, dispatch=None, run_row=None, messages=None, reads=None,
           legacy_correlation_unavailable=False):
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
        if legacy_correlation_unavailable:
            # A deployment that never applied the legacy correlation migration
            # cannot read that table at all.
            raise RuntimeError("no such table: claw_local_task_correlation")
        return None

    store._first = first
    store._all = all_rows
    store.get_local_task_correlation = local_correlation
    attach_dispatch_seam(store)  # the seam the real store answers dispatch reads through
    return store


def test_general_run_result_returns_the_actual_message_not_the_summary():
    run_row = {
        "id": RUN_ID, "action": "general", "status": "completed",
        "conversation_id": CID, "result_summary": ANSWER[:50],
    }
    store = _store(
        run_row=run_row,
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {"answer": ANSWER, "answer_source": "model_reply"}


def test_general_run_result_refuses_every_unverified_shape():
    completed = {
        "id": RUN_ID, "action": "general", "status": "completed",
        "conversation_id": CID,
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
        "id": RUN_ID, "action": "general", "status": "completed",
        "conversation_id": CID,
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


def test_a_pc_execution_without_its_own_result_keeps_the_unavailable_state():
    """A PC run never answers from a model reply."""
    run_row = {
        "id": RUN_ID, "action": "general", "status": "completed",
        "conversation_id": CID,
    }
    # The run carries a completed PC execution correlation, but its verified
    # message is missing.
    store = _store(
        dispatch={"command_id": "command_1", "revision_ref": "revision_1"},
        run_row=run_row,
        messages=[],
    )
    assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None
    # With its own verified message the same run answers as a PC command result.
    store = _store(
        dispatch={"command_id": "command_1", "revision_ref": "revision_1"},
        run_row=run_row,
        messages=[{"id": "msg_ltr_x", "content": "PC COMMAND OUTPUT"}],
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {
        "answer": "PC COMMAND OUTPUT", "answer_source": "pc_command_result",
    }


def test_a_model_reply_requires_the_server_verified_model_only_action():
    """Only a run the server recorded as model-only may answer with a model reply."""
    for action in ("txt_read", "desktop_capture", "", None):
        run_row = {
            "id": RUN_ID, "action": action, "status": "completed",
            "conversation_id": CID,
        }
        store = _store(
            run_row=run_row,
            messages=[{"id": MESSAGE_ID, "content": ANSWER}],
        )
        assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None, action
    # The model-only action the general lane itself records does answer.
    store = _store(
        run_row={
            "id": RUN_ID, "action": "general", "status": "completed",
            "conversation_id": CID,
        },
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {"answer": ANSWER, "answer_source": "model_reply"}


def test_command_run_result_keeps_the_verified_pc_source():
    store = _store(
        dispatch={"command_id": "command_1", "revision_ref": "revision_1"},
        messages=[{"id": "msg_ltr_x", "content": "PC COMMAND OUTPUT"}],
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {
        "answer": "PC COMMAND OUTPUT", "answer_source": "pc_command_result",
    }


def test_an_unavailable_legacy_correlation_table_never_hides_the_model_reply():
    """#5015: a deployment without the legacy correlation table still answers.

    The legacy local-runner correlation table comes from a source migration a
    deployment may never have applied. An unavailable table means the
    deployment holds no local-runner correlation at all, so it must not turn a
    model-only run into an unavailable result.
    """
    run_row = {
        "id": RUN_ID, "action": "general", "status": "completed",
        "conversation_id": CID,
    }
    store = _store(
        run_row=run_row,
        messages=[{"id": MESSAGE_ID, "content": ANSWER}],
        legacy_correlation_unavailable=True,
    )
    resolved = asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID))
    assert resolved == {"answer": ANSWER, "answer_source": "model_reply"}


def test_an_unavailable_legacy_correlation_table_never_fabricates_a_pc_answer():
    """A PC run stays unavailable without its own verified result."""
    for action in ("txt_read", "desktop_capture", "pc_files_query"):
        store = _store(
            run_row={
                "id": RUN_ID, "action": action, "status": "completed",
                "conversation_id": CID,
            },
            messages=[{"id": MESSAGE_ID, "content": ANSWER}],
            legacy_correlation_unavailable=True,
        )
        assert asyncio.run(store.get_claw_run_result(OWNER, RUN_ID, CID)) is None, action


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


def test_a_running_row_is_reconciled_exactly_like_a_pending_one(monkeypatch):
    """#5573 3-D-2: reporting a PC step in flight cannot withhold the answer.

    The projection moves the staged row pending -> running. Both states are
    non-terminal, and both must still reach the return leg, so a result that
    landed while the conversation waited is delivered in the same GET instead of
    being delayed by a status the reader was shown.
    """
    import app.claw_routes as routes

    class History:
        def __init__(self, status: str) -> None:
            self.status = status

        async def get_claw_run(self, user_id, run_id):
            return {"run_id": run_id, "conversation_id": CID, "status": self.status}

        async def get_claw_run_result(self, user_id, run_id, conversation_id):
            return {"answer": ANSWER, "answer_source": "pc_command_result"}

    class Source:
        configured = True

        def __init__(self, history: History) -> None:
            self.history = history
            self.calls: list[tuple[str, str]] = []

        def project_local_runner_result(self, *, owner_id, run_id):
            assert (owner_id, run_id) == (OWNER, RUN_ID), (owner_id, run_id)
            self.calls.append((owner_id, run_id))
            # The return leg seals the run in its own conversation.
            self.history.status = "completed"

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    delivered = {}
    for status in ("pending", "running"):
        history = History(status)
        source = Source(history)
        request = _request(history)
        request.scope["app"].state.local_task_result_source = source
        response = asyncio.run(claw_pending_result(request))
        assert response.status_code == 200, (status, response.status_code)
        body = json.loads(response.body)["result"]
        assert source.calls == [(OWNER, RUN_ID)], status
        assert body["status"] == "completed", (status, body)
        assert body["answer"] == ANSWER, status
        delivered[status] = body["answer_source"]
    assert delivered == {"pending": "pc_command_result", "running": "pc_command_result"}


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


# ---------------------------------------------------------------- #5573 3-D-2
# The conversation polls its own run row for progress, so the row the server
# moved to "running" has to reach the status chip — and a chip that showed a
# running step must be settled by the run's real outcome.

def _pc_poll_source() -> str:
    from pathlib import Path

    app_js = (
        Path(__file__).resolve().parents[1] / "static" / "app.js"
    ).read_text(encoding="utf-8")
    poll = app_js.split("async function waitForAcceptedPcRun(", 1)[1]
    return poll.split("async function requestStreamingAnswer(", 1)[0]


def test_the_pc_wait_loop_shows_the_server_observed_running_step():
    poll = _pc_poll_source()
    observed = poll.index('result.status === "running"')
    painted = poll.index('showPcRuntimeStatus(article, "tool_started")')
    # The chip is applied inside the same branch that keeps waiting and before
    # the loop continues, so an observed running state cannot be skipped.
    assert observed < painted < poll.index("continue;")
    # A still-pending run invents nothing: it keeps the preparing chip.
    assert poll.count("tool_started") == 1


def test_a_pc_running_chip_is_never_left_stale_by_the_outcome():
    poll = _pc_poll_source()
    assert poll.index('showPcRuntimeStatus(article, "run_failed")') < poll.index(
        "MESSAGE_LIFECYCLE.FAILED"
    )
    # A model reply is not a completed PC execution, so the running chip is
    # released instead of confirmed.
    released = poll.index('applyRuntimeLabel?.(article, "", "status")')
    assert released < poll.index("MESSAGE_LIFECYCLE.COMPLETED")
    # The verified PC result settles the chip after the preparing release, so
    # the release can never erase the terminal wording.
    assert poll.index("releasePreparingRuntimeLabel") < poll.index(
        'showPcRuntimeStatus(article, "run_completed")'
    )


def test_a_recovered_answer_releases_the_running_chip_it_was_shown():
    """#5735: the result-recovery GET must not leave a step marked running.

    The PC wait paints the observed step onto the chip, and the preparing
    release deliberately keeps a chip that carries a real status. The recovery
    renderer therefore releases it explicitly, after the stored answer replaces
    the content and before the turn is settled.
    """
    from pathlib import Path

    app = (
        Path(__file__).resolve().parents[1] / "static" / "app.js"
    ).read_text(encoding="utf-8")
    render = app.split("function renderStoredPcAnswer(", 1)[1].split("\n  }", 1)[0]
    assert "content.replaceChildren();" in render, render
    released = render.index('applyRuntimeLabel?.(article, "", "status")')
    assert render.index("content.replaceChildren();") < released, render
    assert released < render.index("MESSAGE_LIFECYCLE.COMPLETED"), render
    # One shared guard, declared before both readers of the run, so the same
    # recovered run can never be painted into the conversation twice.
    declared = app.index("const resolvedPcRuns = new Set();")
    assert declared < app.index("async function waitForAcceptedPcRun(")
    assert declared < app.index("async function recoverStoredPcResult(")


def test_the_observed_pc_step_is_carried_on_the_card_that_shows_it():
    """The card owns the live status, so a running turn has to reach the card."""
    poll = _pc_poll_source()
    running = poll.index('result.status === "running"')
    hinted = poll.index('setTaskHint?.(article, "tool")')
    painted = poll.index('showPcRuntimeStatus(article, "tool_started")')
    assert running < hinted < painted < poll.index("continue;")
    # Every outcome releases the hint before it settles the turn, so a step that
    # already ended cannot keep showing the running wording on a finished turn.
    for outcome in ("run_failed", "run_completed"):
        at = poll.index(f'showPcRuntimeStatus(article, "{outcome}")')
        assert poll.rindex("setTaskHint?.(article, null)", 0, at) < at
    assert poll.count("setTaskHint?.(article, null)") == 3


def test_the_pc_progress_kinds_exist_in_the_real_stage_vocabulary():
    """An unknown kind yields no copy, and a missing chip would fail silently."""
    from pathlib import Path

    table = (
        Path(__file__).resolve().parents[1] / "static" / "claw-run-event-projection.js"
    ).read_text(encoding="utf-8")
    for kind in ("tool_started", "run_completed", "run_failed"):
        rows = [line for line in table.splitlines() if line.strip().startswith(kind + ":")]
        assert len(rows) == 1, rows
        pair = rows[0].split("[", 1)[1].rsplit("]", 1)[0]
        ko, _, en = pair.partition('", "')
        assert ko.startswith('"') and en.endswith('"'), pair
        assert ko[1:].strip() and en[:-1].strip(), pair
