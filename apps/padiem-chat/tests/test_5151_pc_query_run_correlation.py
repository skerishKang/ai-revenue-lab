"""#5151 — offline correlation of a product PC query run with the session row.

The b62 Chat product owns the session/conversation contract: a PC query run
is staged as an owner-scoped run row whose conversation and workspace linkage
is immutable. This suite stages a run through that existing contract, runs
the product-side PC query assembly offline with a synthetic drive tool, and
proves that the executed run is the run that owns the conversation.

A synthetic tool success is a local assembly proof only: it is not a PC
connection, not a dispatch, and not an operational transition.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from app.chat_pc_run_correlation import (
    CORRELATION_CORRELATED,
    CORRELATION_INVALID_REQUEST,
    CORRELATION_LINK_MISSING,
    CORRELATION_RUN_MISMATCH,
    CORRELATION_RUN_NOT_FOUND,
    CORRELATION_RUN_ONLY,
    verify_pc_query_run_correlation,
)
from app.history import D1HistoryStore, HistoryError

from kagent import pc_query_adapter as product_adapter
from kagent.pc_query_core_execution import (
    PcQueryCoreRequest,
    run_pc_query_with_core,
)

from padiem_ai_core.tool_runtime import ToolRuntime

OWNER = "usr_owner_5151"
OTHER_OWNER = "usr_other_5151"
WORKSPACE = "ws_5151"
RUN_ID = "chat_pcq_5151correlate"
INPUT_TEXT = "내 PC 드라이브 목록 알려줘"
ANSWER = "확인된 PC 드라이브: C:/ (250GB free)"
DEVICE_ID = "pc-com2"

_SCHEMA = """
CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    project_id TEXT, title TEXT, created_at TEXT, updated_at TEXT,
    product_scope TEXT NOT NULL);
CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT);
CREATE TABLE claw_run_history (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, user_id TEXT NOT NULL,
    channel TEXT, action TEXT, title TEXT, status TEXT, created_at TEXT,
    updated_at TEXT, result_summary TEXT, artifact_document_id TEXT,
    artifact_filename TEXT, artifact_media_type TEXT, conversation_id TEXT,
    workspace_id TEXT);
"""


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
        return dict(zip([column[0] for column in cur.description], row))

    async def run(self):
        self._execute()
        return {"meta": {"changes": self._conn.total_changes}}


class _FakeD1:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self._conn, sql)


def _store() -> D1HistoryStore:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(_SCHEMA)
    return D1HistoryStore(_FakeD1(conn))


def _synthetic_runtime() -> ToolRuntime:
    """A Core ToolRuntime with a synthetic drive tool (no PC, no network)."""
    runtime = ToolRuntime()

    async def synthetic_query_drives(arguments):
        return {
            "dispatch_id": "dispatch_synthetic_5151",
            "output": '[{"Name":"C:","Root":"C:\\\\","Used":1,"Free":2}]',
            "result_sha256": "0" * 64,
            "execution_confirmed": True,
            "termination": "exited",
            "exit_code": 0,
        }

    runtime.register(product_adapter.pc_drives_tool_spec(), synthetic_query_drives)
    return runtime


class _StepSelector:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *, context, compiled_profile, observations):
        self.calls += 1
        if context.tool_results:
            return {"action": "complete", "answer": ANSWER}
        return {
            "action": "tool",
            "tool_id": product_adapter.PC_DRIVES_TOOL_ID,
            "arguments": {},
        }


def _contract():
    return product_adapter.build_pc_query_product_contract(
        app_id=product_adapter.CHAT_APP_ID,
        agent_id=product_adapter.CHAT_PC_QUERY_AGENT_ID,
    )


def _run_assembly(run_id: str, *, subject_id: str = "sub_" + "5" * 32):
    return asyncio.run(run_pc_query_with_core(
        request=PcQueryCoreRequest(
            contract=_contract(),
            tool_runtime=_synthetic_runtime(),
            input_text=INPUT_TEXT,
            run_id=run_id,
            subject_id=subject_id,
            device_id=DEVICE_ID,
        ),
        select_step=_StepSelector(),
    ))


def test_staged_run_and_executed_run_correlate_to_the_same_conversation() -> None:
    store = _store()
    conversation_id = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=RUN_ID, workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))
    assert conversation_id.startswith("chat_")

    outcome = _run_assembly(RUN_ID)
    assert outcome.completed is True

    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OWNER, run_id=RUN_ID, outcome=outcome,
    ))

    assert verdict.status == CORRELATION_CORRELATED
    assert verdict.correlated is True
    # The conversation and workspace come from the staged row, not from a caller.
    assert verdict.conversation_id == conversation_id
    assert verdict.workspace_id == WORKSPACE
    assert verdict.product_app_id == product_adapter.CHAT_APP_ID
    assert verdict.agent_id == product_adapter.CHAT_PC_QUERY_AGENT_ID


def test_a_run_that_was_never_staged_is_not_correlated() -> None:
    store = _store()
    outcome = _run_assembly("chat_pcq_never_staged")
    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OWNER, run_id="chat_pcq_never_staged", outcome=outcome,
    ))
    assert verdict.status == CORRELATION_RUN_NOT_FOUND
    assert verdict.correlated is False
    assert verdict.conversation_id is None


def test_another_owner_cannot_claim_the_staged_run() -> None:
    store = _store()
    asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=RUN_ID, workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))
    outcome = _run_assembly(RUN_ID)
    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OTHER_OWNER, run_id=RUN_ID, outcome=outcome,
    ))
    assert verdict.status == CORRELATION_RUN_NOT_FOUND
    assert verdict.conversation_id is None


def test_an_executed_run_that_is_not_the_requested_run_is_refused() -> None:
    store = _store()
    asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=RUN_ID, workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))
    other_outcome = _run_assembly("chat_pcq_other_run")
    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OWNER, run_id=RUN_ID, outcome=other_outcome,
    ))
    assert verdict.status == CORRELATION_RUN_MISMATCH
    assert verdict.correlated is False
    assert verdict.conversation_id is None


def test_the_existing_session_contract_keeps_the_conversation_linkage_immutable() -> None:
    """The reused contract: a staged run never transfers to another conversation."""
    store = _store()
    conversation_id = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=RUN_ID, workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))
    other = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id="chat_pcq_5151other", workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))
    assert other != conversation_id

    with pytest.raises(HistoryError):
        asyncio.run(store.record_claw_run(
            user_id=OWNER, run_id=RUN_ID, channel="web", action="pc_drive_query",
            title="PC 드라이브 조회: 다시", status="pending",
            conversation_id=other, workspace_id=WORKSPACE,
        ))


def test_an_invalid_request_is_refused_without_a_store_read() -> None:
    class _NoReadStore:
        def __init__(self) -> None:
            self.reads = 0

        async def get_claw_run(self, user_id, run_id):
            self.reads += 1
            return None

    store = _NoReadStore()
    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id="", run_id=RUN_ID, outcome=None,
    ))
    assert verdict.status == CORRELATION_INVALID_REQUEST
    assert store.reads == 0


def test_a_stored_run_without_an_execution_result_is_not_correlated() -> None:
    """Looking the run up is not the same as correlating an executed run."""
    store = _store()
    conversation_id = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=RUN_ID, workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))

    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OWNER, run_id=RUN_ID, outcome=None,
    ))

    assert verdict.status == CORRELATION_RUN_ONLY
    assert verdict.correlated is False
    # The owner-scoped linkage is still reported, only the executed-run
    # correlation is unproven.
    assert verdict.conversation_id == conversation_id
    assert verdict.workspace_id == WORKSPACE


def test_a_row_without_a_conversation_link_is_not_correlated() -> None:
    store = _store()
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=RUN_ID, channel="web", action="pc_drive_query",
        title="PC 드라이브 조회: 링크 없음", status="pending",
        conversation_id=None, workspace_id=WORKSPACE,
    ))
    outcome = _run_assembly(RUN_ID)

    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OWNER, run_id=RUN_ID, outcome=outcome,
    ))

    assert verdict.status == CORRELATION_LINK_MISSING
    assert verdict.correlated is False
    assert verdict.conversation_id is None


def test_a_row_without_a_workspace_link_is_not_correlated() -> None:
    store = _store()
    conversation_id = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id="chat_pcq_5151ws", workspace_id=WORKSPACE,
        user_text=INPUT_TEXT, conversation_id=None,
    ))
    # A run row that links the conversation but carries no workspace: the
    # existing contract keeps a staged run's workspace immutable, so this row
    # is written without one from the start.
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id="chat_pcq_5151nows", channel="web",
        action="pc_drive_query", title="PC 드라이브 조회: 워크스페이스 없음",
        status="pending", conversation_id=conversation_id, workspace_id=None,
    ))
    outcome = _run_assembly("chat_pcq_5151nows")

    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=store, user_id=OWNER, run_id="chat_pcq_5151nows", outcome=outcome,
    ))

    assert verdict.status == CORRELATION_LINK_MISSING
    assert verdict.correlated is False
    assert verdict.workspace_id is None


def test_a_row_for_another_run_is_refused() -> None:
    """The returned row must be the requested run."""

    class _OtherRunStore:
        async def get_claw_run(self, user_id, run_id):
            return {
                "run_id": "chat_pcq_someotherrun",
                "conversation_id": "chat_" + "b" * 32,
                "workspace_id": WORKSPACE,
            }

    outcome = _run_assembly(RUN_ID)
    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=_OtherRunStore(), user_id=OWNER, run_id=RUN_ID, outcome=outcome,
    ))
    assert verdict.status == CORRELATION_RUN_MISMATCH
    assert verdict.correlated is False
    assert verdict.conversation_id is None


@pytest.mark.parametrize("row_run_id", [None, ""])
def test_a_row_without_a_usable_run_id_is_refused(row_run_id) -> None:
    """A missing or empty run id cannot prove which run the row is."""

    class _UnusableRunIdStore:
        async def get_claw_run(self, user_id, run_id):
            return {
                "run_id": row_run_id,
                "conversation_id": "chat_" + "b" * 32,
                "workspace_id": WORKSPACE,
            }

    outcome = _run_assembly(RUN_ID)
    verdict = asyncio.run(verify_pc_query_run_correlation(
        store=_UnusableRunIdStore(), user_id=OWNER, run_id=RUN_ID, outcome=outcome,
    ))
    assert verdict.status == CORRELATION_RUN_MISMATCH
    assert verdict.correlated is False
    assert verdict.conversation_id is None
