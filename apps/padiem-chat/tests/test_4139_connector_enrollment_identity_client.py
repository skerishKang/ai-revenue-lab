"""Typed client contract for the private canonical Identity enrollment RPCs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.control_plane_identity import IdentityBridgeError

NOW = "2026-10-12T10:00:00+00:00"


class Binding:
    def __init__(self):
        self.calls = []
        self.response = None

    async def grant_connector_enrollment_consent(self, payload):
        self.calls.append(("grant", payload))
        return self.response

    async def revoke_connector_enrollment_consent(self, payload):
        self.calls.append(("revoke", payload))
        return self.response

    async def install_connector_enrollment_schema(self, payload):
        self.calls.append(("schema", payload))
        return self.response

    async def resolve_connector_enrollment_consent_for_device(self, payload):
        self.calls.append(("resolve_consent", payload))
        return self.response

    async def bind_connector_enrollment_challenge(self, payload):
        self.calls.append(("bind_challenge", payload))
        return self.response

    async def authorize_connector_enrollment_redeem(self, payload):
        self.calls.append(("authorize_redeem", payload))
        return self.response


def good_consent(*, revoked=False):
    return {
        "consent_id": "consent.test.1",
        "device_id": "device.windows.1",
        "granted_at": NOW,
        "withdrawn_at": NOW if revoked else None,
        "dispatch_authorized": False,
        "grants_read": False,
        "grants_write": False,
    }


def envelope(field, value):
    return {"ok": True, field: value}


def test_private_grant_has_closed_identity_inputs_and_checks_safe_receipt():
    binding = Binding()
    binding.response = envelope("consent", good_consent())
    client = CloudflareControlPlaneIdentityAuthority(binding)
    result = asyncio.run(client.grant_connector_enrollment_consent(
        session_id="session.canonical.1",
        device_id="device.windows.1",
        confirmed=True,
    ))
    assert result["consent_id"] == "consent.test.1"
    method, payload = binding.calls[0]
    assert method == "grant"
    assert payload == {
        "session_id": "session.canonical.1",
        "device_id": "device.windows.1",
        "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    }
    assert "owner_subject_id" not in payload and "workspace_ref" not in payload and "tenant_id" not in payload


def test_private_grant_refuses_without_explicit_confirmation_before_rpc():
    binding = Binding()
    client = CloudflareControlPlaneIdentityAuthority(binding)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(client.grant_connector_enrollment_consent(
            session_id="session.canonical.1", device_id="device.windows.1", confirmed=False
        ))
    assert exc.value.code == "connector_enrollment_explicit_consent_required"
    assert binding.calls == []


@pytest.mark.parametrize("mutate", [
    {"device_id": "device.other"},
    {"dispatch_authorized": True},
    {"grants_read": True},
    {"grants_write": True},
    {"withdrawn_at": NOW},
])
def test_private_grant_rejects_receipt_mismatch_or_overgrant(mutate):
    receipt = good_consent()
    receipt.update(mutate)
    binding = Binding()
    binding.response = envelope("consent", receipt)
    client = CloudflareControlPlaneIdentityAuthority(binding)
    with pytest.raises(IdentityBridgeError) as exc:
        asyncio.run(client.grant_connector_enrollment_consent(
            session_id="session.canonical.1", device_id="device.windows.1", confirmed=True
        ))
    assert exc.value.code == "control_plane_rpc_invalid"


def test_private_revoke_requires_same_consent_and_withdrawal_timestamp():
    receipt = good_consent(revoked=True)
    binding = Binding()
    binding.response = envelope("consent", receipt)
    client = CloudflareControlPlaneIdentityAuthority(binding)
    result = asyncio.run(client.revoke_connector_enrollment_consent(
        session_id="session.canonical.1", consent_id="consent.test.1", confirmed=True
    ))
    assert result["withdrawn_at"] == NOW
    assert binding.calls[0] == (
        "revoke", {
            "session_id": "session.canonical.1",
            "consent_id": "consent.test.1",
            "confirmed": True,
            "confirmation_version": "pc-enrollment-consent-v1",
        }
    )


def test_schema_install_requires_exact_reviewed_version_and_no_auto_flag():
    binding = Binding()
    binding.response = envelope("schema", {"schema": "connector-enrollment-v1", "installed_by_default": False})
    client = CloudflareControlPlaneIdentityAuthority(binding)
    result = asyncio.run(client.install_connector_enrollment_schema(migration_id="connector-enrollment-v1"))
    assert result["installed_by_default"] is False
    assert binding.calls[0] == ("schema", {"migration_id": "connector-enrollment-v1"})


def test_invalid_private_rpc_shape_is_not_trusted():
    binding = Binding()
    binding.response = envelope("consent", {**good_consent(), "extra": "untrusted"})
    client = CloudflareControlPlaneIdentityAuthority(binding)
    with pytest.raises(IdentityBridgeError):
        asyncio.run(client.grant_connector_enrollment_consent(
            session_id="session.canonical.1", device_id="device.windows.1", confirmed=True
        ))

def test_current_consent_read_uses_canonical_session_and_returns_no_permission():
    binding = Binding()
    binding.response = envelope("consent", {
        "consent_id": "consent.test.1", "device_id": "device.windows.1",
        "owner_subject_id": "sub.canonical.1", "account_ref": "account.1",
        "workspace_ref": "workspace.1", "granted_at": NOW, "withdrawn_at": None,
    })
    result = asyncio.run(CloudflareControlPlaneIdentityAuthority(binding).resolve_connector_enrollment_consent_for_device(
        session_id="session.canonical.1", device_id="device.windows.1",
    ))
    assert result["consent_id"] == "consent.test.1"
    assert binding.calls == [("resolve_consent", {
        "session_id": "session.canonical.1", "device_id": "device.windows.1",
    })]


def test_bind_challenge_confirms_server_stored_session_without_echoing_session_id():
    binding = Binding()
    binding.response = envelope("binding", {
        "challenge_id": "pairing.challenge.1", "session_id_bound": True,
        "expires_at": NOW, "raw_session_id_returned": False,
    })
    result = asyncio.run(CloudflareControlPlaneIdentityAuthority(binding).bind_connector_enrollment_challenge(
        session_id="session.canonical.1", challenge_id="pairing.challenge.1", expires_at=NOW,
    ))
    assert result["session_id_bound"] is True and result["raw_session_id_returned"] is False
    assert binding.calls == [("bind_challenge", {
        "session_id": "session.canonical.1", "challenge_id": "pairing.challenge.1", "expires_at": NOW,
    })]


def test_redeem_authorization_requires_exact_owner_scope_and_no_permission():
    binding = Binding()
    binding.response = envelope("authorization", {
        "challenge_id": "pairing.challenge.1", "consent_id": "consent.1",
        "device_id": "device.1", "owner_subject_id": "sub.1",
        "account_ref": "account.1", "workspace_ref": "workspace.1",
        "authorized_at": NOW, "dispatch_authorized": False, "grants_read": False, "grants_write": False,
    })
    result = asyncio.run(CloudflareControlPlaneIdentityAuthority(binding).authorize_connector_enrollment_redeem(
        challenge_id="pairing.challenge.1", consent_id="consent.1", device_id="device.1",
        owner_ref="sub.1", account_ref="account.1", workspace_ref="workspace.1",
    ))
    assert result["consent_id"] == "consent.1"
    assert binding.calls[0][0] == "authorize_redeem"
    binding.response = envelope("authorization", {
        "challenge_id": "pairing.challenge.1", "consent_id": "consent.other",
        "device_id": "device.1", "owner_subject_id": "sub.1",
        "account_ref": "account.1", "workspace_ref": "workspace.1",
        "authorized_at": NOW, "dispatch_authorized": False, "grants_read": False, "grants_write": False,
    })
    with pytest.raises(IdentityBridgeError):
        asyncio.run(CloudflareControlPlaneIdentityAuthority(binding).authorize_connector_enrollment_redeem(
            challenge_id="pairing.challenge.1", consent_id="consent.1", device_id="device.1",
            owner_ref="sub.1", account_ref="account.1", workspace_ref="workspace.1",
        ))

