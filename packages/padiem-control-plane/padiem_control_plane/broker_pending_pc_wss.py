"""Source-only Cloudflare Python Durable Object PC-offer WebSocket ingress.

The existing canonical Broker DO, not a new Worker or DB, owns BOTH the
native server WebSocket and its one-use SQLite offer. The official Cloudflare
Python DO API is ctx.acceptWebSocket(server), WebSocketPair.new().object_values(),
webSocketMessage/webSocketClose, Response(status=101, web_socket=client).

This is an operator-acceptance ingress seam, NOT a deployed customer endpoint.
No product Worker fetch path is activated. A DO restart/hibernation loses
session-local ephemeral key proof, intentionally closing surviving sockets
and disallowing re-use rather than accepting unverified restored state.

After one approved-code send the socket is NOT enrolled: full canonical WSS
redeem + Windows DPAPI acknowledgement remain separately required.
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
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlsplit

from .pending_pc_link import DurablePendingPcLink, VerifiedPendingPc
from .broker_pending_pc_private_rpc import BrokerPendingPcPrivateRefused, _enabled

WSS_REVIEW_PATH = "/internal/connector/pc-offer-4139"
WSS_PRODUCTION_ENABLED = False
WSS_PUBLIC_FETCH_MOUNTED = False
WSS_HIBERNATED_SESSION_RESTORE_ENABLED = False
WSS_OWNER_APPROVAL_AUTO_ENABLED = False
MAX_WSS_FRAME = 4096
MAX_PENDING_PC_WSS_PER_DO = 32
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_KEY = re.compile(r"^[A-Za-z0-9+/]{43}=$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9+/]{86}==$")
_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")


class PendingPcWssRefused(RuntimeError):
    pass


def _frame(raw: Any, keys: set[str]) -> dict[str, Any]:
    if type(raw) is not str or not 0 < len(raw) <= MAX_WSS_FRAME:
        raise PendingPcWssRefused("pending_pc_frame_invalid")
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PendingPcWssRefused("pending_pc_frame_invalid")
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError):
        raise PendingPcWssRefused("pending_pc_frame_invalid") from None
    if type(data) is not dict or set(data) != keys:
        raise PendingPcWssRefused("pending_pc_frame_invalid")
    return data


def _b64(value: Any, shape: re.Pattern[str], count: int) -> bytes:
    if type(value) is not str or shape.fullmatch(value) is None:
        raise PendingPcWssRefused("pending_pc_crypto_invalid")
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != count or base64.b64encode(raw).decode("ascii") != value:
            raise ValueError("noncanonical")
        return raw
    except (ValueError, binascii.Error):
        raise PendingPcWssRefused("pending_pc_crypto_invalid") from None


def _native_pair():
    # Lazy Worker-only import; this package must be buildable on ordinary
    # CPython and in Cloudflare's Python/Pyodide packaging.
    from js import WebSocketPair  # type: ignore[import-not-found]
    from workers import Response
    return WebSocketPair.new().object_values(), Response


async def native_ed25519_verify(*, public_key: bytes, signature: bytes,
                                transcript: bytes) -> bool:
    """Real Cloudflare WebCrypto; no native/cffi wheel in Pyodide."""
    if len(public_key) != 32 or len(signature) != 64 or not transcript:
        return False
    try:
        from js import crypto, Uint8Array  # type: ignore[import-not-found]
        from pyodide.ffi import to_js  # type: ignore[import-not-found]
        def typed(value):
            result = Uint8Array.new(len(value))
            for i, byte in enumerate(value):
                result[i] = byte
            return result
        key = await crypto.subtle.importKey(
            "raw", typed(public_key), "Ed25519", False, to_js(["verify"]),
        )
        valid = await crypto.subtle.verify(
            "Ed25519", key, typed(signature), typed(transcript),
        )
        return valid is True
    except Exception:
        return False


class NativePcWss:
    def __init__(self, ws: Any) -> None:
        self.raw = ws
        self._closed = False
    @property
    def closed(self) -> bool:
        return self._closed or getattr(self.raw, "readyState", None) != 1
    async def send_text(self, value: str) -> None:
        if self.closed:
            raise PendingPcWssRefused("pending_pc_socket_closed")
        self.raw.send(value)
    async def close(self, *, code: int = 1008) -> None:
        self._closed = True
        try:
            self.raw.close(code, "")
        except Exception:
            pass


class LivePcWssOffer:
    """Verified ephemeral possession and same-socket single-use DO CAS."""

    def __init__(self, *, storage: Any, socket: NativePcWss,
                 verifier: Callable[..., Any],
                 nonce_factory: Callable[[], str] | None = None,
                 ref_factory: Callable[[], str] | None = None) -> None:
        self._socket = socket
        self._gateway = SimpleNamespace(_socket=socket)
        self._stage = "begin"
        self._ready = False
        self._disconnected = False
        self._request_ref: str | None = None
        self._expiry: datetime | None = None
        self._device: str | None = None
        self._public: bytes | None = None
        self._fingerprint: str | None = None
        self._nonce: str | None = None
        self._offering = False
        self._verifier = verifier
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(32))
        self._began_at: datetime | None = None
        self._broker = DurablePendingPcLink(
            storage=storage, canonical_broker_storage=storage,
            channel_verified=self._live, ref_factory=ref_factory,
        )
        self._lock = asyncio.Lock()

    def _live(self, request_ref: str, device_id: str, fingerprint: str) -> bool:
        return (
            not self._disconnected and not self._socket.closed
            and self._ready
            and self._device == device_id
            and self._fingerprint == fingerprint
            and ((self._offering and self._request_ref is None)
                 or (request_ref == self._request_ref and self._stage == "pending"))
        )

    def mark_disconnected(self) -> None:
        self._disconnected = True

    async def message(self, frame: Any, *, owner_do: Any) -> None:
        async with self._lock:
            if self._disconnected or self._socket.closed:
                raise PendingPcWssRefused("pending_pc_socket_closed")
            if self._stage == "begin":
                begin = _frame(frame, {"type", "device_id", "public_key_b64"})
                if (begin["type"] != "pc_offer_begin"
                    or type(begin["device_id"]) is not str
                    or _DEVICE.fullmatch(begin["device_id"]) is None):
                    raise PendingPcWssRefused("pending_pc_device_invalid")
                self._device = begin["device_id"]
                self._public = _b64(begin["public_key_b64"], _KEY, 32)
                self._nonce = self._nonce_factory()
                if type(self._nonce) is not str or _NONCE.fullmatch(self._nonce) is None:
                    raise PendingPcWssRefused("pending_pc_nonce_invalid")
                self._began_at = datetime.now(timezone.utc)
                self._stage = "prove"
                await self._socket.send_text(json.dumps({
                    "type": "pc_offer_challenge", "device_id": self._device,
                    "nonce_hex": self._nonce,
                }, separators=(",", ":"), sort_keys=True))
            elif self._stage == "prove":
                if (self._began_at is None
                    or (datetime.now(timezone.utc) - self._began_at).total_seconds() > 10):
                    raise PendingPcWssRefused("pending_pc_proof_expired")
                signed = _frame(frame, {"type", "signature_b64"})
                if signed["type"] != "pc_offer_prove":
                    raise PendingPcWssRefused("pending_pc_signature_invalid")
                signature = _b64(signed["signature_b64"], _SIGNATURE, 64)
                assert self._public is not None and self._nonce is not None
                transcript = (
                    b"padiem.connector-pending-pc.v1\n"
                    + self._device.encode("ascii") + b"\n"
                    + bytes.fromhex(self._nonce) + b"\n" + self._public
                )
                self._stage = "verifying"
                try:
                    ok = await asyncio.wait_for(
                        self._verifier(public_key=self._public,
                                       signature=signature, transcript=transcript),
                        timeout=5.0,
                    )
                except Exception:
                    ok = False
                if ok is not True:
                    raise PendingPcWssRefused("pending_pc_signature_invalid")
                self._fingerprint = hashlib.sha256(self._public).hexdigest()
                self._ready = True
                self._offering = True
                try:
                    receipt = self._broker.offer(
                        attested=VerifiedPendingPc(
                            device_id=self._device,
                            possession_key_sha256=self._fingerprint,
                        ), now=datetime.now(timezone.utc),
                    )
                finally:
                    self._offering = False
                self._request_ref = receipt["request_ref"]
                self._expiry = datetime.fromisoformat(
                    receipt["expires_at"].replace("Z", "+00:00")
                )
                self._stage = "pending"
                owner_do._bind_verified_pc_wss(
                    request_ref=self._request_ref, actor=self,
                )
                await self._socket.send_text(json.dumps({
                    "type": "pc_offer_ready", "device_id": self._device,
                    "request_ref": self._request_ref,
                    "expires_at": receipt["expires_at"],
                }, separators=(",", ":"), sort_keys=True))
            else:
                # MUST NOT silently treat canonical enrollment frames as a
                # completion ACK. The canonical post-approval handler is NOT
                # installed in this Worker. Fail closed until implemented.
                raise PendingPcWssRefused("pending_pc_canonical_wss_unavailable")

    async def reserve_once(self, *, request_ref: str) -> dict[str, Any]:
        async with self._lock:
            if (self._stage != "pending" or self._socket.closed
                or self._disconnected or request_ref != self._request_ref):
                raise PendingPcWssRefused("pending_pc_reserve_denied")
            return self._broker.reserve_once(
                request_ref=request_ref, now=datetime.now(timezone.utc),
            )

    async def deliver_once(self, *, request_ref: str, device_id: str,
                           challenge_id: str, pairing_code: str) -> None:
        async with self._lock:
            if (self._stage != "pending" or self._socket.closed
                or self._disconnected or request_ref != self._request_ref
                or device_id != self._device
                or type(challenge_id) is not str
                or _DEVICE.fullmatch(challenge_id) is None
                or type(pairing_code) is not str
                or _CODE.fullmatch(pairing_code) is None):
                raise PendingPcWssRefused("pending_pc_delivery_denied")
            # Atomic durable claim first. Never retry on uncertain send.
            self._broker.claim_delivery_once(
                request_ref=request_ref, device_id=device_id,
                now=datetime.now(timezone.utc),
            )
            self._stage = "delivered"
            try:
                await self._socket.send_text(json.dumps({
                    "type": "pc_offer_approved", "request_ref": request_ref,
                    "device_id": device_id, "challenge_id": challenge_id,
                    "pairing_code": pairing_code,
                }, separators=(",", ":"), sort_keys=True))
            except Exception:
                self.mark_disconnected()
                await self._socket.close()
                raise PendingPcWssRefused("pending_pc_delivery_uncertain") from None


def _wss_admitted(request: Any, env: Any) -> bool:
    if not _enabled(env) or getattr(env, "LOCAL_AGENT_BROKER_PENDING_PC_WSS_ENABLED", None) != "enabled":
        return False
    try:
        url = urlsplit(request.url)
        headers = request.headers
        return (
            request.method == "GET" and url.scheme == "https"
            and not url.username and not url.password
            and url.path == WSS_REVIEW_PATH and not url.query and not url.fragment
            and headers.get("upgrade") == "websocket"
            and headers.get("origin") is None and headers.get("cookie") is None
            and headers.get("sec-websocket-protocol") is None
        )
    except (AttributeError, TypeError, ValueError):
        return False


async def fetch_broker_pending_pc_wss(
    owner_do: Any, request: Any, *,
    pair_factory: Callable[..., Any] = _native_pair,
    verifier: Callable[..., Any] = native_ed25519_verify,
    nonce_factory: Callable[[], str] | None = None,
    ref_factory: Callable[[], str] | None = None,
):
    """DO-local native WSS fetch; NOT reachable via existing Default.fetch."""
    from workers import Response
    if not _wss_admitted(request, owner_do.env):
        return Response("Not Found", status=404,
                        headers={"cache-control": "no-store"})
    # One canonical DO and its canonical SQLite; no schema installation.
    owner_do._pending_pc_live()
    if len(getattr(owner_do, "_pending_pc_wss_by_id", {})) >= MAX_PENDING_PC_WSS_PER_DO:
        return Response("Not Found", status=404,
                        headers={"cache-control": "no-store"})
    try:
        (client, server), response_factory = pair_factory()
        ctx = owner_do._pending_pc_ctx
        ctx.acceptWebSocket(server)
        session = secrets.token_hex(16)
        server.serializeAttachment("pc-offer-4139." + session)
        wrapper = NativePcWss(server)
        actor = LivePcWssOffer(
            storage=owner_do._storage, socket=wrapper, verifier=verifier,
            nonce_factory=nonce_factory, ref_factory=ref_factory,
        )
        # In-memory state ONLY. DO hibernation/restart clears it and forbids
        # restoring a verified key from client-controlled attachment alone.
        if not hasattr(owner_do, "_pending_pc_wss_by_id"):
            owner_do._pending_pc_wss_by_id = {}
        owner_do._pending_pc_wss_by_id[session] = actor
        return response_factory(None, status=101, web_socket=client)
    except Exception:
        try:
            server.close(1008, "")
        except Exception:
            pass
        return Response("Not Found", status=404,
                        headers={"cache-control": "no-store"})


def _resolve_native_actor(owner_do: Any, ws: Any):
    try:
        tag = ws.deserializeAttachment()
        if type(tag) is not str or not tag.startswith("pc-offer-4139."):
            return None
        session = tag[len("pc-offer-4139."):]
        if len(session) != 32 or re.fullmatch(r"[0-9a-f]{32}", session) is None:
            return None
        actor = getattr(owner_do, "_pending_pc_wss_by_id", {}).get(session)
        if actor is None or actor._socket.raw is not ws:
            return None
        return session, actor
    except Exception:
        return None


async def broker_pending_pc_wss_message(owner_do: Any, ws: Any, message: Any) -> None:
    matched = _resolve_native_actor(owner_do, ws)
    if matched is None:
        # A hibernated session has LOST its server-side ephemeral key proof;
        # do not restore authorization from an unsigned serialized tag.
        ws.close(1008, "")
        return
    session, actor = matched
    try:
        await actor.message(message, owner_do=owner_do)
    except Exception:
        await broker_pending_pc_wss_close(owner_do, ws)


async def broker_pending_pc_wss_close(owner_do: Any, ws: Any) -> None:
    matched = _resolve_native_actor(owner_do, ws)
    if matched is not None:
        session, actor = matched
        actor.mark_disconnected()
        owner_do._pending_pc_wss_by_id.pop(session, None)
        if actor._request_ref is not None:
            owner_do._pending_pc_live_by_ref.pop(actor._request_ref, None)
    try:
        ws.close(1008, "")
    except Exception:
        pass


async def route_private_pc_wss_upgrade(worker: Any, request: Any, normal_http_handler):
    """Exact server-side upgrade gate in existing private Broker Worker.

    The Worker Entrypoint routes by its existing authority_ref DO stub, NEVER
    by a URL/user-controlled DO name. If not armed, preserve preexisting
    private HTTP semantics without mutating or opening any WebSocket.
    """
    if not _wss_admitted(request, worker.env):
        return await normal_http_handler(request, worker._stub)
    # Defense-in-depth: DO's fetch repeats the same strict review gate.
    return await worker._stub().fetch(request)
