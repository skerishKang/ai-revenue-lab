"""PC-side source-only ephemeral offer → owner approval → same socket.

Synthetic TLS verifier/WSS only; never claims installed hardware or live owner.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from claw_connect.pending_pc_offer import (
    run_pending_pc_offer, run_pending_pc_offer_and_enroll,
    ownership_transcript, pending_owner_approval_url,
    PC_OFFER_PRODUCTION_ENABLED, PC_OFFER_AUTOSTART_ENABLED,
)
from claw_connect.device_wss_enrollment import DeviceSessionRefused

DEVICE = "device.pc.1"
NONCE = "b"*64
REQUEST = "link."+"a"*32
CODE = "c"*32
CHALLENGE = "challenge.1"


def expiry():
    return (datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()


class FakeTls:
    def __init__(self, *, admitted=True):
        self.admitted = admitted
        self.calls = 0
    async def verify(self, socket):
        self.calls += 1
        return self.admitted


class FakePcSocket:
    def __init__(self):
        self.outbound = []
        self.public = None
        self.received_nonce = False
        self.offer_granted = False
        self.approval_attempted = False
        self.closed = False
        self.challenge_device = DEVICE
        self.ready_ref = REQUEST
        self.ready_expiry = expiry()
        self.approval_ref = REQUEST
        self.approval_code = CODE
        self.approval_device = DEVICE
    async def send_text(self, raw):
        frame = json.loads(raw)
        self.outbound.append(frame)
        if frame["type"] == "pc_offer_begin":
            self.public = base64.b64decode(frame["public_key_b64"], validate=True)
            assert len(self.public) == 32
        if frame["type"] == "pc_offer_prove":
            signature = base64.b64decode(frame["signature_b64"], validate=True)
            Ed25519PublicKey.from_public_bytes(self.public).verify(
                signature,
                ownership_transcript(
                    device_id=DEVICE, nonce_hex=NONCE, public_key=self.public,
                ),
            )
            self.offer_granted = True
    async def receive_text(self):
        if self.public is not None and not self.received_nonce:
            self.received_nonce = True
            return json.dumps({
                "type": "pc_offer_challenge", "device_id": self.challenge_device,
                "nonce_hex": NONCE,
            })
        if self.offer_granted and not self.approval_attempted:
            self.approval_attempted = True
            return json.dumps({
                "type": "pc_offer_ready", "device_id": DEVICE,
                "request_ref": self.ready_ref, "expires_at": self.ready_expiry,
            })
        if self.approval_attempted:
            return json.dumps({
                "type": "pc_offer_approved", "device_id": self.approval_device,
                "request_ref": self.approval_ref,
                "challenge_id": CHALLENGE, "pairing_code": self.approval_code,
            })
        raise AssertionError("Unexpected WSS state")
    async def close(self):
        self.closed = True


def run(socket=None, tls=None, callback=None):
    socket = socket or FakePcSocket()
    tls = tls or FakeTls()
    urls = []
    callback = callback or urls.append
    result = asyncio.run(run_pending_pc_offer(
        socket=socket, trusted_tls=tls, device_id=DEVICE,
        owner_approval_open=callback,
    ))
    return socket, tls, urls, result


def test_generated_ephemeral_signature_and_one_click_browser_link_only():
    socket, tls, urls, (receipt, challenge, code) = run()
    assert tls.calls == 1
    assert [item["type"] for item in socket.outbound] == [
        "pc_offer_begin", "pc_offer_prove",
    ]
    assert receipt.request_ref == REQUEST and receipt.device_id == DEVICE
    assert receipt.awaiting_confirmation is True
    assert receipt.authenticated_owner is False and receipt.enrolled is False
    assert (challenge, code) == (CHALLENGE, CODE)
    assert urls == [
        "https://chat.padiem.net/api/claw/connector/enrollments/setup"
        "?request_ref="+REQUEST
    ]
    assert CODE not in urls[0]
    assert CHALLENGE not in urls[0]
    assert socket.closed is False  # SAME socket remains open for canonical WSS!


def test_unverified_tls_cannot_even_send_offer():
    socket = FakePcSocket()
    with pytest.raises(DeviceSessionRefused, match="tls_not_verified"):
        run(socket=socket, tls=FakeTls(admitted=False))
    assert socket.outbound == []


@pytest.mark.parametrize("mutate,reason", [
    ({"challenge_device": "different.device"}, "challenge_invalid"),
    ({"ready_ref": "link."+"A"*32}, "ref_invalid"),
    ({"ready_ref": REQUEST+"?owner=evil"}, "ref_invalid"),
    ({"ready_expiry": "bad"}, "expiry_invalid"),
    ({"ready_expiry": (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}, "expiry_invalid"),
    ({"ready_expiry": (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}, "expiry_invalid"),
    ({"approval_ref": "link."+"d"*32}, "approval_invalid"),
    ({"approval_device": "other.device"}, "approval_invalid"),
    ({"approval_code": "not-pairing"}, "approval_invalid"),
])
def test_spoofed_challenge_offer_approval_refused(mutate, reason):
    socket = FakePcSocket()
    for name, value in mutate.items():
        setattr(socket, name, value)
    with pytest.raises(DeviceSessionRefused, match=reason):
        run(socket=socket)


def test_untrusted_browser_launch_ref_is_rejected_without_url():
    for invalid in ("", "../bad", REQUEST+"&bearer=1", 42, None):
        with pytest.raises(DeviceSessionRefused, match="ref_invalid"):
            pending_owner_approval_url(invalid)


def test_normal_pc_enroll_can_only_start_after_same_socket_one_time_approval(monkeypatch):
    socket = FakePcSocket()
    tls = FakeTls()
    record = SimpleNamespace(device_id=DEVICE)
    enrollment = SimpleNamespace(record=lambda: record)
    entered = []

    async def canonical(**kwargs):
        entered.append(kwargs)
        return {"canonical_dpapi_ack_required": True}
    import claw_connect.device_wss_enrollment as existing
    monkeypatch.setattr(existing, "run_and_stage_review_only_device_enrollment", canonical)
    def owner(url):
        assert url.endswith(REQUEST)
        assert socket.approval_attempted
    result = asyncio.run(run_pending_pc_offer_and_enroll(
        socket=socket, trusted_tls=tls, enrollment=enrollment,
        receiver=object(), owner_approval_open=owner,
        binding_factory=lambda *a, **k: None,
    ))
    assert result == {"canonical_dpapi_ack_required": True}
    assert len(entered) == 1
    assert entered[0]["socket"] is socket
    assert entered[0]["enrollment"] is enrollment
    assert entered[0]["challenge_id"] == CHALLENGE
    assert entered[0]["pairing_code"] == CODE
    assert socket.closed is True


def test_failed_offer_never_calls_canonical_enrollment(monkeypatch):
    socket = FakePcSocket()
    socket.approval_code = "forged"
    import claw_connect.device_wss_enrollment as existing
    entered=[]
    async def canonical(**kwargs):
        entered.append(kwargs)
    monkeypatch.setattr(existing,"run_and_stage_review_only_device_enrollment",canonical)
    with pytest.raises(DeviceSessionRefused, match="approval_invalid"):
        asyncio.run(run_pending_pc_offer_and_enroll(
            socket=socket, trusted_tls=FakeTls(),
            enrollment=SimpleNamespace(record=lambda:SimpleNamespace(device_id=DEVICE)),
            receiver=object(), owner_approval_open=lambda _:None,
        ))
    assert entered == []
    assert socket.closed is True


def test_production_and_autostart_never_enabled_by_import():
    assert PC_OFFER_PRODUCTION_ENABLED is False
    assert PC_OFFER_AUTOSTART_ENABLED is False


def test_real_pinned_wss_dialer_one_click_review_gate_is_closed_by_default(monkeypatch):
    import claw_connect.review_wss_transport as transport
    called = []
    monkeypatch.setattr(transport, "open_review_only_wss_socket",
                        lambda **kwargs: called.append(kwargs))
    with pytest.raises(DeviceSessionRefused, match="not_authorized"):
        asyncio.run(transport.run_review_only_one_click_pc_link(
            enrollment=object(), receiver=object(), owner_approval_open=lambda _: None,
        ))
    assert called == []
    monkeypatch.setattr(transport, "WSS_PRODUCTION_DIALER_ENABLED", True)
    with pytest.raises(DeviceSessionRefused, match="production_gate_changed"):
        asyncio.run(transport.run_review_only_one_click_pc_link(
            enrollment=object(), receiver=object(), owner_approval_open=lambda _: None,
            source_test_authorized=True,
        ))
    assert called == []


def test_one_click_review_reuses_exact_preapproved_wss_socket(monkeypatch):
    from contextlib import asynccontextmanager
    import claw_connect.review_wss_transport as transport
    import claw_connect.pending_pc_offer as pending

    socket = object()
    seen = []
    @asynccontextmanager
    async def reviewed(*, source_test_authorized=False, acceptance=False):
        seen.append(("dial", source_test_authorized, acceptance))
        yield socket
        seen.append(("closed",))
    monkeypatch.setattr(transport, "open_review_only_wss_socket", reviewed)

    async def same_socket(*, socket, trusted_tls, enrollment,
                          receiver, owner_approval_open, acceptance=False):
        seen.append(("pipeline", socket, type(trusted_tls).__name__, acceptance))
        assert socket is expected
        assert enrollment is registration
        assert receiver is store
        assert owner_approval_open is browser
        return "source_only_ack"
    monkeypatch.setattr(pending, "run_pending_pc_offer_and_enroll", same_socket)
    expected = socket
    registration = object()
    store = object()
    def browser(url):
        raise AssertionError("fake transport must not launch browser")
    result = asyncio.run(transport.run_review_only_one_click_pc_link(
        enrollment=registration, receiver=store,
        owner_approval_open=browser,
        source_test_authorized=True, acceptance=True,
    ))
    assert result == "source_only_ack"
    assert seen == [
        ("dial", True, True), ("pipeline", socket, "VerifiedReviewTls", True),
        ("closed",),
    ]


def test_acceptance_PC_WSS_opens_only_isolated_owner_approval_origin():
    socket=FakePcSocket()
    urls=[]
    received=asyncio.run(run_pending_pc_offer(
        socket=socket,trusted_tls=FakeTls(),device_id=DEVICE,
        owner_approval_open=urls.append,acceptance=True,
    ))
    assert received[0].request_ref==REQUEST
    assert urls==[
        "https://connector-acceptance.padiem.net"
        "/api/claw/connector/enrollments/setup?request_ref="+REQUEST
    ]
    assert CODE not in urls[0] and CHALLENGE not in urls[0]
    assert socket.closed is False


def test_owner_approval_url_rejects_forged_stage_selector():
    for invalid in (1,"true",None,[],{}):
        with pytest.raises(DeviceSessionRefused,match="pc_offer_origin_invalid"):
            pending_owner_approval_url(REQUEST, acceptance=invalid)
