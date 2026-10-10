#!/usr/bin/env python3
"""#3396: protected CGI alpha account, TWO isolated real Chromium logins, GET only.

Requires explicit exact-main GitHub production workflow dispatch. No quote writes,
no model calls, no screenshots, no credential/cookie/ID or raw response logging.
Both Chromium contexts have independent cookie jars; *each* logs in separately.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ORIGIN = "https://quick-quote-kr.pages.dev"
GUIDED = "/api/padiem/b66/guided-draft"
AUTH_LOGIN = "/api/padiem/auth/password/login"
AUTH_LOGOUT = "/api/padiem/auth/logout"
AUTHORIZED_POSTS = frozenset({AUTH_LOGIN, AUTH_LOGOUT})
MAX_LOGINS = 2
MAX_MODEL_POSTS = 0
MAX_PDF_POSTS = 0
PRODUCTION_ROW_MUTATIONS = 0
PASSIVE_MODE = True


class BoundedFailure(Exception):
    """Only fixed error classes are printed; never a browser exception body."""


def allow_http(method: str, url: str) -> bool:
    route = urlsplit(url)
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return True
    if method.upper() == "POST":
        return (route.scheme == "https" and route.netloc == "quick-quote-kr.pages.dev"
                and route.path in AUTHORIZED_POSTS)
    return False


def classify_state(data: object) -> str:
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise BoundedFailure("guided_read_not_ok")
    if "state" not in data:
        raise BoundedFailure("guided_state_missing")
    state = data["state"]
    if state is None:
        return "EMPTY"
    if (not isinstance(state, dict) or
            state.get("schema") != "b66.guided-draft.v1" or
            state.get("mode") != "guided"):
        raise BoundedFailure("guided_state_schema_invalid")
    return "PRESENT"


def api_snapshot(page) -> tuple[str, object]:
    # Work with arbitrary customer content only in-memory. Never echo payload.
    response = page.evaluate(
        """async () => {
          const r = await fetch('/api/padiem/b66/guided-draft', {
            method:'GET', credentials:'same-origin', cache:'no-store'
          });
          return {status:r.status, body:await r.json()};
        }"""
    )
    if not isinstance(response, dict) or response.get("status") != 200:
        raise BoundedFailure("guided_http_not_200")
    return classify_state(response.get("body")), response["body"].get("state")


def browser_guard(route):
    if allow_http(route.request.method, route.request.url):
        route.continue_()
    else:
        route.abort("blockedbyclient")
        raise BoundedFailure("blocked_network_mutation")


def logout(page) -> bool:
    try:
        # Explicit session logout is the sole permitted non-login POST.
        result = page.evaluate(
            """async () => {
                const r=await fetch('/api/padiem/auth/logout',{
                    method:'POST',credentials:'same-origin'
                });
                const s=await fetch('/api/padiem/auth/status',{
                    method:'GET',credentials:'same-origin',cache:'no-store'
                });
                const body=await s.json();
                return {logout:r.status,status:s.status,signedIn:body.authenticated===true};
            }"""
        )
        return (isinstance(result, dict) and 200 <= result.get("logout", 0) < 300
                and result.get("status") == 200 and result.get("signedIn") is False)
    except Exception:
        return False


def self_test() -> int:
    assert MAX_LOGINS == 2 and MAX_MODEL_POSTS == 0
    assert MAX_PDF_POSTS == 0 and PRODUCTION_ROW_MUTATIONS == 0
    assert PASSIVE_MODE
    for method in ("PUT", "PATCH", "DELETE"):
        assert not allow_http(method, ORIGIN + GUIDED)
    for path in (GUIDED, "/api/padiem/b66/quote/interpret",
                 "/api/padiem/b66/quote/pdf", "/api/padiem/b66/quotes",
                 "/api/padiem/b66/company-profile",
                 "/api/padiem/b66/saved-skills"):
        assert not allow_http("POST", ORIGIN + path)
    assert allow_http("POST", ORIGIN + AUTH_LOGIN)
    assert allow_http("POST", ORIGIN + AUTH_LOGOUT)
    assert not allow_http("POST", "https://evil.invalid" + AUTH_LOGIN)
    assert classify_state({"ok": True, "state": None}) == "EMPTY"
    assert classify_state({"ok": True, "state": {
        "schema": "b66.guided-draft.v1", "mode": "guided"
    }}) == "PRESENT"
    for invalid in (None, {}, {"ok": False, "state": None},
                    {"ok": True, "state": []}):
        try:
            classify_state(invalid)
        except BoundedFailure:
            continue
        raise AssertionError("invalid state accepted")
    print("B66_3396_CGI_READONLY_SOURCE=PASS")
    print("PRODUCTION_ROW_MUTATIONS=0")
    print("MODEL_CALLS=0")
    return 0


def run_live() -> int:
    username = os.getenv("B66_CGI_ALPHA_USERNAME", "")
    password = os.getenv("B66_CGI_ALPHA_PASSWORD", "")
    if not username or not password:
        print("B66_3396_CGI_READONLY=FAIL_CREDENTIAL_UNAVAILABLE")
        return 2

    # Import the existing, operator-approved CGI login contract without
    # implementing an alternative identity method or printing credentials.
    sys.path.insert(0, str(Path(__file__).parent))
    from b66_cgi_final_handoff_smoke import _login

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("B66_3396_CGI_READONLY=FAIL_CHROMIUM_UNAVAILABLE")
        return 3

    contexts = []
    logged_in = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for i in range(MAX_LOGINS):
                    ctx = browser.new_context(
                        viewport={"width": 1440, "height": 900},
                        service_workers="block",
                    )
                    contexts.append(ctx)
                    ctx.route("**/*", browser_guard)
                    page = ctx.new_page()
                    _login(page, username, password)
                    logged_in.append(page)
                    readiness = page.evaluate(
                        "() => window.B66QuoteRuntimeBridge?.readiness?.()"
                    )
                    if not isinstance(readiness, dict) or not all(
                        readiness.get(k) is True
                        for k in ("authenticated", "profileReady", "skillReady", "ready")
                    ):
                        raise BoundedFailure("cgi_runtime_not_ready")
                    print(f"CGI_INDEPENDENT_LOGIN_{i+1}=PASS", flush=True)

                first = api_snapshot(logged_in[0])
                second = api_snapshot(logged_in[1])
                if first != second:
                    # Never reveal actual customer draft contents in evidence.
                    raise BoundedFailure("cgi_cross_context_state_mismatch")
                print("CGI_TWO_BROWSER_ACCOUNT_STATE_PARITY=PASS", flush=True)
                print("CGI_STATE_CLASS=" + first[0], flush=True)

                if first[0] == "PRESENT":
                    for page in logged_in:
                        page.locator("#resumeDraftStarter").click(timeout=10000)
                        page.wait_for_function(
                            "() => window.history.state?.b66View === 'guided'",
                            timeout=10000,
                        )
                    print("CGI_EXISTING_DRAFT_UI_RESUME=PASS", flush=True)
                else:
                    print("CGI_EXISTING_DRAFT_UI_RESUME=NOT_APPLICABLE_EMPTY", flush=True)

                print("CGI_NO_QUOTE_WRITE_OR_MODEL_CALL=PASS", flush=True)
            finally:
                cleanup = [logout(page) for page in reversed(logged_in)]
                for ctx in reversed(contexts):
                    ctx.close()
                browser.close()
                if len(cleanup) != MAX_LOGINS or not all(cleanup):
                    raise BoundedFailure("cgi_logout_incomplete")
        print("CGI_TWO_INDEPENDENT_LOGOUTS=PASS")
        print("COOKIE_OUTPUT=0")
        print("PASSWORD_OUTPUT=0")
        print("RAW_RESPONSE_OUTPUT=0")
        print("MODEL_CALLS=0")
        print("PDF_POSTS=0")
        print("PRODUCTION_ROW_MUTATIONS=0")
        print("B66_3396_CGI_READONLY=PASS")
        return 0
    except BoundedFailure as exc:
        print("B66_3396_CGI_READONLY=FAIL_" + str(exc))
        return 1
    except Exception:
        print("B66_3396_CGI_READONLY=FAIL_BOUNDED_BROWSER_STAGE")
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--authorized-live-readonly", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.authorized_live_readonly:
        print("B66_3396_CGI_READONLY=FAIL_EXPLICIT_DISPATCH_REQUIRED")
        return 2
    return run_live()


if __name__ == "__main__":
    raise SystemExit(main())
