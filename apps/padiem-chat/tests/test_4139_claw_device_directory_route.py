"""CENTRAL #4139: authenticated Web multi-PC list over canonical Broker."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH, BrokerDeviceDirectorySource,
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


def make_app(binding=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="4139-device-list-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    source = BrokerDeviceDirectorySource(binding) if binding is not None else None
    app = create_app(settings, history_store=MagicMock(), claw_device_directory_source=source)
    return app, settings


def get(app, settings, *, signed=True, query=None):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if signed:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER))
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
