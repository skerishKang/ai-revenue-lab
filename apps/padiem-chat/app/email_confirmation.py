"""Signed mail port for the shared login's optional email confirmation (#7679).

After an email signup padiem-auth may ask Chat to mail one "is this address
yours" link. Chat owns the mail channel and nothing else here: it mints the
link, hands it to the existing transactional delivery and answers with a
digest of the token. No row is written and the token is never logged or
returned; padiem-auth keeps the digest and decides what a confirmed address
means. The route does not exist unless its own switch is on.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time

from starlette.responses import JSONResponse

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .password_auth import PasswordAuthError, normalize_email
from .password_reset import PASSWORD_RESET_TOKEN_BYTES
from .password_rpc import _consume_service_id, _verify_service_proof

EMAIL_CONFIRMATION_PATH = "/internal/email-confirmation/send"
CONFIRMATION_LINK = "https://auth.padiem.net/email/confirm#token="
_DIGEST_DOMAIN = "padiem-email-confirmation:v1\0"
_LOG = logging.getLogger(__name__)

_MAIL = {
    "ko": (
        "[PADIEM] 이메일 확인",
        "안녕하세요.\n\n"
        "이 이메일로 PADIEM 계정에 가입하셨습니다.\n"
        "본인이 맞으면 아래 링크를 열고 버튼을 눌러 주세요.\n\n"
        "{link}\n\n"
        "- 누르지 않아도 계정은 그대로 쓸 수 있습니다.\n"
        "- 이 링크는 7일 동안 한 번만 쓸 수 있습니다.\n"
        "- 가입한 적이 없으면 이 메일을 무시해 주세요.\n",
    ),
    "en": (
        "[PADIEM] Confirm your email",
        "Hello.\n\n"
        "A PADIEM account was created with this email address.\n"
        "If that was you, open the link below and press the button.\n\n"
        "{link}\n\n"
        "- Your account keeps working even if you do not.\n"
        "- The link works once, for 7 days.\n"
        "- If you did not sign up, please ignore this message.\n",
    ),
}


def confirmation_token_digest(token: str) -> str:
    """The digest padiem-auth stores and recomputes when the link is used."""
    return hashlib.sha256((_DIGEST_DOMAIN + token).encode("utf-8")).hexdigest()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status,
                        headers={"cache-control": "no-store"})


def _answer(value: dict) -> JSONResponse:
    return JSONResponse(value, headers={"cache-control": "no-store"})


async def email_confirmation_rpc(request) -> JSONResponse:
    settings = getattr(request.app.state, "settings", None)
    secret = getattr(settings, "password_rpc_secret", None)
    store = getattr(request.app.state, "history_store", None)
    if (getattr(settings, "email_confirmation_enabled", False) is not True
            or request.url.path != EMAIL_CONFIRMATION_PATH
            or not isinstance(secret, str) or len(secret) < 32 or store is None):
        return _error(404, "not_found", "not found")
    if request.method != "POST":
        return _error(405, "method_not_allowed", "method not allowed")
    try:
        body = await read_bounded_request_body(request, max_bytes=512)
    except RequestBodyTooLarge:
        return _error(401, "unauthorized", "unauthorized")
    verified = _verify_service_proof(headers=request.headers, path=request.url.path, body=body,
                                     secret=secret, now_epoch=int(time.time()))
    if verified is None:
        return _error(401, "unauthorized", "unauthorized")
    try:
        if not await _consume_service_id(store, verified["service_id"], verified["at"]):
            return _error(409, "rpc_replay_detected", "replayed service id")
    except Exception:
        _LOG.warning("email_confirmation reason=storage_failed")
        return _error(503, "email_confirmation_unavailable", "confirmation mail unavailable")
    payload = verified["payload"]
    if not isinstance(payload, dict) or set(payload) != {"email", "lang"} or payload["lang"] not in _MAIL:
        return _error(400, "invalid_request", "invalid request body")
    try:
        email = normalize_email(payload["email"])
    except PasswordAuthError:
        return _error(400, "invalid_request", "invalid request body")
    delivery = getattr(request.app.state, "password_reset_delivery", None)
    if delivery is None:
        _LOG.warning("email_confirmation reason=delivery_unconfigured")
        return _answer({"ok": False})
    token = secrets.token_urlsafe(PASSWORD_RESET_TOKEN_BYTES)
    subject, text = _MAIL[payload["lang"]]
    try:
        sent = await delivery.send(to=email, subject=subject, text=text.format(link=CONFIRMATION_LINK + token))
    except Exception:
        sent = False
    if not sent:
        _LOG.warning("email_confirmation reason=delivery_failed")
        return _answer({"ok": False})
    # Only the digest leaves this function; the link exists in the mail alone.
    return _answer({"ok": True, "token_digest": confirmation_token_digest(token)})
