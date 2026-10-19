"""Android 1.0.1 sign-in return contract (web-only).

Android 1.0.0 keeps `chat.padiem.net` in a WebView and opens the Google page in
the device's external browser. The external browser has neither the WebView's
OAuth state cookie nor any way to hand its own session cookie back. This module
adds the smallest server-side return path that does not change the Android app:

1. The WebView creates a one-time handoff and receives a claim secret plus an
   eight-character code. The secret never appears in a URL; the code is shown to
   the user.
2. The WebView opens Google with a *signed stateless* handoff state. The
   external browser can complete Google because that state is verified by its
   signature, not by a cookie the browser never had.
3. The callback binds the verified Google profile to the handoff and asks the
   user for the code shown in the app. A valid OAuth state alone never yields a
   session, so a victim who completes an attacker's Google link cannot hand the
   attacker a session.
4. The WebView polls with its claim secret and claims exactly once. The claim
   issues the existing `padiem_session` token for the existing `users` row.

No second account, session, owner-scope, or identity authority is introduced.
The standard cookie-bound `/auth/google/start` flow is untouched.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .android_auth_store import (
    AndroidAuthHandoffStore,
    AndroidHandoffRecord,
    HANDOFF_STATUS_AWAITING_CONFIRMATION,
    HANDOFF_STATUS_AWAITING_LOGIN,
    HANDOFF_STATUS_CANCELLED,
    HANDOFF_STATUS_CLAIMED,
    HANDOFF_STATUS_READY,
    TERMINAL_HANDOFF_STATUSES,
)
from .auth import (
    SESSION_COOKIE,
    AuthError,
    create_android_handoff_state,
    create_session_token,
    is_android_handoff_id,
    session_cookie_kwargs,
    verify_android_handoff_state,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .config import Settings

ANDROID_HANDOFF_TTL_SECONDS = 600
ANDROID_HANDOFF_CONFIRM_ATTEMPTS = 10
ANDROID_HANDOFF_SECRET_HEADER = "X-Padiem-Handoff-Secret"
_ANDROID_HANDOFF_MAX_CONFIRM_BODY_BYTES = 8 * 1024
_ANDROID_HANDOFF_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_ANDROID_HANDOFF_CODE_LENGTH = 8
_ANDROID_HANDOFF_SECRET_MIN_CHARS = 16
_ANDROID_HANDOFF_SECRET_MAX_CHARS = 128

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _store(request: Request) -> AndroidAuthHandoffStore | None:
    return getattr(request.app.state, "android_handoff_store", None)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _expires_in(record: AndroidHandoffRecord) -> int:
    expires_at = _parse_iso(record.expires_at)
    if expires_at is None:
        return 0
    return max(0, int((expires_at - _now()).total_seconds()))


def _digest(settings: Settings, purpose: str, value: str) -> str:
    secret = settings.session_secret or ""
    return hmac.new(
        secret.encode("utf-8"),
        purpose.encode("ascii") + b"\x00" + value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _hash_claim_secret(settings: Settings, claim_secret: str) -> str:
    return _digest(settings, "padiem-chat/android-handoff-secret/v1", claim_secret)


def _hash_user_code(settings: Settings, handoff_id: str, user_code: str) -> str:
    return _digest(settings, "padiem-chat/android-handoff-code/v1", handoff_id + "\x00" + user_code)


def _generate_user_code() -> str:
    raw = "".join(secrets.choice(_ANDROID_HANDOFF_CODE_ALPHABET) for _ in range(_ANDROID_HANDOFF_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def _canonical_code(value: str) -> str:
    return "".join(character for character in value.upper() if character in _ANDROID_HANDOFF_CODE_ALPHABET)


def _normalize_user_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _canonical_code(value)
    return normalized if len(normalized) == _ANDROID_HANDOFF_CODE_LENGTH else None


def _json_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=_NO_STORE_HEADERS)


def _header_value(request: Request, name: str, *, maximum: int) -> str | None:
    value = request.headers.get(name)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > maximum:
        return None
    return value


def _form_value(values: Mapping[str, list[str]], name: str, *, maximum: int) -> str | None:
    items = values.get(name)
    if not isinstance(items, list) or not items:
        return None
    value = items[0]
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    return value


def _bearer_record_match(record: AndroidHandoffRecord, supplied_hash: str) -> bool:
    return hmac.compare_digest(record.secret_hash, supplied_hash)


async def _authorized_record(request: Request) -> tuple[AndroidHandoffRecord | None, JSONResponse | None]:
    settings = _settings(request)
    store = _store(request)
    if not settings.session_secret or store is None:
        return None, _json_error(
            503, "android_handoff_unavailable", "앱 로그인을 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
        )
    handoff_id = request.path_params.get("handoff_id")
    if not is_android_handoff_id(handoff_id):
        return None, _json_error(404, "android_handoff_not_found", "로그인 요청을 찾을 수 없습니다.")
    claim_secret = _header_value(
        request,
        ANDROID_HANDOFF_SECRET_HEADER,
        maximum=_ANDROID_HANDOFF_SECRET_MAX_CHARS,
    )
    if claim_secret is None or len(claim_secret) < _ANDROID_HANDOFF_SECRET_MIN_CHARS:
        return None, _json_error(404, "android_handoff_not_found", "로그인 요청을 찾을 수 없습니다.")
    try:
        record = await store.get(handoff_id)
    except Exception:
        return None, _json_error(
            503, "android_handoff_unavailable", "앱 로그인을 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
        )
    if record is None or not _bearer_record_match(record, _hash_claim_secret(settings, claim_secret)):
        return None, _json_error(404, "android_handoff_not_found", "로그인 요청을 찾을 수 없습니다.")
    return record, None


async def android_handoff_create(request: Request) -> Response:
    settings = _settings(request)
    store = _store(request)
    oauth = getattr(request.app.state, "google_oauth", None)
    if not settings.session_secret or store is None or oauth is None:
        return _json_error(
            503, "android_handoff_unavailable", "앱 로그인을 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
        )
    handoff_id = "aho_" + secrets.token_urlsafe(24)
    claim_secret = secrets.token_urlsafe(32)
    user_code = _generate_user_code()
    now = _now()
    expires_at = now + timedelta(seconds=ANDROID_HANDOFF_TTL_SECONDS)
    try:
        state = create_android_handoff_state(settings, handoff_id)
        authorization_url = oauth.authorization_url(state)
        await store.create(
            handoff_id=handoff_id,
            secret_hash=_hash_claim_secret(settings, claim_secret),
            code_hash=_hash_user_code(settings, handoff_id, _canonical_code(user_code)),
            now_iso=_iso(now),
            expires_at_iso=_iso(expires_at),
        )
    except AuthError as exc:
        return _json_error(exc.status_code, exc.code, exc.user_message)
    except Exception:
        return _json_error(
            503, "android_handoff_unavailable", "앱 로그인을 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
        )
    return JSONResponse(
        {
            "handoff_id": handoff_id,
            "claim_secret": claim_secret,
            "user_code": user_code,
            "authorization_url": authorization_url,
            "expires_in": ANDROID_HANDOFF_TTL_SECONDS,
        },
        headers=_NO_STORE_HEADERS,
    )


async def android_handoff_status(request: Request) -> Response:
    record, error = await _authorized_record(request)
    if error is not None or record is None:
        return error or _json_error(404, "android_handoff_not_found", "로그인 요청을 찾을 수 없습니다.")
    now_iso = _now_iso()
    if record.status == HANDOFF_STATUS_CLAIMED:
        status = HANDOFF_STATUS_CLAIMED
    elif record.status == HANDOFF_STATUS_CANCELLED:
        status = HANDOFF_STATUS_CANCELLED
    elif record.is_expired(now_iso):
        status = "expired"
    else:
        status = record.status
    return JSONResponse(
        {"status": status, "expires_in": _expires_in(record)},
        headers=_NO_STORE_HEADERS,
    )


async def android_handoff_claim(request: Request) -> Response:
    record, error = await _authorized_record(request)
    if error is not None or record is None:
        return error or _json_error(404, "android_handoff_not_found", "로그인 요청을 찾을 수 없습니다.")
    settings = _settings(request)
    store = _store(request)
    if store is None:
        return _json_error(503, "android_handoff_unavailable", "앱 로그인을 현재 사용할 수 없습니다.")
    now_iso = _now_iso()
    if record.is_expired(now_iso):
        return _json_error(410, "android_handoff_expired", "로그인 시간이 만료되었습니다. 앱에서 다시 시도해 주세요.")
    if record.status == HANDOFF_STATUS_CLAIMED:
        return _json_error(409, "android_handoff_claimed", "이미 사용된 로그인입니다. 앱에서 다시 시도해 주세요.")
    if record.status == HANDOFF_STATUS_CANCELLED:
        return _json_error(410, "android_handoff_expired", "로그인 시간이 만료되었습니다. 앱에서 다시 시도해 주세요.")
    if record.status != HANDOFF_STATUS_READY:
        return _json_error(409, "android_handoff_pending", "로그인이 아직 확인되지 않았습니다.")
    claim_secret = _header_value(
        request,
        ANDROID_HANDOFF_SECRET_HEADER,
        maximum=_ANDROID_HANDOFF_SECRET_MAX_CHARS,
    )
    if claim_secret is None:
        return _json_error(404, "android_handoff_not_found", "로그인 요청을 찾을 수 없습니다.")
    try:
        user_id = await store.claim(
            record.handoff_id,
            secret_hash=_hash_claim_secret(settings, claim_secret),
            now_iso=now_iso,
        )
    except Exception:
        return _json_error(
            503, "android_handoff_unavailable", "앱 로그인을 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
        )
    if user_id is None:
        return _json_error(409, "android_handoff_claimed", "이미 사용된 로그인입니다. 앱에서 다시 시도해 주세요.")
    try:
        session = create_session_token(settings, user_id, now=int(_now().timestamp()))
    except AuthError as exc:
        return _json_error(exc.status_code, exc.code, exc.user_message)
    response = JSONResponse({"authenticated": True}, headers=_NO_STORE_HEADERS)
    response.set_cookie(SESSION_COOKIE, session, **session_cookie_kwargs(settings))
    return response


_PAGE_STYLE = (
    "body{margin:0;padding:32px 20px;background:#0f1115;color:#f3f4f6;"
    "font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.55}"
    "main{max-width:420px;margin:0 auto}h1{font-size:22px;margin:0 0 12px}"
    "p{margin:0 0 14px;color:#c7cbd3}.en{font-size:13px;color:#8b93a1}"
    "form{margin:20px 0 0}label{display:block;font-weight:600;margin-bottom:8px}"
    "input{width:100%;box-sizing:border-box;padding:14px;border-radius:10px;"
    "border:1px solid #3b4252;background:#171a21;color:#f3f4f6;font-size:20px;"
    "letter-spacing:.12em;text-align:center;text-transform:uppercase}"
    "button{margin-top:14px;width:100%;padding:14px;border:0;border-radius:10px;"
    "background:#f3f4f6;color:#0f1115;font-size:16px;font-weight:700}"
    ".error{background:#3a1519;border:1px solid #7f2d36;color:#ffd7db;"
    "padding:12px;border-radius:10px;margin:0 0 16px}"
    ".note{font-size:13px;color:#8b93a1;margin-top:18px}"
)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    document = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\"><title>{html.escape(title)}</title>"
        f"<style>{_PAGE_STYLE}</style></head><body><main>{body}</main></body></html>"
    )
    return HTMLResponse(document, status_code=status, headers=_NO_STORE_HEADERS)


def android_handoff_confirm_page(
    state_token: str,
    *,
    error: str = "",
    attempts_left: int | None = None,
    status: int = 200,
) -> HTMLResponse:
    error_html = ""
    if error:
        error_html = f"<p class=\"error\" role=\"alert\">{html.escape(error)}</p>"
    attempts_html = ""
    if attempts_left is not None and attempts_left > 0:
        attempts_html = f"<p class=\"note\">남은 시도: {int(attempts_left)}회</p>"
    body = (
        "<h1>Padiem 앱 로그인 확인</h1>"
        "<p>Padiem 앱에 표시된 8자리 코드를 입력하세요.</p>"
        "<p class=\"en\">Enter the 8-character code shown in the Padiem app.</p>"
        f"{error_html}"
        "<form method=\"post\" action=\"/auth/android/confirm\">"
        f"<input type=\"hidden\" name=\"state\" value=\"{html.escape(state_token, quote=True)}\">"
        "<label for=\"user_code\">로그인 코드 / Sign-in code</label>"
        "<input id=\"user_code\" name=\"user_code\" type=\"text\" inputmode=\"text\" "
        "autocomplete=\"off\" autocapitalize=\"characters\" spellcheck=\"false\" "
        "maxlength=\"16\" required autofocus>"
        "<button type=\"submit\">확인 / Confirm</button>"
        "</form>"
        f"{attempts_html}"
        "<p class=\"note\">로그인을 시작한 앱으로 돌아가면 코드를 확인할 수 있습니다. "
        "이 창은 확인 후 닫아도 됩니다.</p>"
    )
    return _page("Padiem 로그인 확인", body, status)


def android_handoff_terminal_page(kind: str) -> HTMLResponse:
    pages = {
        "confirmed": (
            200,
            "로그인이 확인되었습니다.",
            "Padiem 앱으로 돌아가면 자동으로 로그인됩니다. 이 창은 닫아도 됩니다.",
        ),
        "ready": (
            200,
            "이미 로그인이 확인되었습니다.",
            "Padiem 앱으로 돌아가 주세요.",
        ),
        "used": (
            409,
            "이미 사용된 로그인입니다.",
            "Padiem 앱에서 다시 로그인해 주세요.",
        ),
        "expired": (
            410,
            "로그인 시간이 만료되었습니다.",
            "Padiem 앱에서 다시 로그인해 주세요.",
        ),
        "failed": (
            409,
            "로그인 요청을 완료하지 못했습니다.",
            "Padiem 앱에서 다시 로그인해 주세요.",
        ),
        "invalid": (
            400,
            "로그인 요청을 확인할 수 없습니다.",
            "Padiem 앱에서 다시 로그인해 주세요.",
        ),
        "unavailable": (
            503,
            "앱 로그인을 현재 사용할 수 없습니다.",
            "잠시 후 Padiem 앱에서 다시 시도해 주세요.",
        ),
    }
    status, title, detail = pages.get(kind, pages["invalid"])
    body = f"<h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p>"
    return _page(title, body, status)


async def load_android_handoff_for_callback(
    request: Request, state_token: str
) -> tuple[AndroidHandoffRecord | None, HTMLResponse | None]:
    """Resolve a signed handoff callback state to a live, unbound record.

    ``awaiting_login`` is returned so the caller can exchange the Google code and
    bind the verified profile. ``awaiting_confirmation`` is returned without a
    new exchange so a reload still renders the code form. Every other *valid*
    handoff state has a terminal page. A state that is not a handoff token at
    all returns ``(None, None)`` so the caller keeps its existing OAuth-state
    rejection contract instead of exposing a handoff-specific page.
    """
    settings = _settings(request)
    handoff_id = verify_android_handoff_state(settings, state_token)
    if handoff_id is None:
        return None, None
    store = _store(request)
    if not settings.session_secret or store is None:
        return None, android_handoff_terminal_page("unavailable")
    try:
        record = await store.get(handoff_id)
    except Exception:
        return None, android_handoff_terminal_page("unavailable")
    if record is None:
        return None, android_handoff_terminal_page("invalid")
    now_iso = _now_iso()
    if record.status in TERMINAL_HANDOFF_STATUSES:
        if record.status == HANDOFF_STATUS_CLAIMED:
            return None, android_handoff_terminal_page("used")
        return None, android_handoff_terminal_page("expired")
    if record.is_expired(now_iso):
        return None, android_handoff_terminal_page("expired")
    if record.status == HANDOFF_STATUS_READY:
        return None, android_handoff_terminal_page("ready")
    if record.status not in {HANDOFF_STATUS_AWAITING_LOGIN, HANDOFF_STATUS_AWAITING_CONFIRMATION}:
        return None, android_handoff_terminal_page("invalid")
    return record, None


async def bind_android_handoff_user(request: Request, handoff_id: str, user_id: str) -> bool:
    store = _store(request)
    if store is None:
        return False
    try:
        return await store.bind_user(handoff_id, user_id=user_id, now_iso=_now_iso())
    except Exception:
        return False


async def android_handoff_confirm(request: Request) -> Response:
    settings = _settings(request)
    store = _store(request)
    if not settings.session_secret or store is None:
        return android_handoff_terminal_page("unavailable")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        return android_handoff_terminal_page("invalid")
    try:
        raw = await read_bounded_request_body(
            request, max_bytes=_ANDROID_HANDOFF_MAX_CONFIRM_BODY_BYTES
        )
    except RequestBodyTooLarge:
        return android_handoff_terminal_page("invalid")
    try:
        values = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True, max_num_fields=16)
    except ValueError:
        return android_handoff_terminal_page("invalid")
    state_token = _form_value(values, "state", maximum=4096)
    if state_token is None:
        return android_handoff_terminal_page("invalid")
    handoff_id = verify_android_handoff_state(settings, state_token)
    if handoff_id is None:
        return android_handoff_terminal_page("invalid")
    try:
        record = await store.get(handoff_id)
    except Exception:
        return android_handoff_terminal_page("unavailable")
    if record is None:
        return android_handoff_terminal_page("invalid")
    now_iso = _now_iso()
    if record.status in TERMINAL_HANDOFF_STATUSES:
        return android_handoff_terminal_page(
            "used" if record.status == HANDOFF_STATUS_CLAIMED else "expired"
        )
    if record.is_expired(now_iso):
        return android_handoff_terminal_page("expired")
    if record.status == HANDOFF_STATUS_READY:
        return android_handoff_terminal_page("confirmed")
    if record.status != HANDOFF_STATUS_AWAITING_CONFIRMATION:
        return android_handoff_terminal_page("invalid")
    user_code = _normalize_user_code(_form_value(values, "user_code", maximum=32))
    if user_code is None:
        return android_handoff_confirm_page(
            state_token,
            error="로그인 코드를 확인해 주세요. 앱에 표시된 8자리 코드를 입력하세요.",
            attempts_left=ANDROID_HANDOFF_CONFIRM_ATTEMPTS - record.attempts,
            status=400,
        )
    try:
        confirmed = await store.confirm(
            handoff_id,
            code_hash=_hash_user_code(settings, handoff_id, user_code),
            now_iso=now_iso,
        )
    except Exception:
        return android_handoff_terminal_page("unavailable")
    if confirmed:
        return android_handoff_terminal_page("confirmed")
    try:
        attempts = await store.record_failed_attempt(
            handoff_id,
            maximum=ANDROID_HANDOFF_CONFIRM_ATTEMPTS,
            now_iso=now_iso,
        )
    except Exception:
        return android_handoff_terminal_page("unavailable")
    attempts_left = max(0, ANDROID_HANDOFF_CONFIRM_ATTEMPTS - attempts)
    if attempts_left <= 0:
        return android_handoff_terminal_page("expired")
    return android_handoff_confirm_page(
        state_token,
        error="코드가 일치하지 않습니다. 앱에 표시된 코드를 다시 확인하세요.",
        attempts_left=attempts_left,
        status=400,
    )


__all__ = [
    "ANDROID_HANDOFF_CONFIRM_ATTEMPTS",
    "ANDROID_HANDOFF_SECRET_HEADER",
    "ANDROID_HANDOFF_TTL_SECONDS",
    "android_handoff_claim",
    "android_handoff_confirm",
    "android_handoff_confirm_page",
    "android_handoff_create",
    "android_handoff_status",
    "android_handoff_terminal_page",
    "bind_android_handoff_user",
    "load_android_handoff_for_callback",
]
