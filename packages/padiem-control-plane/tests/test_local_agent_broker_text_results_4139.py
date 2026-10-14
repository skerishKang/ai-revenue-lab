"""#4139: the Broker-side producer of the merged consumer's TXT contract.

Real canonical broker state and real SQLite, with only the device HTTP surface
exercised directly. The receipt shapes asserted here are exactly the ones
``claw_local_task_result_projection.verify_broker_file_text`` accepts.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace

import pytest

from padiem_control_plane.local_agent_broker import BrokerBindingState
from local_agent_broker_text_results import (
    MAX_TEXT_RESULT_BYTES,
    TEXT_RESULT_DEVICE_ROUTE,
    TEXT_RESULT_WIRE_VERSION,
    BrokerTextResultStore,
    TextResultRefused,
    read_verified_file_text_rpc,
)
from local_agent_broker_device_http import DEVICE_HTTP_ROUTES
from test_local_agent_broker_device_http import (
    AUTHORITY_REF,
    BASE,
    CREDENTIAL,
    _envelope,
    _service_fixture,
)

COMMAND_ID = "command.text.4139"
RUN_ID = "run.text.4139"
REQUEST_FINGERPRINT = "c" * 64
KOREAN_TEXT = "오늘 PC의 실제 테스트 파일입니다.\n"

#: The exact field set the merged consumer requires on a content receipt.
CONSUMER_FIELDS = frozenset({
    "ok", "available", "kind", "account_ref", "workspace_ref", "run_id",
    "command_id", "tool_request_ref", "request_id", "revision_ref",
    "evidence_ref", "request_fingerprint", "content_utf8", "content_sha256",
})

READ = {
    "account_ref": "account.http.1",
    "workspace_ref": "workspace.http.1",
    "run_id": RUN_ID,
    "command_id": COMMAND_ID,
}


class SqlCursor:
    """Cloudflare's statement-scoped result shape, over a real SQLite cursor."""

    def __init__(self, cursor):
        self.cursor = cursor
        self.rowsWritten = max(0, cursor.rowcount)

    def toArray(self):
        return [dict(row) for row in self.cursor.fetchall()]


class Sql:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def exec(self, statement, *params):
        return SqlCursor(self.conn.execute(statement, params))


class Clock:
    def __init__(self):
        self.now = BASE + timedelta(seconds=10)

    def __call__(self):
        return self.now


def fixture(*, ack=True, termination="exited", exit_code=0):
    state, authority, _, service = _service_fixture()
    session = authority.open_session(
        session_id="session.text.4139", binding_ref="binding.http.1",
        credential=CREDENTIAL, account_ref="account.http.1",
        workspace_ref="workspace.http.1", now=BASE + timedelta(seconds=1),
    )
    command = authority.enqueue_command(
        command_id=COMMAND_ID, binding_ref="binding.http.1", run_id=RUN_ID,
        tool_request_ref="tool.text.4139", request_fingerprint=REQUEST_FINGERPRINT,
        now=BASE + timedelta(seconds=2),
    )
    authority.admit_command(
        admission_ref="admission.text.4139", evidence_ref="evidence.text.4139",
        session_id=session.session_id, binding_ref="binding.http.1",
        credential=CREDENTIAL, command_id=command.command_id,
        request_fingerprint=REQUEST_FINGERPRINT, request_id="request.text.4139",
        now=BASE + timedelta(seconds=3),
    )
    if ack:
        authority.acknowledge(
            session_id=session.session_id, binding_ref="binding.http.1",
            credential=CREDENTIAL, command_id=command.command_id,
            admission_ref="admission.text.4139", evidence_ref="evidence.text.4139",
            revision_ref=command.revision_ref, termination=termination,
            request_id="request.text.4139", exit_code=exit_code,
            now=BASE + timedelta(seconds=4),
        )
    clock = Clock()
    store = BrokerTextResultStore(
        storage=SimpleNamespace(sql=Sql()), state_port=state,
        authority_ref=AUTHORITY_REF, clock=clock,
    )
    service._text_results = store
    return authority, service, store, clock


def stage(service, *, state="content", text=KOREAN_TEXT, digest=None, byte_count=None,
          command_id=COMMAND_ID, run_id=RUN_ID, fingerprint=REQUEST_FINGERPRINT,
          credential=CREDENTIAL, binding_ref="binding.http.1", extra=None,
          route=TEXT_RESULT_DEVICE_ROUTE):
    body = {
        "contract_version": TEXT_RESULT_WIRE_VERSION,
        "command_id": command_id, "run_id": run_id,
        "request_fingerprint": fingerprint, "state": state,
        # The device asserts only these; every other correlation ref is served
        # from the persisted canonical command.
        "binding_ref": binding_ref,
        "credential_b64": base64.b64encode(credential).decode("ascii"),
    }
    if state == "content":
        raw = text.encode("utf-8")
        body["content_utf8"] = text
        body["content_sha256"] = sha256(raw).hexdigest() if digest is None else digest
        body["content_bytes"] = len(raw) if byte_count is None else byte_count
    if extra:
        body.update(extra)
    return service.handle(_envelope(json.dumps(body).encode("utf-8"), route=route))


def rpc(store, **override):
    payload = dict(READ)
    payload.update(override)
    return read_verified_file_text_rpc(store, payload)


def stored_rows(store):
    return len(store._sql.exec("SELECT command_id FROM local_agent_text_result").toArray())


def test_an_unreported_command_keeps_the_existing_terminal_only_answer():
    _, _, store, _ = fixture()
    answer = rpc(store)
    assert answer == {"ok": True, "available": False, "kind": "other"}
    assert frozenset(answer) == {"ok", "available", "kind"}


def test_a_declared_read_answers_the_pending_shape_before_the_body_arrives():
    _, service, store, _ = fixture()
    response = stage(service, state="pending")
    assert response["status"] == 200
    assert response["body"] == {"ok": True, "text_result": {"stored": True, "reused": False, "state": "pending", "content_present": False}}
    answer = rpc(store)
    assert answer == {"ok": True, "available": False, "kind": "file_read_text"}
    assert frozenset(answer) == {"ok", "available", "kind"}


def test_a_staged_body_answers_exactly_the_consumer_receipt():
    _, service, store, _ = fixture()
    assert stage(service)["status"] == 200
    answer = rpc(store)
    assert frozenset(answer) == CONSUMER_FIELDS
    assert answer["ok"] is True and answer["available"] is True
    assert answer["kind"] == "file_read_text"
    assert answer["account_ref"] == "account.http.1"
    assert answer["workspace_ref"] == "workspace.http.1"
    assert answer["run_id"] == RUN_ID and answer["command_id"] == COMMAND_ID
    assert answer["content_utf8"] == KOREAN_TEXT
    assert answer["content_sha256"] == sha256(KOREAN_TEXT.encode("utf-8")).hexdigest()
    assert len(KOREAN_TEXT.encode("utf-8")) <= MAX_TEXT_RESULT_BYTES


def test_the_receipt_correlation_comes_from_the_canonical_command():
    authority, service, store, _ = fixture()
    command = authority.load_command(command_id=COMMAND_ID) if hasattr(authority, "load_command") else None
    assert stage(service)["status"] == 200
    answer = rpc(store)
    # Nothing the device sent can choose these: the wire carries no such fields,
    # and a wrong request fingerprint is refused before any row is written.
    assert answer["tool_request_ref"] == "tool.text.4139"
    assert answer["request_id"] == "request.text.4139"
    assert answer["request_fingerprint"] == REQUEST_FINGERPRINT
    assert answer["revision_ref"]
    assert answer["evidence_ref"] == "evidence.text.4139"
    assert command is None or answer["revision_ref"] == command.revision_ref


def test_a_body_for_a_foreign_request_is_refused_before_storage():
    _, service, store, _ = fixture()
    response = stage(service, fingerprint="d" * 64)
    assert response["status"] == 409
    assert stored_rows(store) == 0
    assert rpc(store) == {"ok": True, "available": False, "kind": "other"}


def test_an_unknown_command_or_run_is_refused():
    _, service, store, _ = fixture()
    assert stage(service, command_id="command.other.4139")["status"] == 409
    assert stage(service, run_id="run.other.4139")["status"] == 409
    assert stored_rows(store) == 0


def test_a_foreign_scope_cannot_read_a_staged_result():
    _, service, store, _ = fixture()
    assert stage(service)["status"] == 200
    assert rpc(store, account_ref="account.other.1") == {"ok": True, "available": False, "kind": "other"}
    assert rpc(store, workspace_ref="workspace.other.1") == {"ok": True, "available": False, "kind": "other"}
    assert rpc(store, run_id="run.other.4139") == {"ok": True, "available": False, "kind": "other"}
    assert rpc(store, command_id="command.other.4139") == {"ok": True, "available": False, "kind": "other"}


def test_oversize_control_and_inconsistent_bodies_are_refused():
    _, service, store, _ = fixture()
    cases = (
        {"text": "가" * 400},                       # over 768 UTF-8 bytes
        {"text": "bad\x00data"},                    # control character
        {"digest": "0" * 64},                       # digest does not match
        {"byte_count": 3},                          # declared byte count wrong
        {"extra": {"content_bytes": 999}},          # disagreeing byte count
    )
    for case in cases:
        assert stage(service, **case)["status"] == 409, case
    assert stored_rows(store) == 0
    # A refused body is refused in the store itself too, not only at the route.
    for case in ({"text": "가" * 400}, {"digest": "0" * 64}):
        payload = {
            "contract_version": TEXT_RESULT_WIRE_VERSION,
            "command_id": COMMAND_ID, "run_id": RUN_ID,
            "request_fingerprint": REQUEST_FINGERPRINT, "state": "content",
            "content_utf8": case["text"] if "text" in case else KOREAN_TEXT,
            "content_sha256": case.get("digest", sha256(KOREAN_TEXT.encode("utf-8")).hexdigest()),
            "content_bytes": 999,
        }
        with pytest.raises(TextResultRefused):
            store.record(payload, binding_ref="binding.http.1",
                         owner="account.http.1", workspace="workspace.http.1")
    assert stored_rows(store) == 0


def test_exact_replay_is_inert_and_a_conflict_never_overwrites():
    _, service, store, _ = fixture()
    first = stage(service, state="pending")["body"]["text_result"]
    assert first["reused"] is False
    replay = stage(service, state="pending")["body"]["text_result"]
    assert replay["reused"] is True
    content = stage(service)["body"]["text_result"]
    assert content["state"] == "content"
    # The body is now immutable: a different body for the same command is refused
    # and the stored text is served unchanged.
    assert stage(service, text="다른 본문\n")["status"] == 409
    assert stage(service, state="pending")["status"] == 409
    assert rpc(store)["content_utf8"] == KOREAN_TEXT


@pytest.mark.parametrize("variant", ["unacknowledged", "failed_exit", "cancelled"])
def test_the_write_gate_requires_a_successful_admitted_execution(variant):
    kwargs = {
        "unacknowledged": {"ack": False},
        "failed_exit": {"exit_code": 1},
        "cancelled": {"termination": "cancelled"},
    }[variant]
    _, service, store, _ = fixture(**kwargs)
    assert stage(service)["status"] == 409
    assert stored_rows(store) == 0


def test_revoking_the_binding_after_staging_stops_serving_the_body():
    authority, service, store, _ = fixture()
    assert stage(service)["status"] == 200
    authority.revoke_binding(
        binding_ref="binding.http.1", now=BASE + timedelta(seconds=20),
    )
    answer = rpc(store)
    assert answer == {"ok": False, "error": {"code": "verified_file_text_unavailable"}}
    assert "content_utf8" not in answer


def test_the_private_reader_fails_closed_on_current_authority_not_on_row_presence():
    """The Office read precedent: revoked authority never serves staged bytes.

    Revocation drops the device session, so the route refuses before the store
    is reached. The private reader must still re-derive current authority
    itself, otherwise a stale binding row would serve a body the device lost
    the right to deliver.
    """

    authority, service, store, _ = fixture()
    assert stage(service)["status"] == 200
    authority.revoke_binding(
        binding_ref="binding.http.1", now=BASE + timedelta(seconds=20),
    )
    # The rows the reader itself resolves are still there and still scoped to
    # this command, so only the read-time authority check can be what refuses.
    snapshot = store._state.load(authority_ref=AUTHORITY_REF).snapshot
    binding = [item for item in snapshot.bindings if item.binding_ref == "binding.http.1"]
    command = [item for item in snapshot.commands if item.command_id == COMMAND_ID]
    assert len(binding) == 1 and len(command) == 1
    assert binding[0].state is BrokerBindingState.REVOKED
    with pytest.raises(TextResultRefused, match="no longer current"):
        store.read(
            owner="account.http.1", workspace="workspace.http.1",
            run_id=RUN_ID, command_id=COMMAND_ID,
        )


def test_an_expired_result_is_purged_and_never_served():
    _, service, store, clock = fixture()
    assert stage(service)["status"] == 200
    clock.now = BASE + timedelta(days=3)
    assert stored_rows(store) == 0 or rpc(store) != {"ok": True, "available": True, "kind": "file_read_text"}
    assert stored_rows(store) == 0


def test_the_private_reader_accepts_only_the_closed_key_set():
    _, service, store, _ = fixture()
    assert stage(service)["status"] == 200
    assert read_verified_file_text_rpc(store, {**READ, "extra": 1}) == {
        "ok": False, "error": {"code": "verified_file_text_unavailable"},
    }
    missing = dict(READ)
    missing.pop("command_id")
    assert read_verified_file_text_rpc(store, missing) == {
        "ok": False, "error": {"code": "verified_file_text_unavailable"},
    }
    assert read_verified_file_text_rpc(None, dict(READ)) == {
        "ok": False, "error": {"code": "verified_file_text_unavailable"},
    }


def test_the_route_is_behind_the_canonical_authenticated_device_surface():
    assert TEXT_RESULT_DEVICE_ROUTE in DEVICE_HTTP_ROUTES
    _, service, _, _ = fixture()
    assert stage(service, credential=b"not-the-device-credential")["status"] == 401
    body = json.dumps({"contract_version": TEXT_RESULT_WIRE_VERSION}).encode("utf-8")
    assert service.handle(_envelope(body, route=TEXT_RESULT_DEVICE_ROUTE, tls_verified=False))["status"] == 403
    # Unknown routes stay 404: the surface is a closed set, not a prefix match.
    assert service.handle(_envelope(body, route="/text-result-extra"))["status"] == 404


def test_the_device_credential_is_verified_before_the_payload_is_treated_as_a_result():
    _, service, store, _ = fixture()
    response = stage(service, extra={"binding_ref": "binding.other.1"})
    assert response["status"] == 401
    assert stored_rows(store) == 0


def test_a_store_without_durable_sql_never_serves_or_stages():
    with pytest.raises(TextResultRefused):
        BrokerTextResultStore(
            storage=SimpleNamespace(), state_port=SimpleNamespace(),
            authority_ref=AUTHORITY_REF,
        )
