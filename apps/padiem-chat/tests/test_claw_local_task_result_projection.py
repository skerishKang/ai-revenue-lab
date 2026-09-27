"""#3139 — the bounded Local Runner terminal result returns to its Claw conversation.

Real-path integration. Nothing under test is faked except the two injected
boundaries that are boundaries by design:

* the **result port** is the injected read of the canonical broker, bound here
  to the *real* `StateBackedLocalAgentBrokerAuthority` over its serialized wire
  state, so every terminal fact is the canonical one;
* the **D1 handle** is a real SQLite database with the app's own migrations
  applied, so the messages primary key, the conversation-ownership join and the
  guarded run update all execute for real.

What runs for real: the broker's enqueue -> admit -> acknowledge and
reconcile-expired lifecycles, the `D1HistoryStore` conversation and run writes,
and the projection module.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import sqlite3
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "padiem-control-plane"))

from app.claw_local_task_result_projection import (  # noqa: E402
    LocalRunnerTerminalObservation,
    LocalTaskResultError,
    project_local_runner_terminal_result,
    result_message_id,
)
from app.history import D1HistoryStore, HistoryError, HistoryForbidden  # noqa: E402
from padiem_control_plane.local_agent_broker import BrokerCommandState  # noqa: E402
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority  # noqa: E402
from padiem_control_plane.local_agent_broker_state_wire import (  # noqa: E402
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
PEPPER = b"local-task-result-projection-pepper"
CREDENTIAL = b"local-task-result-device-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.3139.test.v1"
BINDING_REF = "binding.3139.1"
ACCOUNT = "account.3139.1"
WORKSPACE = "workspace.3139.1"
OTHER_WORKSPACE = "workspace.3139.other"
CRED_B64 = base64.b64encode(CREDENTIAL).decode("ascii")
OWNER_SUBJECT = "owner-3139"
OTHER_SUBJECT = "other-3139"
FINGERPRINT = "b" * 64
COMMAND_TTL = 300


class _Statement:
    def __init__(self, connection, sql):
        self._connection = connection
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values):
        self._values = values
        return self

    async def run(self):
        # The app reads a SELECT through `run()` and expects D1's result shape:
        # rows under `results`, affected rows under `meta.rows_written`.
        cursor = self._connection.execute(self._sql, self._values)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        if columns:
            rows = cursor.fetchall()
            return {"results": [dict(zip(columns, row)) for row in rows], "meta": {"rows_written": 0}}
        return {"results": [], "meta": {"rows_written": cursor.rowcount if cursor.rowcount >= 0 else 0}}

    async def first(self):
        # D1's `first()` resolves to the single row itself, not a result object.
        cursor = self._connection.execute(self._sql, self._values)
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
        return dict(zip(columns, rows[0])) if rows else None

    async def all(self):
        # D1 shapes a multi-row result as an object carrying `results`, and the
        # store's reader depends on that, so the adapter must match it.
        cursor = self._connection.execute(self._sql, self._values)
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
        return {"results": [dict(zip(columns, row)) for row in rows], "meta": {"rows_written": 0}}


class _SqliteD1:
    """A D1-shaped handle over a real SQLite file.

    `batch` is the call the exactly-once claim rests on, and D1 applies a batch
    as one unit, so this wraps it in BEGIN / COMMIT and rolls the whole unit
    back on any failure.
    """

    def __init__(self, path: Path):
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._path = path
        self.statements: list[str] = []

    def prepare(self, sql):
        self.statements.append(sql)
        return _Statement(self._connection, sql)

    async def batch(self, statements):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self._connection.execute(statement._sql, statement._values)
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if columns else []
                if columns:
                    results.append({"results": [dict(zip(columns, row)) for row in rows]})
                else:
                    results.append({"meta": {"rows_written": cursor.rowcount if cursor.rowcount >= 0 else 0}})
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")
        return results

    def close(self):
        self._connection.close()


def _open_database(path: Path, *, migrate: bool = True) -> _SqliteD1:
    db = _SqliteD1(path)
    if migrate:
        for migration in sorted((APP_ROOT / "migrations").glob("*.sql")):
            db._connection.executescript(migration.read_text(encoding="utf-8"))
    return db


class _BrokerResultPort:
    """The injected boundary: a read of the real canonical broker state."""

    def __init__(self, state_port):
        self._state_port = state_port
        self.calls: list[str] = []

    async def command_result(self, *, command_id: str):
        self.calls.append(command_id)
        snapshot = self._state_port.load(authority_ref=AUTHORITY_REF).snapshot
        command = next((item for item in snapshot.commands if item.command_id == command_id), None)
        if command is None or command.state not in {
            BrokerCommandState.ACKNOWLEDGED,
            BrokerCommandState.EXPIRED,
        }:
            return None
        return LocalRunnerTerminalObservation(
            command_id=command.command_id,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            request_id=command.request_id or f"request.{command.command_id}",
            revision_ref=command.revision_ref,
            evidence_ref=command.evidence_ref,
            request_fingerprint=command.request_fingerprint,
            sequence=command.sequence,
            state=command.state.value,
            termination=command.termination,
            exit_code=command.exit_code,
            acknowledged_at=command.acknowledged_at.isoformat() if command.acknowledged_at else None,
        )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _accounts(history) -> dict[str, str]:
    """Both accounts exist before any conversation: the D1 foreign keys are real.

    The user id is whatever the existing authority derives from the subject; this
    test never invents one.
    """

    resolved = {}
    for subject, email in ((OWNER_SUBJECT, "owner@example.test"), (OTHER_SUBJECT, "other@example.test")):
        profile = _run(history.upsert_google_user(subject, email, f"user {subject}", ""))
        resolved[subject] = profile.id
    return resolved


def _new_broker() -> tuple[StateBackedLocalAgentBrokerAuthority, SerializedLocalAgentBrokerStatePort]:
    state_port = SerializedLocalAgentBrokerStatePort(
        backend=InMemorySerializedLocalAgentBrokerStateBackend()
    )
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state_port,
    )
    authority.register_binding(
        binding_ref=BINDING_REF,
        device_id="device.3139.1",
        account_ref=ACCOUNT,
        workspace_ref=WORKSPACE,
        credential=CREDENTIAL,
        now=BASE,
    )
    authority.open_session(
        session_id="session.3139.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        account_ref=ACCOUNT,
        workspace_ref=WORKSPACE,
        now=BASE + timedelta(seconds=1),
    )
    return authority, state_port


def _enqueue(authority, *, command_id: str, run_id: str, at: datetime) -> None:
    authority.enqueue_command(
        command_id=command_id,
        binding_ref=BINDING_REF,
        run_id=run_id,
        tool_request_ref=f"tool.{command_id}",
        request_fingerprint=FINGERPRINT,
        now=at,
        ttl_seconds=COMMAND_TTL,
    )


def _admit(authority, *, command_id: str, run_id: str, at: datetime):
    return authority.admit_command(
        admission_ref=f"admission.{command_id}",
        evidence_ref=f"evidence.{command_id}",
        session_id="session.3139.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id=command_id,
        request_fingerprint=FINGERPRINT,
        request_id=f"request.{command_id}",
        now=at,
    )


def _acknowledge(authority, command_id, admission, *, at: datetime) -> None:
    authority.acknowledge(
        session_id="session.3139.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id=command_id,
        admission_ref=admission.admission_ref,
        evidence_ref=admission.evidence_ref,
        revision_ref=admission.revision_ref,
        termination="exited",
        request_id=admission.request_id,
        exit_code=0,
        now=at,
    )


def _conversation_with_run(history, *, owner: str, run_id: str, workspace_id: str = WORKSPACE) -> str:
    conversation_id = _run(history.append_exchange(owner, None, "로컬 러너로 이 작업을 실행해줘", "알겠습니다"))
    _run(
        history.record_claw_run(
            user_id=owner,
            run_id=run_id,
            channel="web",
            action="local_runner_task",
            title="bounded local task",
            status="running",
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
    )
    return conversation_id


def _messages(history, conversation_id: str) -> list[dict]:
    return _run(
        history._all(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY sequence_number ASC",
            conversation_id,
        )
    )


@pytest.fixture()
def harness(tmp_path):
    authority, state_port = _new_broker()
    database_path = tmp_path / "chat.sqlite3"
    db = _open_database(database_path)
    history = D1HistoryStore(db)
    yield authority, state_port, history, database_path, _BrokerResultPort(state_port), _accounts(history)
    db.close()


def test_acknowledged_result_is_projected_once_into_the_originating_conversation(harness):
    authority, state_port, history, database_path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.3139.1", run_id="run.3139.1", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.3139.1", run_id="run.3139.1", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.3139.1", admission, at=BASE + timedelta(seconds=4))

    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.3139.1")
    before = len(_messages(history, conversation_id))

    decision = _run(
        project_local_runner_terminal_result(
            history=history,
            result_port=port,
            user_id=owner,
            run_id="run.3139.1",
            command_id="command.3139.1",
            expected_workspace_id=WORKSPACE,
        )
    )

    assert decision.append is True
    assert decision.status == "completed"
    after = _messages(history, conversation_id)
    assert len(after) == before + 1
    projected = after[-1]
    assert projected["role"] == "assistant"
    assert "exited" in projected["content"]
    # Bounded correlation and outcome only, never command material.
    assert "argv" not in projected["content"]
    assert "stdout" not in projected["content"]
    assert CREDENTIAL.decode() not in projected["content"]
    assert CRED_B64 not in projected["content"]

    # An exact retry of the same observation appends nothing.
    retry = _run(
        project_local_runner_terminal_result(
            history=history,
            result_port=port,
            user_id=owner,
            run_id="run.3139.1",
            command_id="command.3139.1",
        )
    )
    assert retry.append is False
    assert len(_messages(history, conversation_id)) == before + 1

    # A restart reread — a brand new store over the same durable file — also appends nothing.
    reopened = _open_database(database_path, migrate=False)
    restarted_store = D1HistoryStore(reopened)
    restarted = _run(
        project_local_runner_terminal_result(
            history=restarted_store,
            result_port=port,
            user_id=owner,
            run_id="run.3139.1",
            command_id="command.3139.1",
        )
    )
    assert restarted.append is False
    assert len(_messages(restarted_store, conversation_id)) == before + 1
    reopened.close()


def test_expired_result_reports_no_execution_and_fabricates_nothing(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.3139.2", run_id="run.3139.2", at=BASE + timedelta(seconds=2))
    _admit(authority, command_id="command.3139.2", run_id="run.3139.2", at=BASE + timedelta(seconds=3))
    revision_ref = next(
        item.revision_ref
        for item in state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands
        if item.command_id == "command.3139.2"
    )
    authority.reconcile_expired_command(
        session_id="session.3139.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id="command.3139.2",
        admission_ref="admission.command.3139.2",
        revision_ref=revision_ref,
        request_id="request.command.3139.2",
        request_fingerprint=FINGERPRINT,
        termination=None,
        exit_code=None,
        now=BASE + timedelta(seconds=COMMAND_TTL + 10),
    )
    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.3139.2")
    before = len(_messages(history, conversation_id))

    decision = _run(
        project_local_runner_terminal_result(
            history=history,
            result_port=port,
            user_id=owner,
            run_id="run.3139.2",
            command_id="command.3139.2",
        )
    )

    assert decision.append is True
    assert decision.status == "expired"
    content = _messages(history, conversation_id)[-1]["content"]
    assert "exited" not in content
    assert "종료 코드" not in content
    assert "기한 만료" in content


def test_foreign_run_workspace_and_account_fail_closed(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    other = accounts[OTHER_SUBJECT]
    _enqueue(authority, command_id="command.3139.3", run_id="run.3139.3", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.3139.3", run_id="run.3139.3", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.3139.3", admission, at=BASE + timedelta(seconds=4))

    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.3139.3")
    before = len(_messages(history, conversation_id))

    # Another account can neither read nor project into this run.
    with pytest.raises(HistoryForbidden):
        _run(
            project_local_runner_terminal_result(
                history=history,
                result_port=port,
                user_id=other,
                run_id="run.3139.3",
                command_id="command.3139.3",
            )
        )
    assert len(_messages(history, conversation_id)) == before

    # A caller expecting a different workspace is refused.
    with pytest.raises(LocalTaskResultError) as mismatch:
        _run(
            project_local_runner_terminal_result(
                history=history,
                result_port=port,
                user_id=owner,
                run_id="run.3139.3",
                command_id="command.3139.3",
                expected_workspace_id=OTHER_WORKSPACE,
            )
        )
    assert mismatch.value.code == "local_task_result_workspace_mismatch"
    assert len(_messages(history, conversation_id)) == before

    # A command that belongs to a different run never projects into this one.
    _enqueue(authority, command_id="command.3139.other", run_id="run.3139.other", at=BASE + timedelta(seconds=6))
    other_admission = _admit(
        authority, command_id="command.3139.other", run_id="run.3139.other", at=BASE + timedelta(seconds=7)
    )
    _acknowledge(authority, "command.3139.other", other_admission, at=BASE + timedelta(seconds=8))
    with pytest.raises(LocalTaskResultError) as wrong_run:
        _run(
            project_local_runner_terminal_result(
                history=history,
                result_port=port,
                user_id=owner,
                run_id="run.3139.3",
                command_id="command.3139.other",
            )
        )
    assert wrong_run.value.code == "local_task_result_run_mismatch"
    assert len(_messages(history, conversation_id)) == before


def test_a_projected_run_cannot_be_rewritten_with_a_different_outcome(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.3139.4", run_id="run.3139.4", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.3139.4", run_id="run.3139.4", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.3139.4", admission, at=BASE + timedelta(seconds=4))
    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.3139.4")
    before = len(_messages(history, conversation_id))

    _run(
        project_local_runner_terminal_result(
            history=history,
            result_port=port,
            user_id=owner,
            run_id="run.3139.4",
            command_id="command.3139.4",
        )
    )
    assert len(_messages(history, conversation_id)) == before + 1
    projected = _run(history.get_claw_run(owner, "run.3139.4"))
    assert projected["status"] == "completed"
    assert projected["result_summary"] == "exited/0"

    # A later, contradictory outcome for the same run is refused outright, and
    # the already-projected message is left alone.
    with pytest.raises(HistoryError):
        _run(
            history.append_local_task_result(
                user_id=owner,
                run_id="run.3139.4",
                message_id="msg_ltr_contradiction",
                summary="expired/no-result",
                content="contradictory result",
                status="expired",
            )
        )
    assert len(_messages(history, conversation_id)) == before + 1
    unchanged = _run(history.get_claw_run(owner, "run.3139.4"))
    assert unchanged["result_summary"] == "exited/0"
    assert unchanged["status"] == "completed"


def test_the_destination_conversation_is_server_owned(tmp_path):
    """The caller never names a conversation: the origin run row does."""

    db = _open_database(tmp_path / "chat.sqlite3")
    history = D1HistoryStore(db)
    owner = _accounts(history)[OWNER_SUBJECT]
    conversation_id = _run(history.append_exchange(owner, None, "hello", "hi"))
    _run(
        history.record_claw_run(
            user_id=owner,
            run_id="run.owned.1",
            channel="web",
            action="local_runner_task",
            title="task",
            status="running",
            conversation_id=conversation_id,
        )
    )
    observation = LocalRunnerTerminalObservation(
        command_id="command.owned.1",
        run_id="run.owned.1",
        tool_request_ref="tool.owned.1",
        request_id="request.owned.1",
        revision_ref="rev.owned.1",
        evidence_ref="evidence.owned.1",
        request_fingerprint=FINGERPRINT,
        sequence=1,
        state="acknowledged",
        termination="exited",
        exit_code=0,
    )

    class _Port:
        async def command_result(self, *, command_id):
            return observation if command_id == observation.command_id else None

    decision = _run(
        project_local_runner_terminal_result(
            history=history,
            result_port=_Port(),
            user_id=owner,
            run_id="run.owned.1",
            command_id="command.owned.1",
        )
    )
    assert decision.append is True
    # The deterministic id comes from the ORIGIN conversation, never a caller input.
    assert decision.message_id == result_message_id(
        conversation_id=conversation_id,
        command_id="command.owned.1",
        revision_ref="rev.owned.1",
    )
    assert len(_messages(history, conversation_id)) == 3
    db.close()


def test_a_run_without_an_originating_conversation_fails_closed(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.3139.5", run_id="run.3139.5", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.3139.5", run_id="run.3139.5", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.3139.5", admission, at=BASE + timedelta(seconds=4))
    _run(
        history.record_claw_run(
            user_id=owner,
            run_id="run.3139.5",
            channel="web",
            action="local_runner_task",
            title="orphan run",
            status="running",
        )
    )
    with pytest.raises(LocalTaskResultError) as no_origin:
        _run(
            project_local_runner_terminal_result(
                history=history,
                result_port=port,
                user_id=owner,
                run_id="run.3139.5",
                command_id="command.3139.5",
            )
        )
    assert no_origin.value.code == "local_task_result_no_origin"


def test_a_non_terminal_command_projects_nothing_yet(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.3139.6", run_id="run.3139.6", at=BASE + timedelta(seconds=2))
    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.3139.6")
    before = len(_messages(history, conversation_id))

    decision = _run(
        project_local_runner_terminal_result(
            history=history,
            result_port=port,
            user_id=owner,
            run_id="run.3139.6",
            command_id="command.3139.6",
        )
    )
    assert decision.append is False
    assert decision.reason == "no canonical terminal result is available yet"
    assert len(_messages(history, conversation_id)) == before


def test_an_expired_observation_cannot_carry_an_execution_outcome():
    with pytest.raises(LocalTaskResultError) as fabricated:
        LocalRunnerTerminalObservation(
            command_id="command.fabricated.1",
            run_id="run.fabricated.1",
            tool_request_ref="tool.1",
            request_id="request.1",
            revision_ref="rev.1",
            evidence_ref="evidence.1",
            request_fingerprint=FINGERPRINT,
            sequence=1,
            state="expired",
            termination="exited",
            exit_code=0,
        )
    assert fabricated.value.code == "local_task_result_fabricated_execution"


def test_source_truth_keeps_the_projection_local_and_bounded():
    from app import claw_local_task_result_projection as module

    assert module.CANONICAL_TERMINAL_RESULT_CONSUMER is True
    assert module.SERVER_OWNED_ORIGIN_CORRELATION is True
    assert module.ORIGIN_CONVERSATION_CHOSEN_BY_CALLER is False
    assert module.ORIGIN_CONVERSATION_READ_FROM_RUN_ROW is True
    assert module.DUPLICATE_APPEND_SUPPRESSED_BY_STORE is True
    assert module.EXPIRED_FABRICATES_EXECUTION is False
    assert module.RAW_MATERIAL_IN_PROJECTION is False
    assert module.SECOND_CONVERSATION_AUTHORITY is False
    assert module.SECOND_RESULT_AUTHORITY is False
    assert module.BROKER_COMMAND_AUTHORITY is False
    assert module.BROKER_STATE_WRITTEN is False
    assert module.DEVICE_LIFECYCLE_PROJECTION_TOUCHED is False
    assert module.PRODUCTION_MUTATION is False
    assert module.PRODUCTION_READY is False
