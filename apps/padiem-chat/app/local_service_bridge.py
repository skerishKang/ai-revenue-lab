"""CPython-mode HTTPS stand-ins for the Chat Worker's Service bindings (#5573 stage 2).

The Worker reaches its siblings through same-account Service bindings: either a
fetch-shaped HTTP contract over a binding, or a direct RPC method on the target
Worker entrypoint. A native CPython process has neither. This module is the one
place where those calls become HTTPS, and it is imported only by
`app.local_cpython` — the Cloudflare path keeps its bindings untouched.

Every call carries the same service-to-service proof the COM2 lanes already use
(a shared secret held on both hosts, HMAC over the exact request, never in a
log or an exception)::

    x-padiem-service-at:     <unix seconds>
    x-padiem-service-id:     <fresh random id, one per attempt>
    x-padiem-service-proof:  v2=<hex(hmac_sha256(secret,
        "v2\\n" + method + "\\n" + path + "\\n" + at + "\\n" + service_id + "\\n" + body))>

A target accepts the call only when the proof verifies, the timestamp is inside
its own window, and it has not already consumed that id (#6417) — which is why
the id is signed: an id outside the signature is a label, not an identity.

The B66 PDF renderer is not the RPC ingress and does not verify a v2 proof, so
its stand-in keeps signing v1.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from typing import Any, Callable

import httpx

from .b14_upstream_composition import compose_b14_transports
from .config import ConfigError
from .identity_cache_metrics import record_rpc
from .journal_host import ensure_journal_visible
from .orchestration_timing import LOG as _IDENTITY_KEEPWARM_LOG

__all__ = [
    "HttpRpcBinding",
    "LocalB66PdfRendererClient",
    "ServiceProofConfigError",
    "compose_local_b14_transports",
    "new_service_id",
    "service_proof_headers",
]

PROOF_HEADER = "x-padiem-service-proof"
PROOF_AT_HEADER = "x-padiem-service-at"
SERVICE_ID_HEADER = "x-padiem-service-id"
PROOF_VERSION = b"v1"
PROOF_VERSION_V2 = b"v2"
# The ingress answers 409 rpc_replay_detected before dispatching the handler, so
# a refusal is not a half-applied call: retrying it under a new id is safe.
RPC_REPLAY_STATUS = 409
RPC_MAX_ATTEMPTS = 3
PDF_RENDER_PATH = "/internal/v1/render"
PDF_RESPONSE_MAX_BYTES = 32 * 1024 * 1024
_RPC_PATH_PREFIX = "/internal/rpc/"
_METHOD_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
# One journal line per warm cycle (status and milliseconds only) — ops proves
# the ignition without a turn, the same way the Engine's keepwarm line does.
_SECRET_MIN_CHARS = 32
# The identity authority is woken with a real dispatchable RPC, not a bare
# request: only ``/internal/rpc/<method>`` leaves the gateway Worker, so a
# no-route ping would warm the edge while the Durable Object that owns the
# canonical identity rows — the part the next turn pays for — stayed cold.
# ``resolve_product_user_for_subject`` is strictly read-only (#3247): the DO
# reads the existing ``canonical_product_identity_link`` row for the exact
# ``(product_id, canonical_subject_id)`` pair and fails closed on a missing
# one, so this synthetic subject writes nothing and its answer is discarded.
IDENTITY_KEEPWARM_METHOD = "resolve_product_user_for_subject"
IDENTITY_KEEPWARM_PAYLOAD: dict[str, Any] = {
    "product_id": "b62",
    "canonical_subject_id": "padiem-chat-identity-keepwarm-synthetic",
}


class ServiceProofConfigError(ConfigError):
    """A local-mode service origin/secret is missing or malformed."""


class ServiceRpcHttpError(RuntimeError):
    """Closed diagnostic code; no URL, proof, request or response body."""

    def __init__(self, status: int):
        self.code = {
            401: 'service_rpc_unauthorized', 403: 'service_rpc_forbidden',
            404: 'service_rpc_not_found', 409: 'service_rpc_replay_rejected',
            429: 'service_rpc_rate_limited',
        }.get(status, 'service_rpc_http_failed')
        super().__init__(self.code)


def _require_https_origin(value: str | None, *, name: str) -> str:
    raw = "" if value is None else str(value).strip()
    parsed = httpx.URL(raw) if raw else None
    if not raw or parsed is None or parsed.scheme != "https" or not parsed.host:
        raise ServiceProofConfigError(f"{name} must be an https origin")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.userinfo:
        raise ServiceProofConfigError(f"{name} must be a bare https origin")
    return raw.rstrip("/")


def _require_secret(value: str | None, *, name: str) -> str:
    raw = "" if value is None else str(value).strip()
    if len(raw) < _SECRET_MIN_CHARS:
        raise ServiceProofConfigError(f"{name} must be at least {_SECRET_MIN_CHARS} characters")
    return raw


def new_service_id() -> str:
    """One fresh request identity, never reused across attempts.

    The ingress keeps every id for the life of its clock window, so a repeated
    id is a replay it refuses however carefully this side signed it.
    """

    return str(uuid.uuid4())


def service_proof_headers(
    secret: str,
    *,
    method: str,
    path: str,
    body: bytes,
    at: int | None = None,
    service_id: str | None = None,
) -> dict[str, str]:
    """The exact proof a target verifies.

    With a ``service_id`` the proof is v2 and binds that id, which is what makes
    a captured request impossible to replay. Without one it stays the v1 proof
    that only the B66 PDF renderer verifies.
    """

    timestamp = str(int(time.time()) if at is None else int(at)).encode("ascii")
    if service_id is None:
        signed = b"\n".join(
            (PROOF_VERSION, method.upper().encode("ascii"), path.encode("utf-8"),
             timestamp, bytes(body))
        )
        proof = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        return {PROOF_AT_HEADER: timestamp.decode("ascii"), PROOF_HEADER: "v1=" + proof}
    signed = b"\n".join(
        (
            PROOF_VERSION_V2,
            method.upper().encode("ascii"),
            path.encode("utf-8"),
            timestamp,
            service_id.encode("utf-8"),
            bytes(body),
        )
    )
    proof = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return {
        PROOF_AT_HEADER: timestamp.decode("ascii"),
        SERVICE_ID_HEADER: service_id,
        PROOF_HEADER: "v2=" + proof,
    }


_IDENTITY_RPC_LOG = logging.getLogger("padiem_chat.identity_rpc_client")


def _colo_of(response: Any) -> str:
    """The Cloudflare edge location from ``cf-ray`` (``<hex>-<COLO>``).

    Only the three-letter location code is kept: it names the POP that answered,
    never a request id, a token or a client address.
    """
    try:
        ray = response.headers.get("cf-ray", "")
    except Exception:
        return "none"
    if not isinstance(ray, str) or "-" not in ray:
        return "none"
    colo = ray.rsplit("-", 1)[-1].strip()
    return colo if re.fullmatch(r"[A-Za-z]{3}\Z", colo) else "none"


def _connection_reused(response: Any, previous: int | None) -> tuple[str, int | None]:
    """Whether this response reused a pooled TLS connection, and its marker.

    httpcore exposes the underlying stream; a reused connection hands back the
    same ``SSLObject``. When the runtime does not expose it (Cloudflare's Python
    runtime, an injected transport), the answer is ``unknown`` rather than a
    guess — the metric must never invent a fact.
    """
    try:
        stream = (response.extensions or {}).get("network_stream")
        ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
    except Exception:
        return "unknown", previous
    if ssl_object is None:
        return "unknown", previous
    marker = id(ssl_object)
    if previous is None:
        return "first", marker
    return ("true" if marker == previous else "false"), marker


class HttpRpcBinding:
    """A Binding-shaped RPC surface over HTTPS.

    `CloudflareControlPlaneIdentityAuthority`-style adapters call
    ``binding.<method>(payload)``; this object answers the same way by POSTing
    the payload to ``<origin>/internal/rpc/<method>`` and returning the parsed
    JSON object. The response envelope is the target's responsibility; the
    adapter above still validates it exactly as it does over a real binding.
    """

    # Class-level warm state keeps subclasses that bypass this __init__ (the
    # loopback COM2 port binding composes its own fields) safe: for them the
    # warm cycle simply stays off, and every real RPC still reaches the wire
    # exactly as it did before.
    _keepwarm = 0.0
    _warm_timer: asyncio.TimerHandle | None = None
    _warm_task: asyncio.Task[Any] | None = None
    _warm_stopped = False
    # Class-level default: subclasses that bypass __init__ (the loopback COM2
    # port binding) must not trip the attribute guard in ``__getattr__``.
    _ssl_marker: int | None = None

    def __init__(
        self,
        origin: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        sign_request_id: bool = True,
        keepwarm_seconds: float = 0.0,
    ):
        self._origin = _require_https_origin(origin, name="RPC origin")
        self._secret = _require_secret(secret, name="RPC service secret")
        self._client = client
        # An injected client belongs to the caller; one built here is closed by
        # :meth:`aclose` at host shutdown (#6613).
        self._owns_client = client is None
        self._timeout = timeout_seconds
        # A target without a replay memory refuses every v2 request, so a
        # caller bound to one keeps the v1 proof until that target has a guard.
        self._sign_request_id = bool(sign_request_id)
        # Opt-in warm cycle: the host composition passes the configured period
        # (PADIEM_CHAT_IDENTITY_KEEPWARM_SECONDS, default 45, 0 off), so a
        # default-constructed binding behaves exactly as before. The cycle arms
        # here when a loop is already running (tests, in-loop composition) and
        # at the host's ASGI startup otherwise; :meth:`aclose` stops it.
        self._keepwarm = max(0.0, float(keepwarm_seconds))
        self._warm_timer: asyncio.TimerHandle | None = None
        self._warm_task: asyncio.Task[Any] | None = None
        self._warm_stopped = False
        self._ssl_marker: int | None = None
        self._arm_warmer()

    def arm_warmer(self) -> None:
        """Public arm point for the host; one timer outstanding at a time."""

        self._arm_warmer()

    def _arm_warmer(self) -> None:
        """Schedule the next warm cycle on the loop that is already running.

        One timer outstanding at a time: this is a re-armed ``call_later``, not
        a task parked on a sleep, so nothing is left pending when the loop the
        binding served goes away.
        """

        if self._keepwarm <= 0 or self._warm_stopped or self._warm_timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._warm_timer = loop.call_later(self._keepwarm, self._warm_now)

    def _warm_now(self) -> None:
        self._warm_timer = None
        if self._warm_stopped:
            return
        self._warm_task = asyncio.ensure_future(self._warm_once())

    async def _warm_once(self) -> None:
        """One read-only identity RPC; the answer and any failure are dropped.

        The ping goes through the same signed POST as a real call but never
        through the arming closure: the next cycle is scheduled here, after the
        request has finished, so one warm request stays outstanding at a time.
        Warming says nothing about the authority — the next real call carries
        its own proof and its own verdict — and the cycle keeps going after any
        exception; a cancellation (host shutdown) leaves nothing behind. One
        journal line names the outcome (status and milliseconds only) so the
        operator can prove the cycle is firing without a turn.
        """

        started = time.perf_counter()
        status = 0
        try:
            body = json.dumps(
                IDENTITY_KEEPWARM_PAYLOAD, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            response = await self._post_rpc(IDENTITY_KEEPWARM_METHOD, body)
            status = response.status_code
        except asyncio.CancelledError:
            self._warm_task = None
            raise
        except Exception:  # noqa: BLE001 - warming never becomes an authority answer
            status = 0
        # #7542: the ping is counted apart from product calls in the per-minute
        # line, so it can be told from a real reverse lookup of the same name.
        record_rpc(
            "keepwarm", IDENTITY_KEEPWARM_METHOD,
            "answered" if status == 200 else "bad_status" if status else "unavailable",
        )
        _IDENTITY_KEEPWARM_LOG.info(
            "identity_keepwarm status=%d ms=%.1f",
            status,
            (time.perf_counter() - started) * 1000.0,
        )
        self._warm_task = None
        self._arm_warmer()

    def _stop_warmer(self) -> None:
        self._warm_stopped = True
        if self._warm_timer is not None:
            self._warm_timer.cancel()
            self._warm_timer = None

    def _shared_client(self) -> httpx.AsyncClient:
        """The one client this binding keeps (#6613).

        Every RPC used to build its own ``httpx.AsyncClient``, so a password
        login paid six TCP+TLS handshakes to the identity origin on top of the
        six calls themselves (6,721 ms / 6 ≈ 1.1 s each in the 11-02 journal).
        The client is created on first use, inside the running loop, and then
        kept: same origin, same proof, same timeout, same retry rule — only the
        handshake is no longer repeated. httpx pools and reopens a dropped
        connection by itself.
        """
        client = self._client
        if client is None:
            # #6460 4-1: httpx drops an idle pooled connection after 5s by
            # default, so the first RPC after the 30s scope-cache window paid a
            # fresh TCP+TLS handshake (the measured ~2s call). 75s keeps the
            # connection across that reuse window with margin, stays bounded —
            # never unlimited — and must not exceed the identity service's own
            # keep-alive timeout (the identity unit templates carry the same 75).
            client = httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False,
                limits=httpx.Limits(keepalive_expiry=75.0),
            )
            self._client = client
        return client

    async def aclose(self) -> None:
        """Stop the warm cycle and close the pooled client this binding created (host shutdown)."""
        self._stop_warmer()
        task = self._warm_task
        self._warm_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            await client.aclose()

    async def _post_rpc(self, method: str, body: bytes) -> httpx.Response:
        """The signed POST loop shared by real RPCs and the warm ping.

        The replay retry keeps the same rule as before: every attempt signs a
        fresh id, and a target that keeps refusing the id means this side is
        sending the same request more than it is allowed to — the cap is what
        stops it. Arming the warm cycle stays the caller's decision so the warm
        ping itself never schedules another cycle while it is still in flight.
        """

        path = _RPC_PATH_PREFIX + method
        client = self._shared_client()
        response = None
        attempts = RPC_MAX_ATTEMPTS if self._sign_request_id else 1
        for _ in range(attempts):
            # The identity lookup after OAuth exchange crosses Cloudflare
            # too. Keep the same product agent as the token call (#6528),
            # rather than the library default rejected by integrity checks.
            headers = {"Content-Type": "application/json", "Accept": "application/json",
                       "User-Agent": "PADIEM-Chat/1.0 (+https://chat.padiem.net)"}
            headers.update(service_proof_headers(
                self._secret, method="POST", path=path, body=body,
                service_id=new_service_id() if self._sign_request_id else None,
            ))
            started = time.perf_counter()
            response = await client.post(
                self._origin + path, content=body, headers=headers
            )
            # One line per identity RPC: the client-side time to first byte, the
            # edge location that answered, and whether a pooled TLS connection
            # was reused. No payload, token, session or address is recorded.
            reused, self._ssl_marker = _connection_reused(response, self._ssl_marker)
            ensure_journal_visible(_IDENTITY_RPC_LOG)
            _IDENTITY_RPC_LOG.info(
                "identity_rpc_client method=%s status=%s ttfb_ms=%d reused=%s colo=%s attempt=%d",
                method, response.status_code,
                int((time.perf_counter() - started) * 1000.0),
                reused, _colo_of(response),
                1 if attempts == 1 else attempts,
            )
            if response.status_code != RPC_REPLAY_STATUS:
                break
        return response

    def __getattr__(self, method: str):
        if method.startswith("_") or not _METHOD_RE.fullmatch(method):
            raise AttributeError(method)

        async def call(payload: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(payload, dict):
                raise TypeError("RPC payload must be an object")
            # The binding is composed before the host loop exists, so the warm
            # cycle starts here, on the loop the real traffic already runs on.
            self._arm_warmer()
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            response = await self._post_rpc(method, body)
            if response.status_code != 200:
                raise ServiceRpcHttpError(response.status_code)
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("service RPC answered a non-object envelope")
            return data

        return call


class LocalB66PdfRendererClient:
    """The exact `CloudflareB66PdfRendererClient` contract over HTTPS.

    Same path, JSON key set, response ceiling and return shape; only the
    transport changes. Error messages stay generic so provider or document
    material never travels upward.
    """

    def __init__(
        self,
        origin: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120.0,
    ):
        self._origin = _require_https_origin(origin, name="B66 PDF origin")
        self._secret = _require_secret(secret, name="B66 PDF service secret")
        self._client = client
        self._timeout = timeout_seconds

    async def render_pdf(
        self, *, saved_skill_id: str, skill_fingerprint: str,
        profile_fingerprint: str, render_model: dict[str, Any],
    ) -> tuple[int, bytes, str]:
        body = json.dumps({
            "saved_skill_id": saved_skill_id,
            "skill_fingerprint": skill_fingerprint,
            "profile_fingerprint": profile_fingerprint,
            "render_model": render_model,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(service_proof_headers(
            self._secret, method="POST", path=PDF_RENDER_PATH, body=body,
        ))
        try:
            client = self._client
            if client is None:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as fresh:
                    response = await fresh.post(self._origin + PDF_RENDER_PATH, content=body, headers=headers)
            else:
                response = await client.post(self._origin + PDF_RENDER_PATH, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError("B66 PDF renderer response could not be read") from exc
        content = response.content
        if len(content) > PDF_RESPONSE_MAX_BYTES:
            raise RuntimeError("B66 PDF renderer response could not be read")
        return response.status_code, content, response.headers.get("content-type", "")


def compose_local_b14_transports(
    settings: Any,
    proof_secret: str | None,
    *,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> tuple[Any, Any]:
    """B14 transports for the local run — HTTPS only, never a binding fallback.

    `binding` is passed as None on purpose: a native process has no service
    binding, so the default branch can only ever yield (None, None) and the
    dispatch client fails closed instead of pretending the model is reachable.
    """

    def _client() -> httpx.AsyncClient:
        if client_factory is not None:
            return client_factory()
        return httpx.AsyncClient(timeout=None, follow_redirects=False)

    return compose_b14_transports(
        upstream_mode=str(getattr(settings, "b14_upstream_mode", "") or ""),
        origin=getattr(settings, "b14_base_url", None),
        binding=None,
        proof_secret=proof_secret,
        service_binding_factory=lambda _binding, _proof: None,
        stream_binding_factory=lambda _binding, _proof: None,
        https_client_factory=_client,
    )
