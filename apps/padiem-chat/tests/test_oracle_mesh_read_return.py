"""Oracle management-host MeshCentral read return tests (no live Broker/Identity)."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_local_task_result_projection import result_message_id
from app.control_plane_identity import IdentityBridgeError
from app.history import HistoryForbidden
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

NOW = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
TEXT = (
    "PADIEM MESHCENTRAL SINGLE-PC TXT TEST\nDATE=2026-10-16\nHOST=COM1\n"
    "TEST_CASE=mesh-agent-read-and-return\nEND_OF_FILE\n"
)
SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"


class Request:
    def __init__(self, data, state, content_type="application/json"):
        self.app = SimpleNamespace(state=state)
        raw = json.dumps(data).encode()
        self.headers = {"content-type": content_type, "content-length": str(len(raw))}
        self._data = raw
    async def body(self):
        return self._data


def run(handler, request):
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body), response.headers


async def _verified(request):
    del request
    return SimpleNamespace(session_id="session.canonical.owner.1"), None


async def _workspace(request, uid):
    del request, uid
    return "tenant-ws-1"


def setup_auth(monkeypatch, user="product-user-1"):
    monkeypatch.setattr(routes, "current_user_id", lambda request: user)
    monkeypatch.setattr(routes, "_verified_owner_request", _verified)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)


class FakeIdentity:
    def __init__(self, consent=None):
        self._consent = consent
    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        del session_id
        if self._consent is None:
            raise RuntimeError("no consent")
        assert self._consent["device_id"] == device_id
        return dict(self._consent)


class FakeBrokerSource:
    configured = True
    def __init__(self, binding=None):
        self._binding = binding
    async def resolve_device_binding(self, *, account_ref, workspace_ref, device_id):
        if self._binding is None:
            raise IdentityBridgeError(404, "txt_device_unbound", "unbound")
        assert self._binding["device_id"] == device_id
        return dict(self._binding)


class FakeHistory:
    def __init__(self, run=None, bound=None):
        self._run = run
        self._bound = bound
        self.appended = []
    async def get_claw_run(self, user_id, run_id):
        del user_id
        return dict(self._run) if self._run is not None and self._run["run_id"] == run_id else None
    async def get_local_task_correlation(self, user_id, run_id):
        del user_id, run_id
        return dict(self._bound) if self._bound is not None else None
    async def append_local_task_result(self, **kwargs):
        self.appended.append(dict(kwargs))
        return True


def consent(device="device-oracle-1"):
    return {
        "consent_id": "consent-oracle-1", "device_id": device,
        "owner_subject_id": "subject.canonical.owner.1",
        "account_ref": "account-oracle-1", "workspace_ref": "connector-ws-1",
        "granted_at": (NOW - timedelta(days=1)).isoformat(),
        "withdrawn_at": None,
    }


def binding():
    return {
        "binding_ref": "binding-oracle-1", "device_id": "device-oracle-1",
        "account_ref": "account-oracle-1", "workspace_ref": "connector-ws-1",
        "credential_generation": 3,
    }


def run_row():
    return {"run_id": "run-oracle-1", "conversation_id": "chat_" + "a" * 32,
            "workspace_id": "tenant-ws-1", "status": "waiting"}


def bound():
    return {
        "command_id": "cmd-oracle-1", "tool_request_ref": "tool-oracle-1",
        "request_id": "req-oracle-1", "revision_ref": "rev-oracle-1",
        "evidence_ref": "ev-oracle-1",
        "request_fingerprint": hashlib.sha256(b"oracle-request").hexdigest(),
    }


def body(**overrides):
    payload = {
        "device_id": "device-oracle-1", "command_id": "cmd-oracle-1",
        "run_id": "run-oracle-1", "tool_request_ref": "tool-oracle-1",
        "request_id": "req-oracle-1", "revision_ref": "rev-oracle-1",
        "evidence_ref": "ev-oracle-1",
        "request_fingerprint": hashlib.sha256(b"oracle-request").hexdigest(),
        "termination": "exited", "exit_code": 0, "node_ref": NODE,
        "content_utf8": TEXT, "content_sha256": SHA,
        "content_bytes": len(TEXT.encode("utf-8")),
    }
    payload.update(overrides)
    return payload


def mapping():
    return [{"account_ref": "account-oracle-1",
             "device_id": "device-oracle-1", "node_ref": NODE}]


def state(**overrides):
    return SimpleNamespace(
        oracle_mesh_return_source=overrides.get(
            "mesh", routes.build_oracle_mesh_return_source(mapping())),
        connector_txt_read_source=overrides.get("broker", FakeBrokerSource(binding())),
        control_plane_identity_authority=overrides.get(
            "identity", FakeIdentity(consent())),
        history_store=overrides.get(
            "history", FakeHistory(run_row(), bound())),
    )


def test_verified_return_appends_once_with_stable_id(monkeypatch):
    setup_auth(monkeypatch)
    history = FakeHistory(run_row(), bound())
    status, result, headers = run(
        routes.oracle_mesh_read_return, Request(body(), state(history=history)))
    assert status == 200 and result["ok"] is True
    assert result["runId"] == "run-oracle-1"
    assert result["executor"] == "oracle_management_host"
    assert result["brokerAcknowledged"] is False
    assert headers["Cache-Control"].startswith("no-store")
    assert len(history.appended) == 1
    appended = history.appended[0]
    assert appended["message_id"] == result_message_id(
        conversation_id="chat_" + "a" * 32,
        command_id="cmd-oracle-1", revision_ref="rev-oracle-1",
    )
    assert appended["content"] == "PC 파일 읽기 결과:\n" + TEXT
    assert appended["status"] == "completed"


def test_unconfigured_source_or_missing_run_refused(monkeypatch):
    setup_auth(monkeypatch)
    st = state(mesh=None)
    assert run(routes.oracle_mesh_read_return, Request(body(), st))[0] == 503
    st = state(history=FakeHistory(None, bound()))
    assert run(routes.oracle_mesh_read_return, Request(body(), st))[0] == 404


def test_ownership_and_correlation_mismatch_refused(monkeypatch):
    setup_auth(monkeypatch)
    st = state(mesh=routes.build_oracle_mesh_return_source(
        [{"account_ref": "account-other-9", "device_id": "device-oracle-1",
          "node_ref": NODE}]))
    status, result, _ = run(routes.oracle_mesh_read_return, Request(body(), st))
    assert status == 403 and result["error"]["code"] == "oracle_mesh_ownership_unverified"
    st = state()
    status, result, _ = run(
        routes.oracle_mesh_read_return, Request(body(command_id="cmd-foreign-9"), st))
    assert status == 409 and result["error"]["code"] == "oracle_mesh_correlation_mismatch"


def test_unbound_or_tampered_content_refused(monkeypatch):
    setup_auth(monkeypatch)
    st = state(history=FakeHistory(run_row(), None))
    status, result, _ = run(routes.oracle_mesh_read_return, Request(body(), st))
    assert status == 409 and result["error"]["code"] == "oracle_mesh_correlation_unbound"
    st = state()
    tampered = body(content_utf8="tampered\n")
    status, result, _ = run(routes.oracle_mesh_read_return, Request(tampered, st))
    assert status == 400 and result["error"]["code"] == "oracle_mesh_content_unverified"
    assert run(routes.oracle_mesh_read_return,
               Request(body(exit_code=1), state()))[0] == 400
