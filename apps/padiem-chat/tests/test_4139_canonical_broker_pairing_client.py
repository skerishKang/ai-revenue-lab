"""Typed private Broker Service Binding adapter contract tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from app.control_plane_identity import IdentityBridgeError

NOW = datetime.now(timezone.utc)
CHALLENGE_ID = "pairing." + "a"*32
DEVICE = "device.office.1"
ACCOUNT = "account.owner.1"
WORKSPACE = "workspace.owner.1"
CONSENT = "consent.owner.1"
OWNER = "subject.owner.1"
CODE = "b"*32
PROOF = "pairing-proof:" + "c"*64


class Binding:
    def __init__(self):
        self.calls = []
        self.results = {}

    async def install_pairing_schema(self, payload):
        self.calls.append(("schema", payload))
        return self.results.get("schema", {
            "ok": True, "schema": "canonical-broker-pairing-v1", "installed_by_default": False,
        })

    async def issue_enrollment_challenge(self, payload):
        self.calls.append(("issue", payload))
        return self.results.get("issue", {
            "ok": True,
            "challenge": {
                "challenge_id": CHALLENGE_ID, "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
                "issued_at": NOW.isoformat(), "expires_at": (NOW+timedelta(minutes=5)).isoformat(),
                "single_use": True, "client_time_authority": False, "raw_pairing_secret": False,
            },
            "pairing_code": CODE,
        })

    async def get_enrollment_binding(self, payload):
        self.calls.append(("binding", payload))
        return self.results.get("binding", {
            "ok": True, "binding": {
                "challenge_id": CHALLENGE_ID, "consent_ref": CONSENT, "owner_ref": OWNER,
                "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "device_id": DEVICE,
                "bound_at": NOW.isoformat(), "server_owned_binding": True,
                "client_supplied_receipt_trusted": False, "raw_pairing_secret": False,
            },
        })

    async def redeem_enrollment(self, payload):
        self.calls.append(("redeem", payload))
        return self.results.get("redeem", {
            "ok": True,
            "enrollment": {
                "binding_ref": "pairing-binding.1", "device_id": DEVICE,
                "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "credential_ref": "pairing-credential.1",
                "credential_generation": 1, "issued_at": NOW.isoformat(),
                "credential_expires_at": (NOW+timedelta(days=30)).isoformat(),
                "challenge_id": CHALLENGE_ID, "server_owned_binding_refs": True,
                "raw_device_credential": False, "production_ready": False,
            },
            "credential_b64": "Y3JlZGVudGlhbA==",
            "credential_returned_once": True, "public_http_route": False,
        })


def test_install_schema_requires_private_rpc_and_strict_receipt():
    binding = Binding()
    client = CloudflareCanonicalBrokerPairingClient(binding)
    result = asyncio.run(client.install_schema(migration_id="canonical-broker-pairing-v1"))
    assert result == {"schema": "canonical-broker-pairing-v1", "installed_by_default": False}
    assert binding.calls == [("schema", {"migration_id": "canonical-broker-pairing-v1"})]


def test_issue_challenge_returns_code_once_with_server_correlated_scope():
    binding = Binding()
    client = CloudflareCanonicalBrokerPairingClient(binding)
    challenge, code = asyncio.run(client.issue_enrollment_challenge(
        account_ref=ACCOUNT, workspace_ref=WORKSPACE, consent_ref=CONSENT,
        owner_ref=OWNER, device_id=DEVICE,
    ))
    assert challenge["challenge_id"] == CHALLENGE_ID and code == CODE
    assert binding.calls == [("issue", {
        "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "consent_ref": CONSENT,
        "owner_ref": OWNER, "device_id": DEVICE,
    })]


def test_enrollment_binding_is_closed_and_challenge_correlated():
    binding = Binding()
    client = CloudflareCanonicalBrokerPairingClient(binding)
    result = asyncio.run(client.get_enrollment_binding(
        challenge_id=CHALLENGE_ID, consent_ref=CONSENT, owner_ref=OWNER,
        account_ref=ACCOUNT, workspace_ref=WORKSPACE, device_id=DEVICE,
    ))
    assert result["consent_ref"] == CONSENT
    assert binding.calls == [("binding", {"challenge_id": CHALLENGE_ID})]


def test_redemption_returns_credential_separately_for_private_handoff_only():
    binding = Binding()
    client = CloudflareCanonicalBrokerPairingClient(binding)
    receipt, secret = asyncio.run(client.redeem_enrollment(
        challenge_id=CHALLENGE_ID, device_id=DEVICE, proof_ref=PROOF,
        consent_ref=CONSENT, owner_ref=OWNER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
    ))
    assert receipt["binding_ref"] == "pairing-binding.1"
    assert secret == b"credential"
    _, payload = binding.calls[0]
    assert set(payload) == {
        "challenge_id", "device_id", "proof_ref", "consent_ref", "owner_ref", "account_ref", "workspace_ref",
    }


@pytest.mark.parametrize("override", [
    {"challenge": {
        "challenge_id": CHALLENGE_ID, "account_ref": "account.other", "workspace_ref": WORKSPACE,
        "issued_at": NOW.isoformat(), "expires_at": (NOW+timedelta(minutes=5)).isoformat(),
        "single_use": True, "client_time_authority": False, "raw_pairing_secret": False,
    }},
    {"challenge": {
        "challenge_id": CHALLENGE_ID, "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
        "issued_at": NOW.isoformat(), "expires_at": (NOW+timedelta(minutes=5)).isoformat(),
        "single_use": False, "client_time_authority": False, "raw_pairing_secret": False,
    }},
    {"pairing_code": "not-a-code"},
])
def test_issue_refuses_bad_scope_or_secret_projection(override):
    binding = Binding()
    binding.results["issue"] = {"ok": True, "challenge": {
        "challenge_id": CHALLENGE_ID, "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
        "issued_at": NOW.isoformat(), "expires_at": (NOW+timedelta(minutes=5)).isoformat(),
        "single_use": True, "client_time_authority": False, "raw_pairing_secret": False,
    }, "pairing_code": CODE, **override}
    client = CloudflareCanonicalBrokerPairingClient(binding)
    with pytest.raises(IdentityBridgeError):
        asyncio.run(client.issue_enrollment_challenge(
            account_ref=ACCOUNT, workspace_ref=WORKSPACE, consent_ref=CONSENT,
            owner_ref=OWNER, device_id=DEVICE,
        ))


@pytest.mark.parametrize("change", [
    ("device_id", "device.other"),
    ("server_owned_binding", False),
    ("client_supplied_receipt_trusted", True),
    ("consent_ref", "consent.other"),
    ("owner_ref", "subject.other"),
    ("account_ref", "account.other"),
    ("workspace_ref", "workspace.other"),
])
def test_binding_refuses_mismatched_device_or_untrusted_receipt(change):
    binding = Binding()
    response = binding.results.get("binding") or {
        "ok": True, "binding": {
            "challenge_id": CHALLENGE_ID, "consent_ref": CONSENT, "owner_ref": OWNER,
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "device_id": DEVICE,
            "bound_at": NOW.isoformat(), "server_owned_binding": True,
            "client_supplied_receipt_trusted": False, "raw_pairing_secret": False,
        },
    }
    response["binding"][change[0]] = change[1]
    binding.results["binding"] = response
    with pytest.raises(IdentityBridgeError):
        asyncio.run(CloudflareCanonicalBrokerPairingClient(binding).get_enrollment_binding(
            challenge_id=CHALLENGE_ID, consent_ref=CONSENT, owner_ref=OWNER,
            account_ref=ACCOUNT, workspace_ref=WORKSPACE, device_id=DEVICE,
        ))


@pytest.mark.parametrize("mutate", [
    {"device_id": "device.other"},
    {"server_owned_binding_refs": False},
    {"raw_device_credential": True},
    {"production_ready": True},
])
def test_redemption_refuses_wrong_scope_or_overtrusted_metadata(mutate):
    binding = Binding()
    response = binding.results.get("redeem") or {
        "ok": True,
        "enrollment": {
            "binding_ref": "pairing-binding.1", "device_id": DEVICE,
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "credential_ref": "pairing-credential.1",
            "credential_generation": 1, "issued_at": NOW.isoformat(),
            "credential_expires_at": (NOW+timedelta(days=30)).isoformat(),
            "challenge_id": CHALLENGE_ID, "server_owned_binding_refs": True,
            "raw_device_credential": False, "production_ready": False,
        },
        "credential_b64": "Y3JlZGVudGlhbA==", "credential_returned_once": True, "public_http_route": False,
    }
    response["enrollment"].update(mutate)
    binding.results["redeem"] = response
    with pytest.raises(IdentityBridgeError):
        asyncio.run(CloudflareCanonicalBrokerPairingClient(binding).redeem_enrollment(
            challenge_id=CHALLENGE_ID, device_id=DEVICE, proof_ref=PROOF, consent_ref=CONSENT,
            owner_ref=OWNER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        ))


def test_malformed_base64_private_credential_fails_closed():
    binding = Binding()
    response = binding.results.get("redeem") or {
        "ok": True,
        "enrollment": {
            "binding_ref": "pairing-binding.1", "device_id": DEVICE,
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "credential_ref": "pairing-credential.1",
            "credential_generation": 1, "issued_at": NOW.isoformat(),
            "credential_expires_at": (NOW+timedelta(days=30)).isoformat(),
            "challenge_id": CHALLENGE_ID, "server_owned_binding_refs": True,
            "raw_device_credential": False, "production_ready": False,
        },
        "credential_b64": "bad!", "credential_returned_once": True, "public_http_route": False,
    }
    binding.results["redeem"] = response
    with pytest.raises(IdentityBridgeError):
        asyncio.run(CloudflareCanonicalBrokerPairingClient(binding).redeem_enrollment(
            challenge_id=CHALLENGE_ID, device_id=DEVICE, proof_ref=PROOF, consent_ref=CONSENT,
            owner_ref=OWNER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        ))
