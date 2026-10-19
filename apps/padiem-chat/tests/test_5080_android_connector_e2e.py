"""#5080 Android SAF lane: dispatch -> receipt -> original conversation result.

The Mock Android agent is the canonical private device HTTP surface plus the
real Broker text-result store; there is no real phone and no production
Worker. Storage is real SQLite (Broker DO shape and D1-shaped history), so the
approval material, the exactly-once command, the run receipt and the one-time
conversation append are exercised through the merged #4139 pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.claw_local_task_result_composition import (
    BrokerAuthorityLocalRunnerResultPort,
    LocalRunnerResultSource,
)
from app.connector_android_saf_approval_material import (
    AndroidOwnerTxtApprovalProof,
    AndroidTxtApprovalMaterialError,
    mint_android_txt_read_receipt,
)
from app.history import D1HistoryStore
from local_agent_broker_android_profile import (
    ANDROID_PROFILE_CONTRACT_VERSION,
    ANDROID_PROFILE_DEVICE_ROUTE,
    ANDROID_PROFILE_REF,
    BrokerAndroidSafProfileStore,
    android_saf_profile_rpc,
)
from local_agent_broker_device_http import LocalAgentBrokerDeviceHttpService
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_text_results import (
    TEXT_RESULT_WIRE_VERSION,
    BrokerTextResultStore,
)
from padiem_control_plane.local_agent_broker import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import (
    StateBackedLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

from test_claw_local_task_result_projection import (
    OWNER_SUBJECT,
    _SqliteD1,
    _accounts,
    _conversation_with_run,
)

BASE = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
PEPPER = b"android-connector-5080-pepper"
CREDENTIAL = b"android-connector-5080-credential"
AUTHORITY_REF = "control-plane.local-agent-broker.android-5080.v1"
BINDING = "binding.android.e2e.1"
ACCOUNT = "account-canonical-android-e2e"
CONNECTOR_WS = "connector-ws-android-e2e"
TENANT_WS = "tenant-ws-android-e2e"
DEVICE = "device.android.e2e.1"
SESSION = "session.android.e2e.1"
RUN = "run.android.e2e.1"
ROOT = "safroot-documents"
TEXT = "안드로이드 SAF에서 읽은 본문입니다.\n"

_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _open_database(path):
    """Real app migrations; sync-off keeps Windows fsync-per-statement cheap."""
    db = _SqliteD1(path)
    db._connection.execute("PRAGMA synchronous=OFF")
    for migration in sorted(_MIGRATIONS.glob("*.sql")):
        db._connection.executescript(migration.read_text(encoding="utf-8"))
    return db


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


class _Env:
    LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
    LOCAL_AGENT_BROKER_PEPPER = str(PEPPER)


def _storage(connection):
    def transaction_sync(callback):
        connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")
        return value

    return SimpleNamespace(
        sql=_Sql(connection), transactionSync=transaction_sync,
    )


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


def _envelope(body: bytes, *, route: str) -> dict:
    return {
        "method": "POST", "route": route, "content_type": "application/json",
        "body_b64": base64.b64encode(body).decode("ascii"), "tls_verified": True,
    }


def _setup(tmp_path):
    state_port = SerializedLocalAgentBrokerStatePort(
        backend=InMemorySerializedLocalAgentBrokerStateBackend()
    )
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER, authority_ref=AUTHORITY_REF, state_port=state_port,
    )
    authority.register_binding(
        binding_ref=BINDING, device_id=DEVICE, account_ref=ACCOUNT,
        workspace_ref=CONNECTOR_WS, credential=CREDENTIAL, now=BASE,
    )
    authority.open_session(
        session_id=SESSION, binding_ref=BINDING, credential=CREDENTIAL,
        account_ref=ACCOUNT, workspace_ref=CONNECTOR_WS,
        now=BASE + timedelta(seconds=1),
    )
    broker_connection = sqlite3.connect(
        tmp_path / "broker.sqlite3", isolation_level=None, check_same_thread=False,
    )
    storage = _storage(broker_connection)
    runtime = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    runtime.state_port = state_port
    runtime.material_store._state_port = state_port

    manifest_clock = lambda: BASE + timedelta(seconds=10)
    profiles = BrokerAndroidSafProfileStore(
        storage=storage, state_port=state_port, authority_ref=AUTHORITY_REF,
        clock=manifest_clock,
    )
    text_store = BrokerTextResultStore(
        storage=SimpleNamespace(sql=_Sql(sqlite3.connect(
            tmp_path / "text.sqlite3", isolation_level=None, check_same_thread=False,
        ))),
        state_port=state_port, authority_ref=AUTHORITY_REF, clock=manifest_clock,
    )
    service = LocalAgentBrokerDeviceHttpService(
        state_port=state_port, pepper=PEPPER, authority_ref=AUTHORITY_REF,
        rpc_factory=lambda: LocalAgentBrokerRpcFacade(authority=authority),
        http_state=SimpleNamespace(), material_resolver=object(),
        session_open_transaction=lambda operation: operation(),
        clock=manifest_clock, android_profiles=profiles, text_results=text_store,
    )
    return SimpleNamespace(
        state_port=state_port, authority=authority, runtime=runtime,
        profiles=profiles, service=service, text_store=text_store,
        connection=broker_connection, clock=manifest_clock,
    )


def _declare_folders(built, folders):
    body = {
        "contract_version": ANDROID_PROFILE_CONTRACT_VERSION,
        "session_id": SESSION,
        "profile_ref": ANDROID_PROFILE_REF,
        "folders": folders,
        "binding_ref": BINDING,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
    }
    return built.service.handle(_envelope(
        json.dumps(body).encode("utf-8"), route=ANDROID_PROFILE_DEVICE_ROUTE,
    ))


def _mint(built, *, run_id=RUN, path_relative="notes/report.txt", **ids):
    profile = android_saf_profile_rpc(built.profiles, {
        "account_ref": ACCOUNT, "workspace_ref": CONNECTOR_WS,
        "device_id": DEVICE, "binding_ref": BINDING,
        "profile_ref": ANDROID_PROFILE_REF,
    })
    assert profile["ok"] is True
    proof = AndroidOwnerTxtApprovalProof(
        owner_id="product-owner-android-1",
        workspace_id=CONNECTOR_WS,
        device_id=DEVICE,
        binding_ref=BINDING,
        credential_generation=1,
        consent_id="consent.android.e2e.1",
        run_id=run_id,
        profile_ref=ANDROID_PROFILE_REF,
        root_ref=ROOT,
        allowed_root_refs=tuple(
            item["root_ref"] for item in profile["profile"]["folders"]
        ),
    )
    issued = mint_android_txt_read_receipt(
        approval=proof, path_relative=path_relative,
        now=BASE + timedelta(seconds=2), **ids,
    )
    enqueue = {
        **issued["enqueue"],
        "now": (BASE + timedelta(seconds=2)).isoformat(),
        "ttl_seconds": 300,
    }
    return issued, enqueue


def test_dispatch_receipt_and_original_conversation_result(tmp_path):
    built = _setup(tmp_path)
    declared = _declare_folders(built, [
        {"root_ref": ROOT, "display_name": "Documents"},
        {"root_ref": "safroot-notes", "display_name": "Notes"},
    ])
    assert declared["status"] == 200
    assert declared["body"]["android_profile"]["folder_count"] == 2

    issued, enqueue = _mint(
        built, command_id="andcmd-e2e-5080", request_id="andreq-e2e-5080",
        action_id="andact-e2e-5080", tool_request_ref="andtool-e2e-5080",
    )
    assert issued["material"]["argv"] == []
    assert issued["material"]["p01_approval_payload"]["format"] == (
        "claw-android-saf-txt-read-approval.v1"
    )

    enqueued = built.runtime.enqueue_command_with_material(enqueue, issued["material"])
    assert enqueued["ok"] is True
    command_id = enqueued["command"]["command_id"]
    assert command_id == "andcmd-e2e-5080"
    revision_ref = enqueued["command"]["revision_ref"]

    # A lost response retried with the exact same wire and material is served
    # unchanged: one command, one material, one revision.
    retried = built.runtime.enqueue_command_with_material(enqueue, issued["material"])
    assert retried["ok"] is True
    assert retried["command"]["command_id"] == command_id
    assert retried["command"]["revision_ref"] == revision_ref
    assert retried["command"]["sequence"] == enqueued["command"]["sequence"]

    history = D1HistoryStore(_open_database(tmp_path / "chat.sqlite3"))
    owner = _accounts(history)[OWNER_SUBJECT]
    conversation_id = _conversation_with_run(
        history, owner=owner, run_id=RUN, workspace_id=TENANT_WS,
    )
    before = len(_messages(history, conversation_id))
    _run(history.record_local_task_correlation(
        user_id=owner, run_id=RUN, command_id=command_id,
        tool_request_ref=issued["tool_request_ref"],
        request_id=issued["material"]["request_id"],
        revision_ref=revision_ref, evidence_ref=None,
        request_fingerprint=issued["enqueue"]["request_fingerprint"],
    ))

    binding = _RealServiceBinding(built.runtime, built.text_store)
    port = BrokerAuthorityLocalRunnerResultPort(binding)
    source = LocalRunnerResultSource(history=history, result_port=port)

    # Offline / not-yet-executed phone: pending projection, nothing appended.
    pending = _run(source.project_local_runner_result(
        owner_id=owner, run_id=RUN, workspace_id=TENANT_WS))
    assert pending is not None and pending["appended"] is False
    assert len(_messages(history, conversation_id)) == before

    admission = built.authority.admit_command(
        admission_ref="admission.android.e2e.1",
        evidence_ref="evidence.android.e2e.1",
        session_id=SESSION, binding_ref=BINDING, credential=CREDENTIAL,
        command_id=command_id,
        request_fingerprint=issued["enqueue"]["request_fingerprint"],
        request_id=issued["material"]["request_id"],
        now=BASE + timedelta(seconds=3),
    )
    acknowledged = built.authority.acknowledge(
        session_id=SESSION, binding_ref=BINDING, credential=CREDENTIAL,
        command_id=command_id,
        admission_ref="admission.android.e2e.1",
        evidence_ref="evidence.android.e2e.1",
        revision_ref=admission.revision_ref, termination="exited",
        request_id=issued["material"]["request_id"], exit_code=0,
        now=BASE + timedelta(seconds=4),
    )
    # A phone resending the exact acknowledgement after a lost response gets
    # the same terminal facts; it is not a second execution.
    resend = built.authority.acknowledge(
        session_id=SESSION, binding_ref=BINDING, credential=CREDENTIAL,
        command_id=command_id,
        admission_ref="admission.android.e2e.1",
        evidence_ref="evidence.android.e2e.1",
        revision_ref=admission.revision_ref, termination="exited",
        request_id=issued["material"]["request_id"], exit_code=0,
        now=BASE + timedelta(seconds=5),
    )
    assert resend.state is acknowledged.state
    assert resend.acknowledged_at == acknowledged.acknowledged_at

    # The Mock Android agent calls the same private device surface a phone
    # uses: canonical binding credential auth, then pending intent, then the
    # SHA-256-verified body — never a direct store write.
    intent = built.service.handle(_envelope(json.dumps({
        "contract_version": TEXT_RESULT_WIRE_VERSION, "command_id": command_id,
        "run_id": RUN,
        "request_fingerprint": issued["enqueue"]["request_fingerprint"],
        "state": "pending", "binding_ref": BINDING,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
    }).encode("utf-8"), route="/text-result"))
    assert intent["status"] == 200
    assert intent["body"]["text_result"]["state"] == "pending"
    raw = TEXT.encode("utf-8")
    staged = built.service.handle(_envelope(json.dumps({
        "contract_version": TEXT_RESULT_WIRE_VERSION, "command_id": command_id,
        "run_id": RUN,
        "request_fingerprint": issued["enqueue"]["request_fingerprint"],
        "state": "content", "content_utf8": TEXT,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "content_bytes": len(raw), "binding_ref": BINDING,
        "credential_b64": base64.b64encode(CREDENTIAL).decode("ascii"),
    }).encode("utf-8"), route="/text-result"))
    assert staged["status"] == 200
    assert staged["body"]["text_result"]["state"] == "content"

    projected = _run(source.project_local_runner_result(
        owner_id=owner, run_id=RUN, workspace_id=TENANT_WS))
    assert projected is not None and projected["appended"] is True
    after = _messages(history, conversation_id)
    assert len(after) == before + 1
    assert TEXT.strip() in after[-1]["content"]
    assert CREDENTIAL.decode("ascii", "ignore") not in after[-1]["content"]

    correlation = _run(history.get_local_task_correlation(owner, RUN))
    assert correlation["evidence_ref"] == "evidence.android.e2e.1"
    assert correlation["command_id"] == command_id

    # A re-delivered result, or a repoll after the append, adds nothing.
    again = _run(source.project_local_runner_result(
        owner_id=owner, run_id=RUN, workspace_id=TENANT_WS))
    assert again["appended"] is False
    assert len(_messages(history, conversation_id)) == before + 1


def test_withdrawn_saf_folder_cannot_be_repackaged_into_a_command(tmp_path):
    built = _setup(tmp_path)
    assert _declare_folders(built, [
        {"root_ref": ROOT, "display_name": "Documents"},
    ])["status"] == 200
    # The owner revoked SAF access on the phone: empty declaration replaces it.
    assert _declare_folders(built, [])["status"] == 200
    with pytest.raises(AndroidTxtApprovalMaterialError):
        _mint(built, command_id="andcmd-withdrawn", request_id="andreq-withdrawn",
              action_id="andact-withdrawn", tool_request_ref="andtool-withdrawn")


def test_expired_android_command_never_admits_or_fabricates_a_result(tmp_path):
    built = _setup(tmp_path)
    assert _declare_folders(built, [
        {"root_ref": ROOT, "display_name": "Documents"},
    ])["status"] == 200
    issued, enqueue = _mint(
        built, run_id="run.android.timeout",
        command_id="andcmd-timeout", request_id="andreq-timeout",
        action_id="andact-timeout", tool_request_ref="andtool-timeout",
    )
    enqueue["ttl_seconds"] = 1
    assert built.runtime.enqueue_command_with_material(
        enqueue, issued["material"])["ok"] is True
    with pytest.raises(ControlPlaneContractError) as caught:
        built.authority.admit_command(
            admission_ref="admission.timeout", evidence_ref="evidence.timeout",
            session_id=SESSION, binding_ref=BINDING, credential=CREDENTIAL,
            command_id="andcmd-timeout",
            request_fingerprint=issued["enqueue"]["request_fingerprint"],
            request_id=issued["material"]["request_id"],
            now=BASE + timedelta(seconds=10),
        )
    assert caught.value.code == "broker_command_expired"


def test_profile_declaration_rejects_uri_path_and_traversal_shapes(tmp_path):
    built = _setup(tmp_path)
    for bad in (
        "content://com.android.externalstorage.documents/tree/primary",
        "../Documents", "/sdcard/Documents", r"Documents\Notes", "a" * 257,
    ):
        response = _declare_folders(
            built, [{"root_ref": bad, "display_name": "Docs"}])
        assert response["status"] == 409, bad
        assert response["body"]["error"]["code"] == "android_profile_refused", bad
    profile = android_saf_profile_rpc(built.profiles, {
        "account_ref": ACCOUNT, "workspace_ref": CONNECTOR_WS,
        "device_id": DEVICE, "binding_ref": BINDING,
        "profile_ref": ANDROID_PROFILE_REF,
    })
    assert profile["ok"] is False


def _messages(history, conversation_id):
    from test_claw_local_task_result_projection import _messages as messages
    return messages(history, conversation_id)
