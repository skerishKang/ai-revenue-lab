"""#7078: bounded login helper for production checks.

KEEP THIS MODULE NETWORK-FREE AT IMPORT TIME. The live checks call
``login_session_cookie``; tests import it only for its closed parsing helpers.

Order:
1. Try the existing Chat direct email login. With the migration switch OFF this
   is byte-for-byte the old behaviour.
2. If the server answers 409 ``email_login_moved``, follow the common login
   form at ``login_url`` with the QA email/password and return the Chat session
   cookie the shared callback issues.

No credential, cookie, email or response header is printed. Errors carry a
closed public code only.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

SESSION_COOKIE = "padiem_session"
LOGIN_PATH = "/api/auth/password/login"
SHARED_START_PATH = "/auth/shared/start"
RESPONSE_BYTES_CAP = 200_000
REQUEST_TIMEOUT_SECONDS = 25
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,80}$")
_FORM_ACTION = re.compile(
    r"""<form\b[^>]*\baction\s*=\s*["']([^"']*/login/password\?state=[^"']+)["']""",
    re.IGNORECASE,
)


class SharedLoginError(Exception):
    def __init__(self, public_code: str):
        code = public_code if _SAFE_CODE.fullmatch(public_code) else "shared_login_failed"
        super().__init__(code)
        self.public_code = code


def _read_bounded(response) -> bytes:
    body = response.read(RESPONSE_BYTES_CAP + 1)
    if len(body) > RESPONSE_BYTES_CAP:
        raise SharedLoginError("shared_login_response_too_large")
    return body


def _session_from_set_cookie(raw: str) -> str | None:
    if not raw:
        return None
    for part in raw.split(";"):
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            candidate = value.strip()
            return candidate or None
    return None


def _session_from_jar(jar: http.cookiejar.CookieJar) -> str | None:
    for cookie in jar:
        if cookie.name == SESSION_COOKIE and cookie.value:
            return cookie.value
    return None


def _json_or_empty(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _error_code(payload: dict) -> str:
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _SAFE_CODE.fullmatch(code) else "unknown"


def _direct_login(origin: str, username: str, password: str, timeout: int) -> tuple[int, dict, str | None]:
    body = json.dumps(
        {"identifier": username, "password": password},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        origin.rstrip("/") + LOGIN_PATH,
        method="POST",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": origin.rstrip("/"),
            "Referer": origin.rstrip("/") + "/",
            "User-Agent": "PADIEM-7078-login-helper/1.0",
            "Cache-Control": "no-store",
        },
    )
    try:
        with build_opener().open(request, timeout=timeout) as response:
            return response.status, _json_or_empty(_read_bounded(response)), _session_from_set_cookie(
                response.headers.get("set-cookie", "")
            )
    except HTTPError as err:
        return err.code, _json_or_empty(_read_bounded(err)), _session_from_set_cookie(
            err.headers.get("set-cookie", "") if err.headers else ""
        )
    except (TimeoutError, URLError, OSError) as exc:
        raise SharedLoginError("login_transport_unavailable") from exc


def shared_login_form_action(html: str, page_url: str) -> str | None:
    """Return the absolute email-form action on the common login page."""
    match = _FORM_ACTION.search(html or "")
    if match is None:
        return None
    action = match.group(1)
    return urljoin(page_url, action)


def shared_login_session_cookie(
    origin: str,
    username: str,
    password: str,
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Follow the common login flow and return the Chat session cookie."""
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    start_url = origin.rstrip("/") + SHARED_START_PATH
    try:
        with opener.open(
            Request(start_url, headers={"Accept": "text/html", "Cache-Control": "no-store"}),
            timeout=timeout,
        ) as page:
            page_url = page.geturl()
            html = _read_bounded(page).decode("utf-8", "replace")
    except (TimeoutError, URLError, OSError) as exc:
        raise SharedLoginError("shared_login_unreachable") from exc
    action = shared_login_form_action(html, page_url)
    if not action:
        raise SharedLoginError("shared_login_form_missing")
    form = urlencode({"email": username, "password": password}).encode("utf-8")
    try:
        with opener.open(
            Request(
                action,
                method="POST",
                data=form,
                headers={
                    "Accept": "text/html",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cache-Control": "no-store",
                },
            ),
            timeout=timeout,
        ) as response:
            _read_bounded(response)
    except HTTPError as err:
        # A bounded HTML error page is still a failed login; do not echo it.
        _read_bounded(err)
        raise SharedLoginError("shared_login_refused") from err
    except (TimeoutError, URLError, OSError) as exc:
        raise SharedLoginError("shared_login_unreachable") from exc
    cookie = _session_from_jar(jar)
    if not cookie:
        raise SharedLoginError("shared_login_session_missing")
    return cookie


def login_session_cookie(
    origin: str,
    username: str,
    password: str,
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Direct email login, or the common login when the switch moved it."""
    status, payload, cookie = _direct_login(origin, username, password, timeout)
    if status == 200 and payload.get("ok") is True and cookie:
        return cookie
    if status == 409 and _error_code(payload) == "email_login_moved":
        return shared_login_session_cookie(origin, username, password, timeout=timeout)
    code = _error_code(payload) if status != 200 else "session_cookie_missing"
    raise SharedLoginError(f"login_refused_http_{status}_{code}")


__all__ = [
    "LOGIN_PATH",
    "SESSION_COOKIE",
    "SHARED_START_PATH",
    "SharedLoginError",
    "login_session_cookie",
    "shared_login_form_action",
    "shared_login_session_cookie",
]
