"""B54 original canonical Host -> same-Broker private native PC gateway port.

Synthetic Service Binding and ACK, NOT real Windows DPAPI/live Cloudflare.
The protected Host is reused, its Identity and original Broker remain sole
authorities; no client-origin/supplied session or browser credential response.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.canonical_connector_gateway_handoff import CanonicalGatewayProtectedHandoff
from app.canonical_connector_credential_handoff import (
    installation_proof, DeviceCredentialInstallAck,
)
from app.canonical_connector_enrollment_async_host import CanonicalConnectorEnrollmentAsyncHost
from app.connector_native_pc_gateway_port import (
    CanonicalNativePcTrustedGateway, NativePcGatewayDenied,
    REVIEW_ONLY_NATIVE_PC_GATEWAY_WIRED,
    REVIEW_ONLY_NATIVE_PC_GATEWAY_PRODUCTION_ENABLED,
)
from app.connector_owner_identity_pc_completion import VerifiedCanonicalPcHandoff
from app.control_plane_identity import IdentityBridgeError
from test_4139_connector_enrollment_async_host import (
    Identity, Broker, CHALLENGE, BINDING, ENROLLMENT, CONSENT,
)

REQ="link."+"a"*32
DEVICE=CONSENT["device_id"]
ID=CHALLENGE["challenge_id"]
PROOF="pairing-proof:"+"e"*64
LEASE="gateway."+"f"*32


def verified():
    return VerifiedCanonicalPcHandoff(
        request_ref=REQ,challenge_id=ID,device_id=DEVICE,proof_ref=PROOF,
    )


class PrivateNativeBroker:
    def __init__(self):
        self.calls=[]
        self.credential=None
        self.binding=None
        self.ack=None
        self.reject_auth=False
        self.forge_ack=False
        self.disconnect=False

    async def reserve_native_pc_gateway(self, payload):
        self.calls.append(("reserve",payload))
        assert payload=={
            "request_ref":REQ,"challenge_id":ID,"device_id":DEVICE,
        }
        return {
            **payload,"lease_ref":LEASE,
            "expires_at":(datetime.now(timezone.utc)+timedelta(seconds=40)).isoformat(),
            "authenticated":True,"credential_issued":False,
        }

    async def authenticate_native_pc_gateway(self,payload):
        self.calls.append(("authenticate",payload))
        return {
            **payload,"authenticated":not self.reject_auth,
            "credential_issued":False,
        }

    async def transfer_native_pc_credential_once(self,payload):
        self.calls.append(("send",payload))
        assert payload["request_ref"]==REQ
        assert payload["challenge_id"]==ID and payload["device_id"]==DEVICE
        assert payload["lease_ref"]==LEASE
        assert set(payload["binding"])=={
            "binding_ref","device_id","account_ref","workspace_ref",
            "credential_ref","credential_generation","credential_expires_at",
        }
        import base64
        self.credential=base64.b64decode(payload["credential_b64"],validate=True)
        self.binding=payload["binding"]
        return {"sent_once":True,"credential_installed":False,"registered":False}

    async def receive_native_pc_install_ack(self,payload):
        self.calls.append(("ack",payload))
        if self.disconnect:
            raise RuntimeError("same PC socket terminated")
        b=self.binding
        assert self.credential is not None and b is not None
        self.ack={
            "challenge_id":ID,"device_id":DEVICE,
            "binding_ref":b["binding_ref"],
            "credential_generation":b["credential_generation"],
            "proof_kind":"protected_store_save_readback",
            "transcript_version":"padiem.connector-device-install-ack.v1",
            "local_store_confirmed":True,
            "proof_hex":installation_proof(
                credential=self.credential,challenge_id=ID,device_id=DEVICE,
                binding_ref=b["binding_ref"],
                credential_generation=b["credential_generation"],
            ),
        }
        if self.forge_ack:
            self.ack["proof_hex"]="0"*64
        return {"ack":dict(self.ack),
                "source_authenticated":True,"registered":False}

    async def authenticate_native_pc_install_ack(self,payload):
        self.calls.append(("ack_sender",payload))
        return {
            "source_authenticated":(
                not self.disconnect and payload["ack"]==self.ack
            ),
            "registered":False,
        }

    async def complete_native_pc_enrollment(self,payload):
        self.calls.append(("terminal",payload))
        assert payload=={
            "request_ref":REQ,"challenge_id":ID,"device_id":DEVICE,"lease_ref":LEASE,
        }
        if getattr(self,"terminal_lost",False):
            raise RuntimeError("terminal delivery not confirmed")
        return {"sent_once":True,"connected":False}


class OriginalBroker(Broker):
    async def redeem_enrollment(self, **kwargs):
        value,secret=await super().redeem_enrollment(**kwargs)
        value["credential_ref"]="credential.1"
        return value,secret


def host(*, native=None, identity=None, broker=None):
    n=native or PrivateNativeBroker()
    port=CanonicalNativePcTrustedGateway(
        verified=verified(),private_broker=n,
    )
    h=CanonicalConnectorEnrollmentAsyncHost(
        identity=identity or Identity(), broker=broker or OriginalBroker(),
        credential_handoff=CanonicalGatewayProtectedHandoff(gateway=port),
    )
    return h,n,port


def test_original_B54_host_redeems_only_after_private_same_pc_WSS_ack():
    service,native,port=host()
    result=asyncio.run(service.redeem(
        challenge_id=ID,device_id=DEVICE,proof_ref=PROOF,
    ))
    assert result["credential_installed_by_canonical_handoff"] is True
    assert result["lifecycle"]=="paired_offline"
    assert result["raw_device_credential"] is False
    assert result["dispatch_authorized"] is False
    assert [x[0] for x in native.calls]==[
        "reserve","authenticate","send","ack","ack_sender",
    ]
    assert native.credential==b"one-time-secret-with-length"
    assert native.credential not in repr(result).encode()
    assert "credential" not in repr(result).lower() or result["raw_device_credential"] is False


def test_native_gateway_missing_RPC_fails_before_canonical_broker_redemption():
    class Missing:
        async def reserve_native_pc_gateway(self,payload): return {}
    with pytest.raises(NativePcGatewayDenied,match="private_broker_missing"):
        CanonicalNativePcTrustedGateway(verified=verified(),private_broker=Missing())


def test_no_raw_dict_can_forge_signed_owner_private_proof():
    with pytest.raises(NativePcGatewayDenied,match="verified_owner_required"):
        CanonicalNativePcTrustedGateway(
            verified={"request_ref":REQ,"challenge_id":ID,"device_id":DEVICE},
            private_broker=PrivateNativeBroker(),
        )


def test_canonical_host_refuses_unverified_native_session_before_redeem():
    original=OriginalBroker()
    fixture=PrivateNativeBroker()
    fixture.reject_auth=True
    service,native,port=host(native=fixture,broker=original)
    with pytest.raises(IdentityBridgeError) as caught:
        asyncio.run(service.redeem(
            challenge_id=ID,device_id=DEVICE,proof_ref=PROOF,
        ))
    assert caught.value.code=="credential_handoff_unavailable"
    assert not any(x[0]=="redeem" for x in original.calls)
    assert not any(x[0]=="send" for x in native.calls)


def test_uncertain_native_ack_revokes_original_canonical_Broker_binding():
    original=OriginalBroker()
    fixture=PrivateNativeBroker()
    fixture.disconnect=True
    service,native,port=host(native=fixture,broker=original)
    with pytest.raises(IdentityBridgeError) as caught:
        asyncio.run(service.redeem(
            challenge_id=ID,device_id=DEVICE,proof_ref=PROOF,
        ))
    assert caught.value.code=="enrollment_credential_handoff_failed"
    assert [x[0] for x in original.calls][-2:]==["redeem","revoke"]
    assert len([x for x in native.calls if x[0]=="send"])==1


def test_keyed_dpapi_ack_tamper_forces_canonical_Broker_revoke():
    original=OriginalBroker()
    fixture=PrivateNativeBroker()
    fixture.forge_ack=True
    service,native,port=host(native=fixture,broker=original)
    with pytest.raises(IdentityBridgeError) as caught:
        asyncio.run(service.redeem(
            challenge_id=ID,device_id=DEVICE,proof_ref=PROOF,
        ))
    assert caught.value.code=="enrollment_credential_handoff_failed"
    assert [x[0] for x in original.calls][-2:]==["redeem","revoke"]
    assert not any(x[0]=="ack_sender" for x in native.calls)


def test_all_new_completion_ports_default_OFF():
    assert REVIEW_ONLY_NATIVE_PC_GATEWAY_WIRED is False
    assert REVIEW_ONLY_NATIVE_PC_GATEWAY_PRODUCTION_ENABLED is False


class SameOriginalOwnerIdentity(Identity):
    async def resolve_connector_enrollment_consent_for_device(
        self, *, session_id, device_id,
    ):
        self.calls.append(("current_owner",session_id,device_id))
        assert session_id=="canonical.session.1"
        assert device_id==DEVICE
        return dict(CONSENT)


class SamePcOwnerPrivateGateway(PrivateNativeBroker):
    def __init__(self):
        super().__init__()
        self.claims=0

    async def pending_pc_identity_status(self,payload):
        assert payload=={"request_ref":REQ}
        self.calls.append(("live_pc_status",payload))
        if getattr(self, "defer_status_once", False):
            self.defer_status_once = False
            raise RuntimeError("signed PC fetch has not arrived yet")
        return {
            "request_ref":REQ,"challenge_id":ID,"device_id":DEVICE,
            "signed_fetch_verified":True,"identity_authorized":False,
            "credential_issued":False,"connected":False,
        }

    async def claim_pending_pc_identity_proof(self,payload):
        assert payload=={
            "request_ref":REQ,"challenge_id":ID,"device_id":DEVICE,
        }
        self.calls.append(("identity_proof_claim",payload))
        if self.claims:
            raise ValueError("already claimed by original DO")
        self.claims+=1
        return {
            **payload,"proof_ref":PROOF,
            "identity_authorized":False,
            "credential_issued":False,"connected":False,
        }


@pytest.mark.parametrize("delayed_fetch,terminal_lost", [(False,False),(True,False),(False,True)])
def test_one_existing_signed_B54_owner_proceeds_through_canonical_host_and_ack(delayed_fetch,terminal_lost):
    from dataclasses import replace
    from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
    from app.connector_owner_identity_pc_completion import CanonicalOwnerPcIdentityPreflight
    from app.connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
    from test_4139_connector_one_click_approval import session

    ident=SameOriginalOwnerIdentity()
    broker=OriginalBroker()
    private=SamePcOwnerPrivateGateway()
    private.defer_status_once = delayed_fetch
    private.terminal_lost = terminal_lost
    preflight=CanonicalOwnerPcIdentityPreflight(
        identity=ident,broker=broker,private_broker=private,
    )
    service=CanonicalOwnerNativePcCompletion(
        identity=ident,broker=broker,
        private_broker=private,preflight=preflight,
    )
    original_session=replace(
        session(),
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER,subject_id=CONSENT["owner_subject_id"],
        ),
    )
    if terminal_lost:
        with pytest.raises(IdentityBridgeError) as exc:
            asyncio.run(service.complete(signed_owner=original_session,request_ref=REQ))
        assert exc.value.code=="native_pc_terminal_unconfirmed"
        assert broker.calls[-1][0]=="revoke"
        assert len([x for x in private.calls if x[0]=="terminal"])==1
        return
    result=asyncio.run(service.complete(signed_owner=original_session,request_ref=REQ))
    assert result["lifecycle"]=="paired_offline"
    assert result["credential_installed_by_canonical_handoff"] is True
    assert result["dispatch_authorized"] is False
    assert result["raw_device_credential"] is False
    assert private.claims==1
    assert len([c for c in broker.calls if c[0]=="redeem"])==1
    assert [c[0] for c in private.calls]==(["live_pc_status"] if delayed_fetch else [])+[
        "live_pc_status","identity_proof_claim",
        "reserve","authenticate","send","ack","ack_sender","terminal",
    ]
    assert len([c for c in ident.calls if c[0]=="authorize"])>=4
    # A second owner attempt cannot mint a new credential: original
    # Broker one-use PC proof claim denies it before redemption.
    with pytest.raises(IdentityBridgeError,match="Current PC handoff"):
        asyncio.run(service.complete(
            signed_owner=original_session,request_ref=REQ,
        ))
    assert len([c for c in broker.calls if c[0]=="redeem"])==1
