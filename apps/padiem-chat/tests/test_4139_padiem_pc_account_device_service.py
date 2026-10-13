"""Account-wide PC listing stays private, source-only and fail-closed."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.padiem_pc_account_device_service import (
    PADIEM_PC_ACCOUNT_DEFAULT_READ_ENABLED,
    PADIEM_PC_ACCOUNT_READ_ROUTE_MOUNTED,
    PADIEM_PC_ACCOUNT_REVOKE_ROUTE_MOUNTED,
    PadiemPcAccountDeviceService,
    PrivateCanonicalBrokerDirectoryReader,
    VerifiedPcOwnerContext,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation, ProductPcAccessGrant, ProductPcAccessPolicy,
)
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentScope
from padiem_control_plane.tenants import TenantMembershipRole

NOW = datetime.now(timezone.utc)
CLAW = "b54-padiem-claw"
QUOTE = "b66-padiem-quote"


def owner(product=CLAW, role=TenantMembershipRole.OWNER):
    return VerifiedPcOwnerContext(
        session=AuthSessionSnapshot(
            session_id="session.owner",
            product_id=product,
            subject=CanonicalSubjectRef(
                subject_type=SubjectType.USER, subject_id="subject.owner",
            ),
            tenant_id="tenant.owner",
            issued_at=NOW-timedelta(minutes=5),
            expires_at=NOW+timedelta(days=30),
            state=AuthSessionState.ACTIVE,
        ),
        membership_role=role,
        scope=ConnectorEnrollmentScope(
            owner_subject_id="subject.owner",
            account_ref="account.owner",
            workspace_ref="workspace.owner",
        ),
    )


def directory():
    return {
        "ok": True, "available": True, "owner_scoped": True,
        "device_count": 1, "max_devices": 24,
        "devices": [{
            "canonical_state": "paired_offline",
            "binding": {
                "binding_ref": "binding.one",
                "device_id": "pc.one",
                "account_ref": "account.owner",
                "workspace_ref": "workspace.owner",
            },
            "session": None,
            "heartbeat_last_seen_at": None,
        }],
    }


class Identity:
    def __init__(self, context=None, fails=False):
        self.context = context or owner()
        self.calls = []
        self.fails = fails

    async def resolve_current_owner_context(self, *, canonical_session_id):
        self.calls.append(canonical_session_id)
        if self.fails:
            raise RuntimeError("private test owner secret")
        return self.context


class Broker:
    def __init__(self, reply=None, fails=False):
        self.reply = directory() if reply is None else reply
        self.calls = []
        self.fails = fails

    async def device_directory(self, *, account_ref, workspace_ref):
        self.calls.append((account_ref, workspace_ref))
        if self.fails:
            raise RuntimeError("private test broker secret")
        return self.reply


class Stub:
    def __init__(self):
        self.calls = []

    async def device_directory(self, payload):
        self.calls.append(payload)
        return directory()


def execute(identity=None, broker=None, enabled=True):
    i = identity or Identity()
    b = broker or Broker()
    return PadiemPcAccountDeviceService(
        identity=i, broker=b, read_enabled=enabled,
    ), i, b


def test_production_defaults_off_and_no_mutation_route():
    assert PADIEM_PC_ACCOUNT_DEFAULT_READ_ENABLED is False
    assert PADIEM_PC_ACCOUNT_READ_ROUTE_MOUNTED is False
    assert PADIEM_PC_ACCOUNT_REVOKE_ROUTE_MOUNTED is False
    service, identity, broker = execute(enabled=False)
    response = asyncio.run(service.list_account_devices(canonical_session_id="session.owner"))
    assert response["ok"] is False and response["devices"] == []
    assert identity.calls == [] and broker.calls == []


def test_account_owner_list_uses_existing_identity_and_broker_scope_once():
    service, identity, broker = execute()
    result = asyncio.run(service.list_account_devices(canonical_session_id="session.owner"))
    assert identity.calls == ["session.owner"]
    assert broker.calls == [("account.owner", "workspace.owner")]
    assert result["ok"] is True
    assert result["devices"][0]["device_id"] == "pc.one"
    assert result["devices"][0]["canonical_state"] == "paired_offline"
    assert result["dispatch_authorized"] is False
    for hidden in ("account.owner", "workspace.owner", "session.owner", "binding.one", "credential"):
        assert hidden not in repr(result)


@pytest.mark.parametrize("ctx", [
    owner(product="b66-padiem-quote"),
    owner(role=TenantMembershipRole.VIEWER),
    owner(role=TenantMembershipRole.OPERATOR),
])
def test_denied_product_or_membership_never_calls_broker(ctx):
    service, identity, broker = execute(identity=Identity(context=ctx))
    result = asyncio.run(service.list_account_devices(canonical_session_id="session.owner"))
    assert result["devices"] == []
    assert result["ok"] is False
    assert broker.calls == []


def test_current_owner_identity_error_never_leaks_or_calls_broker():
    service, _, broker = execute(identity=Identity(fails=True))
    result = asyncio.run(service.list_account_devices(canonical_session_id="session.owner"))
    assert result["ok"] is False
    assert broker.calls == []
    assert "secret" not in repr(result)


def test_broker_error_never_leaks_account_or_credentials():
    service, _, broker = execute(broker=Broker(fails=True))
    result = asyncio.run(service.list_account_devices(canonical_session_id="session.owner"))
    assert broker.calls == [("account.owner", "workspace.owner")]
    assert result["ok"] is False and result["devices"] == []
    assert "secret" not in repr(result)


def test_default_off_product_cannot_see_device_visible_in_my_devices():
    service, _, _ = execute()
    result = asyncio.run(service.list_product_devices(
        canonical_session_id="session.owner",
        product_id=QUOTE,
        server_policy=ProductPcAccessPolicy.default_off(),
    ))
    assert result["available"] is False
    assert result["devices"] == []


def test_server_configured_same_product_list_grant_never_grants_read_write():
    service, _, _ = execute()
    policy = ProductPcAccessPolicy(grants=(
        ProductPcAccessGrant(
            product_id=CLAW, workspace_ref="workspace.owner",
            operations=frozenset({PcAccessOperation.DEVICE_LIST}),
        ),
    ))
    result = asyncio.run(service.list_product_devices(
        canonical_session_id="session.owner", product_id=CLAW,
        server_policy=policy,
    ))
    assert result["available"] is True
    assert result["devices"][0]["device_id"] == "pc.one"
    assert result["dispatch_authorized"] is False


def test_quote_grant_never_converts_a_claw_login_into_quote_pc_visibility():
    service, identity, broker = execute()
    policy = ProductPcAccessPolicy(grants=(
        ProductPcAccessGrant(
            product_id=QUOTE, workspace_ref="workspace.owner",
            operations=frozenset({PcAccessOperation.DEVICE_LIST}),
        ),
    ))
    result = asyncio.run(service.list_product_devices(
        canonical_session_id="session.owner", product_id=QUOTE,
        server_policy=policy,
    ))
    assert result["ok"] is False
    assert result["devices"] == []
    assert identity.calls == ["session.owner"]
    assert broker.calls == []


def test_broker_binding_reader_uses_private_closed_scoped_rpc_only():
    bridge = Stub()
    reader = PrivateCanonicalBrokerDirectoryReader(bridge)
    value = asyncio.run(reader.device_directory(
        account_ref="account.owner", workspace_ref="workspace.owner",
    ))
    assert value == directory()
    assert bridge.calls == [{
        "account_ref": "account.owner", "workspace_ref": "workspace.owner",
    }]


def test_service_rejects_incorrect_or_missing_input_without_identity_call():
    service, identity, broker = execute()
    response = asyncio.run(service.list_account_devices(canonical_session_id=""))
    assert response["ok"] is False
    assert identity.calls == [] and broker.calls == []


def test_private_reader_does_not_fallback_to_http_if_binding_missing_rpc():
    reader = PrivateCanonicalBrokerDirectoryReader(SimpleNamespace())
    with pytest.raises(RuntimeError):
        asyncio.run(reader.device_directory(
            account_ref="account.owner", workspace_ref="workspace.owner",
        ))
