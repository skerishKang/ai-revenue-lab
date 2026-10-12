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
