"""#4139 same canonical Broker DO/WSS -> B54 Identity host integration.

Uses the real SQLite-backed Broker DurableObject/WSS harness and the existing
B54 identity/native completion classes in one test. The PC protected-store ACK
is a generated signed fixture, not a real Windows DPAPI or live Cloudflare E2E.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
for _path in (
    _REPO / "apps" / "padiem-chat",
    _REPO / "apps" / "padiem-chat" / "tests",
    _REPO / "packages" / "padiem-control-plane",
    _REPO / "packages" / "padiem-control-plane" / "tests",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_4139_broker_post_approval_bootstrap import native_owner_approved
from test_4139_broker_native_pc_wss import broker_pending_pc_wss_message, DEVICE
from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref
from canonical_broker_gateway_bootstrap import bootstrap_mac, session_mac
from app.connector_owner_identity_pc_completion import CanonicalOwnerPcIdentityPreflight
from app.connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
from app.canonical_connector_credential_handoff import installation_proof
from test_4139_connector_one_click_approval import session
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

REF = "link." + "a" * 32
OWNER = "subject.owner.1"
ACCOUNT = "account.owner.1"
WORKSPACE = "workspace.owner.1"
CONSENT = "consent.owner.1"


class _CanonicalIdentity:
    def __init__(self):
        self.calls = []

    async def resolve_connector_enrollment_consent_for_device(
        self, *, session_id, device_id
    ):
        self.calls.append(("consent", session_id, device_id))
        return {
            "consent_id": CONSENT,
            "device_id": device_id,
            "owner_subject_id": OWNER,
            "account_ref": ACCOUNT,
            "workspace_ref": WORKSPACE,
            "granted_at": "2026-10-16T12:00:00+00:00",
            "withdrawn_at": None,
        }

    async def authorize_connector_enrollment_redeem(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        return {
            "challenge_id": kwargs["challenge_id"],
            "device_id": kwargs["device_id"],
            "consent_id": kwargs["consent_id"],
            "owner_subject_id": kwargs["owner_ref"],
            "account_ref": kwargs["account_ref"],
            "workspace_ref": kwargs["workspace_ref"],
        }

    async def bind_connector_enrollment_challenge(self, **kwargs):
        self.calls.append(("bind", kwargs))
        return {"challenge_id": kwargs["challenge_id"]}


class _CanonicalBrokerServiceBinding:
    """Adapt test DO's raw RPC envelopes to the app's canonical typed client."""

    def __init__(self, pairing_broker):
        self._source = pairing_broker

    async def issue_enrollment_challenge(self, **kwargs):
        return await self._source.issue_enrollment_challenge(kwargs)

    async def get_enrollment_binding(self, *, challenge_id):
        raw = await self._source.get_enrollment_binding(
            {"challenge_id": challenge_id}
        )
        return raw.get("binding") if type(raw) is dict and raw.get("ok") is True else raw

    async def verify_enrollment_bootstrap(self, **kwargs):
        raw = await self._source.verify_enrollment_bootstrap(kwargs)
        return raw.get("bootstrap") if type(raw) is dict and raw.get("ok") is True else raw

    async def redeem_enrollment(self, **kwargs):
        raw = await self._source.redeem_enrollment(kwargs)
        if type(raw) is dict and raw.get("ok") is True and type(raw.get("enrollment")) is dict:
            return raw["enrollment"], base64.b64decode(
                raw["credential_b64"], validate=True
            )
        return raw

    async def revoke_binding(self, *, binding_ref):
        return {"binding_ref": binding_ref, "state": "revoked"}


def test_same_canonical_do_wss_fetch_flows_through_b54_host_and_signed_install_ack(
    monkeypatch,
):
    async def run():
        # One shared SQLite store: same owner-approved PC WSS DO and canonical
        # pairing Broker, not separate mocks for the transport and credential.
        do, pairing_broker, server, challenge_id, pairing_code = (
            await native_owner_approved(monkeypatch)
        )
        do.env.LOCAL_AGENT_BROKER_PENDING_PC_IDENTITY_HANDOFF_ENABLED = "enabled"
        do.env.LOCAL_AGENT_BROKER_PENDING_PC_NATIVE_DELIVERY_ENABLED = "enabled"

        proof_ref = pairing_proof_ref(
            challenge_id=challenge_id, device_id=DEVICE, pairing_code=pairing_code
        )
        await broker_pending_pc_wss_message(
            do, server, json.dumps({
                "type": "begin", "challenge_id": challenge_id,
                "device_id": DEVICE, "proof_ref": proof_ref,
            })
        )
        nonce = server.sent[-1]
        assert nonce["type"] == "nonce"
        await broker_pending_pc_wss_message(
            do, server, json.dumps({
                "type": "finish", "lease_ref": nonce["lease_ref"],
                "proof_hex": bootstrap_mac(
                    pairing_code=pairing_code, challenge_id=challenge_id,
                    device_id=DEVICE, nonce_hex=nonce["nonce_hex"],
                    lease_ref=nonce["lease_ref"],
                ),
            })
        )
        assert server.sent[-1]["type"] == "bootstrap_verified"

        fetch_mac = session_mac(
            pairing_code=pairing_code, challenge_id=challenge_id,
            device_id=DEVICE, nonce_hex=nonce["nonce_hex"],
            lease_ref=nonce["lease_ref"], action="credential_fetch", counter=1,
            payload_sha256=hashlib.sha256(b"").hexdigest(),
        )
        await broker_pending_pc_wss_message(
            do, server, json.dumps({
                "type": "credential_fetch", "counter": 1, "proof_hex": fetch_mac,
            })
        )
        assert not server.closes
        actor = next(iter(do._pending_pc_wss_by_id.values()))
        assert actor._canonical_bootstrap.authenticated_fetch_receipt(
            challenge_id=challenge_id, device_id=DEVICE
        ) is True

        identity = _CanonicalIdentity()
        broker = _CanonicalBrokerServiceBinding(pairing_broker)
        owner = replace(
            session(),
            subject=CanonicalSubjectRef(
                subject_type=SubjectType.USER, subject_id=OWNER
            ),
        )
        preflight = CanonicalOwnerPcIdentityPreflight(
            identity=identity, broker=broker, private_broker=do
        )
        completion = CanonicalOwnerNativePcCompletion(
            identity=identity, broker=broker, private_broker=do,
            preflight=preflight,
        )
        owner_task = asyncio.create_task(
            completion.complete(signed_owner=owner, request_ref=REF)
        )

        delivered = []
        for _ in range(100):
            await asyncio.sleep(0)
            delivered = [f for f in server.sent if f.get("type") == "credential_once"]
            if delivered:
                break
        assert len(delivered) == 1
        frame = delivered[0]
        credential = base64.b64decode(frame["credential_b64"], validate=True)
        binding = frame["binding"]

        # Synthetic protected-store save/readback proof, signed with the exact
        # one-use credential sent to this same WSS actor.
        ack = {
            "challenge_id": challenge_id, "device_id": DEVICE,
            "binding_ref": binding["binding_ref"],
            "credential_generation": binding["credential_generation"],
            "proof_kind": "protected_store_save_readback",
            "transcript_version": "padiem.connector-device-install-ack.v1",
            "local_store_confirmed": True,
            "proof_hex": installation_proof(
                credential=credential, challenge_id=challenge_id, device_id=DEVICE,
                binding_ref=binding["binding_ref"],
                credential_generation=binding["credential_generation"],
            ),
        }
        body = json.dumps(ack, sort_keys=True, separators=(",", ":")).encode()
        ack_mac = session_mac(
            pairing_code=pairing_code, challenge_id=challenge_id, device_id=DEVICE,
            nonce_hex=nonce["nonce_hex"], lease_ref=frame["lease_ref"],
            action="install_ack", counter=2,
            payload_sha256=hashlib.sha256(body).hexdigest(),
        )
        await broker_pending_pc_wss_message(
            do, server, json.dumps({
                "type": "install_ack", "counter": 2,
                "body_b64": base64.b64encode(body).decode(),
                "proof_hex": ack_mac,
            })
        )
        result = await asyncio.wait_for(owner_task, timeout=3)

        assert result["credential_installed_by_canonical_handoff"] is True
        assert result["lifecycle"] == "paired_offline"
        assert result["dispatch_authorized"] is False
        assert result["raw_device_credential"] is False
        assert len([f for f in server.sent if f.get("type") == "credential_once"]) == 1
        assert len([f for f in server.sent if f.get("type") == "terminal"]) == 1
        assert server.sent[-1] == {
            "type": "terminal", "status": "paired_offline",
            "can_retry_challenge": False,
        }

    asyncio.run(run())
