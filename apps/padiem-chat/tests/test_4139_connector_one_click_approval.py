"""No-manual-code owner->PC handoff only after canonical signed owner approval.

Synthetic isolated transport only; neither real device enrollment nor live
worker routing is claimed by these tests.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.connector_one_click_approval import (
    ONE_CLICK_ENROLLMENT_HTTP_MOUNTED, ONE_CLICK_ENROLLMENT_PRODUCTION_ENABLED,
    OneClickDenied, OneClickOwnerApproval,
)
from app.app_factory import create_app
from app.config import Settings
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


def test_one_owner_click_delivers_code_only_on_attested_pc_channel():
    fx = Fixture()
    result = fx.run()
    assert result == {
        "ok": True, "state": "awaiting_device_confirmation",
        "device_id": DEVICE, "connected": False, "registered": False,
        "dispatch_authorized": False,
    }
    assert [call[0] for call in fx.calls] == ["attest", "consent", "issue", "deliver"]
    assert fx.calls[1][1] == {
        "session_id": "canonical.session.1", "device_id": DEVICE,
        "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1",
    }
    assert fx.calls[2][1] == {
        "canonical_session_id": "canonical.session.1", "device_id": DEVICE,
    }
    assert fx.calls[3][1] == {
        "request_ref": REQUEST, "device_id": DEVICE,
        "challenge_id": CHALLENGE, "pairing_code": CODE,
    }
    assert CODE not in repr(result)
    assert CHALLENGE not in repr(result)


@pytest.mark.parametrize("kwargs", [
    {"owner_session": session(product="b66-quote")},
    {"owner_session": session(active=False)},
    {"owner_session": None},
    {"confirmed": False},
    {"confirmed": "true"},
    {"request_ref": "link.invalid"},
    {"request_ref": REQUEST + "?cookie=bad"},
    {"request_ref": None},
])
def test_owner_session_consent_and_intent_shape_fail_before_any_pc_call(kwargs):
    fx = Fixture()
    refused(fx, "explicit_pc_consent_required"
            if "confirmed" in kwargs else
            "invalid_pending_pc_request" if "request_ref" in kwargs else
            "canonical_owner_session_required", **kwargs)
    assert fx.calls == []


@pytest.mark.parametrize("change,reason", [
    ({"device_possession_verified": False}, "pending_pc_not_authenticated"),
    ({"connected_to_outbound_channel": False}, "pending_pc_not_authenticated"),
    ({"reserved_once": False}, "pending_pc_not_authenticated"),
    ({"request_ref": "link."+"c"*32}, "pending_pc_not_authenticated"),
    ({"device_id": "bad device"}, "pending_pc_not_authenticated"),
    ({"admin": True}, "pending_pc_not_authenticated"),
    ({"expires_at": "not-time"}, "pending_pc_expired"),
    ({"expires_at": (datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat()}, "pending_pc_expired"),
    ({"expires_at": (datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()}, "pending_pc_expired"),
    ({"expires_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}, "pending_pc_expired"),
])
def test_untrusted_pc_offer_never_reaches_identity_or_broker(change, reason):
    fx = Fixture()
    fx.pending.update(change)
    refused(fx, reason)
    assert [entry[0] for entry in fx.calls] == ["attest"]


def test_repeated_owner_approval_does_not_mint_another_broker_challenge():
    fx = Fixture()
    assert fx.run()["connected"] is False
    refused(fx, "pending_pc_unavailable")
    assert [entry[0] for entry in fx.calls] == [
        "attest", "consent", "issue", "deliver", "attest",
    ]


def test_attestation_dependency_failure_is_bounded():
    fx = Fixture()
    fx.attestation_fails = True
    refused(fx, "pending_pc_unavailable")
    assert len(fx.calls) == 1


@pytest.mark.parametrize("change", [
    {"device_id": "device-swapped"}, {"withdrawn_at": "2026-10-14T00:00:00Z"},
    {"consent_id": None}, {"grants_read": True},
    {"grants_write": True}, {"dispatch_authorized": True},
])
def test_canonical_consent_mutation_prevents_challenge_issue(change):
    fx = Fixture()
    fx.consent.update(change)
    refused(fx, "canonical_consent_unconfirmed")
    assert [entry[0] for entry in fx.calls] == ["attest", "consent"]


@pytest.mark.parametrize("change", [
    {"pairing_code": "bad"},
    {"raw_device_credential": True},
    {"dispatch_authorized": True},
    {"code_returned_once": False},
    {"challenge": {"challenge_id": "bad id"}},
    {"unreviewed_secret": "not allowed"},
])
def test_malformed_canonical_issuance_never_delivers_to_pc(change):
    fx = Fixture()
    fx.issued.update(change)
    refused(fx, "canonical_challenge_invalid")
    assert [entry[0] for entry in fx.calls] == ["attest", "consent", "issue"]


def test_failed_delivery_does_not_auto_reissue_or_leak_code():
    fx = Fixture()
    fx.delivery_fails = True
    refused(fx, "pc_delivery_unconfirmed")
    assert [entry[0] for entry in fx.calls] == ["attest", "consent", "issue", "deliver"]


def test_never_mounted_on_ordinary_product_routes():
    assert ONE_CLICK_ENROLLMENT_HTTP_MOUNTED is False
    assert ONE_CLICK_ENROLLMENT_PRODUCTION_ENABLED is False
    application = create_app(settings=Settings.from_env())
    assert not any("one-click" in str(getattr(route, "path", "")) for route in application.routes)
