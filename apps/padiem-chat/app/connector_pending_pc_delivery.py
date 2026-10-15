"""Source-only one-use delivery between owner approval and trusted outbound PC.

This is NOT mounted in Cloudflare. Its Broker port MUST point to the existing
canonical DO durable pending-link ledger, and the channel port MUST be bound
to the same socket that the Broker checked. Neither a browser URL, cookie,
unverified client payload nor an in-memory mock is sufficient live authority.
"""
from __future__ import annotations

import re
from typing import Any, Protocol

_PC_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_CHALLENGE = _DEVICE
_CODE = re.compile(r"^[0-9a-f]{32}$")

PENDING_PC_DELIVERY_PRODUCTION_ENABLED = False
PENDING_PC_DELIVERY_HTTP_MOUNTED = False


class PcDeliveryRefused(RuntimeError):
    """Bounded, credential-free denial for the owner approval composition."""


class CanonicalPendingPcBrokerPort(Protocol):
    async def reserve_once(self, *, request_ref: str) -> dict[str, Any]: ...
    async def claim_delivery_once(
        self, *, request_ref: str, device_id: str,
    ) -> None: ...


class SameVerifiedOutboundSocket(Protocol):
    async def send_once(
        self, *, request_ref: str, device_id: str,
        challenge_id: str, pairing_code: str,
    ) -> None: ...


class CanonicalPendingPcDelivery:
    """Broker CAS before exactly one secret send, with no retry or escrow.

    The source-only port is deliberately separate from the browser's owner
    session and from S1 challenge redemption. A complete Windows install ACK
    still requires the existing authenticated WSS + canonical DPAPI contract.
    """

    def __init__(
        self, *, broker: CanonicalPendingPcBrokerPort,
        socket: SameVerifiedOutboundSocket,
    ) -> None:
        for target, method in (
            (broker, "reserve_once"), (broker, "claim_delivery_once"),
            (socket, "send_once"),
        ):
            if not callable(getattr(target, method, None)):
                raise ValueError("trusted canonical Broker/same-socket delivery required")
        self._broker = broker
        self._socket = socket

    async def reserve_once(self, *, request_ref: str) -> dict[str, Any]:
        if type(request_ref) is not str or _PC_REF.fullmatch(request_ref) is None:
            raise PcDeliveryRefused("pending_pc_request_invalid")
        try:
            receipt = await self._broker.reserve_once(request_ref=request_ref)
        except Exception:
            raise PcDeliveryRefused("pending_pc_reservation_unavailable") from None
        # The owner composer validates the exact pending offer shape and live
        # possession flags again. Never add "connected"/"enrolled" here.
        if type(receipt) is not dict:
            raise PcDeliveryRefused("pending_pc_reservation_invalid")
        return receipt

    async def deliver_once(
        self, *, request_ref: str, device_id: str,
        challenge_id: str, pairing_code: str,
    ) -> None:
        if (
            type(request_ref) is not str or _PC_REF.fullmatch(request_ref) is None
            or type(device_id) is not str or _DEVICE.fullmatch(device_id) is None
            or type(challenge_id) is not str or _CHALLENGE.fullmatch(challenge_id) is None
            or type(pairing_code) is not str or _CODE.fullmatch(pairing_code) is None
        ):
            raise PcDeliveryRefused("pending_pc_delivery_invalid")
        try:
            # This must atomically consume the reserved slot, and recheck the
            # SAME verified live outbound PC channel before forwarding a code.
            await self._broker.claim_delivery_once(
                request_ref=request_ref, device_id=device_id,
            )
        except Exception:
            raise PcDeliveryRefused("pending_pc_delivery_not_authorized") from None
        try:
            await self._socket.send_once(
                request_ref=request_ref, device_id=device_id,
                challenge_id=challenge_id, pairing_code=pairing_code,
            )
        except Exception:
            # Broker slot is already consumed; DO NOT auto-replay or mint a new
            # challenge. Caller must wait for explicit reconciliation evidence.
            raise PcDeliveryRefused("pending_pc_delivery_unconfirmed") from None
