"""#4139 CENTRAL synthetic private gateway seam tests; zero network/Windows IO.

All fake authenticated lease and store-readback ACKs here are test fixtures,
NOT production device attestation. The actual port remains unconfigured.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.canonical_connector_gateway_handoff import (
    CanonicalGatewayProtectedHandoff,
    GatewayBootstrapLease,
    GATEWAY_TRANSPORT_PRODUCTION_ENABLED,
)
from app.canonical_connector_credential_handoff import (
    DeviceCredentialInstallAck,
    INSTALL_ACK_TRANSCRIPT_VERSION,
    installation_proof,
)
from app.canonical_connector_enrollment_async_host import CanonicalConnectorEnrollmentAsyncHost
from app.control_plane_identity import IdentityBridgeError

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
CHALLENGE = "pairing." + "a" * 32
DEVICE = "device.1"
KEY = b"fixture-secret-one-time-credential"
BINDING = {
    "binding_ref": "pairing-binding.1",
    "device_id": DEVICE,
    "account_ref": "account.1",
    "workspace_ref": "workspace.1",
    "credential_ref": "credential.1",
    "credential_generation": 1,
    "credential_expires_at": (NOW + timedelta(days=30)).isoformat(),
}


class FakeReviewedGateway:
    """Synthetic test port ONLY; not a live attestable PC or Gateway."""

    def __init__(self):
        self.calls = []
        self.authorized = True
        self.ack_authorized = True
        self.expired = False
        self.wrong_device = False
        self.raw_ack_override = None
        self.lease = None
        self.credential = None
        self.binding = None

    async def reserve_authenticated_bootstrap(self, *, challenge_id, device_id):
        self.calls.append("reserve")
        lease = GatewayBootstrapLease(
            lease_ref="gateway-session.1",
            challenge_id=challenge_id,
            device_id="device.swap" if self.wrong_device else device_id,
            expires_at=NOW - timedelta(seconds=1) if self.expired else NOW + timedelta(minutes=2),
        )
        self.lease = lease
        return lease

    async def authenticate_bootstrap_lease(self, *, lease, challenge_id, device_id):
        self.calls.append("bootstrap_auth")
        assert lease is self.lease
        return self.authorized

    async def transfer_credential_once(self, *, lease, credential, binding):
        self.calls.append("deliver")
        assert lease is self.lease
        self.credential = credential
        self.binding = dict(binding)

    async def receive_authenticated_install_ack(self, *, lease):
        self.calls.append("receive_ack")
        if self.raw_ack_override is not None:
            return self.raw_ack_override
        return {
            "challenge_id": lease.challenge_id, "device_id": lease.device_id,
            "binding_ref": self.binding["binding_ref"],
            "credential_generation": self.binding["credential_generation"],
            "proof_kind": "protected_store_save_readback",
            "transcript_version": INSTALL_ACK_TRANSCRIPT_VERSION,
            "local_store_confirmed": True,
            "proof_hex": installation_proof(
                credential=self.credential,
                challenge_id=lease.challenge_id,
                device_id=lease.device_id,
                binding_ref=self.binding["binding_ref"],
                credential_generation=self.binding["credential_generation"],
            ),
        }

    async def authenticate_ack_sender(self, *, lease, ack):
        self.calls.append("sender_auth")
        assert lease is self.lease
        return self.ack_authorized


def adapter(gateway=None, *, instant=NOW):
    return CanonicalGatewayProtectedHandoff(
        gateway=gateway, clock=lambda: instant,
    )


async def do_ack(hand, *, enrollment=None):
    assert await hand.ready(challenge_id=CHALLENGE, device_id=DEVICE) is True
    ack = await hand.deliver_once(
        challenge_id=CHALLENGE, device_id=DEVICE, credential=KEY,
        enrollment=BINDING if enrollment is None else enrollment,
        now=NOW,
    )
    return ack


def test_default_is_unconfigured_and_never_transmits():
    assert GATEWAY_TRANSPORT_PRODUCTION_ENABLED is False
    h = adapter()
    assert asyncio.run(h.ready(challenge_id=CHALLENGE, device_id=DEVICE)) is False
    with pytest.raises(RuntimeError):
        asyncio.run(h.deliver_once(
            challenge_id=CHALLENGE, device_id=DEVICE,
            credential=KEY, enrollment=BINDING, now=NOW,
        ))


@pytest.mark.parametrize("fault", ["expired", "wrong_device", "unauthorized"])
def test_unverified_bootstrap_refused_before_broker_redemption(fault):
    g = FakeReviewedGateway()
    g.expired = fault == "expired"
    g.wrong_device = fault == "wrong_device"
    g.authorized = fault != "unauthorized"
    h = adapter(g)
    assert asyncio.run(h.ready(challenge_id=CHALLENGE, device_id=DEVICE)) is False
    assert "deliver" not in g.calls


def test_synthetic_one_shot_roundtrip_is_bound_to_lease_and_exact_binding():
    g = FakeReviewedGateway()
    h = adapter(g)
    ack = asyncio.run(do_ack(h))
    assert type(ack) is DeviceCredentialInstallAck
    assert asyncio.run(h.verify_authenticated_ack(
        challenge_id=CHALLENGE, device_id=DEVICE, ack=ack,
    )) is True
    assert g.binding == BINDING
    assert len(g.binding) == 7
    assert "credential" not in g.binding and "owner_ref" not in g.binding
    assert g.calls == ["reserve", "bootstrap_auth", "deliver", "receive_ack", "sender_auth"]
    with pytest.raises(RuntimeError):
        asyncio.run(h.deliver_once(
            challenge_id=CHALLENGE, device_id=DEVICE,
            credential=KEY, enrollment=BINDING, now=NOW,
        ))
    assert g.calls.count("deliver") == 1


def test_copied_ack_and_wrong_pc_are_not_gateway_authenticated():
    g = FakeReviewedGateway()
    h = adapter(g)
    ack = asyncio.run(do_ack(h))
    copied = replace(ack)
    assert asyncio.run(h.verify_authenticated_ack(
        challenge_id=CHALLENGE, device_id=DEVICE, ack=copied,
    )) is False
    assert asyncio.run(h.verify_authenticated_ack(
        challenge_id=CHALLENGE, device_id="device.other", ack=ack,
    )) is False
    assert "sender_auth" not in g.calls


@pytest.mark.parametrize("tamper", [
    {"binding_ref": None},
    {"device_id": "device.other"},
    {"account_ref": None},
    {"workspace_ref": ""},
    {"credential_generation": True},
    {"credential_ref": None},
    {"credential_expires_at": "2020-01-01T00:00:00+00:00"},
    {"credential_expires_at": "2099-01-01T00:00:00"},
    {"credential_expires_at": "invalid"},
])
def test_mismatched_or_invalid_delivery_metadata_never_reaches_gateway(tamper):
    g = FakeReviewedGateway()
    h = adapter(g)
    assert asyncio.run(h.ready(challenge_id=CHALLENGE, device_id=DEVICE))
    bad = {**BINDING, **tamper}
    # Canonical account/workspace cross-owner correlation belongs to the
    # private Broker/Identity client. This seam still refuses structurally
    # missing/invalid scope, device, generation and credential expiry.
    with pytest.raises(ValueError):
        asyncio.run(h.deliver_once(
            challenge_id=CHALLENGE, device_id=DEVICE,
            credential=KEY, enrollment=bad, now=NOW,
        ))
    assert "deliver" not in g.calls


@pytest.mark.parametrize("raw_ack", [
    False,
    {},
    {"local_store_confirmed": True},
    {"challenge_id": CHALLENGE, "device_id": DEVICE, "credential_b64": "forbidden"},
])
def test_untrusted_ack_shape_rejected_without_sender_attestation(raw_ack):
    g = FakeReviewedGateway()
    g.raw_ack_override = raw_ack
    h = adapter(g)
    assert asyncio.run(h.ready(challenge_id=CHALLENGE, device_id=DEVICE))
    with pytest.raises(ValueError):
        asyncio.run(h.deliver_once(
            challenge_id=CHALLENGE, device_id=DEVICE,
            credential=KEY, enrollment=BINDING, now=NOW,
        ))
    assert "sender_auth" not in g.calls
    assert g.calls.count("deliver") == 1


def test_a_valid_hmac_does_not_make_untrusted_gateway_sender_valid():
    g = FakeReviewedGateway()
    g.ack_authorized = False
    h = adapter(g)
    ack = asyncio.run(do_ack(h))
    assert ack.local_store_confirmed is True
    assert asyncio.run(h.verify_authenticated_ack(
        challenge_id=CHALLENGE, device_id=DEVICE, ack=ack,
    )) is False
    assert g.calls.count("sender_auth") == 1


def test_no_in_memory_lease_can_prove_durable_pc_replay_authority():
    g = FakeReviewedGateway()
    h = adapter(g)
    assert asyncio.run(do_ack(h))
    assert asyncio.run(h.ready(challenge_id=CHALLENGE, device_id=DEVICE)) is False
    assert g.calls.count("reserve") == 1
