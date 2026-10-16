"""#4139 integrated in-process acceptance: same real Broker DO/WSS plus canonical B54 host.

This integrates the existing SQLite-backed Broker DO, signed PC frames, one-use
Identity proof claim, canonical B54 redemption, native credential-once delivery,
and signed protected-store ACK. The PC ACK is a deterministic protocol peer,
not a real Windows DPAPI process and not a deployed Cloudflare worker E2E.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "padiem-chat"))
sys.path.insert(0, str(ROOT / "packages" / "padiem-control-plane" / "tests"))

from app.canonical_connector_credential_handoff import installation_proof
from app.connector_owner_identity_pc_completion import CanonicalOwnerPcIdentityPreflight
from app.connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
from app.control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from app.control_plane_identity import IdentityBridgeError
from canonical_broker_gateway_bootstrap import bootstrap_mac, session_mac
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
from test_4139_broker_post_approval_bootstrap import native_owner_approved
from test_4139_broker_native_pc_wss import broker_pending_pc_wss_message


class OriginalB54Identity:
    """Deterministic canonical Identity authority bound to one active B54 owner."""

    def __init__(self, *, owner: str, device: str, consent: str,
                 account: str, workspace: str, session_id: str,
                 withdrawn: bool = False):
        self.owner = owner
        self.device = device
        self.consent = consent
        self.account = account
        self.workspace = workspace
        self.session_id = session_id
        self.withdrawn = withdrawn
        self.calls = []

    async def resolve_connector_enrollment_consent_for_device(
        self, *, session_id, device_id,
    ):
        self.calls.append(("resolve_consent", session_id, device_id))
        if session_id != self.session_id or device_id != self.device:
            raise PermissionError("original Identity scope mismatch")
        return {
            "consent_id": self.consent,
            "device_id": self.device,
            "owner_subject_id": self.owner,
            "account_ref": self.account,
            "workspace_ref": self.workspace,
            "granted_at": datetime.now(timezone.utc).isoformat(),
            "withdrawn_at": (
                datetime.now(timezone.utc).isoformat() if self.withdrawn else None
            ),
            "dispatch_authorized": False,
            "grants_read": False,
            "grants_write": False,
        }

    async def authorize_connector_enrollment_redeem(
        self, *, challenge_id, consent_id, device_id,
        owner_ref, account_ref, workspace_ref,
    ):
        self.calls.append(("authorize", challenge_id, device_id))
        if self.withdrawn:
            raise PermissionError("original Identity consent withdrawn")
        if (
            consent_id != self.consent or device_id != self.device
            or owner_ref != self.owner or account_ref != self.account
            or workspace_ref != self.workspace
        ):
            raise PermissionError("original Identity scope mismatch")
        return {
            "challenge_id": challenge_id,
            "consent_id": self.consent,
            "device_id": self.device,
            "owner_subject_id": self.owner,
            "account_ref": self.account,
            "workspace_ref": self.workspace,
        }

    async def bind_connector_enrollment_challenge(
        self, *, session_id, challenge_id, expires_at,
    ):
        self.calls.append(("bind_challenge", session_id, challenge_id))
        if session_id != self.session_id:
            raise PermissionError("wrong canonical session")


class SameCanonicalBrokerBinding:
    """Private service-binding façade to methods on the exact live Broker DO."""

    def __init__(self, owner_do):
        self.do = owner_do

    async def pending_pc_identity_status(self, payload):
        return await self.do.pending_pc_identity_status(payload)

    async def claim_pending_pc_identity_proof(self, payload):
        return await self.do.claim_pending_pc_identity_proof(payload)

    async def reserve_native_pc_gateway(self, payload):
        return await self.do.reserve_native_pc_gateway(payload)

    async def authenticate_native_pc_gateway(self, payload):
        return await self.do.authenticate_native_pc_gateway(payload)

    async def transfer_native_pc_credential_once(self, payload):
        return await self.do.transfer_native_pc_credential_once(payload)

    async def receive_native_pc_install_ack(self, payload):
        return await self.do.receive_native_pc_install_ack(payload)

    async def authenticate_native_pc_install_ack(self, payload):
        return await self.do.authenticate_native_pc_install_ack(payload)

    async def complete_native_pc_enrollment(self, payload):
        return await self.do.complete_native_pc_enrollment(payload)


def signed_owner(session_id: str, owner: str):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id=session_id,
        product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id=owner,
        ),
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        tenant_id="tenant.owner.1",
    )


async def _reach_verified_fetch(monkeypatch):
    do, _broker, server, challenge_id, pairing_code = await native_owner_approved(
        monkeypatch,
    )
    # Exercise the same explicit private service flags as the source-reviewed
    # owner handoff. These test-only flags never mutate deployed Worker config.
    do.env.LOCAL_AGENT_BROKER_PENDING_PC_IDENTITY_HANDOFF_ENABLED = "enabled"
    do.env.LOCAL_AGENT_BROKER_PENDING_PC_NATIVE_DELIVERY_ENABLED = "enabled"

    proof_ref = pairing_proof_ref(
        challenge_id=challenge_id,
        device_id="windows.device.1",
        pairing_code=pairing_code,
    )
    await broker_pending_pc_wss_message(do, server, json.dumps({
        "type": "begin", "challenge_id": challenge_id,
        "device_id": "windows.device.1", "proof_ref": proof_ref,
    }))
    nonce = server.sent[-1]
    assert nonce["type"] == "nonce"
    await broker_pending_pc_wss_message(do, server, json.dumps({
        "type": "finish",
        "lease_ref": nonce["lease_ref"],
        "proof_hex": bootstrap_mac(
            pairing_code=pairing_code, challenge_id=challenge_id,
            device_id="windows.device.1", nonce_hex=nonce["nonce_hex"],
            lease_ref=nonce["lease_ref"],
        ),
    }))
    assert server.sent[-1]["type"] == "bootstrap_verified"

    fetch_proof = session_mac(
        pairing_code=pairing_code, challenge_id=challenge_id,
        device_id="windows.device.1", nonce_hex=nonce["nonce_hex"],
        lease_ref=nonce["lease_ref"], action="credential_fetch", counter=1,
        payload_sha256=hashlib.sha256(b"").hexdigest(),
    )
    sent_before_fetch = len(server.sent)
    await broker_pending_pc_wss_message(do, server, json.dumps({
        "type": "credential_fetch", "counter": 1, "proof_hex": fetch_proof,
    }))
    assert len(server.sent) == sent_before_fetch  # fetch receipt is not a credential
    actor = next(iter(do._pending_pc_wss_by_id.values()))
    assert actor._canonical_bootstrap.authenticated_fetch_receipt(
        challenge_id=challenge_id, device_id="windows.device.1",
    ) is True
    return do, _broker, server, challenge_id, pairing_code, proof_ref, nonce


async def _complete_live_host(monkeypatch, *, withdrawn=False, lose_actor=False):
    do, broker_rpc, server, challenge, pairing_code, proof_ref, nonce = (
        await _reach_verified_fetch(monkeypatch)
    )
    binding_reply = await broker_rpc.get_enrollment_binding({
        "challenge_id": challenge,
    })
    binding = binding_reply["binding"]
    owner = binding["owner_ref"]
    device = binding["device_id"]
    consent = binding["consent_ref"]
    account = binding["account_ref"]
    workspace = binding["workspace_ref"]
    session_id = "b54.session.native.integration.1"
    identity = OriginalB54Identity(
        owner=owner, device=device, consent=consent, account=account,
        workspace=workspace, session_id=session_id, withdrawn=withdrawn,
    )
    private = SameCanonicalBrokerBinding(do)
    original_broker = CloudflareCanonicalBrokerPairingClient(broker_rpc)
    preflight = CanonicalOwnerPcIdentityPreflight(
        identity=identity, broker=original_broker, private_broker=private,
    )
    completion = CanonicalOwnerNativePcCompletion(
        identity=identity, broker=original_broker,
        private_broker=private, preflight=preflight,
    )
    owner_session = signed_owner(session_id, owner)

    if lose_actor:
        # Model DO eviction: socket actor state must not be reconstructed from
        # SQLite/serialized attachment. The existing canonical owner path fails
        # before any redeem or credential-once send.
        do._pending_pc_wss_by_id.clear()
        with_exception = True
    else:
        with_exception = withdrawn

    if with_exception:
        with pytest.raises(IdentityBridgeError):
            await completion.complete(
                signed_owner=owner_session,
                request_ref=actor_ref_from_do(do, challenge, fallback="link." + "a" * 32),
            )
        assert all(frame.get("type") != "credential_once" for frame in server.sent)
        row = broker_rpc._storage.sql.exec(
            "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge",
        ).toArray()[0]
        assert row["redeemed_at"] is None
        return {"denied": True, "server": server, "broker": broker_rpc}

    request_ref = actor_ref_from_do(do, challenge)
    owner_task = asyncio.create_task(completion.complete(
        signed_owner=owner_session, request_ref=request_ref,
    ))
    credential_frame = None
    for _ in range(300):
        if owner_task.done():
            await owner_task
        credential_frame = next(
            (frame for frame in server.sent if frame.get("type") == "credential_once"),
            None,
        )
        if credential_frame is not None:
            break
        await asyncio.sleep(0.005)
    assert credential_frame is not None, "canonical owner host did not deliver credential_once"

    raw_credential = base64.b64decode(
        credential_frame["credential_b64"], validate=True,
    )
    public_binding = credential_frame["binding"]
    ack = {
        "challenge_id": challenge,
        "device_id": device,
        "binding_ref": public_binding["binding_ref"],
        "credential_generation": public_binding["credential_generation"],
        "proof_kind": "protected_store_save_readback",
        "transcript_version": "padiem.connector-device-install-ack.v1",
        "local_store_confirmed": True,
        "proof_hex": installation_proof(
            credential=raw_credential, challenge_id=challenge,
            device_id=device, binding_ref=public_binding["binding_ref"],
            credential_generation=public_binding["credential_generation"],
        ),
    }
    body = json.dumps(ack, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = base64.b64encode(body).decode("ascii")
    ack_mac = session_mac(
        pairing_code=pairing_code, challenge_id=challenge, device_id=device,
        nonce_hex=nonce["nonce_hex"], lease_ref=nonce["lease_ref"],
        action="install_ack", counter=2,
        payload_sha256=hashlib.sha256(body).hexdigest(),
    )
    await broker_pending_pc_wss_message(do, server, json.dumps({
        "type": "install_ack", "counter": 2,
        "body_b64": body_b64, "proof_hex": ack_mac,
    }))
    result = await asyncio.wait_for(owner_task, timeout=3)

    assert result["device_id"] == device
    assert result["lifecycle"] == "paired_offline"
    assert result["credential_installed_by_canonical_handoff"] is True
    assert result["raw_device_credential"] is False
    assert result["dispatch_authorized"] is False
    assert raw_credential not in repr(result).encode("utf-8")
    assert sum(frame.get("type") == "credential_once" for frame in server.sent) == 1
    assert server.sent[-1] == {
        "type": "terminal", "status": "paired_offline", "can_retry_challenge": False,
    }
    assert len([call for call in identity.calls if call[0] == "authorize"]) >= 4
    redeemed = broker_rpc._storage.sql.exec(
        "SELECT redeemed_at FROM canonical_local_agent_pairing_challenge",
    ).toArray()
    assert len(redeemed) == 1 and redeemed[0]["redeemed_at"] is not None
    return {"denied": False, "result": result, "server": server, "broker": broker_rpc}


def actor_ref_from_do(owner_do, challenge, fallback=None):
    actors = [
        actor for actor in getattr(owner_do, "_pending_pc_wss_by_id", {}).values()
        if getattr(actor, "_approved_challenge", None) == challenge
    ]
    return actors[0]._request_ref if len(actors) == 1 else fallback


def test_same_sqlite_do_wss_identity_host_and_signed_dpapi_ack_complete_one_enrollment(monkeypatch):
    async def run():
        result = await _complete_live_host(monkeypatch)
        assert result["denied"] is False
    asyncio.run(run())


def test_withdrawn_identity_consent_never_sends_credential_once(monkeypatch):
    async def run():
        result = await _complete_live_host(monkeypatch, withdrawn=True)
        assert result["denied"] is True
    asyncio.run(run())


def test_evicted_same_do_socket_never_recovers_owner_proof_or_credential(monkeypatch):
    async def run():
        result = await _complete_live_host(monkeypatch, lose_actor=True)
        assert result["denied"] is True
    asyncio.run(run())
