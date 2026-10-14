"""Per-canonical-Broker-DO, one-live-PC-socket pending approval actor (#4139).

Source-only, no route, no Worker binding, no global or cross-isolate socket
registry. A single DO actor instance owns its OWN canonical SQLite storage
and actual outgoing PC WSS, and handles owner approval on THAT instance only.
Requests routed to another DO / evicted instance must fail closed.

Caller must invoke begin_and_wait() on the accepted WSS, and route a signed
B54 owner's approved action to reserve_once/deliver_once on this SAME actor.
On successful delivery, that WSS handler MUST continue with the existing
canonical Broker handshake and Windows DPAPI readback before returning an
enrollment result. This actor returns no device registration authority.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
import re

from padiem_control_plane.pending_pc_link import DurablePendingPcLink
from .connector_pending_pc_offer_gateway import VerifiedPcOfferGateway
from .connector_worker_webcrypto_verify import CloudflareWorkerEd25519Verifier

SOCKET_ACTOR_ENABLED_IN_WORKER = False
SOCKET_ACTOR_WSS_ROUTE_MOUNTED = False
SOCKET_ACTOR_OWNER_RPC_EXPORTED = False
_SOCKET_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")


class PendingSocketActorRefused(RuntimeError):
    """Bounded, credential-free rejection."""


class CanonicalBrokerPendingSocketActor:
    """One actor per accepted PC socket; never on a process-global singleton."""

    def __init__(
        self, *, canonical_broker_storage: Any,
        socket: Any, trusted_ingress: Any,
        key_verifier: CloudflareWorkerEd25519Verifier,
        ref_factory: Callable[[], str] | None = None,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        if type(key_verifier) is not CloudflareWorkerEd25519Verifier:
            raise ValueError("only Worker-native Ed25519 verifier is admissible")
        if (not callable(getattr(socket, "close", None))
                or not callable(getattr(socket, "accept", None))):
            raise ValueError("trusted live socket with accept/closure required")
        if getattr(socket, "closed", None) is not False:
            raise ValueError("socket must expose a trusted closed property")
        if not callable(getattr(trusted_ingress, "verify", None)):
            raise ValueError("trusted Cloudflare ingress required")
        self._socket = socket
        self._trusted_ingress = trusted_ingress
        self._disconnected = False
        self._approved = False
        self._delivered = asyncio.Event()
        self._request_ref: str | None = None
        self._expiry: datetime | None = None
        self._ready = False
        self._broker = DurablePendingPcLink(
            storage=canonical_broker_storage,
            canonical_broker_storage=canonical_broker_storage,
            channel_verified=self._live_channel,
            ref_factory=ref_factory,
        )
        self._gateway = VerifiedPcOfferGateway(
            socket=socket, trusted_ingress=trusted_ingress,
            pending_ledger=self._broker, key_verifier=key_verifier,
            nonce_factory=nonce_factory,
        )

    def _live_channel(self, request_ref: str, device_id: str, fingerprint: str) -> bool:
        return (
            not self._disconnected and not self._delivered.is_set()
            and getattr(self._socket, "closed", None) is False
            and self._gateway.owns_live_channel(request_ref, device_id, fingerprint)
        )

    def mark_disconnected(self) -> None:
        """Server-owned WSS close/error event; refuse all later mutations."""
        self._disconnected = True
        # Wake the WSS handler at once, without an expiry-length hang.
        self._delivered.set()

    async def _refuse_and_close(self) -> None:
        self.mark_disconnected()
        try:
            await asyncio.wait_for(self._socket.close(code=1008), timeout=2.0)
        except Exception:
            pass

    async def begin_and_wait(self) -> dict[str, Any]:
        """Wait for owner action on same actor without polling or code escrow.

        Returns only after one successful approved-code send; NOT an ACK.
        The upstream WSS handler must subsequently reuse this SAME socket
        to complete the existing canonical credential+DPAPI protocol.
        """
        if self._ready or self._disconnected:
            raise PendingSocketActorRefused("pending_socket_already_used")
        self._ready = True
        try:
            # Cloudflare/Starlette requires exactly ONE WSS accept. Reject
            # untrusted TLS metadata BEFORE returning HTTP 101.
            if await asyncio.wait_for(
                self._trusted_ingress.verify(self._socket), timeout=5.0,
            ) is not True:
                raise PendingSocketActorRefused("pending_socket_ingress_denied")
            await asyncio.wait_for(self._socket.accept(), timeout=5.0)
            issued = await self._gateway.accept_offer()
            self._request_ref = issued["request_ref"]
            if type(self._request_ref) is not str or _SOCKET_REF.fullmatch(self._request_ref) is None:
                raise PendingSocketActorRefused("pending_socket_invalid_offer")
            expiry = datetime.fromisoformat(issued["expires_at"].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if (
                expiry.tzinfo is None or expiry.utcoffset() is None
                or not now < expiry <= now + timedelta(seconds=90)
            ):
                raise PendingSocketActorRefused("pending_socket_invalid_expiry")
            self._expiry = expiry
            await asyncio.wait_for(
                self._delivered.wait(),
                timeout=(expiry - now).total_seconds(),
            )
            if self._disconnected or self._request_ref is None:
                raise PendingSocketActorRefused("pending_socket_disconnected")
            # Code is not returned, stored or escrowed by this actor.
            return {
                "state": "awaiting_canonical_dpapi_ack",
                "request_ref": self._request_ref,
                "registered": False, "connected": False,
            }
        except Exception:
            await self._refuse_and_close()
            raise PendingSocketActorRefused("pending_socket_unconfirmed") from None

    def _match_ref(self, request_ref: Any) -> bool:
        return (
            not self._disconnected
            and self._ready and self._request_ref is not None
            and type(request_ref) is str and request_ref == self._request_ref
            and getattr(self._socket, "closed", None) is False
            and self._expiry is not None and datetime.now(timezone.utc) < self._expiry
            and not self._delivered.is_set()
        )

    async def _recheck_live_ingress(self) -> None:
        """Revalidate real TLS provenance before any owner-triggered CAS.

        A socket may remain open after ingress trust expires; its prior
        Ed25519 proof and connected flag are not enough to mint a challenge.
        """
        if self._disconnected or getattr(self._socket, "closed", None) is not False:
            raise PendingSocketActorRefused("pending_socket_unavailable")
        try:
            if await asyncio.wait_for(
                self._trusted_ingress.verify(self._socket), timeout=5.0,
            ) is not True:
                raise PendingSocketActorRefused("pending_socket_ingress_denied")
        except PendingSocketActorRefused:
            raise
        except Exception:
            raise PendingSocketActorRefused("pending_socket_ingress_denied") from None
        if self._disconnected or getattr(self._socket, "closed", None) is not False:
            raise PendingSocketActorRefused("pending_socket_unavailable")

    async def reserve_once(self, *, request_ref: str) -> dict[str, Any]:
        """Private actor-only port, called after signed owner CSRF/consent."""
        if not self._match_ref(request_ref):
            raise PendingSocketActorRefused("pending_socket_unavailable")
        await self._recheck_live_ingress()
        try:
            return self._broker.reserve_once(
                request_ref=request_ref, now=datetime.now(timezone.utc),
            )
        except Exception:
            raise PendingSocketActorRefused("pending_socket_reservation_denied") from None

    async def deliver_once(
        self, *, request_ref: str, device_id: str,
        challenge_id: str, pairing_code: str,
    ) -> None:
        """CAS claim before secret send. No replay on any delivery uncertainty."""
        if (
            not self._match_ref(request_ref)
            or type(device_id) is not str or _DEVICE.fullmatch(device_id) is None
        ):
            raise PendingSocketActorRefused("pending_socket_delivery_denied")
        await self._recheck_live_ingress()
        try:
            self._broker.claim_delivery_once(
                request_ref=request_ref, device_id=device_id,
                now=datetime.now(timezone.utc),
            )
        except Exception:
            raise PendingSocketActorRefused("pending_socket_delivery_denied") from None
        try:
            await self._gateway.send_once(
                request_ref=request_ref, device_id=device_id,
                challenge_id=challenge_id, pairing_code=pairing_code,
            )
            self._approved = True
            self._delivered.set()
        except Exception:
            await self._refuse_and_close()
            raise PendingSocketActorRefused("pending_socket_delivery_uncertain") from None



class _PreacceptedCanonicalSocket:
    """One-use facade over the SAME underlying accepted WSS.

    The legacy canonical handler performs its own TLS and Broker checks and
    calls accept(). On a socket already accepted for the pending owner offer,
    only that repeated ASGI accept is suppressed; frames, TLS metadata and
    close operations always use the original socket.
    """

    def __init__(self, socket: Any) -> None:
        self._raw_socket = socket
        self._accepted_once = False

    def __getattr__(self, key: str) -> Any:
        return getattr(self._raw_socket, key)

    async def accept(self) -> None:
        if self._accepted_once or getattr(self._raw_socket, "closed", None) is not False:
            raise PendingSocketActorRefused("pending_socket_double_accept_denied")
        self._accepted_once = True

    async def send_text(self, value: str) -> None:
        await self._raw_socket.send_text(value)

    async def receive_text(self) -> str:
        return await self._raw_socket.receive_text()

    async def close(self, *, code: int = 1000) -> None:
        await self._raw_socket.close(code=code)


async def run_approved_pc_offer_then_canonical_session(
    *, actor: CanonicalBrokerPendingSocketActor, socket: Any,
    trusted_tls: Any, canonical_broker: Any, host_factory: Any,
) -> None:
    """One preaccepted WSS, existing canonical Broker + DPAPI ACK unchanged.

    No new entitlement is created; the canonical host independently checks
    challenge / Identity owner consent / signed counters / DPAPI readback.
    This source-only method is NOT mounted on the deployed Python Worker.
    """
    if (
        type(actor) is not CanonicalBrokerPendingSocketActor
        or actor._socket is not socket
        or not callable(getattr(trusted_tls, "verify", None))
        or not callable(getattr(canonical_broker, "gateway_bootstrap_rpc", None))
        or not callable(host_factory)
    ):
        raise PendingSocketActorRefused("pending_socket_canonical_boundary_denied")
    await actor.begin_and_wait()
    if (
        actor._approved is not True or actor._disconnected
        or getattr(socket, "closed", None) is not False
    ):
        raise PendingSocketActorRefused("pending_socket_canonical_boundary_denied")
    from .connector_gateway_websocket_session import run_device_initiated_enrollment
    try:
        await run_device_initiated_enrollment(
            _PreacceptedCanonicalSocket(socket),
            trusted_tls=trusted_tls,
            broker=canonical_broker,
            host_factory=host_factory,
        )
    finally:
        actor.mark_disconnected()
