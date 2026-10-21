#!/usr/bin/env python3
"""Owner-authorized bounded B62 production QA: logout revokes the session (#5225).

Uses ONLY the pre-existing CGI Alpha QA identity from the protected GitHub
production environment. Does not print secrets, cookies, user identity,
conversation content or response headers. Creates no account, mutates no admin
model/tier authorization and calls no model, so the check costs no provider
budget.

What it proves, in one bounded pass:

* a login establishes a session that a protected Chat API accepts;
* the logout of that session succeeds;
* the cookie stored before the logout is then REFUSED by a protected Chat API;
* another session of the same account (a second device) keeps working;
* a fresh login after the logout works again.

Every verdict is a bounded PASS/FAIL code. A missing credential, an
unexpected transport error or an unexpected status is a BLOCK, never a PASS.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

ORIGIN = "https://chat.padiem.net"
LOGIN = "/api/auth/password/login"
LOGOUT = "/api/auth/logout"
STATUS = "/api/auth/status"
CONVERSATIONS = "/api/conversations"
SESSION_COOKIE = "padiem_session"
MAX_REQUESTS = 11
RESPONSE_BYTES_CAP = 200_000
REQUEST_TIMEOUT_SECONDS = 25
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,80}$")


class CanaryError(Exception):
    def __init__(self, public_code: str):
        super().__init__(public_code)
        self.public_code = public_code


def bounded_call(
    opener,
    path: str,
    *,
    method: str = "GET",
    payload=None,
    cookie: str | None = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
):
    """One bounded request. Never logs headers, cookies or bodies."""

    assert path.startswith("/") and not path.startswith("//")
    headers = {
        "Accept": "application/json",
        "User-Agent": "PADIEM-B62-owner-logout-reuse-check/1.0",
        "Cache-Control": "no-store",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Origin": ORIGIN, "Referer": ORIGIN + "/"})
    if cookie:
        headers["Cookie"] = f"{SESSION_COOKIE}={cookie}"
    request = Request(ORIGIN + path, method=method, data=data, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            raw_set_cookie = response.headers.get("set-cookie", "")
            body = response.read(RESPONSE_BYTES_CAP + 1)
    except HTTPError as err:
        status = err.code
        raw_set_cookie = err.headers.get("set-cookie", "") if err.headers else ""
        body = err.read(RESPONSE_BYTES_CAP + 1)
    except (TimeoutError, URLError, OSError) as exc:
        raise CanaryError("http_transport_unavailable") from exc
    if len(body) > RESPONSE_BYTES_CAP:
        raise CanaryError("http_response_exceeds_qa_guard")
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        decoded = {}
    if not isinstance(decoded, dict):
        decoded = {}
    return status, decoded, _session_cookie_value(raw_set_cookie)


def _session_cookie_value(raw_set_cookie: str) -> str | None:
    """Read the issued session cookie value in memory only. Never printed."""

    if not raw_set_cookie:
        return None
    for part in raw_set_cookie.split(";"):
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            candidate = value.strip()
            return candidate or None
    return None


def error_code(payload) -> str:
    value = payload.get("error", {})
    code = value.get("code") if isinstance(value, dict) else None
    return code if isinstance(code, str) and _CODE.fullmatch(code) else "no_safe_error_code"


def run() -> int:
    username = os.environ.get("B66_CGI_ALPHA_USERNAME", "")
    password = os.environ.get("B66_CGI_ALPHA_PASSWORD", "")
    if not username or not password:
        print("B62_LOGOUT_REUSE_CHECK=BLOCKED_NO_APPROVED_QA_CREDENTIAL")
        return 3
    # No cookie processor: every request carries exactly the cookie this check
    # wants to prove something about, and the issued session cookie is read
    # from the response header in memory only.
    opener = build_opener()
    try:
        # 1. Two independent logins of the same account: the first session and a
        #    second "device" session. Both are normal, unaffected logins.
        status, body, device_a = bounded_call(
            opener, LOGIN, method="POST",
            payload={"identifier": username, "password": password},
        )
        if status != 200 or body.get("ok") is not True or not device_a:
            print("B62_LOGOUT_REUSE_LOGIN_A=FAILED", "HTTP=" + str(status))
            return 4
        status, body, device_b = bounded_call(
            opener, LOGIN, method="POST",
            payload={"identifier": username, "password": password},
        )
        if status != 200 or body.get("ok") is not True or not device_b:
            print("B62_LOGOUT_REUSE_LOGIN_B=FAILED", "HTTP=" + str(status))
            return 4
        if device_a == device_b:
            print("B62_LOGOUT_REUSE_LOGIN_B=FAILED", "REASON=IDENTICAL_SESSION")
            return 4
        print("B62_LOGOUT_REUSE_TWO_SESSIONS=PASS")

        # 2. The first session works before the logout.
        status, body, _ = bounded_call(opener, CONVERSATIONS, cookie=device_a)
        if status != 200:
            print("B62_LOGOUT_REUSE_PRE_LOGIN_PROTECTED_API=FAILED", "HTTP=" + str(status))
            return 5
        print("B62_LOGOUT_REUSE_PRE_LOGIN_PROTECTED_API=PASS")

        # 3. The logout of that one session succeeds.
        status, body, _ = bounded_call(opener, LOGOUT, method="POST", payload={}, cookie=device_a)
        if status != 200 or body.get("ok") is not True:
            print("B62_LOGOUT_REUSE_LOGOUT=FAILED", "HTTP=" + str(status), "CODE=" + error_code(body))
            return 6
        print("B62_LOGOUT_REUSE_LOGOUT=PASS")

        # 4. The cookie stored before the logout must be refused now.
        status, body, _ = bounded_call(opener, CONVERSATIONS, cookie=device_a)
        if status != 401:
            print("B62_LOGOUT_REUSE_STORED_COOKIE_REFUSED=FAILED", "HTTP=" + str(status))
            return 7
        print("B62_LOGOUT_REUSE_STORED_COOKIE_REFUSED=PASS", "CODE=" + error_code(body))

        # 5. The second device session of the same account keeps working.
        status, body, _ = bounded_call(opener, CONVERSATIONS, cookie=device_b)
        if status != 200:
            print("B62_LOGOUT_REUSE_OTHER_SESSION_KEPT=FAILED", "HTTP=" + str(status))
            return 8
        print("B62_LOGOUT_REUSE_OTHER_SESSION_KEPT=PASS")

        # 6. A fresh login after the logout works again.
        status, body, device_c = bounded_call(
            opener, LOGIN, method="POST",
            payload={"identifier": username, "password": password},
        )
        if status != 200 or body.get("ok") is not True or not device_c:
            print("B62_LOGOUT_REUSE_RELOGIN=FAILED", "HTTP=" + str(status))
            return 9
        status, body, _ = bounded_call(opener, STATUS, cookie=device_c)
        if status != 200 or body.get("authenticated") is not True:
            print("B62_LOGOUT_REUSE_RELOGIN=FAILED", "REASON=STATUS_NOT_AUTHENTICATED")
            return 9
        print("B62_LOGOUT_REUSE_RELOGIN=PASS")

        # 7. Leave no live session of this QA account behind.
        for index, cookie in enumerate((device_b, device_c)):
            try:
                status, _, _ = bounded_call(opener, LOGOUT, method="POST", payload={}, cookie=cookie)
                print("B62_LOGOUT_REUSE_CLEANUP_" + str(index) + "=" + ("PASS" if status == 200 else "NEEDS_REVIEW"))
            except CanaryError:
                print("B62_LOGOUT_REUSE_CLEANUP_" + str(index) + "=NEEDS_REVIEW")

        print("B62_LOGOUT_REUSE_LIVE_ACCEPTANCE=PASS")
        return 0
    except CanaryError as exc:
        print("B62_LOGOUT_REUSE_CHECK_ERROR=" + exc.public_code)
        print("B62_LOGOUT_REUSE_LIVE_ACCEPTANCE=FAILED")
        return 10
    finally:
        print("B62_QA_PASSWORD_OR_COOKIE_LOGGED=0")
        print("B62_QA_CUSTOMER_DATA_OR_RAW_RESPONSE_LOGGED=0")


class _FakeResponse:
    """Minimal offline response double for the source-only contract test."""

    def __init__(self, status: int, body: bytes, set_cookie: str = ""):
        self.status = status
        self._body = body
        self.headers = {"set-cookie": set_cookie}

    def read(self, _limit: int) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _FakeOpener:
    """Records the requests this check would send and replays fixed responses."""

    def __init__(self, status: int, body: dict, set_cookie: str = ""):
        self.status = status
        self.body = body
        self.set_cookie = set_cookie
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: int | None = None):
        self.requests.append(request)
        return _FakeResponse(
            self.status,
            json.dumps(self.body).encode("utf-8"),
            self.set_cookie,
        )


def self_test() -> int:
    assert ORIGIN == "https://chat.padiem.net"
    assert SESSION_COOKIE == "padiem_session"
    assert MAX_REQUESTS == 11
    assert REQUEST_TIMEOUT_SECONDS < 60
    assert error_code({"error": {"code": "unauthorized"}}) == "unauthorized"
    assert error_code({"error": {"code": "bad\ncode"}}) == "no_safe_error_code"
    assert _session_cookie_value("padiem_session=abc; Path=/; HttpOnly") == "abc"
    assert _session_cookie_value("other=1; Path=/") is None
    assert _session_cookie_value("") is None

    # The request path itself is exercised offline: a wrong opener, a missing
    # cookie header or a missing Origin on a mutation would break the live
    # check, so the source-only contract proves them here.
    opener = _FakeOpener(200, {"ok": True}, "padiem_session=issued; Path=/; HttpOnly")
    status, body, cookie = bounded_call(
        opener, LOGIN, method="POST", payload={"identifier": "qa", "password": "secret"}
    )
    assert status == 200 and body.get("ok") is True and cookie == "issued"
    sent = opener.requests[0]
    assert sent.get_method() == "POST"
    assert sent.get_header("Origin") == ORIGIN
    assert sent.get_header("Content-type") == "application/json"

    opener = _FakeOpener(200, {"ok": True})
    status, _, _ = bounded_call(opener, CONVERSATIONS, cookie="stored")
    assert status == 200
    assert opener.requests[0].get_header("Cookie") == "padiem_session=stored"
    assert opener.requests[0].get_header("Origin") is None

    print("B62_LOGOUT_REUSE_CANARY_SOURCE=PASS")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    if sys.argv[1:] != ["--authorized-live"]:
        print("B62_LOGOUT_REUSE_DEFAULT_LIVE_EXECUTION=BLOCKED")
        sys.exit(2)
    sys.exit(run())
