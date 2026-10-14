"""Source-only WSS pre-enrollment PC offer verifier on a live outbound socket.

The same trusted socket must remain reachable until owner approval and carry
the approved code and canonical credential/DPAPI ACK frames. This module does
NOT create a public route, Worker socket registry, Identity entitlement,
pairing code, or second Broker. Crypto verifies one ephemeral PC key only:
not hardware identity, account ownership, or permission to act.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Callable

from canonical_broker_pending_pc_link import VerifiedPendingPc

PENDING_PC_OFFER_SERVER_PRODUCTION_ENABLED = False
PENDING_PC_OFFER_WEBSOCKET_ROUTE_MOUNTED = False
OFFER_TIMEOUT_SECONDS = 10.0
SEND_TIMEOUT_SECONDS = 8.0
MAX_FRAME_CHARS = 8192
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_KEY = re.compile(r"^[a-zA-Z0-9+/]{43}=$")
_SIGNATURE = re.compile(r"^[a-zA-Z0-9+/]{86}==$")
_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")


class PendingOfferDenied(RuntimeError):
    """No secret, forged proof or connection details in outward error text."""


def _decode(raw: Any, names: frozenset[str]) -> dict[str, Any]:
    if type(raw) is not str or not 0 < len(raw) <= MAX_FRAME_CHARS:
        raise PendingOfferDenied("pending_offer_frame_denied")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PendingOfferDenied("pending_offer_duplicate_key")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise PendingOfferDenied("pending_offer_frame_denied") from exc
    if type(value) is not dict or set(value) != names:
        raise PendingOfferDenied("pending_offer_frame_denied")
    return value


def ownership_transcript(*, device_id: str, nonce_hex: str, public_key: bytes) -> bytes:
    """Exact, domain-separated wire parity with the Windows client."""
    if (
        type(device_id) is not str or _DEVICE.fullmatch(device_id) is None
        or type(nonce_hex) is not str
        or re.fullmatch(r"[0-9a-f]{64}", nonce_hex) is None
        or type(public_key) is not bytes or len(public_key) != 32
    ):
        raise PendingOfferDenied("pending_offer_transcript_invalid")
    return (
        b"padiem.connector-pending-pc.v1\n" + device_id.encode("ascii")
        + b"\n" + bytes.fromhex(nonce_hex) + b"\n" + public_key
    )


def _canonical(encoded: Any, regex: re.Pattern[str], expected: int) -> bytes:
    if type(encoded) is not str or regex.fullmatch(encoded) is None:
        raise PendingOfferDenied("pending_offer_crypto_invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != expected or base64.b64encode(raw).decode("ascii") != encoded:
            raise ValueError("noncanonical")
        return raw
    except (binascii.Error, ValueError) as exc:
        raise PendingOfferDenied("pending_offer_crypto_invalid") from exc


class VerifiedPcOfferGateway:
    """Per-socket ephemeral proof verifier, not an account/device registry.

    The caller must bind the Broker ledger's channel_verified callback to
    the SAME exact object identity and active connection/TLS truth. This
    object cannot be serialized into a Worker isolate-global socket map.
    """

    def __init__(self, *, socket: Any, trusted_ingress: Any, pending_ledger: Any,
                 nonce_factory: Callable[[], str] | None = None) -> None:
        if any(not callable(getattr(p, op, None)) for p, op in (
            (socket, "send_text"), (socket, "receive_text"),
            (trusted_ingress, "verify"), (pending_ledger, "offer"),
        )):
            raise ValueError("live verified socket and canonical Broker ledger required")
        self._socket = socket
        self._tls = trusted_ingress
        self._ledger = pending_ledger
        self._nonce = nonce_factory or (lambda: secrets.token_hex(32))
        self._offered_ref: str | None = None
        self._device: str | None = None
        self._sent = False
        self._verified = False
        self._offering = False

    def owns_live_channel(self, request_ref: str, device_id: str, fingerprint: str) -> bool:
        """An identity/mTLS gate is still needed to trust this as a physical PC."""
        return (
            self._verified
            and type(request_ref) is str and _REF.fullmatch(request_ref) is not None
            and ((self._offering and self._offered_ref is None)
                 or self._offered_ref == request_ref)
            and self._device == device_id
            and self._fingerprint == fingerprint
            and getattr(self._socket, "closed", False) is False
        )

    async def _close_refused(self) -> None:
        try:
            await asyncio.wait_for(self._socket.close(code=1008), timeout=2.0)
        except Exception:
            pass

    async def accept_offer(self) -> dict[str, str]:
        """Perform real Ed25519 PoP on same TLS WebSocket, then persist offer."""
        if self._verified or self._sent:
            raise PendingOfferDenied("pending_offer_already_used")
        try:
            if (
                getattr(self._socket.url, "scheme", None) != "wss"
                or self._socket.headers.get("origin") is not None
                or self._socket.headers.get("cookie") is not None
                or await asyncio.wait_for(
                    self._tls.verify(self._socket), timeout=5.0,
                ) is not True
            ):
                raise PendingOfferDenied("pending_offer_ingress_denied")
            begin = _decode(
                await asyncio.wait_for(
                    self._socket.receive_text(), timeout=OFFER_TIMEOUT_SECONDS,
                ),
                frozenset({"type", "device_id", "public_key_b64"}),
            )
            if (
                begin["type"] != "pc_offer_begin"
                or type(begin["device_id"]) is not str
                or _DEVICE.fullmatch(begin["device_id"]) is None
            ):
                raise PendingOfferDenied("pending_offer_device_invalid")
            public = _canonical(begin["public_key_b64"], _KEY, 32)
            nonce = self._nonce()
            if (
                type(nonce) is not str or re.fullmatch(r"[0-9a-f]{64}", nonce) is None
            ):
                raise PendingOfferDenied("pending_offer_nonce_invalid")
            await asyncio.wait_for(
                self._socket.send_text(json.dumps({
                    "type": "pc_offer_challenge",
                    "device_id": begin["device_id"], "nonce_hex": nonce,
                }, separators=(",", ":"), sort_keys=True)),
                timeout=SEND_TIMEOUT_SECONDS,
            )
            signed = _decode(
                await asyncio.wait_for(
                    self._socket.receive_text(), timeout=OFFER_TIMEOUT_SECONDS,
                ),
                frozenset({"type", "signature_b64"}),
            )
            if signed["type"] != "pc_offer_prove":
                raise PendingOfferDenied("pending_offer_signature_invalid")
            signature = _canonical(signed["signature_b64"], _SIGNATURE, 64)
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            try:
                Ed25519PublicKey.from_public_bytes(public).verify(
                    signature, ownership_transcript(
                        device_id=begin["device_id"],
                        nonce_hex=nonce, public_key=public,
                    ),
                )
            except Exception as exc:
                # Includes cryptography.exceptions.InvalidSignature.
                raise PendingOfferDenied("pending_offer_signature_invalid") from exc
            self._device = begin["device_id"]
            self._fingerprint = hashlib.sha256(public).hexdigest()
            # Mark this in-process socket proof, but DO requires independently
            # attached live-channel validation at every durable mutation.
            self._verified = True
            self._offered_ref = None
            now = datetime.now(timezone.utc)
            # The ledger's trusted channel verifier must authorize the
            # server-generated offer ref BEFORE it enters canonical SQLite.
            self._offering = True
            try:
                result = self._ledger.offer(
                    attested=VerifiedPendingPc(
                        device_id=self._device,
                        possession_key_sha256=self._fingerprint,
                    ),
                    now=now,
                )
            finally:
                self._offering = False
            if (
                type(result) is not dict
                or set(result) != {"request_ref", "expires_at"}
                or type(result["request_ref"]) is not str
                or _REF.fullmatch(result["request_ref"]) is None
                or type(result["expires_at"]) is not str
            ):
                raise PendingOfferDenied("pending_offer_ledger_invalid")
            self._offered_ref = result["request_ref"]
            await asyncio.wait_for(
                self._socket.send_text(json.dumps({
                    "type": "pc_offer_ready",
                    "device_id": self._device,
                    "request_ref": self._offered_ref,
                    "expires_at": result["expires_at"],
                }, separators=(",", ":"), sort_keys=True)),
                timeout=SEND_TIMEOUT_SECONDS,
            )
            return result
        except PendingOfferDenied:
            await self._close_refused()
            raise
        except Exception as exc:
            await self._close_refused()
            raise PendingOfferDenied("pending_offer_unavailable") from exc

    async def send_once(
        self, *, request_ref: str, device_id: str,
        challenge_id: str, pairing_code: str,
    ) -> None:
        """Called only AFTER the same Broker DO claims its one-use delivery."""
        if (
            self._sent or not self._verified
            or request_ref != self._offered_ref or device_id != self._device
            or type(challenge_id) is not str or _DEVICE.fullmatch(challenge_id) is None
            or type(pairing_code) is not str or _CODE.fullmatch(pairing_code) is None
        ):
            raise PendingOfferDenied("pending_offer_delivery_denied")
        try:
            if await asyncio.wait_for(
                self._tls.verify(self._socket), timeout=5.0,
            ) is not True:
                raise PendingOfferDenied("pending_offer_channel_not_verified")
            self._sent = True
            await asyncio.wait_for(
                self._socket.send_text(json.dumps({
                    "type": "pc_offer_approved", "request_ref": request_ref,
                    "device_id": device_id, "challenge_id": challenge_id,
                    "pairing_code": pairing_code,
                }, separators=(",", ":"), sort_keys=True)),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except PendingOfferDenied:
            raise
        except Exception as exc:
            raise PendingOfferDenied("pending_offer_delivery_unconfirmed") from exc
