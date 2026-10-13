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
    Mints a short-lived Gemini Live ephemeral token so the browser can open a
    Live transcription session without ever holding the long-lived key.

``GET  /internal/v1/voice/capabilities``
    Browser-safe session parameters (model name, VAD window, rotation window)
    and the provider order. Contains no key, token or account identity.

All validation, provider order, chunk/turn/dedup rules and payload construction
live in ``voice_stt_contract``; this module is the thin Workers adapter so the
contract stays unit-testable without the Workers runtime.
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint, fetch

import voice_stt_contract as contract

TRANSCRIBE_PATH = "/internal/v1/voice/transcribe"
LIVE_TOKEN_PATH = "/internal/v1/voice/live-token"
CAPABILITIES_PATH = "/internal/v1/voice/capabilities"

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
    status = contract.STATUS_BY_CODE.get(code, 400)
    return _json(status, {"ok": False, "error": {"code": code}})


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


async def _read_json(request, max_bytes: int) -> dict:
    declared = request.headers.get("content-length") if request.headers is not None else None
    if declared:
        try:
            if int(declared) > max_bytes:
                raise contract.VoiceSttError("request_too_large", 413)
        except ValueError:
            raise contract.VoiceSttError("invalid_content_length", 400)
    raw = await request.text()
    if not isinstance(raw, str):
        raise contract.VoiceSttError("invalid_json", 400)
    if len(raw.encode("utf-8")) > max_bytes:
        raise contract.VoiceSttError("request_too_large", 413)
    try:
        data = json.loads(raw)
    except Exception:
        raise contract.VoiceSttError("invalid_json", 400)
    return data


def _require_json_content_type(request) -> None:
    content_type = request.headers.get("content-type") if request.headers is not None else None
    if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise contract.VoiceSttError("unsupported_media_type", 415)


async def _handle_transcribe(env, request) -> Response:
    _require_json_content_type(request)
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
        try:
            upstream = await fetch(
                contract.GROQ_STT_ENDPOINT,
                method="POST",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
                body=body,
            )
            status = int(getattr(upstream, "status", 0) or 0)
            try:
                parsed = await upstream.json()
            except Exception:
                parsed = None
        except Exception:
            # Transport failure: try the next model, never surface the trace.
            last_code = "stt_unavailable"
            continue

        ok, text, code = contract.parse_groq_transcription_response(status, parsed)
        if ok:
            return _ok({"text": text, "provider": "groq_whisper", "model": model})
        last_code = code or "stt_failed"

    return _error(last_code)


async def _handle_live_token(env, request) -> Response:
    _require_json_content_type(request)
    payload = await _read_json(request, 8 * 1024)
    if not isinstance(payload, dict) or set(payload) - {"sessionId"}:
        raise contract.VoiceSttError("unsupported_field", 400)

    api_key = await _resolve_secret(env, contract.GEMINI_API_KEY_BINDING)
    if not api_key:
        return _error("live_token_unavailable")

    body = contract.build_live_token_request_body()
    try:
        upstream = await fetch(
            contract.GEMINI_LIVE_TOKEN_ENDPOINT,
            method="POST",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            body=json.dumps(body),
        )
        status = int(getattr(upstream, "status", 0) or 0)
        try:
            parsed = await upstream.json()
        except Exception:
            parsed = None
    except Exception:
        return _error("live_token_unavailable")

    token = contract.extract_live_token(parsed) if 200 <= status < 300 else None
    if not token:
        return _error("live_token_unavailable")
    return _ok({"token": token, "session": contract.LiveSessionConfig().to_public_dict()})


def _handle_capabilities() -> Response:
    return _ok(
        {
            "contract_version": contract.CONTRACT_VERSION,
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
        route = urlparse(str(getattr(request, "url", ""))).path
        method = _method(request)
        try:
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
            return _error("stt_failed")
