"""#4139 focused: TXT return leg where all four realm values differ.

Product user id, tenant workspace, canonical account_ref and connector
workspace_ref are four different strings throughout: the trigger uses
Identity-verified canonical scope for Broker calls, history checks stay in
the tenant realm, and the return leg resolves scope from the stored
correlation instead of the caller product id. Request -> enqueue (with the
real issuance receipt in material) -> pre-written correlation -> admit ->
ack -> staged body -> projection appends the body to the originating
conversation. No live Broker, no new tables, no caller-supplied scope.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "padiem-chat"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "padiem-control-plane"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "korean-ai-code-agent" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "padiem-ai-core"))

from test_claw_local_task_result_projection import (  # noqa: E402
    _accounts,
    _conversation_with_run,
    _messages,
    _open_database,
)
from local_agent_broker_text_results import (  # noqa: E402
    TEXT_RESULT_WIRE_VERSION,
)
from app.claw_local_task_result_composition import (  # noqa: E402
    BrokerAuthorityLocalRunnerResultPort,
    LocalRunnerResultSource,
)
from app.connector_txt_approval_material import (  # noqa: E402
    OwnerTxtApprovalProof,
    mint_txt_read_receipt,
)
from app.history import D1HistoryStore  # noqa: E402
from padiem_control_plane.local_agent_broker import BrokerCommandState  # noqa: E402
from padiem_control_plane.local_agent_broker_state import (  # noqa: E402
    StateBackedLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_state_wire import (  # noqa: E402
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)
PEPPER = b"txt-distinct-realm-pepper"
CREDENTIAL = b"txt-distinct-realm-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.txt-distinct.v1"
BINDING_REF = "binding.txt.1"
ACCOUNT = "account-canonical-txt-1"
CONNECTOR_WS = "connector-ws-txt-1"
TENANT_WS = "tenant-ws-txt-1"
TEXT = "연동 확인 본문입니다.\n"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _RealServiceBinding:
    """Private Service Binding shape over the real durable runtime + store."""

    def __init__(self, runtime, text_store):
        self._runtime = runtime
        self._text_store = text_store

    def terminal_command_result(self, payload):
        return self._runtime.terminal_command_result(payload)

    def read_verified_file_text(self, payload):
        from local_agent_broker_text_results import read_verified_file_text_rpc
        return read_verified_file_text_rpc(self._text_store, payload)


def test_distinct_realms_from_request_to_conversation(tmp_path):
    from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime

    history = D1HistoryStore(_open_database(tmp_path / "chat.sqlite3"))
    accounts = _accounts(history)
    owner = next(value for key, value in accounts.items() if "owner" in key)
    # All four realm values differ: product user, tenant workspace,
    # canonical account_ref, connector workspace_ref.
    assert len({owner, TENANT_WS, ACCOUNT, CONNECTOR_WS}) == 4

    state_port = SerializedLocalAgentBrokerStatePort(
        backend=InMemorySerializedLocalAgentBrokerStateBackend()
    )
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER, authority_ref=AUTHORITY_REF, state_port=state_port,
    )
    authority.register_binding(
        binding_ref=BINDING_REF, device_id="device.txt.1",
        account_ref=ACCOUNT, workspace_ref=CONNECTOR_WS,
        credential=CREDENTIAL, now=BASE,
    )
    authority.open_session(
        session_id="session.txt.1", binding_ref=BINDING_REF,
        credential=CREDENTIAL, account_ref=ACCOUNT,
        workspace_ref=CONNECTOR_WS, now=BASE + timedelta(seconds=1),
    )

    # Issuance from the trigger-verified proof (canonical scope inside).
    issued = mint_txt_read_receipt(
        approval=OwnerTxtApprovalProof(
            owner_id=owner, workspace_id=CONNECTOR_WS, device_id="device.txt.1",
            binding_ref=BINDING_REF, credential_generation=1,
            consent_id="consent.txt.1", run_id="run.txt.1",
        ),
        root_ref="root.txt.1", path_relative="notes\\report.txt",
        now=BASE + timedelta(seconds=1),
    )

    class _Env:
        LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        LOCAL_AGENT_BROKER_PEPPER = str(PEPPER)

    import sqlite3

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

    broker_connection = sqlite3.connect(tmp_path / "broker.sqlite3", isolation_level=None)

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

    def _transaction_sync(callback):
        broker_connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
        except BaseException:
            broker_connection.execute("ROLLBACK")
            raise
        broker_connection.execute("COMMIT")
        return value

    broker_storage = SimpleNamespace(
        sql=_Sql(broker_connection), transactionSync=_transaction_sync,
    )
    runtime = LocalAgentBrokerDurableRuntime(storage=broker_storage, env=_Env())
    runtime.state_port = state_port
    runtime.material_store._state_port = state_port

    enqueued = runtime.enqueue_command_with_material(
        {
            "command_id": issued["enqueue"]["command_id"],
            "binding_ref": BINDING_REF,
            "run_id": "run.txt.1",
            "tool_request_ref": issued["tool_request_ref"],
            "request_fingerprint": issued["enqueue"]["request_fingerprint"],
            "now": (BASE + timedelta(seconds=2)).isoformat(),
            "ttl_seconds": 300,
        },
        issued["material"],
    )
    assert enqueued["ok"] is True
    revision_ref = enqueued["command"]["revision_ref"]

    # The conversation turn (with its run row) exists before the TXT request.
    conversation_id = _conversation_with_run(
        history, owner=owner, run_id="run.txt.1", workspace_id=TENANT_WS)
    before = len(_messages(history, conversation_id))
    # Trigger pre-write (evidence still unknown before admission).
    _run(history.record_local_task_correlation(
        user_id=owner, run_id="run.txt.1",
        command_id=issued["enqueue"]["command_id"],
        tool_request_ref=issued["tool_request_ref"],
        request_id=issued["material"]["request_id"],
        revision_ref=revision_ref, evidence_ref=None,
        request_fingerprint=issued["enqueue"]["request_fingerprint"],
    ))

    from local_agent_broker_text_results import BrokerTextResultStore

    text_store = BrokerTextResultStore(
        storage=SimpleNamespace(sql=_Sql(sqlite3.connect(tmp_path / "text.sqlite3",
                                                         isolation_level=None))),
        state_port=state_port, authority_ref=AUTHORITY_REF,
        clock=lambda: BASE + timedelta(seconds=10),
    )
    binding = _RealServiceBinding(runtime, text_store)
    port = BrokerAuthorityLocalRunnerResultPort(binding)
    source = LocalRunnerResultSource(history=history, result_port=port)

    # Legacy owner-as-account reads find nothing in mismatched realms.
    assert _run(port.command_result(
        command_id=issued["enqueue"]["command_id"], run_id="run.txt.1",
        owner_id=owner, workspace_id=TENANT_WS)) is None

    # Pre-admission poll: pending, nothing appended.
    pending = _run(source.project_local_runner_result(
        owner_id=owner, run_id="run.txt.1", workspace_id=TENANT_WS))
    assert pending is not None and pending["appended"] is False
    assert len(_messages(history, conversation_id)) == before

    admission = authority.admit_command(
        admission_ref="admission.txt.1", evidence_ref="evidence.txt.1",
        session_id="session.txt.1", binding_ref=BINDING_REF,
        credential=CREDENTIAL, command_id=issued["enqueue"]["command_id"],
        request_fingerprint=issued["enqueue"]["request_fingerprint"],
        request_id=issued["material"]["request_id"],
        now=BASE + timedelta(seconds=3),
    )
    authority.acknowledge(
        session_id="session.txt.1", binding_ref=BINDING_REF,
        credential=CREDENTIAL, command_id=issued["enqueue"]["command_id"],
        admission_ref="admission.txt.1", evidence_ref="evidence.txt.1",
        revision_ref=admission.revision_ref, termination="exited",
        request_id=issued["material"]["request_id"], exit_code=0,
        now=BASE + timedelta(seconds=4),
    )
    raw = TEXT.encode("utf-8")
    text_store.record(
        {"contract_version": TEXT_RESULT_WIRE_VERSION,
         "command_id": issued["enqueue"]["command_id"], "run_id": "run.txt.1",
         "request_fingerprint": issued["enqueue"]["request_fingerprint"],
         "state": "content", "content_utf8": TEXT,
         "content_sha256": hashlib.sha256(raw).hexdigest(),
         "content_bytes": len(raw)},
        binding_ref=BINDING_REF, owner=ACCOUNT, workspace=CONNECTOR_WS,
    )

    projected = _run(source.project_local_runner_result(
        owner_id=owner, run_id="run.txt.1", workspace_id=TENANT_WS))
    assert projected is not None and projected["appended"] is True
    after = _messages(history, conversation_id)
    assert len(after) == before + 1
    assert TEXT.strip() in after[-1]["content"]
    assert after[-1]["content"].startswith("PC 파일 읽기 결과:")
    assert CREDENTIAL.decode("ascii", "ignore") not in after[-1]["content"]

    # The evidence fill landed exactly once; a repoll appends nothing.
    bound = _run(history.get_local_task_correlation(owner, "run.txt.1"))
    assert bound["evidence_ref"] == "evidence.txt.1"
    again = _run(source.project_local_runner_result(
        owner_id=owner, run_id="run.txt.1", workspace_id=TENANT_WS))
    assert again["appended"] is False
    assert len(_messages(history, conversation_id)) == before + 1
