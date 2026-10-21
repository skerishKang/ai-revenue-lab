"""Chat/Claw browser -> private STT Worker bridge for #4643 voice input.

Why this module exists
----------------------
The browser must never hold a provider key and must never reach the private
``padiem-voice-stt`` Worker directly: that Worker is ``workers_dev = false`` and
is reachable only over a Service Binding from a reviewed product Worker. So the
recognizer in ``static/voice-stt-wiring.js`` posts audio to this app, and this
app forwards it over that Service Binding.

What this module does *not* do
------------------------------
It is not an authorization authority. It authenticates the caller with the
**existing** ``padiem_session`` cookie -- no new login, no OWNER-only gate, no
new account system, no personal/business split -- resolves that user's
**canonical** Control Plane session, and forwards two opaque clues. The STT
Worker then independently re-resolves the session, the tenant, the entitlement
and the per-request cost reservation from the Control Plane before it reads a
Secret or spends anything.

Anything that is not a plain, authenticated, canonical-session-backed forward
fails closed here with a bounded error. In particular this module never:

* accepts a caller-supplied ``product_id``, tenant, subject, entitlement, plan,
  cost cap or spend limit -- no such field exists in its request surface;
* reads, forwards or logs a Cloudflare Secret value;
* bypasses, relaxes or re-implements the STT Worker's caller guard;
* sends a chat message. A transcript is a candidate for the existing composer
  input only; the user still presses the existing send button.

Activation state
----------------
The STT Worker deployment gate, the canonical Control Plane bindings
(``CONTROL_PLANE_IDENTITY`` / ``CONTROL_PLANE_ENGINE_ADMISSION``) and the
``voice.stt.*`` entitlement grants are owned by CENTRAL and are NOT enabled
here. Until they exist, ``voice_transcribe`` answers one bounded error and the
browser shows a truthful mic error instead of a fabricated transcript. Flipping
any of those gates is an operational change, not a source change.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    read_bounded_service_binding_body,
)

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .same_origin_guard import expected_browser_origin

__all__ = [
    "IDENTITY_PATH",
    "TRANSCRIBE_PATH",
    "LIVE_TOKEN_PATH",
    "CLAW_IDENTITY_PATH",
    "CLAW_TRANSCRIBE_PATH",
    "CLAW_LIVE_TOKEN_PATH",
    "STT_INTERNAL_ORIGIN",
    "STT_TRANSCRIBE_PATH",
    "STT_LIVE_TOKEN_PATH",
    "VOICE_STT_LANGUAGE",
    "MAX_AUDIO_BASE64_CHARS",
    "MAX_VOICE_TRANSCRIBE_BYTES",
    "MAX_VOICE_LIVE_TOKEN_BYTES",
    "CALLER_PRODUCT_HEADER",
    "CALLER_SESSION_HEADER",
    "CloudflareVoiceSttServiceTransport",
    "voice_identity",
    "voice_transcribe",
    "voice_live_token",
]

IDENTITY_PATH = "/api/voice/identity"
TRANSCRIBE_PATH = "/api/voice/transcribe"
LIVE_TOKEN_PATH = "/api/voice/live-token"
CLAW_IDENTITY_PATH = "/api/claw/voice/identity"
CLAW_TRANSCRIBE_PATH = "/api/claw/voice/transcribe"
CLAW_LIVE_TOKEN_PATH = "/api/claw/voice/live-token"

#: Internal-only. The browser never learns or addresses this origin/path; only
#: this module does, and only over the Service Binding.
STT_INTERNAL_ORIGIN = "https://padiem-voice-stt.internal"
STT_TRANSCRIBE_PATH = "/internal/v1/voice/transcribe"
STT_LIVE_TOKEN_PATH = "/internal/v1/voice/live-token"

#: Language is a server constant, never a browser field. "auto" is the STT
#: contract's own default and avoids pinning a wrong language onto a customer.
VOICE_STT_LANGUAGE = "auto"

#: The STT contract caps decoded audio at 3 MiB; base64 inflates by ~4/3, so the
#: browser envelope is bounded slightly above that and still fails closed here
#: before anything is forwarded.
MAX_AUDIO_BASE64_CHARS = 5 * 1024 * 1024

#: Maximum size of the raw voice transcription request body. It must cover the
#: reviewed 5 MiB base64 envelope plus a modest JSON wrapper; larger bodies
#: are rejected before they are materialized into memory.
MAX_VOICE_TRANSCRIBE_BYTES = MAX_AUDIO_BASE64_CHARS + 65536

#: The live-token request carries no audio. It is one small JSON object, and
#: the STT Worker's own live-token route is bounded far below this.
MAX_VOICE_LIVE_TOKEN_BYTES = 8 * 1024

#: The two opaque clues the STT Worker's caller guard reads. They select a
#: Control Plane session to resolve; they are not themselves an identity.
CALLER_PRODUCT_HEADER = "x-padiem-product-id"
CALLER_SESSION_HEADER = "x-padiem-auth-session-id"

_ALLOWED_BROWSER_FIELDS = frozenset({"audio_base64", "mime_type", "utterance_id"})
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_MIME_RE = re.compile(r"^audio/[A-Za-z0-9.+-]{1,60}$")
_ID_CHARS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_MAX_UTTERANCE_ID_CHARS = 96
_MAX_RESPONSE_BYTES = 131072


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": code}}, status_code=status)


def _identity_key(settings: Any, canonical_session_id: str) -> str:
    """An opaque, stable, non-reversible key for one canonical session.

    It exists only so the browser can notice "the account behind this page
    changed" while ``authenticated`` stays true -- the blind spot of the
    boolean-only ``padiem:auth-state`` event (#3790). It is derived from the
    session id with the server's session secret, so it is stable for a session,
    differs between accounts, and reveals nothing about either.
    """
    secret = getattr(settings, "session_secret", None)
    if not secret:
        return ""
    digest = hmac.new(
        str(secret).encode("utf-8"),
        ("padiem-chat/voice-identity/v1:" + canonical_session_id).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:32]


async def _canonical_session(request: Request) -> Any | None:
    """Resolve the exact server-owned B62 or B54 session for this route.

    Route path fixes the product, not a browser-controlled plan/product id.
    Both use the same signed PADIEM cookie and existing CP identity authority.
    """
    path = request.url.path
    if path in (CLAW_IDENTITY_PATH, CLAW_TRANSCRIBE_PATH, CLAW_LIVE_TOKEN_PATH):
        from .b54_canonical_session import resolve_current_b54_canonical_session
        return await resolve_current_b54_canonical_session(request)
    if path not in (IDENTITY_PATH, TRANSCRIBE_PATH, LIVE_TOKEN_PATH):
        return None

    # B62 must never be billed with a B54 grant merely because both products
    # share one user login. Read the B62 session from the existing CP authority.
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from padiem_control_plane.auth_sessions import AuthSessionSnapshot
    from padiem_control_plane.contracts import SubjectType
    from .auth_routes import auth_ready, current_user_id

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    uid = current_user_id(request) if auth_ready(request) else None
    if authority is None or not uid:
        return None
    try:
        session = await authority.resolve_current_auth_session(
            product_id="b62", product_user_id=uid,
        )
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    if (
        not isinstance(session, AuthSessionSnapshot)
        or session.product_id != "b62"
        or session.subject.subject_type is not SubjectType.USER
        or not session.tenant_id
        or not session.is_active(now=now)
    ):
        return None
    # The B54 bridge exposes .auth_session; preserve that typed envelope shape
    # without minting a second identity or session, only wrapping verified CP.
    return SimpleNamespace(auth_session=session)


async def voice_identity(request: Request) -> JSONResponse:
    """Opaque voice identity key for the current session.

    Signed out, or no canonical session resolvable yet: ``""`` with 200, so the
    browser can simply compare the previous key against the new one instead of
    branching on a status code.
    """
    settings = request.app.state.settings
    try:
        session = await _canonical_session(request)
    except Exception:
        session = None
    if session is None:
        return JSONResponse({"identity_key": ""}, status_code=200)
    key = _identity_key(settings, session.auth_session.session_id)
    return JSONResponse({"identity_key": key}, status_code=200)


def _read_audio(payload: object) -> tuple[str, str]:
    """Validate the browser envelope into ``(mime_type, audio_base64)``."""
    if not isinstance(payload, Mapping):
        raise ValueError("invalid_json")
    if not _ALLOWED_BROWSER_FIELDS.issuperset(set(payload)):
        raise ValueError("unsupported_field")
    audio_base64 = payload.get("audio_base64")
    if not isinstance(audio_base64, str) or not audio_base64:
        raise ValueError("invalid_audio")
    if len(audio_base64) > MAX_AUDIO_BASE64_CHARS:
        raise ValueError("audio_too_large")
    stripped = audio_base64.strip()
    if not _BASE64_RE.fullmatch(stripped):
        raise ValueError("invalid_audio")
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("invalid_audio") from None
    if not decoded:
        raise ValueError("invalid_audio")
    mime_type = payload.get("mime_type")
    if mime_type is not None:
        if not isinstance(mime_type, str):
            raise ValueError("invalid_audio")
        # MediaRecorder reports its container with codec parameters, e.g.
        # ``audio/webm;codecs=opus``. The forwarding contract carries a bare
        # media type, so validate that and drop the parameters.
        mime_type = mime_type.split(";", 1)[0].strip()
        if not _MIME_RE.fullmatch(mime_type):
            raise ValueError("invalid_audio")
    return (mime_type or "audio/webm"), stripped


def _utterance_id(payload: object) -> str | None:
    """Echo the caller's own turn id back, bounded.

    Never forwarded upstream and never used for authorization; it only lets the
    shared adapter de-duplicate the utterance it already heard.
    """
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("utterance_id")
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > _MAX_UTTERANCE_ID_CHARS:
        return None
    if not _ID_CHARS.fullmatch(candidate):
        return None
    return candidate


async def voice_transcribe(request: Request) -> JSONResponse:
    """Authenticate, forward one bounded audio chunk, return one candidate.

    The browser's own ``utterance_id`` is dropped here: the STT contract has a
    closed field set and would reject an unknown field outright.
    """
    settings = getattr(request.app.state, "settings", None) if getattr(request, "app", None) else None
    expected_origin = expected_browser_origin(settings)
    origin = request.headers.get("origin") if getattr(request, "headers", None) is not None else None
    if expected_origin is not None and origin is not None and origin.strip() != expected_origin:
        return _error("origin_rejected", 403)

    content_type = request.headers.get("content-type") if getattr(request, "headers", None) is not None else None
    media_type = "" if content_type is None else str(content_type).split(";", 1)[0].strip().lower()
    if media_type not in ("application/json", "application/octet-stream"):
        return _error("unsupported_media_type", 415)

    try:
        raw_body = await read_bounded_request_body(
            request,
            max_bytes=(3 * 1024 * 1024 if media_type == "application/octet-stream" else MAX_VOICE_TRANSCRIBE_BYTES),
        )
    except RequestBodyTooLarge:
        return _error("request_too_large", 413)
    if media_type == "application/octet-stream":
        if not raw_body:
            return _error("invalid_audio", 400)
        raw_mime = request.headers.get("x-padiem-audio-type", "audio/webm").split(";", 1)[0].strip()
        if not _MIME_RE.fullmatch(raw_mime):
            return _error("invalid_audio", 400)
        payload = {"utterance_id": request.headers.get("x-padiem-utterance-id", "")}
        mime_type, audio_base64 = raw_mime, base64.b64encode(raw_body).decode("ascii")
    else:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return _error("invalid_json", 400)
        try:
            mime_type, audio_base64 = _read_audio(payload)
        except ValueError as exc:
            return _error(str(exc), 400)

    try:
        session = await _canonical_session(request)
    except Exception:
        session = None
    if session is None:
        # No authenticated canonical session: never reach the paid STT route.
        return _error("voice_signin_required", 401)

    transport = getattr(request.app.state, "voice_stt_transport", None)
    if transport is None:
        return _error("voice_stt_unavailable", 503)

    auth_session = session.auth_session
    body = {
        "language": VOICE_STT_LANGUAGE,
        "audioDataUrl": f"data:{mime_type};base64,{audio_base64}",
    }
    try:
        status, raw = await transport.transcribe(
            body=body,
            product_id=auth_session.product_id,
            session_id=auth_session.session_id,
        )
    except (ServiceBindingResponseError, ServiceBindingResponseTooLarge):
        return _error("voice_stt_unavailable", 503)
    except Exception:
        return _error("voice_stt_failed", 502)

    if status != 200:
        # Pass the STT Worker's own bounded code through unchanged so the UI can
        # stay truthful about cost/authority refusals. Never leak a body.
        code = "voice_stt_denied"
        try:
            parsed = json.loads(raw.decode("utf-8"))
            candidate = parsed.get("error", {}).get("code")
            if isinstance(candidate, str) and candidate:
                code = candidate
        except Exception:
            pass
        return _error(code, 403 if status in (401, 403) else 502)

    try:
        parsed = json.loads(raw.decode("utf-8"))
        text = parsed.get("text")
    except Exception:
        return _error("voice_stt_failed", 502)
    if not isinstance(text, str) or not text.strip():
        return _error("voice_stt_empty", 200)

    payload_out: dict[str, Any] = {"text": text.strip()}
    utterance = _utterance_id(payload)
    if utterance is not None:
        payload_out["utterance_id"] = utterance
    return JSONResponse(payload_out, status_code=200)


async def voice_live_token(request: Request) -> JSONResponse:
    """Mint one ephemeral Gemini Live token for the authenticated session.

    The browser needs a short-lived, model-locked token to open a real-time
    Live transcription session. The long-lived provider key stays in the
    private STT Worker, which is reachable only over the Service Binding, and
    the Control Plane admits the call against the same voice entitlement and
    cost authority the transcription route uses.
    """
    settings = getattr(request.app.state, "settings", None) if getattr(request, "app", None) else None
    expected_origin = expected_browser_origin(settings)
    origin = request.headers.get("origin") if getattr(request, "headers", None) is not None else None
    if expected_origin is not None and origin is not None and origin.strip() != expected_origin:
        return _error("origin_rejected", 403)

    content_type = request.headers.get("content-type") if getattr(request, "headers", None) is not None else None
    media_type = "" if content_type is None else str(content_type).split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return _error("unsupported_media_type", 415)

    try:
        raw_body = await read_bounded_request_body(
            request, max_bytes=MAX_VOICE_LIVE_TOKEN_BYTES
        )
    except RequestBodyTooLarge:
        return _error("request_too_large", 413)
    if raw_body:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return _error("invalid_json", 400)
        if not isinstance(payload, dict) or set(payload) - {"sessionId"}:
            return _error("unsupported_field", 400)
    else:
        payload = {}

    try:
        session = await _canonical_session(request)
    except Exception:
        session = None
    if session is None:
        # No authenticated canonical session: never reach the paid Live route.
        return _error("voice_signin_required", 401)

    transport = getattr(request.app.state, "voice_stt_transport", None)
    if transport is None:
        return _error("voice_stt_unavailable", 503)

    auth_session = session.auth_session
    body = {"sessionId": str(auth_session.session_id)}
    try:
        status, raw = await transport.live_token(
            body=body,
            product_id=auth_session.product_id,
            session_id=auth_session.session_id,
        )
    except (ServiceBindingResponseError, ServiceBindingResponseTooLarge):
        return _error("voice_stt_unavailable", 503)
    except Exception:
        return _error("voice_stt_failed", 502)

    if status != 200:
        # Pass the STT Worker's own bounded code through unchanged so the UI can
        # stay truthful about cost/authority refusals. Never leak a body.
        code = "voice_stt_denied"
        try:
            parsed = json.loads(raw.decode("utf-8"))
            candidate = parsed.get("error", {}).get("code")
            if isinstance(candidate, str) and candidate:
                code = candidate
        except Exception:
            pass
        return _error(code, 403 if status in (401, 403) else 502)

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return _error("voice_stt_failed", 502)
    token = parsed.get("token")
    if not isinstance(token, str) or not token.strip():
        return _error("voice_live_token_unavailable", 502)

    # Only the browser-safe fields cross back. The token itself is the
    # credential the browser needs; the session block is the public contract
    # (model, activity-detection window, rotation window, transcription mode).
    payload_out: dict[str, Any] = {"token": token.strip()}
    expire = parsed.get("expireTime")
    if isinstance(expire, str) and expire:
        payload_out["expireTime"] = expire
    live_session = parsed.get("session")
    if isinstance(live_session, dict):
        payload_out["session"] = live_session
    return JSONResponse(payload_out, status_code=200)


class CloudflareVoiceSttServiceTransport:
    """Service Binding transport to the private STT Worker.

    ``request_factory`` is injected (the workers-runtime ``Request``) so this
    module stays importable and unit-testable outside the Workers runtime.
    """

    def __init__(self, binding: Any, request_factory: Any) -> None:
        self._binding = binding
        self._request_factory = request_factory

    async def transcribe(
        self, *, body: dict[str, Any], product_id: str, session_id: str
    ) -> tuple[int, bytes]:
        request = self._request_factory(
            STT_INTERNAL_ORIGIN + STT_TRANSCRIBE_PATH,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                CALLER_PRODUCT_HEADER: product_id,
                CALLER_SESSION_HEADER: session_id,
            },
            body=json.dumps(body, ensure_ascii=False),
        )
        response = await self._binding.fetch(request.js_object)
        status = int(response.status)
        raw = await read_bounded_service_binding_body(
            response, max_bytes=_MAX_RESPONSE_BYTES
        )
        return status, raw

    async def live_token(
        self, *, body: dict[str, Any], product_id: str, session_id: str
    ) -> tuple[int, bytes]:
        """Ask the private STT Worker for one ephemeral Live token.

        The long-lived provider key never leaves the STT Worker. Only the
        short-lived, model-locked token travels, and only to the authenticated
        browser that asked for it over the same origin.
        """
        request = self._request_factory(
            STT_INTERNAL_ORIGIN + STT_LIVE_TOKEN_PATH,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                CALLER_PRODUCT_HEADER: product_id,
                CALLER_SESSION_HEADER: session_id,
            },
            body=json.dumps(body, ensure_ascii=False),
        )
        response = await self._binding.fetch(request.js_object)
        status = int(response.status)
        raw = await read_bounded_service_binding_body(
            response, max_bytes=_MAX_RESPONSE_BYTES
        )
        return status, raw