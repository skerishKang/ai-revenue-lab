"""Authenticated host→Chat-Worker RPC for the private STT lane (#7228 recovery).

The COM2 Chat host has no Service Binding to ``padiem-voice-stt`` — only the
Cloudflare Chat Worker does (``VOICE_STT_SERVICE`` in wrangler.toml). The host
therefore fills ``app.state.voice_stt_transport`` with a transport that calls
THIS receiver over the same v2 service-proof RPC surface the other host
lanes already use (``app/local_service_bridge.py``), and this receiver answers
from the Worker's own service-binding transport. The STT Worker keeps zero new
HTTPS ingress: it is still reached only through the existing binding.

Contract (the password_rpc receiver shape, one dedicated secret):

    PADIEM_CHAT_VOICE_RPC_SECRET   — Worker secret; the host holds the same
                                     value as PADIEM_CHAT_VOICE_RPC_SECRET
                                     next to PADIEM_CHAT_VOICE_RPC_ORIGIN.
    x-padiem-service-at:     <unix seconds>
    x-padiem-service-id:     <fresh random id, one per attempt>
    x-padiem-service-proof:  v2=<hex(hmac_sha256(secret,
        "v2\\nPOST\\n" + path + "\\n" + at + "\\n" + service_id + "\\n" + body))>

Body is one JSON object: ``{"op": "live_token"|"transcribe", "productId",
"sessionId"}`` plus, for transcribe, ``language`` and ``audioDataUrl`` under
the same bounds the public route enforces. The answer is
``{"status": <upstream status>, "body": "<upstream utf-8 json>"}`` so the
caller can pass the STT Worker's own bounded codes through unchanged.

An unconfigured secret keeps this route answering 404 like every other
internal RPC receiver — never a silent downgrade.
"""
from __future__ import annotations

import json
import logging
import time

from starlette.requests import Request
from starlette.responses import JSONResponse

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .password_rpc import _consume_service_id, _error, _verify_service_proof
from .service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
)
from .voice_stt_routes import MAX_AUDIO_BASE64_CHARS, _MAX_RESPONSE_BYTES

VOICE_RPC_PATH = "/internal/rpc/voice_stt"

# The transcribe op carries the same base64 audio the public route accepts;
# the envelope around it (op/productId/sessionId/language) is bounded too.
_VOICE_RPC_ENVELOPE_BYTES = 4096
VOICE_RPC_BODY_LIMIT = MAX_AUDIO_BASE64_CHARS + 65536 + _VOICE_RPC_ENVELOPE_BYTES

_IDENTITY_FIELD_LIMIT = 256
_LIVE_TOKEN_OPS = ("live_token", "transcribe")

_STT_RPC_LOG = logging.getLogger(__name__)


def _identity_field(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if len(value) > _IDENTITY_FIELD_LIMIT:
        return None
    return value


async def voice_stt_rpc(request: Request) -> JSONResponse:
    """POST /internal/rpc/voice_stt — authenticated live-token/transcribe RPC."""
    settings = getattr(request.app.state, "settings", None)
    secret = getattr(settings, "voice_rpc_secret", None)
    store = getattr(request.app.state, "history_store", None)
    transport = getattr(request.app.state, "voice_stt_transport", None)
    if not isinstance(secret, str) or len(secret) < 32 or transport is None or \
            store is None or not callable(getattr(store, "consume_service_id", None)):
        return _error(404, "not_found", "not found")
    if request.url.path != VOICE_RPC_PATH:
        return _error(404, "not_found", "not found")
    try:
        body = await read_bounded_request_body(request, max_bytes=VOICE_RPC_BODY_LIMIT)
    except RequestBodyTooLarge:
        return _error(401, "unauthorized", "unauthorized")
    verified = _verify_service_proof(
        headers=request.headers, path=VOICE_RPC_PATH, body=body, secret=secret,
        now_epoch=int(time.time()), max_body_bytes=VOICE_RPC_BODY_LIMIT,
    )
    if verified is None:
        return _error(401, "unauthorized", "unauthorized")
    try:
        if not await _consume_service_id(store, verified["service_id"], verified["at"]):
            return _error(409, "rpc_replay_detected", "replayed service id")
    except Exception as exc:
        _STT_RPC_LOG.warning("voice_stt_rpc_store_error exception_type=%s", type(exc).__name__)
        return _error(503, "voice_storage_error", "verification store unavailable")

    payload = verified["payload"]
    if not isinstance(payload, dict):
        return _error(400, "invalid_request", "invalid request body")
    op = payload.get("op")
    product_id = _identity_field(payload.get("productId"))
    session_id = _identity_field(payload.get("sessionId"))
    if op not in _LIVE_TOKEN_OPS or product_id is None or session_id is None:
        return _error(400, "invalid_request", "invalid request body")

    try:
        if op == "live_token":
            status, raw = await transport.live_token(
                body={"sessionId": session_id},
                product_id=product_id,
                session_id=session_id,
            )
        else:
            language = payload.get("language")
            audio = payload.get("audioDataUrl")
            if not isinstance(language, str) or not language.strip() or \
                    not isinstance(audio, str) or not audio.startswith("data:") or \
                    len(audio) > MAX_AUDIO_BASE64_CHARS:
                return _error(400, "invalid_request", "invalid request body")
            status, raw = await transport.transcribe(
                body={"language": language, "audioDataUrl": audio},
                product_id=product_id,
                session_id=session_id,
            )
    except (ServiceBindingResponseError, ServiceBindingResponseTooLarge):
        return _error(503, "voice_stt_unavailable", "voice stt unavailable")
    except Exception:
        return _error(502, "voice_stt_failed", "voice stt failed")

    if not isinstance(status, int) or isinstance(status, bool) or \
            not isinstance(raw, (bytes, bytearray)) or len(raw) > _MAX_RESPONSE_BYTES:
        return _error(502, "voice_stt_failed", "voice stt failed")
    return JSONResponse(
        {"status": int(status), "body": bytes(raw).decode("utf-8", "replace")},
        status_code=200,
    )
