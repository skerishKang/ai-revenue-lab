"""#8061 12차: the connector one-click approval hub's shared test setup."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.connector_one_click_approval import (
    OneClickDenied, OneClickOwnerApproval,
)
from app.control_plane_identity import IdentityBridgeError
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

REQUEST = "link." + "a" * 32
DEVICE = "windows.device.1"
CODE = "b" * 32
CHALLENGE = "challenge.1"


def session(*, product="b54-padiem-claw", active=True):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="canonical.session.1", product_id=product,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="owner.1"),
        issued_at=now-timedelta(minutes=1 if active else 180),
        expires_at=now+timedelta(hours=1 if active else -1),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.1",
    )


def pending(**overrides):
    item = {
        "request_ref": REQUEST, "device_id": DEVICE,
        "device_possession_verified": True,
        "connected_to_outbound_channel": True, "reserved_once": True,
        "expires_at": (datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),
    }
    item.update(overrides)
    return item


class Fixture:
    def __init__(self):
        self.calls = []
        self.pending = pending()
        self.consent = {
            "device_id": DEVICE, "consent_id": "consent.1",
            "withdrawn_at": None, "dispatch_authorized": False,
            "grants_read": False, "grants_write": False,
        }
        self.issued = {
            "challenge": {"challenge_id": CHALLENGE},
            "pairing_code": CODE,
            "code_returned_once": True, "raw_device_credential": False,
            "dispatch_authorized": False,
        }
        self.delivery_fails = False
        self.attestation_fails = False
        self.reserved = False

    async def reserve_once(self, *, request_ref):
        self.calls.append(("attest", request_ref))
        if self.attestation_fails or self.reserved:
            raise RuntimeError("sensitive upstream attestation or duplicate intent")
        self.reserved = True
        return self.pending

    async def resolve_connector_enrollment_consent_for_device(self, **kwargs):
        raise IdentityBridgeError(403, "enrollment_consent_required", "No prior consent")

    async def resolve_connector_owner_scope(self, *, session_id):
        assert session_id == "canonical.session.1"
        return {"account_ref": "account.1", "workspace_ref": "workspace.1"}

    async def grant_connector_enrollment_consent(self, **kwargs):
        self.calls.append(("consent", kwargs))
        return self.consent

    async def issue(self, **kwargs):
        self.calls.append(("issue", kwargs))
        return self.issued

    async def deliver_once(self, **kwargs):
        self.calls.append(("deliver", kwargs))
        if self.delivery_fails:
            raise RuntimeError("sensitive pairing code in error")

    def service(self):
        return OneClickOwnerApproval(identity=self, host=self, pc_rendezvous=self)

    def run(self, **kwargs):
        return asyncio.run(self.service().approve(
            owner_session=kwargs.pop("owner_session", session()),
            request_ref=kwargs.pop("request_ref", REQUEST),
            confirmed=kwargs.pop("confirmed", True),
        ))


def refused(fx, expected, **kwargs):
    with pytest.raises(OneClickDenied) as err:
        fx.run(**kwargs)
    assert str(err.value) == expected
    assert CODE not in str(err.value)
