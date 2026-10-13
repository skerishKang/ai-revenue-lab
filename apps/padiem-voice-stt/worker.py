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
whole Worker answers ``voice_stt_disabled``. Even the ``ON`` state requires the
``VOICE_STT_CALLER_GUARD`` Service Binding, whose presence alone only opens the
key-free capabilities route. Paid routes (transcribe, live-token) additionally
require the guard to approve the request through its verified ``authorize``
contract (``_require_caller_authorization``): caller identity plus a bounded
per-account cost scope. No approval exists yet, so this Worker cannot serve a
paid route today. See ``voice_stt_contract`` for why.

All validation, provider order, chunk/turn/dedup rules and payload construction
live in ``voice_stt_contract``; this module is the thin Workers adapter so the
contract stays unit-testable without the Workers runtime.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from workers import Response, WorkerEntrypoint, fetch

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


def _binding_present(env, name: str) -> bool:
    value = getattr(env, name, None)
    return value is not None


def _caller_guard(env):
    """Return the caller-guard binding, or ``None`` when it is not attached."""
    return getattr(env, contract.VOICE_STT_CALLER_GUARD_BINDING, None)


async def _require_caller_authorization(env, *, route: str) -> None:
    """Require a real caller-identity / cost authorization for paid routes.

    Presence of the ``VOICE_STT_CALLER_GUARD`` binding only proves the binding
    is attached. A paid upstream call additionally requires the guard to
    approve this request through its verified ``authorize`` contract
    (``authorize_caller`` / ``authorize`` / ``verify``): it must return a
    truthy approval — synchronously or as an awaitable. Anything else
    (missing method, exception, falsy/ambiguous result, missing identity or
    missing cost scope) fails closed with ``caller_guard_unavailable`` before
    any Secret is read or any provider is called.

    The capabilities route carries no Secret, token, account identity or paid
    call, so it stays on the presence-only gate.
    """
    guard = _caller_guard(env)
    if guard is None:
        raise contract.VoiceSttError("caller_guard_unavailable", 503)
    candidate = None
    for method_name in ("authorize_caller", "authorize", "verify"):
        method = getattr(guard, method_name, None)
        if callable(method):
            candidate = method
            break
    if candidate is None:
        raise contract.VoiceSttError("caller_guard_unavailable", 503)
    try:
        decision = candidate({"route": route})
    except TypeError:
        try:
            decision = candidate(route)
        except Exception:
            raise contract.VoiceSttError("caller_guard_unavailable", 503)
    except Exception:
        raise contract.VoiceSttError("caller_guard_unavailable", 503)
    try:
        # Duck-typed awaitable detection (no ``inspect`` import): a coroutine
        # or any thenable carries ``__await__``.
        if hasattr(decision, "__await__"):
            decision = await decision
    except Exception:
        raise contract.VoiceSttError("caller_guard_unavailable", 503)
    if decision is True:
        return
    if isinstance(decision, dict):
        allowed = decision.get("allowed", decision.get("authorized", False))
        identity = decision.get("caller", decision.get("identity", decision.get("account_id")))
        scope = decision.get("cost_scope", decision.get("scope", decision.get("budget")))
        if allowed is True and isinstance(identity, str) and identity.strip() and scope is not None:
            return
    raise contract.VoiceSttError("caller_guard_unavailable", 503)


async def _require_enabled(env) -> None:
    """Gate every route. Order matters: no Secret read or provider call if OFF."""
    flag = getattr(env, contract.VOICE_STT_ENABLED_BINDING, None)
    if isinstance(flag, str):
        enabled = flag.strip().lower() == "true"
    elif flag is None:
        enabled = False
    else:
        enabled = flag is True
    if not enabled:
        raise contract.VoiceSttError("voice_stt_disabled", 503)

    # ON is not reachable without the caller-identity / cost-authorization
    # Service Binding. Presence alone only opens the key-free capabilities
    # route; paid routes re-verify the guard per request. Do not relax this
    # to make tests pass.
    if not _binding_present(env, contract.VOICE_STT_CALLER_GUARD_BINDING):
        raise contract.VoiceSttError("caller_guard_unavailable", 503)


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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _handle_transcribe(env, request) -> Response:
    _require_json_content_type(request)
    await _require_caller_authorization(env, route=TRANSCRIBE_PATH)
    payload = await _read_json(request, contract.MAX_REQUEST_BYTES)
    language, audio = contract.validate_transcribe_request(payload)

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
        upstream = await _upstream_fetch(
            contract.GROQ_STT_ENDPOINT,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
            body=body,
            timeout_ms=contract.GROQ_REQUEST_TIMEOUT_MS,
        )
        status = int(getattr(upstream, "status", 0) or 0)
        try:
            parsed = await upstream.json()
        except Exception:
            parsed = None

        ok, text, code = contract.parse_groq_transcription_response(status, parsed)
        if ok:
            return _ok({"text": text, "provider": "groq_whisper", "model": model})
        last_code = code or "stt_failed"

    return _error(last_code)


async def _handle_live_token(env, request) -> Response:
    _require_json_content_type(request)
    await _require_caller_authorization(env, route=LIVE_TOKEN_PATH)
    payload = await _read_json(request, LIVE_TOKEN_MAX_BYTES)
    if not isinstance(payload, dict) or set(payload) - {"sessionId"}:
        raise contract.VoiceSttError("unsupported_field", 400)

    api_key = await _resolve_secret(env, contract.GEMINI_API_KEY_BINDING)
    if not api_key:
        return _error("live_token_unavailable")

    body = contract.build_live_token_request_body()
    upstream = await _upstream_fetch(
        contract.GEMINI_LIVE_TOKEN_ENDPOINT,
        method="POST",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        body=json.dumps(body),
        timeout_ms=contract.LIVE_TOKEN_REQUEST_TIMEOUT_MS,
    )
    status = int(getattr(upstream, "status", 0) or 0)
    try:
        parsed = await upstream.json()
    except Exception:
        parsed = None

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
            # Presence of the guard binding opens only this key-free route. Paid
            # routes additionally require the guard's per-request ``authorize``
            # approval (caller identity + bounded cost scope); until such a
            # guard exists no paid route is reachable.
            "enabled_route_contract": "fail_closed_paid_needs_authorize",
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
                return await _handle_transcribe(self.env, request)
            if route == LIVE_TOKEN_PATH:
                if method != "POST":
                    return _error("method_not_allowed")
                return await _handle_live_token(self.env, request)
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
