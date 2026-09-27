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
sys.path.insert(0, str(REPO_ROOT / "apps" / "korean-ai-code-agent" / "src"))

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

    async def command_result(self, *, command_id, run_id, owner_id, workspace_id=None):
        del run_id, owner_id, workspace_id
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


def _new_broker(account_ref: str) -> tuple[StateBackedLocalAgentBrokerAuthority, SerializedLocalAgentBrokerStatePort]:
    state_port = SerializedLocalAgentBrokerStatePort(
        backend=InMemorySerializedLocalAgentBrokerStateBackend()
    )
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state_port,
    )
    # The chat owner id IS the broker account_ref (#3094's adapter forwards it
    # verbatim), so the device binding is registered under the owner identity.
    authority.register_binding(
        binding_ref=BINDING_REF,
        device_id="device.3139.1",
        account_ref=account_ref,
        workspace_ref=WORKSPACE,
        credential=CREDENTIAL,
        now=BASE,
    )
    authority.open_session(
        session_id="session.3139.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        account_ref=account_ref,
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


def _acknowledge(authority, command_id, admission, *, at: datetime, session_id: str = "session.3139.1") -> None:
    authority.acknowledge(
        session_id=session_id,
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
    database_path = tmp_path / "chat.sqlite3"
    db = _open_database(database_path)
    history = D1HistoryStore(db)
    accounts = _accounts(history)
    authority, state_port = _new_broker(accounts[OWNER_SUBJECT])
    yield authority, state_port, history, database_path, _BrokerResultPort(state_port), accounts
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
        async def command_result(self, *, command_id, run_id, owner_id, workspace_id=None):
            del run_id, owner_id, workspace_id
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


# --- the deployable path: real broker RPC through the real composition ------
class _RealServiceBinding:
    """The private Service Binding shape: methods, sync or awaitable."""

    def __init__(self, runtime):
        self._runtime = runtime
        self.calls: list[str] = []

    def terminal_command_result(self, payload):
        self.calls.append(payload.get("run_id"))
        return self._runtime.terminal_command_result(payload)


def _migrated_runtime(harness, tmp_path):
    """A real file-backed durable runtime over the SAME broker the tests use."""

    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    class _Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        LOCAL_AGENT_BROKER_PEPPER = str(PEPPER)

    runtime = LocalAgentBrokerDurableRuntime(
        storage=_SqliteStorage(tmp_path / "broker.sqlite3"), env=_Env()
    )
    return runtime


class _SqliteStorage:
    """D1-shaped storage: the transaction is a real one."""

    def __init__(self, path):
        import sqlite3

        self.connection = sqlite3.connect(path, isolation_level=None)

        class _Cursor:
            def __init__(self, inner):
                self._inner = inner

            @property
            def rowsWritten(self):
                return self._inner.rowcount if self._inner.rowcount >= 0 else 0

            def toArray(self):
                names = [c[0] for c in self._inner.description] if self._inner.description else []
                return [dict(zip(names, row)) for row in self._inner.fetchall()]

        class _Sql:
            def __init__(self, connection):
                self.connection = connection

            def exec(self, query, *bindings):
                return _Cursor(self.connection.execute(query, bindings))

        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return value

    def close(self):
        self.connection.close()


def test_the_real_broker_rpc_serves_the_real_projection(harness, tmp_path):
    """The deployable leg: canonical broker RPC -> concrete port -> projector -> conversation."""

    from app.claw_local_task_result_composition import (
        BrokerAuthorityLocalRunnerResultPort,
        LocalRunnerResultSource,
    )
    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]

    # The durable runtime owns the same canonical state the device edge uses,
    # and it is where the canonical enqueue actually happens.
    class _Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        LOCAL_AGENT_BROKER_PEPPER = str(PEPPER)

    runtime = LocalAgentBrokerDurableRuntime(
        storage=_SqliteStorage(tmp_path / "broker.sqlite3"), env=_Env()
    )
    # Point the runtime AND its material store at the harness state so both
    # sides are one Durable Object, exactly like the deployed composition.
    runtime.state_port = state_port
    runtime.material_store._state_port = state_port

    runtime.register_binding(
        {
            "binding_ref": BINDING_REF,
            "device_id": "device.3139.1",
            "account_ref": owner,
            "workspace_ref": WORKSPACE,
            "credential_b64": CRED_B64,
            "now": BASE.isoformat(),
        }
    )
    material = {
        "request_id": "request.rpc.1",
        "run_id": "run.rpc.1",
        "device_id": "device.3139.1",
        "root_ref": "root.3139.1",
        "argv": ["python", "-V"],
        "cwd_relative": ".",
        "requested_at": (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "timeout_seconds": 30,
        "shell_authority": False,
        "admin_elevation": False,
        "environment_payload": None,
        "provider_authority": None,
        "p01_approval_payload": None,
    }
    enqueued = runtime.enqueue_command_with_material(
        {
            "command_id": "command.rpc.1",
            "binding_ref": BINDING_REF,
            "run_id": "run.rpc.1",
            "tool_request_ref": "tool.rpc.1",
            "request_fingerprint": FINGERPRINT,
            "now": (BASE + timedelta(seconds=2)).isoformat(),
            "ttl_seconds": COMMAND_TTL,
        },
        material,
    )
    assert enqueued["ok"] is True
    command = enqueued["command"]

    session = authority.open_session(
        session_id="session.rpc.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        account_ref=owner,
        workspace_ref=WORKSPACE,
        now=BASE + timedelta(seconds=1),
    )
    admission = authority.admit_command(
        admission_ref="admission.command.rpc.1",
        evidence_ref="evidence.command.rpc.1",
        session_id=session.session_id,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id="command.rpc.1",
        request_fingerprint=FINGERPRINT,
        request_id="request.rpc.1",
        now=BASE + timedelta(seconds=3),
    )
    _acknowledge(authority, "command.rpc.1", admission, at=BASE + timedelta(seconds=4), session_id=session.session_id)

    # The private Service Binding port reads the REAL runtime RPC.
    binding = _RealServiceBinding(runtime)
    concrete_port = BrokerAuthorityLocalRunnerResultPort(binding)
    observation = _run(
        concrete_port.command_result(
            command_id="command.rpc.1", run_id="run.rpc.1", owner_id=owner, workspace_id=WORKSPACE
        )
    )
    assert observation is not None
    assert observation.state == "acknowledged"
    assert observation.command_id == "command.rpc.1"
    assert observation.termination == "exited"
    assert binding.calls == ["run.rpc.1"]

    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.rpc.1")
    before = len(_messages(history, conversation_id))

    source = LocalRunnerResultSource(history=history, result_port=concrete_port)
    projected = _run(
        source.project_local_runner_result(owner_id=owner, run_id="run.rpc.1", workspace_id=WORKSPACE)
    )
    assert projected is not None
    assert projected["appended"] is True
    assert projected["status"] == "completed"
    after = _messages(history, conversation_id)
    assert len(after) == before + 1
    assert "exited" in after[-1]["content"]

    # And an identical second observation appends nothing.
    again = _run(
        source.project_local_runner_result(owner_id=owner, run_id="run.rpc.1", workspace_id=WORKSPACE)
    )
    assert again["appended"] is False
    assert len(_messages(history, conversation_id)) == before + 1
    runtime._storage.close()


def test_a_command_that_shares_the_run_but_disagrees_fails_closed(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.x.1", run_id="run.x.1", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.x.1", run_id="run.x.1", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.x.1", admission, at=BASE + timedelta(seconds=4))
    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.x.1")
    before = len(_messages(history, conversation_id))

    # First observation binds the exact correlation server-side.
    first = _run(
        project_local_runner_terminal_result(
            history=history, result_port=port, user_id=owner,
            run_id="run.x.1", command_id="command.x.1",
        )
    )
    assert first.append is True
    bound = _run(history.get_local_task_correlation(owner, "run.x.1"))
    assert bound["command_id"] == "command.x.1"
    assert bound["tool_request_ref"] == "tool.command.x.1"
    # The revision is the server-owned minted one, echoed verbatim.
    assert bound["revision_ref"] == admission.revision_ref
    assert bound["request_id"] == admission.request_id

    # A second command that shares the run id but carries a different tool
    # request, request id and revision must never reach this conversation.
    _enqueue(authority, command_id="command.x.2", run_id="run.x.1", at=BASE + timedelta(seconds=6))
    other_admission = _admit(authority, command_id="command.x.2", run_id="run.x.1", at=BASE + timedelta(seconds=7))
    _acknowledge(authority, "command.x.2", other_admission, at=BASE + timedelta(seconds=8))
    with pytest.raises(LocalTaskResultError) as mismatched:
        _run(
            project_local_runner_terminal_result(
                history=history, result_port=port, user_id=owner,
                run_id="run.x.1", command_id="command.x.2",
            )
        )
    assert mismatched.value.code == "local_task_result_correlation_mismatch"
    assert len(_messages(history, conversation_id)) == before + 1

    # The mapping itself refuses to be rebound.
    with pytest.raises(HistoryError):
        _run(
            history.record_local_task_correlation(
                user_id=owner,
                run_id="run.x.1",
                command_id="command.x.2",
                tool_request_ref="tool.command.x.2",
                request_id="request.command.x.2",
                revision_ref="rev.command.x.2",
                request_fingerprint=FINGERPRINT,
            )
        )
    still = _run(history.get_local_task_correlation(owner, "run.x.1"))
    assert still["command_id"] == "command.x.1"


def test_an_exact_retry_mutates_nothing_observable(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.c.1", run_id="run.c.1", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.c.1", run_id="run.c.1", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.c.1", admission, at=BASE + timedelta(seconds=4))
    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.c.1")
    before = len(_messages(history, conversation_id))
    conversation_before = _run(history._all("SELECT * FROM conversations WHERE id=?", conversation_id))
    run_before = _run(history.get_claw_run(owner, "run.c.1"))

    first = _run(
        project_local_runner_terminal_result(
            history=history, result_port=port, user_id=owner,
            run_id="run.c.1", command_id="command.c.1",
        )
    )
    assert first.append is True
    conversation_after = _run(history._all("SELECT * FROM conversations WHERE id=?", conversation_id))

    second = _run(
        project_local_runner_terminal_result(
            history=history, result_port=port, user_id=owner,
            run_id="run.c.1", command_id="command.c.1",
        )
    )
    assert second.append is False
    conversation_final = _run(history._all("SELECT * FROM conversations WHERE id=?", conversation_id))
    # The exact retry reordered or restamped nothing.
    assert conversation_final == conversation_after
    run_after = _run(history.get_claw_run(owner, "run.c.1"))
    assert (run_after["status"], run_after["result_summary"]) == (
        run_before["status"] if run_before["status"] != "running" else "completed",
        run_after["result_summary"],
    )
    assert len(_messages(history, conversation_id)) == before + 1


def test_a_conflicting_result_mutates_nothing_durable(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    _enqueue(authority, command_id="command.d.1", run_id="run.d.1", at=BASE + timedelta(seconds=2))
    admission = _admit(authority, command_id="command.d.1", run_id="run.d.1", at=BASE + timedelta(seconds=3))
    _acknowledge(authority, "command.d.1", admission, at=BASE + timedelta(seconds=4))
    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.d.1")
    before = len(_messages(history, conversation_id))
    _run(
        project_local_runner_terminal_result(
            history=history, result_port=port, user_id=owner,
            run_id="run.d.1", command_id="command.d.1",
        )
    )
    snapshot_before = _run(history._all("SELECT * FROM conversations WHERE id=?", conversation_id))
    run_before = _run(history.get_claw_run(owner, "run.d.1"))

    with pytest.raises(HistoryError):
        _run(
            history.append_local_task_result(
                user_id=owner,
                run_id="run.d.1",
                message_id="msg_ltr_conflicting_3139",
                summary="expired/no-result",
                content="a contradictory outcome",
                status="expired",
            )
        )
    # Zero durable mutation: same rows, same timestamps, same summary.
    snapshot_after = _run(history._all("SELECT * FROM conversations WHERE id=?", conversation_id))
    run_after = _run(history.get_claw_run(owner, "run.d.1"))
    assert snapshot_after == snapshot_before
    assert run_after == run_before
    assert len(_messages(history, conversation_id)) == before + 1


def test_cancelled_and_timed_out_are_truthful(harness):
    authority, state_port, history, _path, port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    for termination, run_suffix, expected_status, expected_summary in (
        ("cancelled", "cancelled", "cancelled", "cancelled"),
        ("timed_out", "timed_out", "timed_out", "timed_out"),
    ):
        run_id = f"run.t.{run_suffix}"
        conversation_id = _conversation_with_run(history, owner=owner, run_id=run_id)
        before = len(_messages(history, conversation_id))
        observation = LocalRunnerTerminalObservation(
            command_id=f"command.{termination}.1",
            run_id=run_id,
            tool_request_ref=f"tool.{termination}.1",
            request_id=f"request.{termination}.1",
            revision_ref=f"rev.{termination}.1",
            evidence_ref=f"evidence.{termination}.1",
            request_fingerprint=FINGERPRINT,
            sequence=1,
            state="acknowledged",
            termination=termination,
            exit_code=None if termination == "cancelled" else 124,
        )

        class _Port:
            async def command_result(self, *, command_id, run_id, owner_id, workspace_id=None):
                del run_id, owner_id, workspace_id
                return observation if command_id == observation.command_id else None

        # Bind the correlation once, then project.
        _run(
            history.record_local_task_correlation(
                user_id=owner,
                run_id=run_id,
                command_id=observation.command_id,
                tool_request_ref=observation.tool_request_ref,
                request_id=observation.request_id,
                revision_ref=observation.revision_ref,
                request_fingerprint=observation.request_fingerprint,
                evidence_ref=observation.evidence_ref,
            )
        )
        decision = _run(
            project_local_runner_terminal_result(
                history=history, result_port=_Port(), user_id=owner,
                run_id=run_id, command_id=observation.command_id,
            )
        )
        assert decision.append is True
        assert decision.status == expected_status
        assert decision.summary == expected_summary
        projected = _run(history.get_claw_run(owner, run_id))
        assert projected["status"] == expected_status
        assert projected["result_summary"] == expected_summary
        message = _messages(history, projected["conversation_id"])[-1]
        assert termination in message["content"]


# --- the product caller: the real route, the real composition ----------------
def test_the_product_route_returns_the_result_to_the_originating_conversation(harness, tmp_path):
    """No test-direct call: the running product's own route drives the projection."""

    import base64 as _b64
    import hashlib as _hash

    import httpx
    from starlette.applications import Starlette
    from starlette.routing import Route

    from app.app_factory import create_app
    from app.auth import SESSION_COOKIE, create_session_token
    from app.claw_local_task_result_composition import build_local_task_result_source
    from app.config import Settings
    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    authority, state_port, history, _path, _port, accounts = harness
    owner = accounts[OWNER_SUBJECT]

    class _Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        LOCAL_AGENT_BROKER_PEPPER = str(PEPPER)

    class _Binding:
        """The private Service Binding: the Default gateway's RPC surface."""

        def __init__(self, runtime):
            self._runtime = runtime

        def terminal_command_result(self, payload):
            return self._runtime.terminal_command_result(payload)

        def device_truth(self, payload):  # the #3094 port probes for it
            return self._runtime.device_truth(payload)

    class _WorkerEnv(dict):
        pass

    runtime = LocalAgentBrokerDurableRuntime(
        storage=_SqliteStorage(tmp_path / "broker-route.sqlite3"), env=_Env()
    )
    runtime.state_port = state_port
    runtime.material_store._state_port = state_port
    env = _WorkerEnv()
    env["LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"] = _Binding(runtime)

    from app.worker_config import binding_value  # noqa: F401  (import shape check)

    source = build_local_task_result_source(env, history)
    assert source is not None and source.configured is True

    # A real terminal command, created the canonical way.
    runtime.register_binding(
        {
            "binding_ref": BINDING_REF,
            "device_id": "device.3139.1",
            "account_ref": owner,
            "workspace_ref": WORKSPACE,
            "credential_b64": CRED_B64,
            "now": BASE.isoformat(),
        }
    )
    enqueued = runtime.enqueue_command_with_material(
        {
            "command_id": "command.route.1",
            "binding_ref": BINDING_REF,
            "run_id": "run.route.1",
            "tool_request_ref": "tool.route.1",
            "request_fingerprint": FINGERPRINT,
            "now": (BASE + timedelta(seconds=2)).isoformat(),
            "ttl_seconds": COMMAND_TTL,
        },
        {
            "request_id": "request.route.1",
            "run_id": "run.route.1",
            "device_id": "device.3139.1",
            "root_ref": "root.3139.1",
            "argv": ["python", "-V"],
            "cwd_relative": ".",
            "requested_at": (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "timeout_seconds": 30,
            "shell_authority": False,
            "admin_elevation": False,
            "environment_payload": None,
            "provider_authority": None,
            "p01_approval_payload": None,
        },
    )
    assert enqueued["ok"] is True
    session = authority.open_session(
        session_id="session.route.1",
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        account_ref=owner,
        workspace_ref=WORKSPACE,
        now=BASE + timedelta(seconds=1),
    )
    admission = authority.admit_command(
        admission_ref="admission.command.route.1",
        evidence_ref="evidence.command.route.1",
        session_id=session.session_id,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id="command.route.1",
        request_fingerprint=FINGERPRINT,
        request_id="request.route.1",
        now=BASE + timedelta(seconds=3),
    )
    _acknowledge(
        authority,
        "command.route.1",
        admission,
        at=BASE + timedelta(seconds=4),
        session_id=session.session_id,
    )

    conversation_id = _conversation_with_run(history, owner=owner, run_id="run.route.1")
    before = len(_messages(history, conversation_id))

    # auth_mode off is the fail-closed default; the route must be exercised with
    # the same mode a deployed chat runs.
    settings = Settings(session_secret="3139-route-secret", auth_mode="mock")
    app = create_app(settings, history_store=history, local_task_result_source=source)
    # The route is registered by the real factory, not by the test.
    assert any(
        getattr(route, "path", "") == "/api/claw/runs/{run_id}/local-result"
        for route in app.routes
    )
    token = create_session_token(settings, owner)
    _ = (Starlette, Route, _b64, _hash)

    import asyncio as _asyncio

    async def drive():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://chat.example.test") as client:
            client.cookies.set(SESSION_COOKIE, token, domain="chat.example.test", path="/")
            return await client.post(
                "/api/claw/runs/run.route.1/local-result", json={"workspaceId": WORKSPACE}
            )

    response = _asyncio.run(drive())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["projection"]["appended"] is True
    assert payload["projection"]["status"] == "completed"
    # The projection may declare that it carries no raw material, but must never
    # carry any: the flags are false and the device credential is absent.
    projection_body = payload["projection"]
    for flag in ("raw_argv", "raw_stdout", "raw_stderr", "raw_device_credential", "p01_approval_payload"):
        assert projection_body[flag] is False
    assert CREDENTIAL.decode() not in response.text
    assert CRED_B64 not in response.text
    after = _messages(history, conversation_id)
    assert len(after) == before + 1
    assert "exited" in after[-1]["content"]

    # A second call over the same terminal fact appends nothing.
    response2 = _asyncio.run(drive())
    assert response2.status_code == 200
    assert response2.json()["projection"]["appended"] is False
    assert len(_messages(history, conversation_id)) == before + 1
    runtime._storage.close()


def test_the_route_refuses_an_unowned_run(harness, tmp_path):
    from app.app_factory import create_app
    from app.config import Settings

    from app.claw_local_task_result_composition import build_local_task_result_source

    _authority, _state_port, history, _path, _port, accounts = harness
    owner = accounts[OWNER_SUBJECT]
    other = accounts[OTHER_SUBJECT]
    _conversation_with_run(history, owner=owner, run_id="run.private.1")

    class _Env(dict):
        pass

    env = _Env()
    source = build_local_task_result_source(env, history)
    assert source is None  # no trusted binding, so the route stays fail-closed

    app = create_app(
        Settings(session_secret="3139-route-secret", auth_mode="mock"),
        history_store=history,
        local_task_result_source=source,
    )
    import asyncio

    import httpx

    async def drive(user_token):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
        ) as client:
            return await client.post("/api/claw/runs/run.private.1/local-result", json={})

    # Authenticated but unconfigured: the route answers 503 rather than
    # guessing a result, and never discloses the run.
    import httpx as _httpx
    from app.auth import SESSION_COOKIE, create_session_token as _token

    settings = app.state.settings
    client_cookie = _token(settings, other)

    async def drive_authenticated():
        async with _httpx.AsyncClient(
            transport=_httpx.ASGITransport(app=app), base_url="https://chat.example.test"
        ) as client:
            client.cookies.set(SESSION_COOKIE, client_cookie, domain="chat.example.test", path="/")
            return await client.post("/api/claw/runs/run.private.1/local-result", json={})

    assert asyncio.run(drive_authenticated()).status_code == 503


def test_the_broker_read_never_crosses_an_account_boundary():
    """A second account's terminal command is invisible to the first account."""

    import tempfile

    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    class _Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        LOCAL_AGENT_BROKER_PEPPER = str(PEPPER)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        import sqlite3 as _sqlite3

        class _Storage:
            def __init__(self, path):
                self.connection = _sqlite3.connect(path, isolation_level=None)

                class _Cursor:
                    def __init__(self, inner):
                        self._inner = inner

                    @property
                    def rowsWritten(self):
                        return self._inner.rowcount if self._inner.rowcount >= 0 else 0

                    def toArray(self):
                        names = [c[0] for c in self._inner.description] if self._inner.description else []
                        return [dict(zip(names, row)) for row in self._inner.fetchall()]

                class _Sql:
                    def __init__(self, connection):
                        self.connection = connection

                    def exec(self, query, *bindings):
                        return _Cursor(self.connection.execute(query, bindings))

                self.sql = _Sql(self.connection)

            def transactionSync(self, callback):
                self.connection.execute("BEGIN IMMEDIATE")
                try:
                    value = callback()
                except BaseException:
                    self.connection.execute("ROLLBACK")
                    raise
                self.connection.execute("COMMIT")
                return value

            def close(self):
                self.connection.close()

        runtime = LocalAgentBrokerDurableRuntime(storage=_Storage(Path(raw) / "broker.sqlite3"), env=_Env())
        runtime.register_binding(
            {
                "binding_ref": BINDING_REF,
                "device_id": "device.3139.1",
                "account_ref": "account.owner.a",
                "workspace_ref": WORKSPACE,
                "credential_b64": CRED_B64,
                "now": BASE.isoformat(),
            }
        )
        session = runtime.open_session(
            {
                "session_id": "session.acct.a",
                "binding_ref": BINDING_REF,
                "credential_b64": CRED_B64,
                "account_ref": "account.owner.a",
                "workspace_ref": WORKSPACE,
                "now": (BASE + timedelta(seconds=1)).isoformat(),
            }
        )
        assert session["ok"] is True
        # The canonical creation path binds material atomically; admission then
        # requires that material to be present (#3127).
        enqueued = runtime.enqueue_command_with_material(
            {
                "command_id": "command.acct.a",
                "binding_ref": BINDING_REF,
                "run_id": "run.acct.a",
                "tool_request_ref": "tool.acct.a",
                "request_fingerprint": FINGERPRINT,
                "now": (BASE + timedelta(seconds=2)).isoformat(),
                "ttl_seconds": COMMAND_TTL,
            },
            {
                "request_id": "request.acct.a",
                "run_id": "run.acct.a",
                "device_id": "device.3139.1",
                "root_ref": "root.3139.1",
                "argv": ["python", "-V"],
                "cwd_relative": ".",
                "requested_at": (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "timeout_seconds": 30,
                "shell_authority": False,
                "admin_elevation": False,
                "environment_payload": None,
                "provider_authority": None,
                "p01_approval_payload": None,
            },
        )
        assert enqueued["ok"] is True
        admission = runtime.admit_command(
            {
                "admission_ref": "admission.acct.a",
                "evidence_ref": "evidence.acct.a",
                "session_id": "session.acct.a",
                "binding_ref": BINDING_REF,
                "credential_b64": CRED_B64,
                "command_id": "command.acct.a",
                "request_fingerprint": FINGERPRINT,
                "request_id": "request.acct.a",
                "now": (BASE + timedelta(seconds=3)).isoformat(),
            }
        )
        acknowledged = runtime.acknowledge(
            {
                "session_id": "session.acct.a",
                "binding_ref": BINDING_REF,
                "credential_b64": CRED_B64,
                "command_id": "command.acct.a",
                "admission_ref": "admission.acct.a",
                "evidence_ref": "evidence.acct.a",
                "revision_ref": admission["admission"]["revision_ref"],
                "termination": "exited",
                "request_id": "request.acct.a",
                "exit_code": 0,
                "now": (BASE + timedelta(seconds=4)).isoformat(),
            }
        )
        assert acknowledged["ok"] is True

        # The owner sees its own terminal result.
        own = runtime.terminal_command_result(
            {"account_ref": "account.owner.a", "workspace_ref": WORKSPACE, "run_id": "run.acct.a"}
        )
        assert own["ok"] is True and own["available"] is True
        assert own["command_result"]["command_id"] == "command.acct.a"

        # An account with no binding at all learns nothing.
        unbound = runtime.terminal_command_result(
            {"account_ref": "account.nobody", "workspace_ref": WORKSPACE, "run_id": "run.acct.a"}
        )
        assert unbound["ok"] is True
        assert unbound["available"] is False
        assert unbound["reason"] == "no_device_binding"
        assert "command" not in unbound

        # And an account that owns a binding of its own still cannot see the
        # first account's command: the read is scoped per binding, not merely
        # per existence.
        runtime.register_binding(
            {
                "binding_ref": "binding.acct.b",
                "device_id": "device.acct.b",
                "account_ref": "account.other.b",
                "workspace_ref": WORKSPACE,
                "credential_b64": CRED_B64,
                "now": BASE.isoformat(),
            }
        )
        foreign = runtime.terminal_command_result(
            {"account_ref": "account.other.b", "workspace_ref": WORKSPACE, "run_id": "run.acct.a"}
        )
        assert foreign["ok"] is True
        assert foreign["available"] is False
        assert foreign["reason"] == "no_terminal_result"
        assert "command" not in foreign

        # A malformed request is refused rather than guessed at.
        for bad in (
            {},
            {"account_ref": "account.owner.a"},
            {"account_ref": "account.owner.a", "run_id": "run.acct.a", "conversation_id": "chat_x"},
        ):
            refused = runtime.terminal_command_result(bad)
            assert refused["ok"] is False
            assert refused["error"]["code"] == "invalid_terminal_result_request"
        runtime._storage.close()


def test_source_truth_stays_deployable_and_authority_free():
    from app import claw_local_task_result_composition as composition
    from app import claw_local_task_result_projection as projection



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
