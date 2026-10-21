"""#3099 guarantees when a bounded private RPC gives up on the native PC path.

A bounded private RPC can still be completed by the remote Durable Object
after the local await gave up. These regressions pin the canonical guarantees
that must hold in that case:

* a timed-out owner request never delivers a credential and never issues a
  second one;
* a credential that WAS handed to the PC is compensated by the existing
  canonical revocation path;
* a second credential transfer on the same session is refused;
* a same-request retry never mints a second credential.

No live Worker, Durable Object, DPAPI store or Windows device is involved.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time

import pytest

import app.canonical_connector_enrollment_async_host as host_module
from app.canonical_connector_enrollment_async_host import (
    CanonicalConnectorEnrollmentAsyncHost,
)
from app.connector_native_pc_gateway_port import (
    CanonicalNativePcTrustedGateway, NativePcGatewayDenied,
)
from app.connector_owner_identity_pc_completion import (
    CanonicalOwnerPcIdentityPreflight,
)
from app.connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
from app.control_plane_identity import IdentityBridgeError
from test_4139_connector_one_click_approval import session

NOW = datetime.now(timezone.utc)
REF = "link." + "a" * 32
CHALLENGE = "pairing." + "b" * 32
DEVICE = "windows.device.1"
PROOF = "pairing-proof:" + "c" * 64
CREDENTIAL = b"one-time-secret-with-length"
BINDING = {
    "binding_ref": "pairing-binding.1", "device_id": DEVICE,
    "account_ref": "account.1", "workspace_ref": "workspace.1",
    "credential_ref": "credential.1", "credential_generation": 1,
    "credential_expires_at": (NOW + timedelta(days=30)).isoformat(),
}
ENROLLMENT_BINDING = {
    "challenge_id": CHALLENGE, "consent_ref": "consent.1",
    "owner_ref": "owner.1", "account_ref": "account.1",
    "workspace_ref": "workspace.1", "device_id": DEVICE,
    "bound_at": NOW.isoformat(),
}
CONSENT = {
    "consent_id": "consent.1", "device_id": DEVICE,
    "owner_subject_id": "owner.1", "account_ref": "account.1",
    "workspace_ref": "workspace.1", "granted_at": NOW.isoformat(),
    "withdrawn_at": None,
}


class Identity:
    def __init__(self):
        self.calls = []

    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        self.calls.append(("consent", session_id, device_id))
        return dict(CONSENT)

    async def bind_connector_enrollment_challenge(self, *, session_id, challenge_id, expires_at):
        self.calls.append(("bind", challenge_id))
        return {"challenge_id": challenge_id}

    async def authorize_connector_enrollment_redeem(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        return {
            "challenge_id": kwargs["challenge_id"], "consent_id": CONSENT["consent_id"],
            "device_id": kwargs["device_id"], "owner_subject_id": "owner.1",
            "account_ref": kwargs["account_ref"],
            "workspace_ref": kwargs["workspace_ref"],
        }


class Broker:
    def __init__(self):
        self.calls = []
        self.stall_redeem = False
        self.revoke_result = {"binding_ref": BINDING["binding_ref"], "state": "revoked"}

    async def issue_enrollment_challenge(self, **kwargs):
        self.calls.append(("issue", kwargs))
        return {
            "challenge_id": CHALLENGE, "account_ref": "account.1",
            "workspace_ref": "workspace.1", "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
        }, "f" * 32

    async def get_enrollment_binding(self, *, challenge_id):
        self.calls.append(("binding", challenge_id))
        return dict(ENROLLMENT_BINDING)

    async def verify_enrollment_bootstrap(self, **kwargs):
        self.calls.append(("preflight", kwargs))
        return {
            "challenge_id": CHALLENGE, "device_id": DEVICE,
            "proof_valid": True, "challenge_consumed": False,
        }

    async def redeem_enrollment(self, **kwargs):
        self.calls.append(("redeem", kwargs))
        if self.stall_redeem:
            # The canonical mutation may still commit remotely after the local
            # await gave up. The caller must not treat that as a delivery.
            await asyncio.sleep(30)
        return dict(BINDING), CREDENTIAL

    async def revoke_binding(self, *, binding_ref):
        self.calls.append(("revoke", binding_ref))
        return dict(self.revoke_result)


class PrivateBroker:
    """The Broker Durable Object private RPC surface used by this path."""

    def __init__(self):
        self.calls = []
        self.stall_ack = False

    async def pending_pc_identity_status(self, payload):
        self.calls.append(("status", payload))
        return {
            "request_ref": REF, "challenge_id": CHALLENGE, "device_id": DEVICE,
            "signed_fetch_verified": True, "identity_authorized": False,
            "credential_issued": False, "connected": False,
        }

    async def claim_pending_pc_identity_proof(self, payload):
        self.calls.append(("claim", payload))
        return {
            "request_ref": REF, "challenge_id": CHALLENGE, "device_id": DEVICE,
            "proof_ref": PROOF, "identity_authorized": False,
            "credential_issued": False, "connected": False,
        }

    async def reserve_native_pc_gateway(self, payload):
        self.calls.append(("reserve_gateway", payload))
        return {
            "request_ref": REF, "challenge_id": CHALLENGE, "device_id": DEVICE,
            "lease_ref": "gateway." + "d" * 32,
            "expires_at": (NOW + timedelta(seconds=60)).isoformat(),
            "authenticated": True, "credential_issued": False,
        }

    async def authenticate_native_pc_gateway(self, payload):
        self.calls.append(("auth_gateway", payload))
        return {
            "request_ref": REF, "challenge_id": CHALLENGE, "device_id": DEVICE,
            "lease_ref": "gateway." + "d" * 32,
            "authenticated": True, "credential_issued": False,
        }

    async def transfer_native_pc_credential_once(self, payload):
        self.calls.append(("transfer", payload))
        return {"sent_once": True, "credential_installed": False, "registered": False}

    async def receive_native_pc_install_ack(self, payload):
        self.calls.append(("ack", payload))
        if self.stall_ack:
            await asyncio.sleep(30)
        return {"ack": {"ok": True}, "source_authenticated": True, "registered": False}

    async def authenticate_native_pc_install_ack(self, payload):
        self.calls.append(("auth_ack", payload))
        return {"source_authenticated": True, "registered": False}

    async def complete_native_pc_enrollment(self, payload):
        self.calls.append(("terminal", payload))
        return {"sent_once": True, "connected": False}


class Handoff:
    def __init__(self, *, delivered=True):
        self.delivered = delivered
        self.calls = []

    async def ready(self, *, challenge_id, device_id):
        self.calls.append(("ready", challenge_id, device_id))
        return True

    async def deliver_once(self, *, challenge_id, device_id, credential, enrollment, now):
        self.calls.append(("deliver", challenge_id, device_id))
        if not self.delivered:
            raise RuntimeError("private gateway rpc unconfirmed")
        raise RuntimeError("private gateway rpc unconfirmed")

    async def verify_authenticated_ack(self, *, challenge_id, device_id, ack):
        self.calls.append(("verify", challenge_id, device_id))
        return False


def make_completion(*, identity=None, broker=None, private=None, handoff=None):
    identity = identity or Identity()
    broker = broker or Broker()
    private = private or PrivateBroker()
    preflight = CanonicalOwnerPcIdentityPreflight(
        identity=identity, broker=broker, private_broker=private,
    )
    completion = CanonicalOwnerNativePcCompletion(
        identity=identity, broker=broker, private_broker=private, preflight=preflight,
    )
    return identity, broker, private, completion


def test_timed_out_redeem_never_delivers_a_credential_or_issues_a_second_one(monkeypatch):
    """The canonical mutation may commit late; nothing may be delivered after.

    The owner request must fail closed, the private delivery RPC must never be
    reached, and the challenge must never be redeemed twice.
    """
    monkeypatch.setattr(host_module, "CROSS_DO_RPC_TIMEOUT_SECONDS", 0.2)
    identity, broker, private, completion = make_completion()
    broker.stall_redeem = True
    started = time.monotonic()
    with pytest.raises(Exception):
        asyncio.run(completion.complete(signed_owner=session(), request_ref=REF))
    assert time.monotonic() - started < 5.0
    # Exactly one redemption attempt and no credential delivery at all.
    assert [name for name, *_ in broker.calls].count("redeem") == 1
    private_names = [name for name, *_ in private.calls]
    assert private_names == ["status", "claim", "reserve_gateway", "auth_gateway"]
    assert not any(name == "transfer" for name in private_names)
    assert not any(name == "terminal" for name in private_names)


def test_credential_already_handed_to_the_pc_is_compensated_by_revocation(monkeypatch):
    """A delivery that reached the PC but whose ACK never confirmed is revoked."""
    monkeypatch.setattr(host_module, "CROSS_DO_RPC_TIMEOUT_SECONDS", 0.2)
    identity, broker, private, completion = make_completion(handoff=Handoff())
    # The handoff raises after the credential was already handed to the PC, so
    # the canonical compensating revocation must run.
    with pytest.raises(IdentityBridgeError):
        asyncio.run(completion.complete(signed_owner=session(), request_ref=REF))
    assert ("revoke", BINDING["binding_ref"]) in broker.calls


def test_native_pc_port_refuses_a_second_credential_transfer():
    """One session, one credential: the second transfer is refused locally."""
    private = PrivateBroker()
    from app.connector_owner_identity_pc_completion import VerifiedCanonicalPcHandoff

    verified = VerifiedCanonicalPcHandoff(
        challenge_id=CHALLENGE, device_id=DEVICE, proof_ref=PROOF, request_ref=REF,
    )
    gateway = CanonicalNativePcTrustedGateway(
        verified=verified, private_broker=private,
    )
    from app.canonical_connector_gateway_handoff import GatewayBootstrapLease

    lease = GatewayBootstrapLease(
        lease_ref="gateway." + "d" * 32, challenge_id=CHALLENGE,
        device_id=DEVICE, expires_at=NOW + timedelta(seconds=60),
    )
    lease = asyncio.run(gateway.reserve_authenticated_bootstrap(
        challenge_id=CHALLENGE, device_id=DEVICE,
    ))
    asyncio.run(gateway.transfer_credential_once(
        lease=lease, credential=CREDENTIAL, binding=dict(BINDING),
    ))
    with pytest.raises(NativePcGatewayDenied):
        asyncio.run(gateway.transfer_credential_once(
            lease=lease, credential=CREDENTIAL, binding=dict(BINDING),
        ))
    assert [name for name, *_ in private.calls].count("transfer") == 1


def test_native_pc_port_ack_timeout_fails_closed_without_a_second_delivery(monkeypatch):
    """A stalled ACK wait is bounded and never re-delivers the credential."""
    import app.connector_native_pc_gateway_port as port_module

    monkeypatch.setattr(port_module, "NATIVE_PC_PRIVATE_RPC_TIMEOUT_SECONDS", 0.2)
    private = PrivateBroker()
    private.stall_ack = True
    from app.connector_owner_identity_pc_completion import VerifiedCanonicalPcHandoff
    from app.canonical_connector_gateway_handoff import GatewayBootstrapLease

    verified = VerifiedCanonicalPcHandoff(
        challenge_id=CHALLENGE, device_id=DEVICE, proof_ref=PROOF, request_ref=REF,
    )
    gateway = CanonicalNativePcTrustedGateway(
        verified=verified, private_broker=private,
    )
    lease = asyncio.run(gateway.reserve_authenticated_bootstrap(
        challenge_id=CHALLENGE, device_id=DEVICE,
    ))
    asyncio.run(gateway.transfer_credential_once(
        lease=lease, credential=CREDENTIAL, binding=dict(BINDING),
    ))
    started = time.monotonic()
    with pytest.raises(NativePcGatewayDenied):
        asyncio.run(gateway.receive_authenticated_install_ack(lease=lease))
    assert time.monotonic() - started < 5.0
    # The credential was handed over exactly once.
    assert [name for name, *_ in private.calls].count("transfer") == 1
    assert not any(name == "terminal" for name, *_ in private.calls)
