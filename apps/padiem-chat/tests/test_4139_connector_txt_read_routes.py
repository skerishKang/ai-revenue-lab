"""Owner-confirmed TXT read request trigger tests (no live Broker/Identity)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import connector_txt_read_routes as routes
from app.control_plane_identity import IdentityBridgeError
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

NOW = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)


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


class Csrf:
    def __init__(self, allowed=True):
        self.allowed = allowed
    def verify(self, request):
        del request
        return self.allowed


class FakeIdentity:
    def __init__(self, consent=None, connector_workspace="connector-ws-1"):
        self._consent = consent
        self._connector_workspace = connector_workspace
    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        del session_id
        if self._consent is None:
            raise RuntimeError("no consent")
        assert self._consent["device_id"] == device_id
        return dict(self._consent)
    async def resolve_connector_workspace(self, *, session_id):
        del session_id
        return self._connector_workspace


class FakeBrokerSource:
    configured = True
    def __init__(self, devices=None, enqueue=None):
        self._devices = devices
        self._enqueue = enqueue
        self.calls = []
    async def resolve_device_binding(self, *, account_ref, workspace_ref, device_id):
        self.calls.append(("resolve", account_ref, workspace_ref, device_id))
        if self._devices is None:
            raise IdentityBridgeError(503, "canonical_broker_unavailable", "unavailable")
        matches = [d for d in self._devices if d["device_id"] == device_id]
        if len(matches) != 1:
            raise IdentityBridgeError(404, "txt_device_unbound", "unbound")
        return dict(matches[0])
    async def installed_txt_execution_profile(self, *, account_ref, workspace_ref, device_id, binding_ref):
        self.calls.append(("profile", account_ref, workspace_ref, device_id, binding_ref))
        return r"C:\Python313\python.exe"
    async def enqueue_txt_read_command(self, *, command, material):
        self.calls.append(("enqueue", command["command_id"]))
        if self._enqueue is None:
            raise IdentityBridgeError(409, "txt_command_refused", "refused")
        assert command["binding_ref"] == self._enqueue["binding_ref"]
        assert material["p01_approval_payload"]["command_id"] == command["command_id"]
        return {"command_id": command["command_id"], "run_id": command["run_id"],
                "revision_ref": "revision.enqueued.1",
                "request_fingerprint": command["request_fingerprint"]}


class FakeHistory:
    def __init__(self, run=None):
        self._run = run
        self.correlations = []
    async def get_claw_run(self, user_id, run_id):
        del user_id
        return dict(self._run) if self._run is not None and self._run["run_id"] == run_id else None
    async def record_local_task_correlation(self, **kwargs):
        self.correlations.append(dict(kwargs))
        return True


def canonical_session():
    return AuthSessionSnapshot(
        session_id="session.canonical.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="subject.canonical.owner.1"),
        issued_at=NOW - timedelta(days=1), expires_at=NOW + timedelta(days=30),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.owner.1",
    )


def setup_auth(monkeypatch, user="product-user-1"):
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: user)
    monkeypatch.setattr(routes, "_verified_owner_request", _verified)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", _workspace)


async def _verified(request):
    del request
    return SimpleNamespace(session_id="session.canonical.owner.1"), None


async def _workspace(request, uid):
    del request, uid
    return "tenant-ws-1"


def state(*, broker=None, identity=None, history=None):
    return SimpleNamespace(
        connector_txt_read_source=broker or FakeBrokerSource(),
        control_plane_identity_authority=identity or FakeIdentity(),
        history_store=history or FakeHistory(),
    )


def consent(device="device-1"):
    return {
        "consent_id": "consent-1", "device_id": device,
        "owner_subject_id": "subject.canonical.owner.1",
        "account_ref": "account-canonical-1", "workspace_ref": "connector-ws-1",
        "granted_at": (NOW - timedelta(days=1)).isoformat(),
        "withdrawn_at": None,
    }


def devices():
    return [{"binding_ref": "binding-1", "device_id": "device-1",
             "credential_generation": 1}]


def run_row():
    return {"run_id": "run-conversation-1", "conversation_id": "conversation-1",
            "workspace_id": "tenant-ws-1", "status": "waiting"}


def body(**overrides):
    payload = {
        "device_id": "device-1", "root_ref": "root.docs",
        "path_relative": "notes\\report.txt",
        "run_id": "run-conversation-1", "confirmed": True,
    }
    payload.update(overrides)
    return payload


def test_confirmed_request_enqueues_through_existing_binding(monkeypatch):
    setup_auth(monkeypatch)
    broker = FakeBrokerSource(
        devices=devices(),
        enqueue={"binding_ref": "binding-1"},
    )
    history = FakeHistory(run_row())
    st = state(broker=broker,
               identity=FakeIdentity(consent()),
               history=history)
    status, result, headers = run(routes.connector_txt_read_request, Request(body(), st))
    assert status == 200 and result["ok"] is True
    assert result["command"]["run_id"] == "run-conversation-1"
    assert result["conversation_id"] == "conversation-1"
    assert headers["Cache-Control"].startswith("no-store")
    # Four realms stay distinct: product user (product-user-1) and tenant
    # workspace (tenant-ws-1) never leak into Broker calls, which use the
    # Identity-verified canonical account and connector workspace only.
    assert ("resolve", "account-canonical-1", "connector-ws-1", "device-1") in broker.calls
    assert any(call[0] == "enqueue" for call in broker.calls)
    assert history.correlations[0]["run_id"] == "run-conversation-1"
    assert history.correlations[0]["evidence_ref"] is None
    assert history.correlations[0]["command_id"] == result["command"]["command_id"]


def test_unconfirmed_or_malformed_body_is_refused(monkeypatch):
    setup_auth(monkeypatch)
    st = state(broker=FakeBrokerSource(devices=devices(), enqueue={"binding_ref": "binding-1"}),
               identity=FakeIdentity(consent()), history=FakeHistory(run_row()))
    assert run(routes.connector_txt_read_request, Request(body(confirmed=False), st))[0] == 400
    assert run(routes.connector_txt_read_request, Request(body(path_relative="notes.pdf"), st))[0] == 400
    assert run(routes.connector_txt_read_request, Request(body(run_id="run-foreign"), st))[0] == 404


def test_consent_withdrawn_unknown_device_or_missing_run_refused(monkeypatch):
    setup_auth(monkeypatch)
    withdrawn = consent()
    withdrawn["withdrawn_at"] = NOW.isoformat()
    st = state(broker=FakeBrokerSource(devices=devices(), enqueue={"binding_ref": "binding-1"}),
               identity=FakeIdentity(withdrawn), history=FakeHistory(run_row()))
    assert run(routes.connector_txt_read_request, Request(body(), st))[0] == 403
    st = state(broker=FakeBrokerSource(devices=[], enqueue={"binding_ref": "binding-1"}),
               identity=FakeIdentity(consent()), history=FakeHistory(run_row()))
    assert run(routes.connector_txt_read_request, Request(body(), st))[0] == 404
    st = state(broker=FakeBrokerSource(devices=devices(), enqueue={"binding_ref": "binding-1"}),
               identity=FakeIdentity(consent()), history=FakeHistory(None))
    assert run(routes.connector_txt_read_request, Request(body(), st))[0] == 404


def test_broker_refusal_is_409_without_secret_or_path_echo(monkeypatch):
    setup_auth(monkeypatch)
    st = state(broker=FakeBrokerSource(devices=devices(), enqueue=None),
               identity=FakeIdentity(consent()), history=FakeHistory(run_row()))
    status, result, _ = run(routes.connector_txt_read_request, Request(body(), st))
    assert status == 409 and result["ok"] is False
    assert "report.txt" not in json.dumps(result)


def test_unconfigured_source_fails_closed(monkeypatch):
    setup_auth(monkeypatch)
    st = state()
    st.connector_txt_read_source = routes.UnconfiguredTxtReadSource()
    assert run(routes.connector_txt_read_request, Request(body(), st))[0] == 503


class _DirectoryBroker(FakeBrokerSource):
    """Broker stub that only proves the owner-scope read happens first."""

    async def owner_device_directory(self, *, account_ref, workspace_ref):
        del account_ref, workspace_ref
        raise AssertionError("the owner-scope refusal must precede the directory")


def test_native_owner_scope_refusal_keeps_the_identity_code(monkeypatch):
    """#4139: the native lane hides the same Identity cause behind one code."""
    emitted: list[dict] = []
    monkeypatch.setattr(routes, "emit_stage_event", lambda **entry: emitted.append(entry))
    setup_auth(monkeypatch)

    class _RefusingIdentity:
        async def resolve_connector_owner_scope(self, *, session_id):
            del session_id
            raise IdentityBridgeError(
                503, "canonical_scope_not_established",
                "one established connector context required",
            )

    st = state(broker=_DirectoryBroker(), identity=_RefusingIdentity())
    device, denial = asyncio.run(
        routes.choose_verified_txt_device(Request(body(), st))
    )

    assert device is None
    assert denial.status_code == 503
    assert json.loads(denial.body)["error"]["code"] == "txt_read_device_directory_unavailable"
    assert emitted == [{
        "stage": "txt_read.owner_scope", "outcome": "error", "duration_ms": 0,
        "code": "canonical_scope_not_established",
    }]


def test_native_owner_scope_refusal_without_code_projects_no_code(monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(routes, "emit_stage_event", lambda **entry: emitted.append(entry))
    setup_auth(monkeypatch)

    class _OpaqueIdentity:
        async def resolve_connector_owner_scope(self, *, session_id):
            del session_id
            raise RuntimeError("raw backend text must never be projected")

    st = state(broker=_DirectoryBroker(), identity=_OpaqueIdentity())
    device, denial = asyncio.run(
        routes.choose_verified_txt_device(Request(body(), st))
    )

    assert device is None
    assert denial.status_code == 503
    assert emitted == [{
        "stage": "txt_read.owner_scope", "outcome": "error", "duration_ms": 0,
        "code": None,
    }]
    assert "raw backend text" not in json.dumps(emitted)
