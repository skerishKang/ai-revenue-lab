"""Unmounted PC-origin outbound WSS offer with ephemeral Ed25519 possession.

This is not an authenticated owner identity, Windows hardware attestation,
production dialer, registry launch, or credential. The authenticated owner
must separately approve this exact one-use offer. Only AFTER that approval
does the canonical one-socket WSS/DPAPI enrollment start.

The existing review-only strict TLS socket must be supplied by the caller.
Never send browser session/cookie/password, pairing code, or secret in URL,
argv, logs or disk. An installer/tray cannot invoke this path by default.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from .device_wss_enrollment import DeviceSessionRefused, _frame, _wire

PC_OFFER_PRODUCTION_ENABLED = False
PC_OFFER_AUTOSTART_ENABLED = False
OFFER_PROTOCOL_VERSION = "padiem.connector-pending-pc.v1"
OFFER_FRAME_TIMEOUT_SECONDS = 10.0
OFFER_OWNER_APPROVAL_TIMEOUT_SECONDS = 95.0
_OFFER = re.compile(r"^link\.[0-9a-f]{32}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")
_OWNER_URL = "https://chat.padiem.net/api/claw/connector/enrollments/setup"


def _exp(value: Any, now: datetime) -> datetime:
    if type(value) is not str:
        raise DeviceSessionRefused("pc_offer_expiry_invalid")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if (
            expiry.tzinfo is None or expiry.utcoffset() is None
            or expiry <= now or expiry > now + timedelta(seconds=90)
        ):
            raise ValueError("expiry outside bounded window")
        return expiry
    except (ValueError, TypeError, OverflowError) as exc:
        raise DeviceSessionRefused("pc_offer_expiry_invalid") from exc


def pending_owner_approval_url(request_ref: str) -> str:
    """Browser-visible correlation only; no secrets, credentials or authority."""
    if type(request_ref) is not str or _OFFER.fullmatch(request_ref) is None:
        raise DeviceSessionRefused("pc_offer_ref_invalid")
    return _OWNER_URL + "?request_ref=" + request_ref


def ownership_transcript(*, device_id: str, nonce_hex: str, public_key: bytes) -> bytes:
    """Domain-separated, exact v1 Ed25519 signature preimage."""
    if (
        type(device_id) is not str or _DEVICE.fullmatch(device_id) is None
        or type(nonce_hex) is not str or _HEX.fullmatch(nonce_hex) is None
        or type(public_key) is not bytes or len(public_key) != 32
    ):
        raise DeviceSessionRefused("pc_offer_proof_input_invalid")
    return (
        OFFER_PROTOCOL_VERSION.encode("ascii") + b"\n"
        + device_id.encode("ascii") + b"\n"
        + bytes.fromhex(nonce_hex) + b"\n"
        + public_key
    )


@dataclass(frozen=True, slots=True)
class PendingPcOfferReceipt:
    device_id: str
    request_ref: str
    expires_at: datetime
    awaiting_confirmation: bool = True
    authenticated_owner: bool = False
    enrolled: bool = False


async def run_pending_pc_offer(
    *, socket: Any, trusted_tls: Any, device_id: str,
    owner_approval_open: Callable[[str], Any],
    now: datetime | None = None,
) -> tuple[PendingPcOfferReceipt, str, str]:
    """Start a verified outbound WSS and receive the one-time owner approval.

    The returned challenge/code stay solely in the Python process; caller
    MUST immediately continue the existing canonical WSS enrollment on the
    SAME socket, or discard both. The one-shot socket is never retried.
    on_pending opens a normal HTTPS browser page with *only* a public ref.
    """
    if (
        type(device_id) is not str or _DEVICE.fullmatch(device_id) is None
        or not callable(getattr(trusted_tls, "verify", None))
        or not callable(getattr(socket, "send_text", None))
        or not callable(getattr(socket, "receive_text", None))
        or not callable(owner_approval_open)
    ):
        raise DeviceSessionRefused("pc_offer_preflight_denied")
    moment = now or datetime.now(timezone.utc)
    if moment.utcoffset() is None:
        raise DeviceSessionRefused("pc_offer_clock_invalid")

    try:
        # The signature proves possession of this ephemeral key, NOT a
        # preexisting device credential or hardware identity.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except ImportError as exc:
        raise DeviceSessionRefused("pc_offer_crypto_dependency_missing") from exc

    if await asyncio.wait_for(trusted_tls.verify(socket), timeout=5.0) is not True:
        raise DeviceSessionRefused("pc_offer_tls_not_verified")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    try:
        await asyncio.wait_for(
            socket.send_text(_wire({
                "type": "pc_offer_begin", "device_id": device_id,
                "public_key_b64": base64.b64encode(public).decode("ascii"),
            })),
            timeout=OFFER_FRAME_TIMEOUT_SECONDS,
        )
        frame = _frame(
            await asyncio.wait_for(socket.receive_text(), timeout=OFFER_FRAME_TIMEOUT_SECONDS),
            frozenset({"type", "device_id", "nonce_hex"}),
        )
        if (
            frame["type"] != "pc_offer_challenge" or frame["device_id"] != device_id
            or type(frame["nonce_hex"]) is not str or _HEX.fullmatch(frame["nonce_hex"]) is None
        ):
            raise DeviceSessionRefused("pc_offer_challenge_invalid")
        signature = private.sign(ownership_transcript(
            device_id=device_id, nonce_hex=frame["nonce_hex"], public_key=public,
        ))
        await asyncio.wait_for(
            socket.send_text(_wire({
                "type": "pc_offer_prove",
                "signature_b64": base64.b64encode(signature).decode("ascii"),
            })),
            timeout=OFFER_FRAME_TIMEOUT_SECONDS,
        )
        ready = _frame(
            await asyncio.wait_for(socket.receive_text(), timeout=OFFER_FRAME_TIMEOUT_SECONDS),
            frozenset({"type", "device_id", "request_ref", "expires_at"}),
        )
        if (
            ready["type"] != "pc_offer_ready" or ready["device_id"] != device_id
            or type(ready["request_ref"]) is not str
            or _OFFER.fullmatch(ready["request_ref"]) is None
        ):
            raise DeviceSessionRefused("pc_offer_ref_invalid")
        # The Broker starts the 90s lease AFTER our nonce/signature roundtrip.
        # Compare to receipt-arrival time, not the earlier PC offer-start time;
        # otherwise a legitimate exact-90s lease appears to exceed its bound.
        received_at = datetime.now(timezone.utc) if now is None else moment
        expires_at = _exp(ready["expires_at"], received_at)
        receipt = PendingPcOfferReceipt(
            device_id=device_id, request_ref=ready["request_ref"], expires_at=expires_at,
        )
        # This does not assert the browser user is signed in; the B54 owner
        # endpoint checks the signed session + explicit consent independently.
        owner_approval_open(pending_owner_approval_url(receipt.request_ref))
        # No retry after approval-frame loss: the broker offer might have been
        # reserved and challenge issued already. Wait only until expiry.
        remaining = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            raise DeviceSessionRefused("pc_offer_expired")
        result = _frame(
            await asyncio.wait_for(
                socket.receive_text(),
                timeout=min(remaining, OFFER_OWNER_APPROVAL_TIMEOUT_SECONDS),
            ),
            frozenset({
                "type", "device_id", "request_ref", "challenge_id", "pairing_code",
            }),
        )
        if (
            result["type"] != "pc_offer_approved"
            or result["device_id"] != device_id
            or result["request_ref"] != receipt.request_ref
            or type(result["challenge_id"]) is not str
            or _DEVICE.fullmatch(result["challenge_id"]) is None
            or type(result["pairing_code"]) is not str
            or _CODE.fullmatch(result["pairing_code"]) is None
        ):
            raise DeviceSessionRefused("pc_offer_approval_invalid")
        return receipt, result["challenge_id"], result["pairing_code"]
    except DeviceSessionRefused:
        raise
    except Exception as exc:
        raise DeviceSessionRefused("pc_offer_security_hold") from exc


async def run_pending_pc_offer_and_enroll(
    *, socket: Any, trusted_tls: Any, enrollment: Any, receiver: Any,
    owner_approval_open: Callable[[str], Any],
    binding_factory: Callable[..., Any] | None = None,
) -> Any:
    """One socket, from pending offer through *existing* Windows DPAPI ACK."""
    from .device_wss_enrollment import (
        canonical_kagent_binding_factory, run_and_stage_review_only_device_enrollment,
    )
    if not callable(getattr(enrollment, "record", None)):
        raise DeviceSessionRefused("pc_offer_enrollment_unavailable")
    try:
        record = enrollment.record()
        receipt, challenge, code = await run_pending_pc_offer(
            socket=socket, trusted_tls=trusted_tls,
            device_id=record.device_id, owner_approval_open=owner_approval_open,
        )
        del receipt  # Not proof of enrollment.
        return await run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=socket, trusted_tls=trusted_tls,
            receiver=receiver, challenge_id=challenge, pairing_code=code,
            binding_factory=binding_factory or canonical_kagent_binding_factory,
        )
    finally:
        # The canonical enrollment itself closes the socket on success/failure.
        # If the approval offer failed BEFORE enrollment, it still must close.
        try:
            await asyncio.wait_for(socket.close(), timeout=2.0)
        except Exception:
            pass
