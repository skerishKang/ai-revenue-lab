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


def synthetic_http(method: str, url: str) -> bool:
    if allow_http(method, url):
        return True
    parsed = urlsplit(url)
    return (method in {"PUT", "DELETE"} and
            parsed.scheme == "https" and
            parsed.netloc == "quick-quote-kr.pages.dev" and
            parsed.path == GUIDED)


def synthetic_guard(route):
    if synthetic_http(route.request.method, route.request.url):
        route.continue_()
    else:
        route.abort("blockedbyclient")


def mutate_guided(page, method: str, payload=None) -> bool:
    if method not in ("PUT", "DELETE"):
        raise BoundedFailure("unsupported_synthetic_mutation")
    result = page.evaluate(
        """async ({method, payload}) => {
            const r=await fetch('/api/padiem/b66/guided-draft', {
              method, credentials:'same-origin',cache:'no-store',
              headers:payload?{'Content-Type':'application/json'}:{},
              body:payload?JSON.stringify(payload):undefined
            });
            const j=await r.json().catch(()=>null);
            return {status:r.status,ok:j?.ok===true};
        }""",
        {"method": method, "payload": payload},
    )
    return isinstance(result, dict) and result.get("status") == 200 and result.get("ok") is True


def exact_synthetic(state, marker: str) -> bool:
    return (isinstance(state, dict) and
            isinstance(state.get("draft"), dict) and
            isinstance(state["draft"].get("meta"), dict) and
            state["draft"]["meta"].get("quoteNo") == marker and
            state.get("schema") == "b66.guided-draft.v1" and
            state.get("step") == "price" and
            isinstance(state["draft"].get("items"), list) and
            len(state["draft"]["items"]) == 1)


def synthetic_payload(marker: str) -> dict:
    return {
        "schema": "b66.guided-draft.v1", "mode": "guided",
        "step": "price", "currentItem": 0,
        "taxUnknown": False, "savedSkillId": "",
        "draft": {
            "recipient": {"company": marker, "person": "TEST",
                          "address": "", "email": ""},
            "sender": {"company": "SYNTHETIC QA ONLY"},
            "items": [{"id": "qa-1", "name": "B66 QA - DELETE",
                       "qty": 2, "unitPrice": None, "unit": ""}],
            "tax": {"mode": "EXCLUSIVE"}, "memo": "SYNTHETIC TEST DELETE",
            "meta": {"quoteNo": marker, "issueDate": "2026-10-11"},
        },
    }


def run_live_synthetic() -> int:
    """One dedicated CGI-alpha synthetic slot. Fail closed on any preexisting row.

    This is a test-only Production D1 mutation, not a customer quote creation.
    The same account must have an empty slot before making one PUT.
    Always attempt guarded exact-marker cleanup prior to two logouts.
    """
    username = os.getenv("B66_CGI_ALPHA_USERNAME", "")
    password = os.getenv("B66_CGI_ALPHA_PASSWORD", "")
    if not username or not password:
        print("B66_3396_CGI_SYNTHETIC=FAIL_CREDENTIAL_UNAVAILABLE")
        return 2

    import uuid
    sys.path.insert(0, str(Path(__file__).parent))
    from b66_cgi_final_handoff_smoke import _login
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("B66_3396_CGI_SYNTHETIC=FAIL_CHROMIUM_UNAVAILABLE")
        return 3

    # Never print this or embed any customer business value in the row.
    marker = "B66-3396-CGI-ALPHA-SYNTH-" + uuid.uuid4().hex
    contexts = []
    logged_in = []
    cleanup_verified = False
    logout_verified = False
    stage_pass = False
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
                    ctx.route("**/*", synthetic_guard)
                    page = ctx.new_page()
                    _login(page, username, password)
                    logged_in.append(page)
                    print(f"CGI_SYNTH_LOGIN_{i+1}=PASS", flush=True)

                a, b = logged_in
                if api_snapshot(a)[0] != "EMPTY" or api_snapshot(b)[0] != "EMPTY":
                    raise BoundedFailure("preexisting_guided_state_no_mutation")
                # Two independent authenticated sessions agree that alpha slot
                # is empty; do not create a production saved quote/history row.
                print("CGI_SYNTHETIC_PREWRITE_EMPTY=PASS", flush=True)

                if not mutate_guided(a, "PUT", synthetic_payload(marker)):
                    raise BoundedFailure("synthetic_put_not_ok")
                first, state_a = api_snapshot(a)
                second, state_b = api_snapshot(b)
                if (first != "PRESENT" or second != "PRESENT"
                        or not exact_synthetic(state_a, marker)
                        or state_a != state_b):
                    raise BoundedFailure("second_session_save_read_mismatch")
                print("CGI_SYNTHETIC_CROSS_BROWSER_D1_READBACK=PASS", flush=True)

                # Account B has a wholly separate cookie jar + browser context.
                b.locator("#resumeDraftStarter").click(timeout=10000)
                b.wait_for_function(
                    "() => window.history.state?.b66View === 'guided'",
                    timeout=10000,
                )
                placeholder = b.locator("#easyComposer").get_attribute("placeholder")
                if placeholder != "예: 1,500,000 또는 150만원":
                    raise BoundedFailure("second_browser_wrong_question")
                print("CGI_SYNTHETIC_SECOND_BROWSER_PRICE_RESUME=PASS", flush=True)
                stage_pass = True
            finally:
                # Cleanup is attempted even if the API call or UI verification
                # fails; NEVER delete a row with a different marker.
                try:
                    if logged_in:
                        state_type, current = api_snapshot(logged_in[0])
                        if state_type == "EMPTY":
                            cleanup_verified = True
                        elif exact_synthetic(current, marker):
                            cleanup_verified = (
                                mutate_guided(logged_in[0], "DELETE")
                                and api_snapshot(logged_in[0])[0] == "EMPTY"
                            )
                            if cleanup_verified and len(logged_in) > 1:
                                cleanup_verified = api_snapshot(logged_in[1])[0] == "EMPTY"
                except Exception:
                    cleanup_verified = False
                logouts = [logout(page) for page in reversed(logged_in)]
                logout_verified = len(logouts) == MAX_LOGINS and all(logouts)
                for ctx in reversed(contexts):
                    ctx.close()
                browser.close()
        if not cleanup_verified:
            raise BoundedFailure("synthetic_cleanup_not_proven")
        if not logout_verified:
            raise BoundedFailure("synthetic_logout_not_proven")
        if not stage_pass:
            raise BoundedFailure("synthetic_resume_not_completed")
        print("CGI_SYNTHETIC_EXACT_MARKER_DELETE=PASS")
        print("CGI_SYNTHETIC_BOTH_SESSIONS_LOGGED_OUT=PASS")
        print("MODEL_POSTS=0")
        print("PDF_POSTS=0")
        print("CUSTOMER_QUOTE_HISTORY_WRITES=0")
        print("B66_3396_CGI_SYNTHETIC_RESUME=PASS")
        return 0
    except BoundedFailure as exc:
        # Bounded error class only. No raw payload, token, credential or IDs.
        print("B66_3396_CGI_SYNTHETIC=FAIL_" + str(exc))
        print("SYNTHETIC_CLEANUP_VERIFIED=" + ("YES" if cleanup_verified else "NO"))
        return 1
    except Exception:
        print("B66_3396_CGI_SYNTHETIC=FAIL_BOUNDED_BROWSER_STAGE")
        print("SYNTHETIC_CLEANUP_VERIFIED=" + ("YES" if cleanup_verified else "NO"))
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--authorized-live-readonly", action="store_true")
    parser.add_argument("--authorized-live-synthetic", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.authorized_live_synthetic and args.authorized_live_readonly:
        print("B66_3396_CGI=FAIL_CONFLICTING_MODES")
        return 2
    if args.authorized_live_synthetic:
        return run_live_synthetic()
    if args.authorized_live_readonly:
        return run_live()
    print("B66_3396_CGI=FAIL_EXPLICIT_DISPATCH_REQUIRED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
