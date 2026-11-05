"""HTTPS stand-in for the Engine's CONTROL_PLANE_ENGINE_ADMISSION binding.

On Cloudflare the Engine reaches the admission authority through a same-account
Service Binding (``apps/padiem-ai-engine/wrangler.toml``
``CONTROL_PLANE_ENGINE_ADMISSION`` → ``padiem-control-plane-engine-admission``).
A CPython host has no binding, so this module is the one place where that
authority becomes HTTPS. It is imported only by ``app.local_runtime``.

The wire contract is the existing private RPC ingress (#5573 A2, #6417), not a
new one::

    POST <origin>/internal/rpc/<method>
    x-padiem-service-at:    <unix seconds>
    x-padiem-service-id:    <fresh random id, one per attempt>
    x-padiem-service-proof: v2=hex(hmac_sha256(secret,
        b"v2\n" + METHOD + b"\n" + path + b"\n" + at + b"\n" + service_id + b"\n" + body))

``proof_for_v2`` reproduces ``packages/padiem-control-plane/internal_rpc_ingress.py``
exactly (same headers, same canonical string), so the target verifies a host
call with the code it already runs. The payload is the same object the binding
call would have carried, and the reply is the same the binding would return.

The id is what the ingress consumes to refuse a replay, so it is signed: a
captured request cannot be re-signed under another id. Every attempt picks a
new one, including the retry after a 409 ``rpc_replay_detected``, which the
ingress answers before dispatching the handler. That retry is capped — a target
that keeps refusing is a failure, never a loop.

Shape matters: this object is *binding shaped* — ``fetch_entitlement_snapshot``,
``reserve_usage``, ``record_usage`` — and is put on the host env under the
binding's own name. ``worker_identity._admission_adapter_for_env`` then composes
the reviewed adapter unchanged, so no admission logic is re-implemented here and
the Engine's own fail-closed gate stays the only decision point.

Idle connections cost the host real time: measured on COM2 on 2026-11-05, one
snapshot RPC over a fresh connection took 2672 ms while the two that followed
over the same keep-alive connection took 635 ms and 653 ms. Turns spaced further
apart than the pool's keep-alive expiry therefore paid that ~2 s handshake and
cold-isolate cost on the first of the two calls every time. So the host keeps the
connection it already owns: a longer keep-alive expiry plus one background warm
cycle per binding every ``PADIEM_ENGINE_ADMISSION_KEEPWARM_SECONDS`` (default
45, 0 turns the cycle off). Its status is discarded and its failures are
swallowed: warming is not an authority answer and can never change an admission
decision.

The first warm cycle shipped as a side-effect-free ``OPTIONS /`` and did not
stop the cold turns (#6956). Measured against the production authority on
2026-11-05 the 404 it got back carried exactly the gateway Worker's own
fallback fingerprint (``text/plain`` 9-byte "Not Found" +
``cache-control: no-store``, i.e. the request did reach the Worker), but
``handle_internal_rpc`` only ever dispatches ``/internal/rpc/<method>`` — so
the OPTIONS warmed the gateway isolate and the keep-alive connection while the
Durable Object that owns the entitlement state, and the identity worker behind
it, stayed cold. A warm ping therefore has to be a real signed RPC: one
``fetch_entitlement_snapshot`` per cycle carrying a synthetic canonical user
subject. The authority answers that with a 200 ``ok:false``
``engine_entitlement_identity_unavailable`` — the reverse identity lookup
fails before any entitlement is produced or installed, so the call writes
nothing; the only durable touch is the bounded replay-guard row every signed
request already leaves, pruned inside its own window. ``reserve_usage`` is
never used for warming: that path records a reservation.

Absent configuration means no binding at all: every model route keeps answering
503 ``entitlement_unavailable``, exactly as it does today. A half-configured or
malformed pair is treated the same way — absent, never permissive.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import logging
import time
import uuid
from typing import Any, Mapping

import httpx

__all__ = [
    "ADMISSION_ORIGIN_ENV",
    "ADMISSION_SECRET_ENV",
    "DEFAULT_KEEPWARM_SECONDS",
    "KEEPALIVE_EXPIRY_SECONDS",
    "KEEPWARM_METHOD",
    "KEEPWARM_PRODUCT_ID",
    "KEEPWARM_SECONDS_ENV",
    "KEEPWARM_SYNTHETIC_SUBJECT",
    "AdmissionBindingConfigError",
    "HttpsAdmissionBinding",
    "admission_binding_for",
    "arm_live_binders",
    "new_service_id",
    "proof_for",
    "proof_for_v2",
]

ADMISSION_ORIGIN_ENV = "PADIEM_ENGINE_LOCAL_ADMISSION_ORIGIN"
ADMISSION_SECRET_ENV = "PADIEM_ENGINE_LOCAL_ADMISSION_SECRET"
KEEPWARM_SECONDS_ENV = "PADIEM_ENGINE_ADMISSION_KEEPWARM_SECONDS"
RPC_PATH_PREFIX = "/internal/rpc/"
AT_HEADER = "x-padiem-service-at"
PROOF_HEADER = "x-padiem-service-proof"
SERVICE_ID_HEADER = "x-padiem-service-id"
PROOF_VERSION = b"v1"
PROOF_VERSION_V2 = b"v2"
RPC_REPLAY_STATUS = 409
RPC_MAX_ATTEMPTS = 3
MIN_SECRET_CHARS = 32
DEFAULT_TIMEOUT_SECONDS = 15.0
# Longer than the 60 s this file shipped with: COM2 PC turns are routinely more
# than a minute apart, and an expired keep-alive makes the next authority call
# pay the handshake and cold-isolate cost again.
KEEPALIVE_EXPIRY_SECONDS = 300.0
DEFAULT_KEEPWARM_SECONDS = 45.0
# The warm ping must leave the gateway Worker: only ``/internal/rpc/<method>``
# dispatches, so the ping is a real signed snapshot RPC for a synthetic
# canonical user. The reverse identity lookup for it fails before anything is
# produced or installed — the authority answers 200 ``ok:false``
# ``engine_entitlement_identity_unavailable`` and writes nothing.
KEEPWARM_METHOD = "fetch_entitlement_snapshot"
KEEPWARM_PRODUCT_ID = "b62"
KEEPWARM_SYNTHETIC_SUBJECT = {
    "subject_type": "user",
    "subject_id": "padiem-engine-keepwarm-synthetic",
}
# One journal line per warm cycle, riding the stderr channel
# ``app.engine_timing.ensure_host_visible`` already binds for the stage line.
# The line carries the status code and the elapsed milliseconds and nothing
# else: no subject, no origin, no payload, no secret.
_KEEPWARM_LOG = logging.getLogger("padiem_ai_engine.engine_timing")


class AdmissionBindingConfigError(ValueError):
    """The configured origin/secret pair cannot form a usable binding."""


def new_service_id() -> str:
    """One fresh request identity, never reused across attempts."""

    return str(uuid.uuid4())


def proof_for(secret: str, *, method: str, path: str, at: int, body: bytes) -> str:
    """The v1 proof; retained for the legacy policy the ingress still accepts."""

    signed = b"\n".join(
        (PROOF_VERSION, method.encode("ascii"), path.encode("utf-8"),
         str(at).encode("ascii"), body)
    )
    return "v1=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def proof_for_v2(
    secret: str, *, method: str, path: str, at: int, service_id: str, body: bytes
) -> str:
    """The id-bound proof the Control Plane ingress verifies (shared contract)."""

    signed = b"\n".join(
        (
            PROOF_VERSION_V2,
            method.encode("ascii"),
            path.encode("utf-8"),
            str(at).encode("ascii"),
            service_id.encode("utf-8"),
            body,
        )
    )
    return "v2=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _require_https_origin(value: str | None) -> str:
    raw = "" if value is None else str(value).strip()
    parsed = httpx.URL(raw) if raw else None
    if not raw or parsed is None or parsed.scheme != "https" or not parsed.host:
        raise AdmissionBindingConfigError("admission origin must be an https origin")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.userinfo:
        raise AdmissionBindingConfigError("admission origin must be a bare https origin")
    return raw.rstrip("/")


def _require_secret(value: str | None) -> str:
    raw = "" if value is None else str(value).strip()
    if len(raw) < MIN_SECRET_CHARS:
        raise AdmissionBindingConfigError(
            f"admission service secret must be at least {MIN_SECRET_CHARS} characters"
        )
    return raw


_POOLED_CLIENTS: dict[int, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}
# Bindings that own the host's pooled client, so shutdown can stop their warm
# cycle before the client it uses goes away. A binding handed a caller's client
# is that caller's business and is never registered here.
_LIVE_BINDINGS: list["HttpsAdmissionBinding"] = []
_HTTP2_AVAILABLE: bool | None = None


def arm_live_binders() -> None:
    """Arm the warm cycle of every live binding, from inside a running loop.

    The host composes its bindings while importing the ASGI app, before any
    event loop exists, so composition alone cannot schedule the first cycle.
    The host's lifespan startup calls this on the running loop; each binding's
    own guard keeps exactly one timer outstanding, and the first-call arming
    path is unchanged.
    """

    for binding in list(_LIVE_BINDINGS):
        binding.arm_warmer()


def _http2_available() -> bool:
    """HTTP/2 is offered only when this deployment can actually load ``h2``.

    A host without the extra keeps HTTP/1.1 rather than failing at the first
    authority call, so the optional dependency never becomes a boot dependency.
    """

    global _HTTP2_AVAILABLE
    if _HTTP2_AVAILABLE is None:
        _HTTP2_AVAILABLE = importlib.util.find_spec("h2") is not None
    return _HTTP2_AVAILABLE


def _pooled_client() -> httpx.AsyncClient:
    """One keep-alive client per running loop for every host authority call.

    A fresh ``AsyncClient`` per RPC pays a new TCP+TLS handshake and can land
    on another, cold Worker isolate; the admission path makes several calls per
    turn. The client carries no authority of its own: every call still builds a
    fresh signed proof with a new service id.
    """

    loop = asyncio.get_running_loop()
    loop_key = id(loop)
    for key in [k for k, (owner, _) in _POOLED_CLIENTS.items() if owner.is_closed()]:
        del _POOLED_CLIENTS[key]
    entry = _POOLED_CLIENTS.get(loop_key)
    if entry is not None and entry[0] is loop:
        return entry[1]
    client = httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT_SECONDS,
        follow_redirects=False,
        limits=httpx.Limits(
            max_connections=8,
            max_keepalive_connections=8,
            keepalive_expiry=KEEPALIVE_EXPIRY_SECONDS,
        ),
        **{"http2": True} if _http2_available() else {},
    )
    _POOLED_CLIENTS[loop_key] = (loop, client)
    return client


async def close_pooled_clients() -> None:
    """Close the host's shared authority clients (lifespan shutdown only)."""

    global _POOLED_CLIENTS
    for binding in list(_LIVE_BINDINGS):
        await binding.aclose()
    clients, _POOLED_CLIENTS = _POOLED_CLIENTS, {}
    for _owner, client in clients.values():
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 - shutdown never masks the exit
            pass


class HttpsAdmissionBinding:
    """``CONTROL_PLANE_ENGINE_ADMISSION`` over HTTPS with the service proof.

    Every error is a plain exception with a generic message: the caller
    (``CloudflareControlPlaneTrustClient``) maps any failure to
    ``entitlement_unavailable``, and no payload, secret or upstream text is
    carried upward.
    """

    def __init__(
        self,
        origin: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        keepwarm_seconds: float | None = None,
    ) -> None:
        self._origin = _require_https_origin(origin)
        self._secret = _require_secret(secret)
        self._client = client
        self._timeout = timeout_seconds
        # A caller-supplied client is the caller's transport; scheduling traffic
        # through it behind the caller's back is not this module's decision.
        self._keepwarm = (
            0.0 if client is not None else (
                DEFAULT_KEEPWARM_SECONDS if keepwarm_seconds is None
                else float(keepwarm_seconds)
            )
        )
        self._warm_timer: asyncio.TimerHandle | None = None
        self._warm_task: asyncio.Task[Any] | None = None
        self._warm_stopped = False
        if self._keepwarm > 0:
            _LIVE_BINDINGS.append(self)
        self._arm_warmer()

    async def _post_signed(self, path: str, body: bytes) -> httpx.Response:
        """One signed POST attempt; every attempt gets its own fresh id.

        The id is what the ingress consumes to refuse a replay, so it is signed:
        a captured request cannot be re-signed under another id. Shared by the
        replay-retry loop in :meth:`_call` and by the single-shot warm ping.
        """

        at = int(time.time())
        service_id = new_service_id()
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            AT_HEADER: str(at),
            SERVICE_ID_HEADER: service_id,
            PROOF_HEADER: proof_for_v2(
                self._secret, method="POST", path=path, at=at,
                service_id=service_id, body=body,
            ),
        }
        try:
            if self._client is None:
                return await _pooled_client().post(
                    self._origin + path,
                    content=body,
                    headers=headers,
                    timeout=self._timeout,
                )
            return await self._client.post(
                self._origin + path, content=body, headers=headers
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("admission authority is unreachable") from exc

    def _arm_warmer(self) -> None:
        """Schedule the next warm cycle on the loop that is already running.

        The host builds this binding while importing its ASGI app, before any
        event loop exists, so the first authority call arms it instead. One timer
        is outstanding at a time, which is why this is a re-armed ``call_later``
        and not a task parked on a 45-second sleep: a task left pending when the
        loop closes would outlive the shutdown it was supposed to honour.
        """

        if self._keepwarm <= 0 or self._warm_stopped or self._warm_timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._warm_timer = loop.call_later(self._keepwarm, self._warm_now)

    def arm_warmer(self) -> None:
        """Public arm point for the host; one timer outstanding at a time.

        The binding is composed before the host loop exists, so the host calls
        this once that loop is running (ASGI lifespan startup). Calling it from
        inside a running loop at composition time arms the cycle immediately.
        """

        self._arm_warmer()

    def _warm_now(self) -> None:
        self._warm_timer = None
        if self._warm_stopped:
            return
        self._warm_task = asyncio.ensure_future(self._warm_once())

    async def _warm_once(self) -> None:
        """One real signed RPC on the pooled client; the body is discarded.

        The ping must dispatch through the gateway to the Durable Object and
        the identity worker behind it — a request that never leaves the gateway
        (the first keepwarm cycle's ``OPTIONS /``) leaves exactly the part cold
        that the next turn pays for. The synthetic-subject snapshot is the one
        dispatchable call that writes nothing. One journal line names the
        outcome (status and milliseconds only); no failure escapes and the
        cycle keeps going after any exception, because a warm attempt says
        nothing about the authority — the next real call carries its own proof
        and its own verdict.
        """

        started = time.perf_counter()
        status = 0
        try:
            body = json.dumps(
                {"product_id": KEEPWARM_PRODUCT_ID, "subject": dict(KEEPWARM_SYNTHETIC_SUBJECT)},
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
            response = await self._post_signed(RPC_PATH_PREFIX + KEEPWARM_METHOD, body)
            status = response.status_code
        except asyncio.CancelledError:
            self._warm_task = None
            raise
        except Exception:  # noqa: BLE001 - warming never becomes an admission answer
            status = 0
        _KEEPWARM_LOG.info(
            "keepwarm status=%d ms=%.1f",
            status,
            (time.perf_counter() - started) * 1000.0,
        )
        self._warm_task = None
        self._arm_warmer()

    async def aclose(self) -> None:
        """Stop this binding's warm cycle; the pooled client itself is shared."""

        self._warm_stopped = True
        if self._warm_timer is not None:
            self._warm_timer.cancel()
            self._warm_timer = None
        task = self._warm_task
        self._warm_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self in _LIVE_BINDINGS:
            _LIVE_BINDINGS.remove(self)

    async def _call(self, method: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        # Composed before the server loop exists, so the warm cycle starts here.
        self._arm_warmer()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        path = RPC_PATH_PREFIX + method
        response = None
        for _ in range(RPC_MAX_ATTEMPTS):
            response = await self._post_signed(path, body)
            if response.status_code != RPC_REPLAY_STATUS:
                break
        if response.status_code != 200:
            raise RuntimeError("admission authority answered a non-success status")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("admission authority answered a non-JSON envelope") from exc
        if not isinstance(data, dict):
            raise RuntimeError("admission authority answered a non-object envelope")
        return data

    async def fetch_entitlement_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("fetch_entitlement_snapshot", payload)

    async def reserve_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("reserve_usage", payload)

    async def record_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("record_usage", payload)


def _keepwarm_setting(values: Mapping[str, Any]) -> float:
    """The configured warm period; 0 switches the cycle off, a bad value keeps 45.

    A typo in an operational number must not silently drop the host back to a
    cold handshake on every turn, and it must not become an authority failure:
    the cycle only ever touches the connection.
    """

    raw = str(values.get(KEEPWARM_SECONDS_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_KEEPWARM_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        return DEFAULT_KEEPWARM_SECONDS
    return parsed if parsed >= 0 else DEFAULT_KEEPWARM_SECONDS


def admission_binding_for(values: Mapping[str, Any]) -> dict[str, Any]:
    """The host env entry for the admission binding, or an empty dict.

    Returns nothing when neither name is set (today's fail-closed behaviour).
    A half-configured pair is also treated as absent instead of raising: a boot
    that silently allowed admission would be far worse than a 503, and the
    healthy path is the only one that needs the binding at all.
    """

    origin = str(values.get(ADMISSION_ORIGIN_ENV, "") or "").strip()
    secret = str(values.get(ADMISSION_SECRET_ENV, "") or "").strip()
    if not origin and not secret:
        return {}
    try:
        binding = HttpsAdmissionBinding(origin, secret, keepwarm_seconds=_keepwarm_setting(values))
    except AdmissionBindingConfigError:
        return {}
    return {"CONTROL_PLANE_ENGINE_ADMISSION": binding}
