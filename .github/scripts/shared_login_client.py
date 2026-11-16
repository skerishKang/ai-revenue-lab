"""#7078: bounded login helper for production checks.

KEEP THIS MODULE NETWORK-FREE AT IMPORT TIME. The live checks call
``login_session_cookie``; tests import it only for its closed parsing helpers.

Order:
1. Try the existing Chat direct email login. With the migration switch OFF this
   is byte-for-byte the old behaviour.
2. If the server answers 409 ``email_login_moved``, follow the common login
   form at ``login_url`` with the QA email/password and return the Chat session
   cookie the shared callback issues.
3. #7853 follow-up: an account created before the age gate answers that form
   with the one-time 만 14세 확인 screen instead of the service redirect. The QA
   helpers confirm it once for their own account and continue; a second screen
   for the same login is a refusal of its own (``shared_login_age_confirm_loop``).

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
#: auth.padiem.net answers 1010 to the default Python-urllib signature.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# The optional tail carries the closed ``stage.code`` from the Chat retry
# header; both parts are allow-listed before a code is built.
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,80}(\.[a-z][a-z0-9_]{0,80}){0,2}$")
_FORM_ACTION = re.compile(
    r"""<form\b[^>]*\baction\s*=\s*["']([^"']*/login/password\?state=[^"']+)["']""",
    re.IGNORECASE,
)
#: #7853: the one-time age screen a pre-gate account gets at login. The form
#: carries an opaque ``handle`` and the browser cookie the gate parked the
#: login with; submitting it resumes the same flow.
AGE_CONFIRM_PATH = "/age-confirm/password"
_AGE_CONFIRM_ACTION = re.compile(
    r"""<form\b[^>]*\baction\s*=\s*["']([^"']*/age-confirm/password[^"']*)["']""",
    re.IGNORECASE,
)
_AGE_CONFIRM_FIELD = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"""\b([a-z_]+)\s*=\s*["']([^"']*)["']""", re.IGNORECASE)

#: The Chat retry-page header carries only these closed values; the client
#: mirrors them so an unknown value never becomes a failure reason.
_LOGIN_CODE_STAGES = frozenset({
    "validate_flow", "client_assertion", "exchange", "resolve_account",
    "provision_profile", "issue_session",
})
_LOGIN_CODE_CODES = frozenset({
    "invalid_flow", "invalid_cookie", "invalid_state", "invalid_exchange", "invalid_grant",
    "state_cookie_missing", "state_expired", "state_mismatch",
    "unknown_account", "invalid_session_response", "invalid_es256_signature",
    "invalid_key", "invalid_token_endpoint", "exchange_failed",
    "exchange_response_too_large", "exchange_invalid_response",
    "invalid_shared_credential", "invalid_verified_claims", "missing_product_link",
    "reverse_lookup_failed", "reverse_lookup_invalid", "shared_auth_failed",
    "invalid_encoding", "invalid_token", "invalid_header", "unknown_key",
    "invalid_signature", "invalid_claims", "token_not_yet_valid", "token_expired",
    "jwks_unavailable", "jwks_too_large",
    "invalid_jwks", "control_plane_identity_unavailable", "control_plane_rpc_invalid",
    "canonical_product_identity_link_not_found",
    "canonical_product_identity_link_not_active", "identity_authority_storage_error",
    "identity_authority_product_mismatch", "profile_store_unavailable",
    "service_rpc_unauthorized", "service_rpc_forbidden", "service_rpc_not_found",
    "service_rpc_replay_rejected", "service_rpc_rate_limited", "service_rpc_http_failed",
    "invalid_profile_response", "profile_account_mismatch", "invalid_profile",
    "legacy_account_conflict",
}) | frozenset(name + "_failed" for name in _LOGIN_CODE_STAGES)
_LOGIN_CODE_HEADER = "x-padiem-login-code"


def _login_code_suffix(headers) -> str:
    """The closed failure-reason suffix for a refusal, without any body text."""
    raw = headers.get(_LOGIN_CODE_HEADER) if headers is not None else None
    if not raw:
        return "_noheader"
    stage, _, code = raw.partition(".")
    if stage in _LOGIN_CODE_STAGES and code in _LOGIN_CODE_CODES and "." not in code:
        return "." + raw
    return "_unknownheader"


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


def shared_age_confirm_form(html: str, page_url: str) -> tuple[str, dict[str, str]] | None:
    """The (absolute action, hidden fields) of the age screen, or None.

    The screen posts an opaque ``handle`` and its cosmetic hidden fields back
    to its own action; only those are carried, so nothing the page shows as
    text is trusted and a page without a handle is not this gate.
    """
    form = _AGE_CONFIRM_ACTION.search(html or "")
    if form is None:
        return None
    fields: dict[str, str] = {}
    for tag in _AGE_CONFIRM_FIELD.findall(html or ""):
        attributes = {name.lower(): value for name, value in _ATTRIBUTE.findall(tag)}
        if attributes.get("type", "").lower() != "hidden":
            continue
        name = attributes.get("name", "")
        if name and name != "age_confirm":
            fields[name] = attributes.get("value", "")
    if not fields.get("handle"):
        return None
    return urljoin(page_url, form.group(1)), fields


def _submit_age_confirm(opener, action: str, fields: dict[str, str], timeout: int) -> tuple[str, str]:
    """Answer the age screen once and return the (body, url) it answers with."""
    form = urlencode({**fields, "age_confirm": "yes"}).encode("utf-8")
    request = Request(
        action,
        method="POST",
        data=form,
        headers={
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-store",
            "User-Agent": _BROWSER_UA,
        },
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return _read_bounded(response).decode("utf-8", "replace"), response.geturl()
    except HTTPError as err:
        _read_bounded(err)
        raise SharedLoginError(
            f"shared_login_age_confirm_refused_http_{err.code}{_login_code_suffix(err.headers)}"
        ) from err
    except (TimeoutError, URLError, OSError) as exc:
        raise SharedLoginError("shared_login_unreachable") from exc


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
            Request(start_url, headers={
                "Accept": "text/html",
                "Cache-Control": "no-store",
                "User-Agent": _BROWSER_UA,
            }),
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
                    "User-Agent": _BROWSER_UA,
                },
            ),
            timeout=timeout,
        ) as response:
            page_url = response.geturl()
            html = _read_bounded(response).decode("utf-8", "replace")
    except HTTPError as err:
        # A bounded HTML error page is still a failed login; do not echo it.
        # The status is a closed number, so it can name the refusal (429 throttle,
        # 503 unavailable) without carrying a value. The Chat retry page also
        # names the finish stage in a closed header; only a value from the
        # closed list is appended, and its absence stays distinguishable.
        _read_bounded(err)
        raise SharedLoginError(
            f"shared_login_refused_http_{err.code}{_login_code_suffix(err.headers)}"
        ) from err
    except (TimeoutError, URLError, OSError) as exc:
        raise SharedLoginError("shared_login_unreachable") from exc
    gate = shared_age_confirm_form(html, page_url)
    if gate is not None:
        # #7853 follow-up: a pre-gate account is asked once. Answer with the
        # handle and hidden fields the screen parked the login under and let
        # the same flow run to the callback; only a screen that comes back
        # after that answer is a loop.
        html, page_url = _submit_age_confirm(opener, gate[0], gate[1], timeout)
        if shared_age_confirm_form(html, page_url) is not None:
            raise SharedLoginError("shared_login_age_confirm_loop")
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
    "AGE_CONFIRM_PATH",
    "LOGIN_PATH",
    "SESSION_COOKIE",
    "SHARED_START_PATH",
    "SharedLoginError",
    "login_session_cookie",
    "shared_age_confirm_form",
    "shared_login_form_action",
    "shared_login_session_cookie",
]
