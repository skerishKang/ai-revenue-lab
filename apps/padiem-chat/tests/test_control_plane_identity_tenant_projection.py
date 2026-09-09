from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority


NOW = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
TENANT_ID = "tenant_0123456789abcdef0123456789abcdef"


def _session_wire(*, tenant_id=...):
    wire = {
        "session_id": "authsession:b62:tenant-test",
        "product_id": "b62",
        "subject": {
            "subject_type": "user",
            "subject_id": "subject:padiem:user:tenant-test",
        },
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "state": "active",
        "revision": 3,
    }
    if tenant_id is not ...:
        wire["tenant_id"] = tenant_id
    return wire


class _Binding:
    def __init__(self, wire):
        self.wire = wire
        self.payloads = []

    async def resolve_auth_session(self, payload):
        self.payloads.append(dict(payload))
        return {"ok": True, "session": dict(self.wire)}


async def test_tenant_aware_session_is_accepted_and_preserved() -> None:
    binding = _Binding(_session_wire(tenant_id=TENANT_ID))
    authority = CloudflareControlPlaneIdentityAuthority(binding)

    session = await authority.resolve_auth_session(session_id="authsession:b62:tenant-test")

    assert session.tenant_id == TENANT_ID
    assert session.product_id == "b62"
    assert session.subject.subject_id == "subject:padiem:user:tenant-test"
    assert binding.payloads == [{"session_id": "authsession:b62:tenant-test"}]


async def test_legacy_session_without_tenant_remains_compatible() -> None:
    authority = CloudflareControlPlaneIdentityAuthority(_Binding(_session_wire()))

    session = await authority.resolve_auth_session(session_id="authsession:b62:tenant-test")

    assert session.tenant_id is None


@pytest.mark.parametrize(
    "tenant_id",
    [
        "b62",
        "subject:padiem:user:tenant-test",
        "tenant id with spaces",
        "",
        None,
    ],
)
async def test_invalid_tenant_projection_fails_closed(tenant_id) -> None:
    authority = CloudflareControlPlaneIdentityAuthority(
        _Binding(_session_wire(tenant_id=tenant_id))
    )

    with pytest.raises(IdentityBridgeError) as raised:
        await authority.resolve_auth_session(session_id="authsession:b62:tenant-test")

    assert raised.value.status_code == 503
    assert raised.value.code == "control_plane_rpc_invalid"


async def test_arbitrary_session_wire_expansion_remains_rejected() -> None:
    wire = _session_wire(tenant_id=TENANT_ID)
    wire["workspace_id"] = "browser-or-rpc-invented-workspace"
    authority = CloudflareControlPlaneIdentityAuthority(_Binding(wire))

    with pytest.raises(IdentityBridgeError) as raised:
        await authority.resolve_auth_session(session_id="authsession:b62:tenant-test")

    assert raised.value.status_code == 503
    assert raised.value.code == "control_plane_rpc_invalid"


async def test_resolve_payload_never_accepts_caller_tenant_authority() -> None:
    binding = _Binding(_session_wire(tenant_id=TENANT_ID))
    authority = CloudflareControlPlaneIdentityAuthority(binding)

    await authority.resolve_auth_session(session_id="authsession:b62:tenant-test")

    assert binding.payloads == [{"session_id": "authsession:b62:tenant-test"}]
    assert "tenant_id" not in binding.payloads[0]
    assert "workspace_id" not in binding.payloads[0]
