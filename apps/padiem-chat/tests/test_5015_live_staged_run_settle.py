"""#5015r live SSE settle semantics for a staged run with no verified answer.

Reproduction of the production shape seen on 2026-10-18: the turn
"내 PC 드라이브 목록 알려줘" is resolved by the real
``_requested_natural_pc_query`` resolver to a ``Get-PSDrive`` query, so the
run is staged as ``pending`` before dispatch. The P01/Engine stream then
ended without a verified answer, and nothing ever moved the run out of
``pending`` — no answer, no terminal state, forever.

The settle contract a staged run is allowed to get:

- proven NOT_DISPATCHED or a verified Engine failure settle as ``failed``;
- a verified cancellation settles as ``cancelled``, never as a failure;
- an approval pause, a browser disconnect and an unverifiable outcome are
  never claimed (no status write at all), so the owner keeps the run;
- a verified completion belongs to ``on_completed`` alone and can never be
  overwritten by a late settle: the history UPDATE is atomically guarded,
  and an existing result_summary is never blanked to NULL.
"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.history import D1HistoryStore
from app.claw_general_routes import _requested_natural_pc_query
from kagent.p01_adapter import P01AdapterError, P01DispatchClass
from padiem_ai_core.orchestration_events import OrchestrationEventKind
from test_3930_b54_live_sse_relay import _event, _streaming_adapter
from test_b54_claw_general_p01_routing import _client, _make_outcome, _payload

PC_DRIVE_TEXT = "내 PC 드라이브 목록 알려줘"
RUN_ID = "run_b0e1833620f7430d98c525d1"
RUN_SUMMARY = "로컬 PC 드라이브: C:/ (250GB free)"


def test_real_resolver_sends_this_turn_to_the_pc_drive_engine_lane():
    """Guard: the fixture really is the pc_drive_query path, not ordinary chat."""
    matched, command = _requested_natural_pc_query(PC_DRIVE_TEXT)
    assert matched is True
    assert "Get-PSDrive" in command


def _tracking_store():
    store = MagicMock()
    store.rows = {}
    store.calls = []

    async def record_txt_pending_run(*, user_id, run_id, workspace_id,
                                     user_text, conversation_id):
        store.rows[run_id] = {
            "run_id": run_id, "user_id": user_id, "status": "pending",
            "conversation_id": conversation_id, "workspace_id": workspace_id,
            "result_summary": None,
        }
        # Production staged a run bound to a real owner conversation, e.g.
        # chat_71d3e8e4af84402ba8379b68ca79d1f5 for the 2026-10-18 turn.
        return conversation_id or ("chat_" + "b" * 32)

    async def update_claw_run_status(user_id, run_id, status, result_summary=None):
        store.calls.append((user_id, run_id, status, result_summary))
        if run_id not in store.rows:
            return False
        row = store.rows[run_id]
        if row["status"] == "completed":
            return False
        row["status"] = status
        row["result_summary"] = result_summary or row["result_summary"]
        return True

    store.record_txt_pending_run = record_txt_pending_run
    store.update_claw_run_status = update_claw_run_status
    return store


OWNER = "usr_owner_1"


def _drive_call(adapter, store, *, enabled=True):
    payload = _payload(messages=[{"role": "user", "content": PC_DRIVE_TEXT}])
    with patch("app.claw_general_routes.auth_ready", lambda r: True), \
         patch("app.claw_general_routes.current_user_id", lambda r: OWNER), \
         patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new=AsyncMock(return_value=SimpleNamespace(
                   auth_session=SimpleNamespace(
                       subject=SimpleNamespace(subject_id="sub_" + "9" * 32))))):
        # Drive grounding is an external service and is not what is under test
        # here; the lane under test is staging -> Engine -> signed callback.
        with patch("app.claw_general_routes.drive_general_grounding",
                   new=AsyncMock(return_value=("drive ground", ()))):
            with _client(adapter) as client:
                client.app.state.history_store = store
                client.app.state.claw_live_sse_enabled = enabled
                return client.post(
                    "/api/claw/general", json=payload,
                    headers={"X-Padiem-Claw-Live": "p01-events-v1"},
                )


def test_verified_completion_still_records_and_does_not_double_settle():
    store = _tracking_store()
    adapter = _streaming_adapter(status="completed")
    response = _drive_call(adapter, store)
    assert response.status_code == 200
    assert "event: done" in response.text
    assert [r["status"] for r in store.rows.values()] == ["pending"], (
        "a verified answer is owned by on_completed, not by the settle hook"
    )


def test_engine_failure_settles_the_staged_run_instead_of_stranding_it():
    """The regression: this is what left run_b0e18336... pending forever."""
    store = _tracking_store()
    adapter = _streaming_adapter(status="failed")
    response = _drive_call(adapter, store)
    assert response.status_code == 200, response.text
    assert "event: error" in response.text
    assert store.rows, "the pc_drive turn must have staged a run"
    assert [r["status"] for r in store.rows.values()] == ["failed"], (
        "a staged run with a verified Engine failure must not stay pending; "
        f"update_claw_run_status calls={store.calls}"
    )


def test_approval_pause_is_never_claimed_as_a_pc_execution_failure():
    """#5015r: 승인 대기 is not 실패. No settle write at all, no failure."""
    store = _tracking_store()
    adapter = _streaming_adapter(status="waiting_approval")
    response = _drive_call(adapter, store)
    assert "event: error" in response.text
    assert [r["status"] for r in store.rows.values()] == ["pending"], (
        "an approval-paused run keeps the staged state the owner can resume"
    )
    assert store.calls == [], (
        "no settle write may claim an approval pause as failed/cancelled"
    )


def test_settle_hook_failure_never_breaks_the_user_facing_stream():
    """History settling is best-effort; the stream must still be readable."""
    store = _tracking_store()

    async def explode(user_id, run_id, status, result_summary=None):
        raise RuntimeError("d1 unavailable")
    store.update_claw_run_status = explode

    adapter = _streaming_adapter(status="failed")
    response = _drive_call(adapter, store)
    assert response.status_code == 200
    assert "event: error" in response.text


def test_bounded_tool_stage_detail_rides_the_live_error_frame():
    """#5015: the live lane exposes the same closed detail as the 502 body.

    The Engine error line names the actual tool stage (e.g. a missing
    verification owner). The browser frame keeps the generic code but adds
    only the bounded, reviewed stage identifier — never Engine text.
    """
    store = _tracking_store()
    error = P01AdapterError(
        "p01_engine_stream_failed",
        "Engine streaming failed before a verified terminal result.",
        dispatch_class=P01DispatchClass.UNKNOWN,
        failure_detail="pc_query_admission_required",
    )
    adapter = _streaming_adapter(status="failed", error=error)
    response = _drive_call(adapter, store)
    assert response.status_code == 200
    assert '"code":"engine_execution_failed"' in response.text
    assert '"detail":"pc_query_admission_required"' in response.text
    assert [r["status"] for r in store.rows.values()] == ["failed"]


def test_unbounded_failure_detail_is_never_projected():
    store = _tracking_store()
    error = P01AdapterError(
        "p01_engine_stream_failed",
        "Engine streaming failed before a verified terminal result.",
        dispatch_class=P01DispatchClass.UNKNOWN,
        failure_detail="Owner text; drop table",
    )
    adapter = _streaming_adapter(status="failed", error=error)
    response = _drive_call(adapter, store)
    assert response.status_code == 200
    assert '"detail"' not in response.text
    assert "drop table" not in response.text


# --- the real D1-ish guard: a verified completion can never be overwritten ---


class _FakeStatement:
    def __init__(self, conn: sqlite3.Connection, sql: str):
        self._conn = conn
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values):
        self._values = values
        return self

    def _execute(self):
        return self._conn.execute(self._sql, self._values)

    async def first(self):
        cur = self._execute()
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))

    async def run(self):
        cur = self._execute()
        return {"meta": {"changes": cur.rowcount}}


class _FakeD1:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self._conn, sql)


_RUN_HISTORY_DDL = """
CREATE TABLE claw_run_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    channel TEXT,
    action TEXT,
    title TEXT,
    status TEXT,
    created_at TEXT,
    updated_at TEXT,
    result_summary TEXT,
    artifact_document_id TEXT,
    artifact_filename TEXT,
    artifact_media_type TEXT,
    conversation_id TEXT,
    workspace_id TEXT
);
"""


def _sqlite_history() -> D1HistoryStore:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(_RUN_HISTORY_DDL)
    return D1HistoryStore(_FakeD1(conn))


def test_history_update_claw_run_status_is_atomically_guarded():
    """#5015r: a late settle can neither flip completed nor null a summary."""
    store = _sqlite_history()

    async def scenario():
        await store.record_claw_run(
            OWNER, RUN_ID, channel="chat", action="txt_read",
            title=PC_DRIVE_TEXT, status="completed", result_summary=RUN_SUMMARY,
        )
        # A late settle racing the verified completion must refuse.
        applied = await store.update_claw_run_status(OWNER, RUN_ID, "failed")
        row = await store.get_claw_run(OWNER, RUN_ID)
        return applied, row

    applied, row = asyncio.run(scenario())
    assert applied is False, "the guarded UPDATE must refuse a completed row"
    assert row["status"] == "completed", "a verified completion is untouchable"
    assert row["result_summary"] == RUN_SUMMARY, "the verified answer survives"

    async def staged_scenario():
        pending = await store.record_claw_run(
            OWNER, "run_pending_1", channel="chat", action="txt_read",
            title=PC_DRIVE_TEXT, status="pending", result_summary=None,
        )
        assert pending is None
        applied = await store.update_claw_run_status(
            OWNER, "run_pending_1", "failed", result_summary=None,
        )
        row = await store.get_claw_run(OWNER, "run_pending_1")
        return applied, row

    applied, row = asyncio.run(staged_scenario())
    assert applied is True
    assert row["status"] == "failed"


def test_browser_disconnect_after_a_saved_result_preserves_it():
    """#5015r: 저장 직후 연결 종료 — the answer and its terminal survive.

    The completion callback writes the verified result; the client then
    disconnects, so the relay's ``finally`` runs before any settled answer.
    The disconnect claims nothing, and even a redundant late settle cannot
    overwrite the guarded completed row.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(_RUN_HISTORY_DDL)
    store = D1HistoryStore(_FakeD1(conn))

    async def write_verified_answer(answer: str) -> str | None:
        await store.record_claw_run(
            OWNER, RUN_ID, channel="chat", action="txt_read",
            title=PC_DRIVE_TEXT, status="completed", result_summary=answer,
            conversation_id="chat_" + "b" * 32,
        )
        return "chat_" + "b" * 32

    class _CompletingAdapter:
        async def execute(self, run, *, on_event, **kwargs):
            await on_event(_event(1, OrchestrationEventKind.RUN_STARTED))
            await on_event(_event(2, OrchestrationEventKind.RUN_COMPLETED))
            return _make_outcome(status="completed", answer=RUN_SUMMARY)

    from app.claw_live_events import live_claw_sse

    async def scenario():
        response = live_claw_sse(
            _CompletingAdapter(),
            SimpleNamespace(run_id=RUN_ID, subject_id="sub_" + "9" * 32),
            {"subject_id": "sub_" + "9" * 32},
            on_completed=write_verified_answer,
        )
        chunks = []
        agen = response.body_iterator
        try:
            async for chunk in agen:
                chunks.append(chunk)
                if b"event: done" in chunk:
                    # The user's browser drops the connection right after the
                    # final frame was produced: force the finally block.
                    await agen.aclose()
                    return chunks
        finally:
            # Every other exit path still closes the generator.
            await agen.aclose()
        return chunks

    asyncio.run(scenario())

    async def read_row():
        return await store.get_claw_run(OWNER, RUN_ID)

    row = asyncio.run(read_row())
    assert row is not None, "the verified result must be in history"
    assert row["status"] == "completed", "a disconnect never downgrades a result"
    assert row["result_summary"] == RUN_SUMMARY, "the saved answer is preserved"


def test_drive_query_selects_the_chat_identity_adapter():
    """#5015: the Chat product drive query uses its Chat Engine identity.

    The signed callback must resolve the active Chat session; the historical
    Claw app identity would require a separate Claw product session and return
    401 before any dispatch.
    """
    store = _tracking_store()
    claw_adapter = _streaming_adapter(status="failed")
    chat_adapter = MagicMock()
    chat_adapter.subject_identity_lane = True
    chat_adapter.execute = AsyncMock(side_effect=P01AdapterError(
        "p01_engine_stream_failed",
        "Engine streaming failed before a verified terminal result.",
        dispatch_class=P01DispatchClass.UNKNOWN,
    ))
    payload = _payload(messages=[{"role": "user", "content": PC_DRIVE_TEXT}])
    with patch("app.claw_general_routes.auth_ready", lambda r: True), \
         patch("app.claw_general_routes.current_user_id", lambda r: OWNER), \
         patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new=AsyncMock(return_value=SimpleNamespace(
                   auth_session=SimpleNamespace(
                       subject=SimpleNamespace(subject_id="sub_" + "9" * 32))))), \
         patch("app.claw_general_routes.drive_general_grounding",
               new=AsyncMock(return_value=("drive ground", ()))):
        with _client(claw_adapter) as client:
            client.app.state.history_store = store
            client.app.state.claw_live_sse_enabled = True
            client.app.state.claw_chat_pc_query_adapter = chat_adapter
            response = client.post(
                "/api/claw/general", json=payload,
                headers={"X-Padiem-Claw-Live": "p01-events-v1"},
            )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert chat_adapter.execute.await_count == 1
