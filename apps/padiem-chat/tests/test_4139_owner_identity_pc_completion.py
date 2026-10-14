"""Only B54's existing Identity/consent service can accept a claimed PC proof.
No raw credential, false 'paired_offline', browser payload, or HTTP mount.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import pytest

from app.connector_owner_identity_pc_completion import (
    CanonicalOwnerPcIdentityPreflight, VerifiedCanonicalPcHandoff,
    B54_NATIVE_PC_IDENTITY_COMPLETION_ROUTE_MOUNTED,
    B54_NATIVE_PC_IDENTITY_COMPLETION_PRODUCTION_ENABLED,
)
from app.control_plane_identity import IdentityBridgeError
from test_4139_connector_one_click_approval import session

REF="link."+"a"*32
CHALLENGE="pairing."+"d"*32
DEVICE="windows.device.1"
PROOF="pairing-proof:"+"e"*64

class Source:
    def __init__(self):
        self.calls=[]
        self.withdraw=False
        self.withdraw_after_claim=False
        self.identity_rejected=False
        self.malformed_claim=False
        self.malformed_status=False
        self.claimed=False
        self.owner="owner.1"
        self.binding={
            "challenge_id":CHALLENGE,"device_id":DEVICE,
            "consent_ref":"consent.1","owner_ref":self.owner,
            "account_ref":"account.1","workspace_ref":"workspace.1",
        }

    async def pending_pc_identity_status(self,payload):
        self.calls.append(("status",payload))
        assert payload=={"request_ref":REF}
        if self.malformed_status:
            return {"request_ref":REF, "challenge_id":CHALLENGE,
                    "device_id":DEVICE,"signed_fetch_verified":"true",
                    "identity_authorized":False,"credential_issued":False,
                    "connected":False}
        return {
            "request_ref":REF,"challenge_id":CHALLENGE,"device_id":DEVICE,
            "signed_fetch_verified":True,"identity_authorized":False,
            "credential_issued":False,"connected":False,
        }

    async def get_enrollment_binding(self,*,challenge_id):
        self.calls.append(("binding",challenge_id))
        assert challenge_id==CHALLENGE
        return dict(self.binding)

    async def resolve_connector_enrollment_consent_for_device(self,*,session_id,device_id):
        self.calls.append(("consent",session_id,device_id))
        assert session_id=="canonical.session.1"
        return {
            "consent_id":"consent.1","device_id":device_id,
            "owner_subject_id":self.owner,"account_ref":"account.1",
            "workspace_ref":"workspace.1",
            "withdrawn_at":(
                "2026-10-14T07:00:00Z" if self.withdraw or (
                    self.withdraw_after_claim and self.claimed
                ) else None
            ),
        }

    async def authorize_connector_enrollment_redeem(self,**kw):
        self.calls.append(("authorize",kw))
        if self.identity_rejected:
            raise RuntimeError("withdrawn original consent")
        return {
            "challenge_id":CHALLENGE,"device_id":DEVICE,
            "consent_id":"consent.1","owner_subject_id":self.owner,
            "account_ref":"account.1","workspace_ref":"workspace.1",
        }

    async def claim_pending_pc_identity_proof(self,payload):
        self.calls.append(("claim",payload))
        if self.claimed:
            raise ValueError("one-use claimed; cannot retry")
        self.claimed=True
        if self.malformed_claim:
            return {"request_ref":REF,"challenge_id":CHALLENGE,
                    "device_id":DEVICE,"proof_ref":PROOF,
                    "identity_authorized":True,
                    "credential_issued":True,"connected":True}
        return {
            "request_ref":REF,"challenge_id":CHALLENGE,
            "device_id":DEVICE,"proof_ref":PROOF,
            "identity_authorized":False,
            "credential_issued":False,"connected":False,
        }

def run(source, *, owner=None):
    port=CanonicalOwnerPcIdentityPreflight(
        identity=source,broker=source,private_broker=source,
    )
    return asyncio.run(port.prepare(
        signed_owner=owner or session(),request_ref=REF,
    ))


def test_signed_b54_owner_existing_identity_checks_before_one_use_claim():
    fake=Source()
    value=run(fake)
    assert type(value) is VerifiedCanonicalPcHandoff
    assert value.challenge_id==CHALLENGE
    assert value.device_id==DEVICE
    assert value.proof_ref==PROOF
    assert value.request_ref==REF
    assert PROOF not in repr(value)
    assert [entry[0] for entry in fake.calls]==[
        "status","binding","consent","authorize","claim","consent",
    ]
    assert fake.calls[4][1]=={
        "request_ref":REF,"challenge_id":CHALLENGE,"device_id":DEVICE,
    }
    assert all(name not in ("redeem","credential_once","paired_offline")
               for name,*_ in fake.calls)
    with pytest.raises(IdentityBridgeError,match="Current PC handoff"):
        run(fake)
    assert len([x for x in fake.calls if x[0]=="claim"])==2


@pytest.mark.parametrize("invalid",[
    {"product":"b62"}, {"active":False},
])
def test_cross_product_or_expired_owner_denied_without_broker_calls(invalid):
    fake=Source()
    with pytest.raises(IdentityBridgeError) as exc:
        run(fake,owner=session(**invalid))
    assert exc.value.code=="pending_pc_owner_required"
    assert fake.calls==[]


@pytest.mark.parametrize("mutator",[
    lambda x:setattr(x,"owner","other.owner"),
    lambda x:x.binding.update(device_id="other.device"),
    lambda x:x.binding.update(consent_ref="consent.other"),
    lambda x:setattr(x,"withdraw",True),
    lambda x:setattr(x,"identity_rejected",True),
])
def test_unauthorized_or_withdrawn_identity_never_claims_proof(mutator):
    fake=Source()
    mutator(fake)
    with pytest.raises(IdentityBridgeError) as exc:
        run(fake)
    assert exc.value.code=="pending_pc_identity_unconfirmed"
    assert all(x[0]!="claim" for x in fake.calls)


def test_nonboolean_signed_status_never_triggers_identity_calls():
    fake=Source()
    fake.malformed_status=True
    with pytest.raises(IdentityBridgeError) as exc:
        run(fake)
    assert exc.value.code=="pending_pc_fetch_invalid"
    assert [x[0] for x in fake.calls]==["status"]


def test_fake_private_claim_does_not_become_credential_grant():
    fake=Source()
    fake.malformed_claim=True
    with pytest.raises(IdentityBridgeError) as exc:
        run(fake)
    assert exc.value.code=="pending_pc_claim_invalid"
    assert fake.claimed is True
    assert "redeem" not in [x[0] for x in fake.calls]


def test_consent_revoked_across_do_claim_is_not_retried_or_reported():
    fake=Source()
    fake.withdraw_after_claim=True
    with pytest.raises(IdentityBridgeError) as exc:
        run(fake)
    assert exc.value.code=="pending_pc_identity_changed"
    assert fake.claimed is True
    assert [x[0] for x in fake.calls][-2:]==["claim","consent"]
    with pytest.raises(IdentityBridgeError):
        run(fake)
    assert all(x[0]!="redeem" for x in fake.calls)


def test_no_unreviewed_public_binding_ever_enabled():
    assert B54_NATIVE_PC_IDENTITY_COMPLETION_ROUTE_MOUNTED is False
    assert B54_NATIVE_PC_IDENTITY_COMPLETION_PRODUCTION_ENABLED is False
    with pytest.raises(ValueError,match="canonical B54"):
        CanonicalOwnerPcIdentityPreflight(
            identity=object(),broker=object(),private_broker=object(),
        )
