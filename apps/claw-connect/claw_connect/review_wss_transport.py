"""Source-only, real WSS transport for PADIEM Connector (#4139).

No production CLI, tray, installer or autostart invokes this code. The reviewed
socket uses OS trust roots + strict hostname verification before sending any
pairing proof. No cookie, Origin, proxy, redirect, automatic retry, device
identity, second Broker or per-frame diagnostic logging is permitted.

This authenticates a TLS peer, NOT the Cloudflare Worker ingress Service
Binding and NOT a physical Windows device. Those remain release blockers.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import ssl
from typing import Any, AsyncIterator

from .device_wss_enrollment import (
    DeviceSessionRefused, MAX_FRAME_CHARS,
    run_and_stage_review_only_device_enrollment,
)
from .wss_target import (
    REVIEW_WSS_HOST, REVIEW_WSS_URL, ACCEPTANCE_WSS_HOST, ACCEPTANCE_WSS_URL,
    WSS_PRODUCTION_DIALER_ENABLED,
    review_only_pinned_wss_target,
)

OPEN_TIMEOUT_SECONDS = 8
CLOSE_TIMEOUT_SECONDS = 2
MAX_QUEUE_FRAMES = 2
REVIEW_WSS_CLIENT_VERSION = "websockets==17.2"

# Even DEBUG cannot log part of a pairing code / raw credential / ACK frame.
_FRAME_LOG = logging.getLogger("padiem.connector.private_wss_frames")
_FRAME_LOG.disabled = True
_FRAME_LOG.propagate = False
_FRAME_LOG.addHandler(logging.NullHandler())


def strict_server_tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def _secure_peer(connection: Any, expected_context: ssl.SSLContext,
                 expected_host: str = REVIEW_WSS_HOST) -> bool:
    """Check established SSLObject; handshake enforced real CA/hostname trust."""
    try:
        tls = connection.transport.get_extra_info("ssl_object")
        return (
            isinstance(tls, ssl.SSLObject)
            and tls.context is expected_context
            and tls.server_hostname == expected_host
            and tls.context.verify_mode == ssl.CERT_REQUIRED
            and tls.context.check_hostname is True
            and tls.version() in ("TLSv1.2", "TLSv1.3")
            and bool(tls.getpeercert())
        )
    except (AttributeError, OSError, ValueError, ssl.SSLError):
        return False


class VerifiedReviewSocket:
    """Existing PC DeviceTextSocket interface backed by verified WebSocket."""

    def __init__(self, connection: Any, tls_context: ssl.SSLContext,
                 expected_host: str = REVIEW_WSS_HOST):
        self._connection = connection
        self._expected_host = expected_host
        self._context = tls_context
        self._closed = False

    def tls_verified(self) -> bool:
        return not self._closed and _secure_peer(self._connection, self._context, self._expected_host)

    async def send_text(self, message: str) -> None:
        if (not self.tls_verified() or type(message) is not str
            or not 0 < len(message) <= MAX_FRAME_CHARS):
            raise DeviceSessionRefused("device_wss_send_denied")
        await self._connection.send(message)

    async def receive_text(self) -> str:
        if not self.tls_verified():
            raise DeviceSessionRefused("device_wss_receive_denied")
        received = await self._connection.recv()
        if type(received) is not str or not 0 < len(received) <= MAX_FRAME_CHARS:
            raise DeviceSessionRefused("device_wss_inbound_shape_denied")
        return received

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._connection.close(code=1000)


class VerifiedReviewTls:
    """The trusted peer verifier for source-review real WebSocket sessions."""

    async def verify(self, socket: VerifiedReviewSocket) -> bool:
        return type(socket) is VerifiedReviewSocket and socket.tls_verified()


@asynccontextmanager
async def open_review_only_wss_socket(
    *, source_test_authorized: bool = False, acceptance: bool = False,
) -> AsyncIterator[VerifiedReviewSocket]:
    """Open genuine outbound TLS WebSocket; never automatically called by UI.

    The caller cannot override URI, SSL context, hostname, headers, proxy,
    or allow a different peer. All redirects are refused, including same-host.
    """
    if source_test_authorized is not True:
        raise DeviceSessionRefused("review_wss_transport_not_authorized")
    target_url = ACCEPTANCE_WSS_URL if acceptance is True else REVIEW_WSS_URL
    target_host = ACCEPTANCE_WSS_HOST if acceptance is True else REVIEW_WSS_HOST
    review_only_pinned_wss_target(target_url, acceptance=acceptance)
    context = strict_server_tls_context()
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise DeviceSessionRefused("review_wss_dependency_missing") from exc

    class NoRedirectConnect(connect):
        def process_redirect(self, exc: Exception) -> Exception:
            # Upstream follows HTTP 30x by default: never send proof to a
            # redirected path or host.
            return exc

    try:
        async with NoRedirectConnect(
            target_url,
            ssl=context,
            server_hostname=target_host,
            proxy=None,
            origin=None,
            compression=None,
            additional_headers=None,
            subprotocols=None,
            open_timeout=OPEN_TIMEOUT_SECONDS,
            close_timeout=CLOSE_TIMEOUT_SECONDS,
            ping_interval=None,
            max_size=MAX_FRAME_CHARS,
            max_queue=MAX_QUEUE_FRAMES,
            logger=_FRAME_LOG,
        ) as connection:
            socket = VerifiedReviewSocket(connection, context, expected_host=target_host)
            if not socket.tls_verified():
                await socket.close()
                raise DeviceSessionRefused("review_wss_peer_not_verified")
            try:
                yield socket
            finally:
                await socket.close()
    except DeviceSessionRefused:
        raise
    except Exception as exc:
        # No unsafe network/credential/error details escape to a user UI.
        raise DeviceSessionRefused("review_wss_connection_refused") from exc


async def run_review_only_wss_pairing(
    *, enrollment: Any, receiver: Any, challenge_id: str,
    pairing_code: str, source_test_authorized: bool = False,
    acceptance: bool = False,
) -> Any:
    """Drive the existing canonical pairing only in operator review harness."""
    if source_test_authorized is not True:
        raise DeviceSessionRefused("review_wss_transport_not_authorized")
    if WSS_PRODUCTION_DIALER_ENABLED is not False:
        raise DeviceSessionRefused("review_wss_production_gate_changed")
    async with open_review_only_wss_socket(source_test_authorized=True, acceptance=acceptance) as socket:
        return await run_and_stage_review_only_device_enrollment(
            enrollment=enrollment, socket=socket, trusted_tls=VerifiedReviewTls(),
            receiver=receiver, challenge_id=challenge_id, pairing_code=pairing_code,
        )


async def run_review_only_one_click_pc_link(
    *, enrollment: Any, receiver: Any, owner_approval_open: Any,
    source_test_authorized: bool = False, acceptance: bool = False,
) -> Any:
    """Reuse the ONE reviewed outbound WSS dialer for the no-code owner offer.

    This does not register the tray/autostart/CLI or mount a public server
    route. The pre-enrollment key proves possession of a fresh socket-local
    key only; authenticated B54 owner consent, canonical Broker challenge,
    and the SAME WSS/DPAPI ACK remain mandatory.
    """
    if source_test_authorized is not True:
        raise DeviceSessionRefused("review_wss_transport_not_authorized")
    if WSS_PRODUCTION_DIALER_ENABLED is not False:
        raise DeviceSessionRefused("review_wss_production_gate_changed")
    from .pending_pc_offer import run_pending_pc_offer_and_enroll
    async with open_review_only_wss_socket(
        source_test_authorized=True, acceptance=acceptance,
    ) as socket:
        return await run_pending_pc_offer_and_enroll(
            socket=socket, trusted_tls=VerifiedReviewTls(),
            enrollment=enrollment, receiver=receiver,
            owner_approval_open=owner_approval_open,
            acceptance=acceptance,
        )
