"""#4139/#4434 B66 GET-only product PC scope and default-OFF regression."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation, ProductPcAccessGrant, ProductPcAccessPolicy,
)
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_pc_directory_routes import B66_PC_DIRECTORY_PATH
from app.claw_device_directory_routes import BrokerDeviceDirectorySource
from app.config import Settings
from app.main import create_app

OWNER = "usr_4434_owner"
OTHER = "usr_4434_other"
WORKSPACE = "owner:" + OWNER
BASE = "https://chat.example.test"


def fake_facts(device_id: str, owner: str = OWNER, workspace: str = WORKSPACE, *,
               state="paired_offline", online=False):
    now = datetime.now(timezone.utc)
    facts = {
        "canonical_state": state,
        "binding": {
            "binding_ref": "bind_" + device_id,
            "device_id": device_id,
            "account_ref": owner,
            "workspace_ref": workspace,
            "credential_generation": 1,
            "issued_at": (now - timedelta(days=1)).isoformat(),
            "credential_expires_at": (now + timedelta(days=30)).isoformat(),
        },
        "session": None,
        "heartbeat_last_seen_at": None,
        "private_key": "DO_NOT_LEAK_BROKER_SECRET",
    }
    if online:
        facts["session"] = {
            "session_id": "sess_" + device_id,
            "binding_ref": "bind_" + device_id,
            "device_id": device_id,
            "account_ref": owner,
            "workspace_ref": workspace,
            "credential_generation": 1,
            "issued_at": (now - timedelta(minutes=2)).isoformat(),
            "expires_at": (now + timedelta(minutes=20)).isoformat(),
        }
        facts["heartbeat_last_seen_at"] = (now - timedelta(seconds=2)).isoformat()
    return facts


class BrokerPort:
    def __init__(self, facts=None, *, scoped=True):
        self.facts = [fake_facts("pc-one")] if facts is None else facts
        self.calls = []
        self.scoped = scoped

    async def device_directory(self, payload):
        self.calls.append(dict(payload))
        return {
            "ok": True, "available": True, "owner_scoped": self.scoped,
            "device_count": len(self.facts), "devices": self.facts,
            "internal_token": "DO_NOT_LEAK_BROKER_SECRET",
        }


def product_policy(*, workspace=WORKSPACE, ops=(PcAccessOperation.DEVICE_LIST,)):
    return ProductPcAccessPolicy(grants=(
        ProductPcAccessGrant(
            product_id="b66", operations=frozenset(ops), workspace_ref=workspace,
        ),
    ))


def configured_app(port=None, *, policy=None, membership=False, member_store=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password",
        public_base_url=BASE,
        session_secret="4434-b66-pc-product-scope-test-session-secret",
        session_max_age_seconds=3600,
        b66_quote_base_url="https://quote.example.test",
    )
    port = port or BrokerPort()
    app = create_app(
        settings=settings, history_store=MagicMock(),
        claw_device_directory_source=BrokerDeviceDirectorySource(port),
        b66_pc_access_policy=policy,
    )
    app.state.b66_membership_enforced = membership
    if member_store is not None:
        app.state.b66_member_admin_store = member_store
    return app, settings, port


def req(app, settings, path=B66_PC_DIRECTORY_PATH, *, owner=OWNER, query=None):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if owner is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner))
            return await client.get(path, params=query)
    return asyncio.run(run())


def test_default_off_does_not_read_broker_or_expose_ui_hint():
    app, settings, port = configured_app()
    response = req(app, settings)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "available": False, "reason": "b66_pc_not_enabled",
    }
    assert response.headers["cache-control"].startswith("private, no-store")
    config = req(app, settings, "/api/b66/runtime-config")
    assert config.status_code == 200
    assert "pc_device_list_enabled" not in config.json()
    assert port.calls == []


def test_anon_denied_and_query_cannot_control_authority():
    app, settings, port = configured_app(policy=product_policy())
    assert req(app, settings, owner=None).status_code == 401
    assert req(app, settings, query={"workspace_ref": "owner:foreign"}).status_code == 400
    assert req(app, settings, query={"product_id": "claw"}).status_code == 400
    assert port.calls == []


@pytest.mark.parametrize("policy", [
    None,
    ProductPcAccessPolicy.default_off(),
    product_policy(workspace=None),
    product_policy(workspace="owner:another"),
    product_policy(ops=(PcAccessOperation.TASK_STATUS,)),
])
def test_wrong_unscoped_or_missing_grant_never_reads_broker(policy):
    app, settings, port = configured_app(policy=policy)
    assert req(app, settings).json()["available"] is False
    assert "pc_device_list_enabled" not in req(app, settings, "/api/b66/runtime-config").json()
    assert port.calls == []


def test_exact_grant_returns_secret_free_canonical_owner_list_and_hint():
    port = BrokerPort([
        fake_facts("pc-z", online=True),
        fake_facts("pc-a", state="revoked"),
    ])
    app, settings, _ = configured_app(port, policy=product_policy())
    config = req(app, settings, "/api/b66/runtime-config")
    assert config.status_code == 200
    assert config.json()["pc_device_list_enabled"] is True
    response = req(app, settings)
    assert response.status_code == 200
    assert response.json()["ownerScoped"] is True
    assert [x["deviceId"] for x in response.json()["devices"]] == ["pc-a", "pc-z"]
    assert response.json()["devices"][1]["state"] == "CONNECTED"
    assert response.json()["devices"][0]["state"] == "REVOKED"
    assert all(k not in response.text for k in (
        "DO_NOT_LEAK", "session_id", "account_ref", "workspace_ref",
        "binding_ref", "product_policy",
    ))
    assert port.calls == [{"account_ref": OWNER, "workspace_ref": WORKSPACE}]


def test_other_owner_cannot_use_exact_owner_workspace_grant():
    app, settings, port = configured_app(policy=product_policy())
    response = req(app, settings, owner=OTHER)
    assert response.json()["available"] is False
    assert "pc_device_list_enabled" not in req(
        app, settings, "/api/b66/runtime-config", owner=OTHER,
    ).json()
    assert port.calls == []


def test_unconfigured_canonical_source_keeps_ui_and_route_off():
    app, settings, _ = configured_app(policy=product_policy())
    app.state.claw_device_directory_source = None
    assert req(app, settings).json()["available"] is False
    assert "pc_device_list_enabled" not in req(app, settings, "/api/b66/runtime-config").json()


def test_product_membership_required_when_enforced():
    class MemberStore:
        def __init__(self, status): self.status = status
        async def runtime_access(self, uid):
            assert uid == OWNER
            return {"status": self.status}

    app, settings, port = configured_app(
        policy=product_policy(), membership=True, member_store=MemberStore("pending")
    )
    assert req(app, settings).json()["available"] is False
    assert "pc_device_list_enabled" not in req(app, settings, "/api/b66/runtime-config").json()
    assert port.calls == []
    app.state.b66_member_admin_store = MemberStore("approved")
    assert req(app, settings).json()["available"] is True
    assert port.calls == [{"account_ref": OWNER, "workspace_ref": WORKSPACE}]


def test_broker_unscoped_or_foreign_row_fails_closed_without_leaks():
    for port in (
        BrokerPort(scoped=False),
        BrokerPort([fake_facts("foreign", owner=OTHER, workspace="owner:" + OTHER)]),
    ):
        app, settings, _ = configured_app(port, policy=product_policy())
        response = req(app, settings)
        assert response.status_code == 200
        assert response.json()["available"] is False
        assert "devices" not in response.json()
        assert "DO_NOT_LEAK" not in response.text


def test_new_endpoint_never_authorizes_pc_execution_or_mutation():
    from app.b66_pc_directory_routes import (
        B66_PC_MUTATION, B66_PC_DISPATCH_AUTHORIZED,
        B66_PC_PRODUCTION_DEFAULT, B66_PC_SECOND_DEVICE_AUTHORITY,
    )
    assert B66_PC_MUTATION is False
    assert B66_PC_DISPATCH_AUTHORIZED is False
    assert B66_PC_PRODUCTION_DEFAULT == "off"
    assert B66_PC_SECOND_DEVICE_AUTHORITY is False
    app, _, _ = configured_app()
    methods = [
        item.methods for item in app.routes
        if getattr(item, "path", "") == B66_PC_DIRECTORY_PATH
    ]
    assert methods == [{"GET", "HEAD"}] or methods == [{"GET"}]
