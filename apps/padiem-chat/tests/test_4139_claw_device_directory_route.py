"""CENTRAL #4139: authenticated Web multi-PC list over canonical Broker."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH, CLAW_PC_SELECT_PATH, BrokerDeviceDirectorySource,
    build_broker_device_directory_source,
)
from app.config import Settings
from app.main import create_app

OWNER = "usr_4139_test"
BASE = "https://chat.example.test"
WORKSPACE = "owner:" + OWNER


def fact(device: str, *, state="paired_offline", account=OWNER, workspace=WORKSPACE):
    now = datetime.now(timezone.utc)
    return {
        "canonical_state": state,
        "binding": {
            "binding_ref": "bind_" + device, "device_id": device,
            "account_ref": account, "workspace_ref": workspace,
            "credential_generation": 1,
            "issued_at": (now - timedelta(days=2)).isoformat(),
            "credential_expires_at": (now + timedelta(days=30)).isoformat(),
        },
        "session": None, "heartbeat_last_seen_at": None,
        "credential": "NEVER_RENDER_ME", "stdout": "PRIVATE",
    }


class Binding:
    def __init__(self, rows=None, *, fail=False, available=True, scoped=True):
        self.rows = list(rows or [])
        self.calls = []
        self.fail = fail
        self.available = available
        self.scoped = scoped

    async def device_directory(self, payload):
        self.calls.append(dict(payload))
        if self.fail:
            raise RuntimeError("SECRET_INTERNAL_STORAGE_PATH")
        if not self.available:
            return {"ok": True, "available": False, "reason": "no_device_binding"}
        return {
            "ok": True, "available": True,
            "owner_scoped": self.scoped,
            "device_count": len(self.rows),
            "devices": self.rows,
            "request_id": "DO_NOT_EXPOSE",
        }


def make_app(binding=None, selection_store=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="4139-device-list-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    source = BrokerDeviceDirectorySource(binding) if binding is not None else None
    app = create_app(
        settings, history_store=MagicMock(), claw_device_directory_source=source,
        claw_pc_device_selection_store=selection_store,
    )
    return app, settings


def get(app, settings, *, signed=True, query=None, user=OWNER):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if signed:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, user))
            return await client.get(CLAW_DEVICE_DIRECTORY_PATH, params=query)
    return asyncio.run(perform())


def test_auth_required_and_query_scope_injection_denied():
    binding = Binding([fact("office")])
    app, settings = make_app(binding)
    response = get(app, settings, signed=False)
    assert response.status_code == 401
    assert binding.calls == []
    response = get(app, settings, query={"account_ref": "victim", "workspace_ref": "victim"})
    assert response.status_code == 400
    assert binding.calls == []


def test_unconfigured_cannot_pretend_zero_devices():
    app, settings = make_app()
    response = get(app, settings)
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "devices" not in response.json()
    assert response.headers["cache-control"].startswith("no-store")


def test_empty_broker_directory_is_authoritatively_empty():
    binding = Binding(available=False)
    app, settings = make_app(binding)
    response = get(app, settings)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "available": True, "ownerScoped": True, "devices": []}
    assert binding.calls == [{"account_ref": OWNER, "workspace_ref": WORKSPACE}]


def test_two_devices_sorted_secret_free_no_implicit_executor():
    binding = Binding([fact("office"), fact("home")])
    app, settings = make_app(binding)
    response = get(app, settings)
    assert response.status_code == 200
    result = response.json()
    assert [x["deviceId"] for x in result["devices"]] == ["home", "office"]
    assert all(x["state"] == "OFFLINE" and x["usable"] is False for x in result["devices"])
    assert all(x["deviceName"] is None and x["platform"] is None for x in result["devices"])
    assert all(key not in response.text for key in ("PRIVATE", "NEVER_RENDER_ME", OWNER, WORKSPACE, "DO_NOT_EXPOSE", "bind_home"))
    assert binding.calls == [{"account_ref": OWNER, "workspace_ref": WORKSPACE}]


@pytest.mark.parametrize("broken", [
    [fact("pc", account="other-owner")],
    [fact("pc", workspace="other-workspace")],
    [fact("duplicate"), fact("duplicate")],
    [fact("bad/path")],
    [fact("pc") for _ in range(25)],
])
def test_invalid_scoped_broker_rows_fail_closed(broken):
    binding = Binding(broken)
    app, settings = make_app(binding)
    data = get(app, settings).json()
    assert data["available"] is False
    assert "devices" not in data


def test_revocation_expiry_and_bad_session_do_not_become_online():
    binding = Binding([fact("revoked", state="revoked"),
                       fact("expired", state="credential_expired"), fact("stale")])
    app, settings = make_app(binding)
    data = get(app, settings).json()
    items = {x["deviceId"]: x for x in data["devices"]}
    assert items["revoked"]["state"] == "REVOKED"
    assert items["revoked"]["revoked"] is True
    assert items["expired"]["expired"] is True
    assert all(x["usable"] is False for x in items.values())


def test_broker_failure_and_unscoped_claim_do_not_expose_devices():
    for binding in [Binding([fact("pc")], fail=True), Binding([fact("pc")], scoped=False)]:
        app, settings = make_app(binding)
        data = get(app, settings).json()
        assert data["available"] is False
        assert "devices" not in data


def test_runtime_composition_requires_true_broker_rpc():
    assert build_broker_device_directory_source({}) is None
    class FakeBinding:
        def fetch(self, *args):
            raise AssertionError
    assert build_broker_device_directory_source({"LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": FakeBinding()}) is None
    source = build_broker_device_directory_source(
        {"LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": Binding([fact("pc")])}
    )
    assert isinstance(source, BrokerDeviceDirectorySource)


def test_recent_canonical_session_and_heartbeat_projects_connected():
    now = datetime.now(timezone.utc)
    row = fact("active")
    issued = now - timedelta(minutes=5)
    expiry = now + timedelta(minutes=35)
    row["session"] = {
        "session_id": "sess_active",
        "binding_ref": "bind_active",
        "device_id": "active",
        "account_ref": OWNER,
        "workspace_ref": WORKSPACE,
        "credential_generation": 1,
        "issued_at": issued.isoformat(),
        "expires_at": expiry.isoformat(),
    }
    row["heartbeat_last_seen_at"] = (now - timedelta(seconds=2)).isoformat()
    binding = Binding([row])
    app, settings = make_app(binding)
    response = get(app, settings)
    assert response.status_code == 200
    assert response.json()["devices"][0]["state"] == "CONNECTED"
    assert response.json()["devices"][0]["usable"] is True
    assert "sess_active" not in response.text
    assert "bind_active" not in response.text


def test_forged_online_claim_without_canonical_evidence_is_ignored():
    row = fact("fake")
    row["state"] = "CONNECTED"
    row["usable"] = True
    row["online"] = True
    binding = Binding([row])
    app, settings = make_app(binding)
    result = get(app, settings).json()["devices"][0]
    assert result["state"] == "OFFLINE"
    assert result["usable"] is False


def test_http_response_is_second_closed_secret_free_projection_boundary():
    class ExtraFieldSource:
        configured = True
        async def list_devices(self, **kwargs):
            return [{
                "deviceId": "pc", "deviceName": "PC", "platform": "Windows",
                "state": "CONNECTED", "usable": True, "revoked": False,
                "expired": False, "credential": "SECRET_EXTRA", "session_id": "SESSION_PRIVATE",
            }]
    app, settings = make_app()
    app.state.claw_device_directory_source = ExtraFieldSource()
    response = get(app, settings)
    assert response.status_code == 200
    assert response.json()["devices"][0] == {
        "deviceId": "pc", "deviceName": "PC", "platform": "Windows",
        "state": "CONNECTED", "usable": True, "revoked": False, "expired": False,
    }
    assert "SECRET_EXTRA" not in response.text
    assert "SESSION_PRIVATE" not in response.text


def test_http_contradictory_connected_or_malformed_source_cannot_claim_success():
    class Malformed:
        configured = True
        def __init__(self, row):
            self.row = row
        async def list_devices(self, **kwargs):
            return [self.row]
    for row in (
        {"deviceId": "a", "state": "CONNECTED", "usable": False, "revoked": False, "expired": False},
        {"deviceId": "a", "state": "CONNECTED", "usable": True, "revoked": True, "expired": False},
        {"deviceId": "a", "state": "MAGIC", "usable": False, "revoked": False, "expired": False},
        # Malformed nested JSON values must return a bounded unavailable envelope,
        # not throw TypeError (HTTP 500) inside the server projection.
        {"deviceId": "a", "state": ["CONNECTED"], "usable": True, "revoked": False, "expired": False},
        {"deviceId": "a", "state": {"value": "CONNECTED"}, "usable": True, "revoked": False, "expired": False},
    ):
        app, settings = make_app()
        app.state.claw_device_directory_source = Malformed(row)
        result = get(app, settings).json()
        assert result["available"] is False
        assert "devices" not in result

class UsageBinding(Binding):
    def __init__(self):
        super().__init__([fact("office")])
        self.paused = False
        self.writes = []

    async def device_directory(self, payload):
        response = await super().device_directory(payload)
        response["usage_paused"] = self.paused
        return response

    async def set_owner_usage(self, payload):
        self.writes.append(dict(payload))
        self.paused = payload["paused"]
        return {"ok": True, "paused": self.paused, "dispatch_authorized": not self.paused}


def _post_usage(app, settings, path, *, signed=True, origin=BASE, json_body=None):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if signed:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER))
            return await client.post(path, headers={"Origin": origin}, json=json_body)
    return asyncio.run(perform())


def test_paused_usage_is_owner_scoped_and_matches_durable_broker_readback():
    from app.claw_device_directory_routes import CLAW_PC_PAUSE_PATH, CLAW_PC_RESUME_PATH
    binding = UsageBinding()
    app, settings = make_app(binding)
    assert get(app, settings).json()["usagePaused"] is False
    response = _post_usage(app, settings, CLAW_PC_PAUSE_PATH)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "usagePaused": True}
    assert binding.writes == [{"account_ref": OWNER, "workspace_ref": WORKSPACE, "paused": True}]
    assert get(app, settings).json()["usagePaused"] is True
    response = _post_usage(app, settings, CLAW_PC_RESUME_PATH)
    assert response.status_code == 200, response.text
    assert get(app, settings).json()["usagePaused"] is False


def test_paused_usage_rejects_guest_cross_origin_and_client_selected_scope():
    from app.claw_device_directory_routes import CLAW_PC_PAUSE_PATH
    binding = UsageBinding()
    app, settings = make_app(binding)
    assert _post_usage(app, settings, CLAW_PC_PAUSE_PATH, signed=False).status_code == 401
    assert _post_usage(app, settings, CLAW_PC_PAUSE_PATH, origin="https://evil.example.test").status_code == 403
    assert _post_usage(app, settings, CLAW_PC_PAUSE_PATH, json_body={"device_id": "office"}).status_code == 403
    assert binding.writes == []
    assert get(app, settings).json()["usagePaused"] is False


def test_pause_missing_private_rpc_never_fabricates_off():
    from app.claw_device_directory_routes import CLAW_PC_PAUSE_PATH
    app, settings = make_app(Binding([fact("office")]))
    response = _post_usage(app, settings, CLAW_PC_PAUSE_PATH)
    assert response.status_code == 503
    assert response.json()["ok"] is False


# ── #5015: saved target preference (server restore, never a grant) ─────────


def active_fact(device):
    now = datetime.now(timezone.utc)
    row = fact(device)
    row["session"] = {
        "session_id": "sess_" + device,
        "binding_ref": "bind_" + device,
        "device_id": device,
        "account_ref": OWNER,
        "workspace_ref": WORKSPACE,
        "credential_generation": 1,
        "issued_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(minutes=35)).isoformat(),
    }
    row["heartbeat_last_seen_at"] = (now - timedelta(seconds=2)).isoformat()
    return row


class SelectionStore:
    def __init__(self, rows=None, *, fail=False):
        self.rows = dict(rows or {})
        self.fail = fail
        self.saves = []

    async def load(self, *, owner_id, workspace_id):
        return self.rows.get((owner_id, workspace_id))

    async def save(self, *, owner_id, workspace_id, device_id, now):
        self.saves.append((owner_id, workspace_id, device_id))
        if self.fail:
            return False
        self.rows[(owner_id, workspace_id)] = device_id
        return True


def post_select(
    app, settings, *, user=OWNER, body=None, origin=BASE,
    content_type="application/json", raw=None,
):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if user is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, user),
                                   domain="chat.example.test", path="/")
            headers = {}
            if origin is not None:
                headers["Origin"] = origin
            if content_type is not None:
                headers["Content-Type"] = content_type
            payload = raw if raw is not None else (
                json.dumps(body, ensure_ascii=False) if body is not None else None
            )
            return await client.post(CLAW_PC_SELECT_PATH, headers=headers, content=payload)
    return asyncio.run(perform())


def test_selection_is_saved_and_restored_for_the_owner():
    store = SelectionStore()
    app, settings = make_app(Binding([active_fact("office")]), selection_store=store)
    saved = post_select(app, settings, body={"device_id": "office"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "ok": True, "selectedDeviceId": "office",
        "selectedUsable": True, "selectedState": "CONNECTED",
    }
    assert store.saves == [(OWNER, WORKSPACE, "office")]
    restored = get(app, settings).json()
    assert restored["selectedDeviceId"] == "office"
    assert restored["selectedUsable"] is True
    assert restored["selectedState"] == "CONNECTED"


def test_selection_store_failure_is_never_reported_as_saved():
    app, settings = make_app(
        Binding([active_fact("office")]), selection_store=SelectionStore(fail=True),
    )
    response = post_select(app, settings, body={"device_id": "office"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pc_selection_not_confirmed"


def test_stale_selection_is_reported_not_substituted():
    store = SelectionStore({(OWNER, WORKSPACE): "gone"})
    app, settings = make_app(Binding([active_fact("office")]), selection_store=store)
    data = get(app, settings).json()
    assert data["selectedDeviceId"] == "gone"
    assert data["selectedUsable"] is False
    assert data["selectedState"] == "NOT_REGISTERED"
    # The only visible device is not promoted to the saved target.
    assert [item["deviceId"] for item in data["devices"]] == ["office"]


def test_offline_stored_selection_is_not_usable():
    store = SelectionStore({(OWNER, WORKSPACE): "office"})
    app, settings = make_app(Binding([fact("office")]), selection_store=store)
    data = get(app, settings).json()
    assert data["selectedDeviceId"] == "office"
    assert data["selectedUsable"] is False
    assert data["selectedState"] == "OFFLINE"


def test_selection_rejects_foreign_offline_guest_origin_and_malformed_bodies():
    store = SelectionStore()
    app, settings = make_app(
        Binding([active_fact("office"), fact("laptop")]), selection_store=store,
    )
    assert post_select(app, settings, body={"device_id": "foreign"}).json()["error"]["code"] == "pc_selection_not_owned"
    offline = post_select(app, settings, body={"device_id": "laptop"})
    assert offline.status_code == 409
    assert offline.json()["error"]["code"] == "pc_selection_not_online"
    assert post_select(app, settings, user=None, body={"device_id": "office"}).status_code == 401
    rejected = post_select(app, settings, body={"device_id": "office"}, origin="https://evil.example.test")
    assert rejected.status_code == 403
    extra = post_select(app, settings, body={"device_id": "office", "account_ref": "victim"})
    assert extra.status_code == 422
    non_json = post_select(app, settings, raw="device_id=office", content_type="text/plain")
    assert non_json.status_code == 415
    assert store.saves == []


def test_selection_is_owner_scoped_and_absent_for_another_account():
    store = SelectionStore({(OWNER, WORKSPACE): "office"})
    owner_app, owner_settings = make_app(
        Binding([active_fact("office")]), selection_store=store,
    )
    assert get(owner_app, owner_settings).json()["selectedDeviceId"] == "office"

    other = "usr_" + "9" * 32
    other_app, other_settings = make_app(Binding(available=False), selection_store=store)
    other_data = get(other_app, other_settings, user=other).json()
    assert other_data["available"] is True and other_data["devices"] == []
    assert "selectedDeviceId" not in other_data
    assert store.rows == {(OWNER, WORKSPACE): "office"}


# ── #5015: Broker-empty / Mesh-target reconciliation in the directory ──────


class _MeshTarget:
    configured = True
    execution_mode = "mesh"

    def __init__(self, row):
        self.row = row

    def command_target(self, *, account_ref, device_id=None):
        del account_ref, device_id
        return dict(self.row)


class _ScopeIdentity:
    async def resolve_connector_owner_scope(self, *, session_id):
        del session_id
        return {"account_ref": "acct-1", "workspace_ref": "ws-connector"}


MESH_ONLY = {"account_ref": "acct-1", "device_id": None,
             "node_ref": "mesh-node", "command_exec": True}


def _mesh_app(binding, *, mesh_row=None, store=None):
    app, settings = make_app(binding, selection_store=store)
    app.state.oracle_mesh_return_source = _MeshTarget(mesh_row or MESH_ONLY)
    app.state.control_plane_identity_authority = _ScopeIdentity()
    return app, settings


def _mesh_patches():
    return (
        patch("app.claw_device_directory_routes._resolve_memory_workspace",
              new=AsyncMock(return_value=WORKSPACE)),
        patch("app.pc_work_context._resolve_owner_session",
              new=AsyncMock(return_value=(WORKSPACE, SimpleNamespace(session_id="sess-1")))),
    )


def test_mesh_only_target_is_listed_selectable_and_saved():
    from app.claw_device_directory_routes import CLAW_PC_SELECT_PATH
    store = SelectionStore()
    app, settings = _mesh_app(Binding(available=False), store=store)
    p1, p2 = _mesh_patches()
    with p1, p2:
        data = get(app, settings).json()
        assert data["available"] is True
        row = next(item for item in data["devices"] if item["deviceId"] == "mesh-node")
        assert row["state"] == "ACTION_REQUIRED"
        assert row["usable"] is False
        assert row["executable"] is True
        assert row["selectable"] is True
        assert "selectedDeviceId" not in data
        saved = post_select(app, settings, body={"device_id": "mesh-node"})
    assert saved.status_code == 200, saved.text
    assert store.saves == [(OWNER, WORKSPACE, "mesh-node")]


def test_broker_row_keeps_explicit_offline_and_revoked_truth():
    for row, expected in (
        (fact("mesh-node"), "OFFLINE"),
        (fact("mesh-node", state="revoked"), "REVOKED"),
    ):
        app, settings = _mesh_app(Binding([row]))
        p1, p2 = _mesh_patches()
        with p1, p2:
            data = get(app, settings).json()
        item = next(x for x in data["devices"] if x["deviceId"] == "mesh-node")
        assert item["state"] == expected
        assert item["executable"] is True
        assert item["selectable"] is False


def test_matching_online_broker_row_is_marked_executable_and_selectable():
    app, settings = _mesh_app(Binding([active_fact("mesh-node")]))
    p1, p2 = _mesh_patches()
    with p1, p2:
        data = get(app, settings).json()
    item = next(x for x in data["devices"] if x["deviceId"] == "mesh-node")
    assert item["state"] == "CONNECTED"
    assert item["executable"] is True
    assert item["selectable"] is True
