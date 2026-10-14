"""#4139 — the real Broker receipt and the real Claw consumer agree, end to end.

Both halves are the shipped code: the canonical broker's durable verified file
result store (over a genuine SQLite database and the canonical serialized broker
state) on one side, and CENTRAL's #4687 / #4690 / #4693 conversation projection
on the other. The test drives the actual TXT content through the actual receipt
into the actual conversation append, so the two contracts cannot drift apart
without this failing.

What is *not* proven here (and is not claimed): a real Windows device producing
the content, the deployed Worker route, and the live Claw conversation. Those
stay with the #4139 integration and Windows acceptance lanes.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.claw_local_task_result_projection import (  # noqa: E402
    LocalRunnerTerminalObservation,
    LocalTaskResultError,
    project_local_runner_terminal_result,
    verify_broker_file_text,
)
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority  # noqa: E402
from padiem_control_plane.local_agent_broker_state_wire import (  # noqa: E402
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

# The broker's durable store is a deployment adapter that lives beside the
# side-effect-free package, exactly like the worker modules under test in
# `packages/padiem-control-plane/tests`. Loading it by path is how the other
# cross-contract suites reach the same code.
_BROKER_ADAPTER_DIR = Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"
if str(_BROKER_ADAPTER_DIR) not in sys.path:
    sys.path.insert(0, str(_BROKER_ADAPTER_DIR))
_SPEC = importlib.util.spec_from_file_location(
    "chat_cross_contract_verified_file_store",
    _BROKER_ADAPTER_DIR / "local_agent_broker_verified_file_store.py",
)
assert _SPEC is not None and _SPEC.loader is not None
verified_store = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = verified_store
_SPEC.loader.exec_module(verified_store)

BASE = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.chat-cross-contract.v1"
PEPPER = b"chat-cross-contract-pepper"
CREDENTIAL = b"chat-cross-contract-device-credential"
FINGERPRINT = "b" * 64
BINDING_REF = "binding.cross.1"
DEVICE_ID = "device.cross.1"
ACCOUNT_REF = "user.padiem.4139"
WORKSPACE_REF = "workspace.padiem.4139"
SESSION_ID = "session.cross.1"
COMMAND_ID = "command.cross.1"
RUN_ID = "run.cross.1"
TOOL_REQUEST_REF = "tool.cross.1"
ADMISSION_REF = "admission.cross.1"
EVIDENCE_REF = "evidence.cross.1"
REQUEST_ID = "request.cross.1"
CONVERSATION_ID = "chat_" + "c" * 32
REAL_WINDOWS_TEXT = "오늘 PC의 실제 테스트 파일입니다.\n두 번째 줄\n"


class _Cursor:
    def __init__(self, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self):
        return list(self._rows)


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def exec(self, query: str, *bindings):
        cursor = self.connection.execute(query, bindings)
        found: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            found = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        return _Cursor(found, cursor.rowcount if cursor.rowcount >= 0 else 0)


class _Storage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _broker_command():
    """One canonical command executed successfully on the device, per the broker."""

    state_port = SerializedLocalAgentBrokerStatePort(backend=InMemorySerializedLocalAgentBrokerStateBackend())
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER, authority_ref=AUTHORITY_REF, state_port=state_port
    )
    authority.register_binding(
        binding_ref=BINDING_REF,
        device_id=DEVICE_ID,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        credential=CREDENTIAL,
        now=BASE,
        credential_ttl_seconds=2_592_000,
    )
    authority.open_session(
        session_id=SESSION_ID,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        now=BASE + timedelta(seconds=1),
        ttl_seconds=3600,
    )
    queued = authority.enqueue_command(
        command_id=COMMAND_ID,
        binding_ref=BINDING_REF,
        run_id=RUN_ID,
        tool_request_ref=TOOL_REQUEST_REF,
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=2),
        ttl_seconds=300,
    )
    authority.admit_command(
        admission_ref=ADMISSION_REF,
        evidence_ref=EVIDENCE_REF,
        session_id=SESSION_ID,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id=COMMAND_ID,
        request_fingerprint=FINGERPRINT,
        request_id=REQUEST_ID,
        now=BASE + timedelta(seconds=3),
    )
    acknowledged = authority.acknowledge(
        session_id=SESSION_ID,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        command_id=COMMAND_ID,
        admission_ref=ADMISSION_REF,
        evidence_ref=EVIDENCE_REF,
        revision_ref=queued.revision_ref,
        termination="exited",
        request_id=REQUEST_ID,
        exit_code=0,
        now=BASE + timedelta(seconds=4),
    )
    assert acknowledged.state.value == "acknowledged"
    return state_port


def _broker_store(state_port) -> "object":
    return verified_store.CloudflareDurableObjectVerifiedFileResultStore(
        _Storage(), state_port=state_port, authority_ref=AUTHORITY_REF
    )


def _receipt_for_real_windows_text(*, content: str | None = REAL_WINDOWS_TEXT) -> dict:
    state_port = _broker_command()
    store = _broker_store(state_port)
    digest = None if content is None else hashlib.sha256(content.encode("utf-8")).hexdigest()
    store.submit(
        {
            "command_id": COMMAND_ID,
            "revision_ref": state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands[0].revision_ref,
            "request_id": REQUEST_ID,
            "evidence_ref": EVIDENCE_REF,
            "kind": "file_read_text",
            "content_utf8": content,
            "content_sha256": digest,
        },
        binding_ref=BINDING_REF,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        now=BASE + timedelta(seconds=5),
    )
    return store.read_verified_file_text(
        {
            "account_ref": ACCOUNT_REF,
            "workspace_ref": WORKSPACE_REF,
            "run_id": RUN_ID,
            "command_id": COMMAND_ID,
        }
    )


OBSERVATION = LocalRunnerTerminalObservation(
    command_id=COMMAND_ID,
    run_id=RUN_ID,
    tool_request_ref=TOOL_REQUEST_REF,
    request_id=REQUEST_ID,
    revision_ref="rev.placeholder",
    evidence_ref=EVIDENCE_REF,
    request_fingerprint=FINGERPRINT,
    sequence=1,
    state="acknowledged",
    termination="exited",
    exit_code=0,
)


class _FakeHistory:
    def __init__(self, revision_ref: str) -> None:
        self.calls: list[dict] = []
        self._revision_ref = revision_ref

    async def get_claw_run(self, user_id, run_id):
        assert (user_id, run_id) == (ACCOUNT_REF, RUN_ID)
        return {"run_id": RUN_ID, "conversation_id": CONVERSATION_ID, "workspace_id": WORKSPACE_REF}

    async def get_local_task_correlation(self, user_id, run_id):
        assert (user_id, run_id) == (ACCOUNT_REF, RUN_ID)
        return {
            "command_id": COMMAND_ID,
            "tool_request_ref": TOOL_REQUEST_REF,
            "request_id": REQUEST_ID,
            "revision_ref": self._revision_ref,
            "evidence_ref": EVIDENCE_REF,
            "request_fingerprint": FINGERPRINT,
        }

    async def append_local_task_result(self, **kwargs):
        self.calls.append(kwargs)
        return True


class _ReceiptPort:
    def __init__(self, receipt: dict, *, revision_ref: str) -> None:
        self._receipt = receipt
        self._revision_ref = revision_ref

    async def command_result(self, **_):
        return LocalRunnerTerminalObservation(
            command_id=COMMAND_ID,
            run_id=RUN_ID,
            tool_request_ref=TOOL_REQUEST_REF,
            request_id=REQUEST_ID,
            revision_ref=self._revision_ref,
            evidence_ref=EVIDENCE_REF,
            request_fingerprint=FINGERPRINT,
            sequence=1,
            state="acknowledged",
            termination="exited",
            exit_code=0,
        )

    async def read_verified_file_text(self, **_):
        return self._receipt


def test_real_broker_receipt_puts_the_real_txt_in_the_original_conversation():
    import asyncio

    receipt = _receipt_for_real_windows_text()
    revision_ref = receipt["revision_ref"]
    history = _FakeHistory(revision_ref)
    outcome = asyncio.run(
        project_local_runner_terminal_result(
            history=history,
            result_port=_ReceiptPort(receipt, revision_ref=revision_ref),
            user_id=ACCOUNT_REF,
            run_id=RUN_ID,
            command_id=COMMAND_ID,
            expected_workspace_id=WORKSPACE_REF,
        )
    )
    assert outcome.append is True and outcome.status == "completed"
    assert len(history.calls) == 1
    appended = history.calls[0]
    assert appended["user_id"] == ACCOUNT_REF
    assert appended["run_id"] == RUN_ID
    assert "PC 파일 읽기 결과:" in appended["content"]
    assert REAL_WINDOWS_TEXT in appended["content"]
    assert appended["content"].endswith(REAL_WINDOWS_TEXT)


def test_receipt_field_set_is_exactly_what_the_claw_consumer_requires():
    receipt = _receipt_for_real_windows_text()
    assert frozenset(receipt) == frozenset(verified_store.RECEIPT_FIELDS)
    # The canonical consumer's own accepted field set, enforced by its validator.
    state, text = verify_broker_file_text(
        receipt,
        origin=_origin(receipt["revision_ref"]),
        observation=_observation(receipt["revision_ref"]),
    )
    assert state == "text" and text == REAL_WINDOWS_TEXT


def test_pending_and_other_shapes_keep_the_conversation_slot_open():
    pending = _receipt_for_real_windows_text(content=None)
    assert pending == {"ok": True, "available": False, "kind": "file_read_text"}
    assert verify_broker_file_text(
        pending, origin=_origin("rev.x"), observation=_observation("rev.x")
    ) == ("pending", None)

    other = _broker_store(_broker_command()).read_verified_file_text(
        {"account_ref": ACCOUNT_REF, "workspace_ref": WORKSPACE_REF, "run_id": RUN_ID, "command_id": COMMAND_ID}
    )
    assert other == {"ok": True, "available": False, "kind": "other"}
    assert verify_broker_file_text(
        other, origin=_origin("rev.x"), observation=_observation("rev.x")
    ) == ("other", None)


def test_tampered_or_foreign_receipts_are_refused_by_the_real_consumer():
    receipt = _receipt_for_real_windows_text()
    for override in (
        {"account_ref": "someone.else"},
        {"workspace_ref": "someone.else"},
        {"content_sha256": "0" * 64},
        {"content_utf8": "변조된 내용"},
        {"run_id": "run.other"},
    ):
        broken = {**receipt, **override}
        with pytest.raises(LocalTaskResultError):
            verify_broker_file_text(
                broken,
                origin=_origin(receipt["revision_ref"]),
                observation=_observation(receipt["revision_ref"]),
            )


def _origin(revision_ref: str):
    from app.claw_local_task_result_projection import LocalTaskCommandCorrelation, LocalTaskOrigin

    return LocalTaskOrigin(
        user_id=ACCOUNT_REF,
        run_id=RUN_ID,
        conversation_id=CONVERSATION_ID,
        workspace_id=WORKSPACE_REF,
        correlation=LocalTaskCommandCorrelation(
            command_id=COMMAND_ID,
            tool_request_ref=TOOL_REQUEST_REF,
            request_id=REQUEST_ID,
            revision_ref=revision_ref,
            evidence_ref=EVIDENCE_REF,
            request_fingerprint=FINGERPRINT,
        ),
    )


def _observation(revision_ref: str) -> LocalRunnerTerminalObservation:
    return LocalRunnerTerminalObservation(
        command_id=COMMAND_ID,
        run_id=RUN_ID,
        tool_request_ref=TOOL_REQUEST_REF,
        request_id=REQUEST_ID,
        revision_ref=revision_ref,
        evidence_ref=EVIDENCE_REF,
        request_fingerprint=FINGERPRINT,
        sequence=1,
        state="acknowledged",
        termination="exited",
        exit_code=0,
    )
