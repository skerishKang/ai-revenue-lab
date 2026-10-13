"""Shared PADIEM voice/STT Cloudflare Worker.

This is the single server-side STT authority for PADIEM Chat, Claw and B66.
It is a **private** Worker (``workers_dev = false``): products reach it over a
Service Binding, never from the public internet, and it is never the browser's
direct target.

Routes
------
``POST /internal/v1/voice/transcribe``
    Server-side Groq Whisper transcription (the last fallback in the chain
    ``gemini_live -> browser_speech -> groq_whisper``). The provider key is read
    from the Cloudflare Secrets Store binding and never returned, logged or
    placed in the response.

``POST /internal/v1/voice/live-token``
    Mints a short-lived, model-locked Gemini Live ephemeral token so the browser
    can open a Live transcription session without ever holding the long-lived key.

``GET  /internal/v1/voice/capabilities``
    Browser-safe session parameters (model name, VAD window, rotation window)
    and the provider order. Contains no key, token or account identity.

Deployment gate
---------------
Every route is closed by default. ``Default.fetch`` resolves
``PADIEM_VOICE_STT_ENABLED`` **before** it reads a Secret, constructs an upstream
request, or performs any paid call. When the flag is not exactly ``"true"`` the
whole Worker answers ``voice_stt_disabled``. The committed ``wrangler.toml`` keeps
that flag OFF and ``workers_dev = false``, so this Worker cannot serve a browser
today.

A paid route additionally requires a real caller authority, implemented in
``voice_stt_caller_auth``. It reuses the canonical Control Plane private Service
Bindings the Engine already uses — ``CONTROL_PLANE_IDENTITY`` for the
authenticated session and tenant, ``CONTROL_PLANE_ENGINE_ADMISSION`` for the
entitlement grant and the per-request cost reservation — and it produces the one
value a paid route consumes, ``contract.CallerAuthorization``. The metering unit
count is computed here from the validated audio length, so a caller cannot
understate its own cost, and there is no client-supplied plan, cap or entitlement
field anywhere on the path.

Neither binding is attached to any deployed environment, and the Control Plane
does not yet issue a ``voice.stt.*`` entitlement grant, so every paid route still
fails closed in practice. What the authority contract removed is the *absence* of
an implemented gate, not the fail-closed posture: an absent binding still answers
``caller_guard_unavailable``, an unverifiable session still answers
``voice_stt_unauthenticated``, a session belonging to another product or tenant
still answers ``voice_stt_forbidden``, and a missing grant or refused reservation
still answers ``voice_stt_cost_denied``.

All validation, provider order, chunk/turn/dedup rules and payload construction
live in ``voice_stt_contract``; this module is the thin Workers adapter so the
contract stays unit-testable without the Workers runtime.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid

from workers import Response, WorkerEntrypoint, fetch

import voice_stt_caller_auth as caller_auth
import voice_stt_contract as contract

TRANSCRIBE_PATH = "/internal/v1/voice/transcribe"
LIVE_TOKEN_PATH = "/internal/v1/voice/live-token"
CAPABILITIES_PATH = "/internal/v1/voice/capabilities"

#: The live-token route takes only a session id, so it is far smaller than the
#: transcribe route's base64 audio envelope.
LIVE_TOKEN_MAX_BYTES = 8 * 1024

JSON_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def _json(status: int, body: dict) -> Response:
    return Response(json.dumps(body, separators=(",", ":")), status=status, headers=JSON_HEADERS)


def _ok(body: dict) -> Response:
    payload = {"ok": True}
    payload.update(body)
    return _json(200, payload)


def _error(code: str) -> Response:
    return _json(contract.status_for_code(code), {"ok": False, "error": {"code": code}})


# ---------------------------------------------------------------------------
# Bounded request reading
# ---------------------------------------------------------------------------


def _chunk_reader(request, chunk_size: int):
    """Read the body in fixed slices, one at a time, never more than requested.

    Uses ``request.body`` (a JS ReadableStream) when available. The caller only
    asks for ``max_bytes - total + 1`` bytes at a time, so an oversized body is
    rejected as soon as it is proven oversized instead of after being fully
    buffered. ``request.text()`` is deliberately *not* used: it materialises the
    whole body first, which is unbounded when Content-Length is absent.

    The reader is single-consumer: the JS reader is acquired once and advanced
    across calls. Requesting a fresh ``getReader()`` per call would replay the
    body from byte zero on some runtimes. A JS chunk that is already larger
    than the remaining budget is rejected here with ``request_too_large``
    *before* any slice or full copy, so no byte is silently dropped and a huge
    JS chunk is never materialised into an unbounded Python ``bytes`` object.
    """

    body = getattr(request, "body", None)
    if body is None:
        raise contract.VoiceSttError("request_too_large", 413)
    if not hasattr(body, "getReader"):
        raise contract.VoiceSttError("request_too_large", 413)
    reader = body.getReader()
    finished = False

    def _js_length(value: object) -> int | None:
        # Length without copying: a JS Uint8Array exposes ``length`` /
        # ``byteLength`` without materialising the bytes in Python.
        for attr in ("byteLength", "length"):
            try:
                raw = getattr(value, attr, None)
            except Exception:
                raw = None
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int) and raw >= 0:
                return raw
        return None

    async def read(limit: int) -> bytes | None:
        nonlocal finished
        if finished:
            return None
        if limit is None or not isinstance(limit, int) or isinstance(limit, bool):
            raise contract.VoiceSttError("request_too_large", 413)
        if limit < 0:
            raise contract.VoiceSttError("request_too_large", 413)
        oversize = False
        done = False
        value = None
        try:
            result = await reader.read()
            done = getattr(result, "done", False)
            value = getattr(result, "value", None)
            if done or value is None:
                finished = True
                return None
            if isinstance(value, str):
                try:
                    encoded = value.encode("utf-8")
                except Exception:
                    raise contract.VoiceSttError("invalid_json", 400)
                if len(encoded) > limit:
                    oversize = True
                    raise contract.VoiceSttError("request_too_large", 413)
                if len(encoded) == 0:
                    return None
                return encoded
            if isinstance(value, (bytes, bytearray, memoryview)):
                if len(value) > limit:
                    oversize = True
                    raise contract.VoiceSttError("request_too_large", 413)
                if len(value) == 0:
                    return None
                return bytes(value)
            # JS proxy (e.g. Uint8Array) or any other runtime chunk: check the
            # declared length first so a giant chunk fails before it is copied
            # into Python memory.
            declared_len = _js_length(value)
            if declared_len is not None:
                if declared_len > limit:
                    oversize = True
                    raise contract.VoiceSttError("request_too_large", 413)
                if declared_len == 0:
                    return None
            try:
                copied = bytes(value)
            except Exception:
                raise contract.VoiceSttError("invalid_json", 400)
            if not isinstance(copied, bytes):
                raise contract.VoiceSttError("invalid_json", 400)
            if len(copied) > limit:
                oversize = True
                raise contract.VoiceSttError("request_too_large", 413)
            if len(copied) == 0:
                return None
            return copied
        finally:
            # The reader stays acquired across calls; releasing per call would
            # let a later ``getReader()`` restart the stream. Release only when
            # the stream is exhausted or when we fail closed on an oversize.
            try:
                if oversize or done or value is None:
                    release = getattr(reader, "releaseLock", None)
                    if callable(release):
                        release()
            except Exception:
                pass

    return read


async def _read_json(request, max_bytes: int) -> object:
    """Read and parse a bounded JSON body."""
    declared = contract.parse_declared_content_length(
        request.headers.get("content-length") if request.headers is not None else None
    )
    if declared is not None and declared > max_bytes:
        raise contract.VoiceSttError("request_too_large", 413)
    raw = await contract.read_bounded_body(_chunk_reader(request, 8192), max_bytes)
    if not raw:
        raise contract.VoiceSttError("invalid_json", 400)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise contract.VoiceSttError("invalid_json", 400)
    return data


def _require_json_content_type(request) -> None:
    content_type = request.headers.get("content-type") if request.headers is not None else None
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise contract.VoiceSttError("unsupported_media_type", 415)


# ---------------------------------------------------------------------------
# Deployment gate — fail closed BEFORE any Secret read or provider call
# ---------------------------------------------------------------------------


def _require_caller_clues(request) -> caller_auth.CallerClues:
    """Read the caller's opaque identity clues before any body is buffered.

    Clues are not an authorization: they only say which Control Plane session to
    resolve. Running this first means a request that presents no identity never
    gets its payload read, while the full verification still happens after the
    payload is validated (the cost units depend on the validated audio length).
    """
    return caller_auth.parse_caller_clues(getattr(request, "headers", None))


async def _require_caller_authorization(
    env,
    *,
    route: str,
    clues: caller_auth.CallerClues,
    capability: str,
    estimated_units: int,
) -> contract.CallerAuthorization:
    """Gate every paid route against the canonical Control Plane authority.

    Fails closed when the two reviewed private Service Bindings are absent
    (``caller_guard_unavailable``), when the Control Plane cannot authenticate the
    session (``voice_stt_unauthenticated``), when the session belongs to another
    product or subject (``voice_stt_forbidden``), when the tenant fact is missing
    (``voice_stt_tenant_unavailable``), and when the voice entitlement grant or
    the cost reservation is absent or refused (``voice_stt_cost_denied``).

    Nothing here is decided from request content beyond those two opaque clues,
    and no verdict is trusted because none is invented here: the subject, tenant,
    entitlement and reservation all come from the Control Plane.
    """
    authority = caller_auth.caller_authority_for_env(env)
    return await authority.authorize(
        clues=clues,
        capability=capability,
        route=route,
        estimated_units=estimated_units,
    )


async def _require_enabled(env) -> None:
    """Gate every route. Order matters: no Secret read or provider call if OFF.

    This is the deployment flag only. Caller identity, tenant scope and cost
    approval are a separate gate (:func:`_require_caller_authorization`) applied
    per paid route, so the key-free capabilities route stays reachable without
    attaching any authority binding.
    """
    flag = getattr(env, contract.VOICE_STT_ENABLED_BINDING, None)
    # Wrangler deploy configuration is a literal string. Do not accept
    # whitespace, alternate casing or a Python boolean as an activation.
    # Any unexpected binding shape must leave this paid feature disabled.
    if flag != "true" or not isinstance(flag, str):
        raise contract.VoiceSttError("voice_stt_disabled", 503)


# ---------------------------------------------------------------------------
# Upstream transport
# ---------------------------------------------------------------------------


async def _resolve_secret(env, binding_name: str) -> str:
    """Resolve one Secrets Store binding without ever logging or returning it.

    Mirrors ``padiem_chat.app.worker_env``: a Secrets Store binding is a handle
    with an async ``get()``; a plain string is accepted only for isolated local
    tests. A missing or failing binding resolves to ``""`` and the caller fails
    closed.
    """
    value = getattr(env, binding_name, None)
    if value is None:
        return ""
    getter = getattr(value, "get", None)
    if callable(getter):
        try:
            resolved = await getter()
        except Exception:
            return ""
        return str(resolved) if resolved is not None else ""
    return value if isinstance(value, str) else ""


def _build_abort_signal(timeout_ms):
    """Build an abort signal for one upstream call, or ``None`` when unavailable.

    Kept as a module-level function (rather than an inline ``import js`` block)
    so the budget can be verified on a developer machine by substituting a
    recorder. A runtime without ``AbortSignal.timeout`` does NOT get an
    unbounded wait: :func:`_upstream_fetch` still wraps the call in
    :func:`asyncio.wait_for` with the same budget, so the 25s/8s ceilings hold
    on every runtime. The transport failure path still fails closed.
    """
    try:
        import js  # Pyodide / Workers only

        if hasattr(js, "AbortSignal") and hasattr(js.AbortSignal, "timeout"):
            return js.AbortSignal.timeout(timeout_ms)
    except Exception:
        pass
    return None


def _timeout_seconds(timeout_ms) -> float:
    """Convert a millisecond budget to seconds; never unbounded or negative."""
    try:
        seconds = float(timeout_ms) / 1000.0
    except Exception:
        seconds = 25.0
    if not (seconds == seconds) or seconds <= 0:
        return 25.0
    return seconds


async def _upstream_fetch(url, *, method, headers, body, timeout_ms):
    """Bounded upstream call with a sizeable, finite budget on every runtime."""
    kwargs: dict = {"method": method, "headers": headers, "body": body}
    signal = _build_abort_signal(timeout_ms)
    if signal is not None:
        kwargs["signal"] = signal
    try:
        # Fail-closed wall clock even when the runtime has no AbortSignal:
        # asyncio.wait_for cancels the hanging fetch at the same budget.
        return await asyncio.wait_for(fetch(url, **kwargs), timeout=_timeout_seconds(timeout_ms))
    except asyncio.TimeoutError as exc:
        raise contract.VoiceSttError("stt_unavailable", 503) from exc
    except contract.VoiceSttError:
        raise
    except Exception as exc:
        raise contract.VoiceSttError("stt_unavailable", 503) from exc


async def _read_upstream_json(response, timeout_seconds: float) -> object:
    """Read and parse the upstream body inside a strict wall-time budget.

    The request budget covers the response body too: a provider that answers
    with headers and then trickles (or never finishes) the body must not hold
    the Worker past its stated ceiling. The read is bounded by
    ``asyncio.wait_for`` on *every* runtime (with or without ``AbortSignal``)
    and by ``contract.MAX_UPSTREAM_RESPONSE_BYTES``.

    ``None`` is returned for a body that is not parseable JSON so the caller can
    apply its normal bounded status handling. A timeout, an oversized body or a
    transport read failure all fail closed with ``stt_unavailable``; provider
    text is never echoed to the caller or to a log.
    """
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
        raise contract.VoiceSttError("stt_unavailable", 503)
    # NaN reads as "no finite budget" and fails closed rather than waiting forever.
    if math.isnan(timeout_seconds) or timeout_seconds <= 0:
        raise contract.VoiceSttError("stt_unavailable", 503)

    async def _body_bytes() -> bytes:
        # Read the same JS ReadableStream API as incoming requests. The
        # limit+1 probe rejects an oversized provider chunk *before* bytes()
        # can copy it into Python memory. Response.text()/json() would
        # materialise unbounded provider data before the size check.
        return await contract.read_bounded_body(
            _chunk_reader(response, 8192), contract.MAX_UPSTREAM_RESPONSE_BYTES
        )

    try:
        raw = await asyncio.wait_for(_body_bytes(), timeout=timeout_seconds)
    except (asyncio.TimeoutError, contract.VoiceSttError) as exc:
        raise contract.VoiceSttError("stt_unavailable", 503) from exc
    except Exception as exc:
        raise contract.VoiceSttError("stt_unavailable", 503) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


async def _upstream_json(url, *, method, headers, body, timeout_ms) -> tuple[int, object]:
    """One upstream call whose *whole* round trip — headers **and** body — is bounded.

    Returns ``(status, parsed)``. The deadline is captured once and the body
    read only gets what is left of it, so the 25s / 8s ceilings are end-to-end
    budgets rather than connect-and-header budgets.
    """
    budget = _timeout_seconds(timeout_ms)
    started = time.monotonic()
    response = await _upstream_fetch(
        url, method=method, headers=headers, body=body, timeout_ms=timeout_ms
    )
    remaining = budget - (time.monotonic() - started)
    if remaining <= 0:
        raise contract.VoiceSttError("stt_unavailable", 503)
    parsed = await _read_upstream_json(response, remaining)
    return int(getattr(response, "status", 0) or 0), parsed


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _require_authorization(authorization: object, route: str) -> None:
    """Re-check the authorization a paid route was dispatched with.

    Defence in depth: the route gate already produced a verified authorization,
    but the handler still insists on the documented shape and on the **exact**
    route and capability it names, so an authorization minted for the live-token
    route can never be replayed against transcription (or the reverse).
    """
    if not isinstance(authorization, contract.CallerAuthorization):
        raise contract.VoiceSttError("voice_stt_authority_unavailable", 503)
    if not authorization.admits(route):
        raise contract.VoiceSttError("voice_stt_authority_unavailable", 503)


async def _handle_transcribe(
    env,
    authorization: contract.CallerAuthorization,
    language: str,
    audio: contract.AudioPayload,
) -> Response:
    _require_authorization(authorization, TRANSCRIBE_PATH)

    api_key = await _resolve_secret(env, contract.GROQ_API_KEY_BINDING)
    if not api_key:
        # Never invent, borrow or print a key. Report the missing binding only.
        return _error("stt_key_missing")

    last_code = "stt_failed"
    for model in contract.groq_model_sequence():
        boundary = "----padiemvoice" + uuid.uuid4().hex
        content_type, body = contract.build_groq_multipart_body(
            model=model, audio=audio, language=language, boundary=boundary
        )
        status, parsed = await _upstream_json(
            contract.GROQ_STT_ENDPOINT,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
            body=body,
            timeout_ms=contract.GROQ_REQUEST_TIMEOUT_MS,
        )

        ok, text, code = contract.parse_groq_transcription_response(status, parsed)
        if ok:
            return _ok({"text": text, "provider": "groq_whisper", "model": model})
        last_code = code or "stt_failed"

    return _error(last_code)


async def _handle_live_token(
    env, authorization: contract.CallerAuthorization
) -> Response:
    _require_authorization(authorization, LIVE_TOKEN_PATH)

    api_key = await _resolve_secret(env, contract.GEMINI_API_KEY_BINDING)
    if not api_key:
        return _error("live_token_unavailable")

    body = contract.build_live_token_request_body()
    status, parsed = await _upstream_json(
        contract.GEMINI_LIVE_TOKEN_ENDPOINT,
        method="POST",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        body=json.dumps(body),
        timeout_ms=contract.LIVE_TOKEN_REQUEST_TIMEOUT_MS,
    )

    token = contract.extract_live_token(parsed) if 200 <= status < 300 else None
    if not token:
        return _error("live_token_unavailable")
    session = contract.LiveSessionConfig().to_public_dict()
    # ``expireTime`` is echoed back as an absolute RFC3339 instant so the client
    # can re-mint without guessing; it carries no credential material.
    return _ok(
        {
            "token": token,
            "expireTime": body["expireTime"],
            "session": session,
        }
    )


def _handle_capabilities() -> Response:
    return _ok(
        {
            "contract_version": contract.CONTRACT_VERSION,
            # A paid route is served only after a canonical Control Plane
            # session, tenant and entitlement grant were resolved and a per-request
            # cost reservation was admitted for it. Nothing else opens one, and
            # the route names themselves are not published to the browser.
            "enabled_route_contract": "canonical_caller_tenant_cost_authority",
            "provider_order": [provider.value for provider in contract.STT_PROVIDER_ORDER],
            "session": contract.LiveSessionConfig().to_public_dict(),
            "groq_models": list(contract.groq_model_sequence()),
            "max_audio_bytes": contract.MAX_AUDIO_BYTES,
        }
    )


def _method(request) -> str:
    """Normalise the request method to an upper-case string."""
    return contract.normalize_http_method(getattr(request, "method", ""))


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        route = _route_of(request)
        method = _method(request)
        try:
            # Deployment gate first: no Secret read and no provider call while OFF.
            await _require_enabled(self.env)
            if route == CAPABILITIES_PATH:
                if method != "GET":
                    return _error("method_not_allowed")
                return _handle_capabilities()
            if route == TRANSCRIBE_PATH:
                if method != "POST":
                    return _error("method_not_allowed")
                # Identity clues first (no body buffered for an anonymous caller),
                # then the bounded body, then the Control Plane authority — whose
                # cost units are computed from the audio length validated here.
                # Nothing below reads a Secret or calls a provider before that.
                clues = _require_caller_clues(request)
                _require_json_content_type(request)
                payload = await _read_json(request, contract.MAX_REQUEST_BYTES)
                language, audio = contract.validate_transcribe_request(payload)
                authorization = await _require_caller_authorization(
                    self.env,
                    route=TRANSCRIBE_PATH,
                    clues=clues,
                    capability=contract.CAPABILITY_TRANSCRIBE,
                    estimated_units=contract.cost_units_for_audio(audio.size),
                )
                return await _handle_transcribe(self.env, authorization, language, audio)
            if route == LIVE_TOKEN_PATH:
                if method != "POST":
                    return _error("method_not_allowed")
                clues = _require_caller_clues(request)
                _require_json_content_type(request)
                payload = await _read_json(request, LIVE_TOKEN_MAX_BYTES)
                if not isinstance(payload, dict) or set(payload) - {"sessionId"}:
                    raise contract.VoiceSttError("unsupported_field", 400)
                authorization = await _require_caller_authorization(
                    self.env,
                    route=LIVE_TOKEN_PATH,
                    clues=clues,
                    capability=contract.CAPABILITY_LIVE_TOKEN,
                    estimated_units=contract.LIVE_TOKEN_COST_UNITS,
                )
                return await _handle_live_token(self.env, authorization)
            return _error("not_found")
        except contract.VoiceSttError as exc:
            return _error(exc.code)
        except Exception:
            # A bounded envelope only. Never leak a provider trace, a Secret or a
            # stack frame to a caller (or to a log) over an unexpected failure.
            return _error("stt_failed")


def _route_of(request) -> str:
    url = getattr(request, "url", "")
    if not isinstance(url, str):
        url = str(url)
    return contract.route_path(url)
