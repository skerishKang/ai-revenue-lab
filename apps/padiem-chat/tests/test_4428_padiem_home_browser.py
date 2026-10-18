"""#4428 S1: PADIEM customer home — actual Chromium privacy and access contracts.

The Home verifies the B62 presentation session then the canonical Chat/Claw
bundle GET projection. Both server facts are mocked; no credentials are read.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

# The focused UI-mixed runner does not install browser-only dependencies.
# Resolve the optional package in the fixture so pytest still collects tests;
# environments without it report explicit skips rather than exit code 5.

ROOT = Path(__file__).resolve().parents[1] / "static"
HOME = "padiem-home.html"
STATUS_ENDPOINT = "/api/auth/status"
ACCESS_ENDPOINT = "/api/home/product-access"
LOGOUT_ENDPOINT = "/api/auth/logout"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        t = threading.Thread(target=web.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/{HOME}"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def status_body(authenticated, session_state, name=None, email=None, ready=True):
    payload = {
        "ready": ready,
        "authenticated": authenticated,
        "history_ready": ready,
        "user": None,
    }
    if authenticated:
        payload["user"] = {"name": name, "email": email, "picture": None}
    payload["session_state"] = session_state
    payload["methods"] = {"google": True, "password": True}
    return payload


def route_status(page, fixture):
    calls = []

    def mock(route):
        calls.append(route.request.method)
        route.fulfill(
            status=fixture.get("status", 200),
            content_type="application/json",
            body=fixture["body"],
        )

    page.route("**" + STATUS_ENDPOINT, mock)
    return calls


def access_body(state="available"):
    return {
        "version": "product-access-projection-v1",
        "products": [
            {"product_id": pid, "access": state, "authority": "padiem-chat-claw-bundle-v1",
             "reason": "server_allow_confirmed" if state == "available" else "authority_unconfirmed"}
            for pid in ("b62", "b54-padiem-claw")
        ],
    }


def open_home(browser, server, fixture, width=1280, logout_status=200,
              access_status=200, access_payload=None):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    calls = route_status(page, fixture)
    page.route("**" + ACCESS_ENDPOINT, lambda route: route.fulfill(
        status=access_status, content_type="application/json",
        body=json.dumps(access_body() if access_payload is None else access_payload),
    ))
    page.route("**" + LOGOUT_ENDPOINT, lambda route: route.fulfill(
        status=logout_status, content_type="application/json",
        body='{"ok": true}' if logout_status == 200 else "{}",
    ))
    page.goto(server, wait_until="domcontentloaded")
    return page, errors, calls


def wait_gate(page):
    page.locator("#padiemHomeGate").wait_for(state="visible", timeout=5000)


def wait_services(page):
    page.locator("#padiemHomeServices").wait_for(state="visible", timeout=5000)


SIGNED_IN = {"body": json.dumps(status_body(
    True, "signed_in", name="김파디", email="private@example.com"), ensure_ascii=False)}
ANONYMOUS = {"body": json.dumps(status_body(False, "guest"))}


def test_anonymous_user_cannot_see_the_private_home(browser, server):
    page, errors, calls = open_home(browser, server, dict(ANONYMOUS))
    wait_gate(page)
    assert page.locator("#padiemHomeGateTitle").inner_text() == "로그인이 필요합니다"
    # The sign-in control is honest about where authentication happens.
    assert page.locator("#padiemHomeGateAction").inner_text() == "Padiem Chat에서 로그인"
    assert page.locator("#padiemHomeGateAction").get_attribute("href") == "./"
    # No service catalog, no account identity, no product links at all.
    assert page.locator("#padiemHomeServices").is_hidden()
    assert page.locator("#padiemHomeGrid li").count() == 0
    assert page.locator("#padiemHomeAccount").is_hidden()
    assert page.locator("#padiemHomeGrid a").count() == 0
    assert calls == ["GET"]
    assert not errors, errors
    page.close()


@pytest.mark.parametrize("state", ["expired", "unavailable"])
def test_expired_and_unavailable_sessions_fail_closed(browser, server, state):
    page, errors, _ = open_home(browser, server, {"body": json.dumps(
        status_body(False, state))})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    assert page.locator("#padiemHomeGrid li").count() == 0
    expected = "세션이 만료" if state == "expired" else "확인할 수 없습니다"
    assert expected in page.locator("#padiemHomeGateBody").inner_text()
    assert not errors, errors
    page.close()


@pytest.mark.parametrize("payload", [
    # ready is not true: the real auth_status only sets it with a live store.
    {"ready": False, "authenticated": True, "session_state": "signed_in", "user": {"name": "A"}},
    # ready missing entirely.
    {"authenticated": True, "session_state": "signed_in", "user": {"name": "A"}},
    # Contradictory: authenticated but not a signed_in state.
    {"ready": True, "authenticated": True, "session_state": "guest", "user": {"name": "A"}},
    {"ready": True, "authenticated": True, "session_state": "expired", "user": {"name": "A"}},
    # Missing / malformed owner identity.
    {"ready": True, "authenticated": True, "session_state": "signed_in", "user": None},
    {"ready": True, "authenticated": True, "session_state": "signed_in"},
    {"ready": True, "authenticated": True, "session_state": "signed_in", "user": []},
    {"ready": True, "authenticated": True, "session_state": "signed_in", "user": {"name": 123}},
    {"ready": True, "authenticated": True, "session_state": "signed_in", "user": {"name": "   "}},
])
def test_contradictory_session_envelopes_fail_closed(browser, server, payload):
    """A signed-in claim needs ready + signed_in + a usable owner identity."""
    page, errors, _ = open_home(browser, server, {"body": json.dumps(payload)})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    assert page.locator("#padiemHomeGrid li").count() == 0
    assert page.locator("#padiemHomeAccount").is_hidden()
    assert not errors, errors
    page.close()


def test_unverifiable_server_response_fails_closed(browser, server):
    """A 500 or malformed body must never render the catalog."""
    page, errors, _ = open_home(browser, server, {"status": 500, "body": "boom"})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    page.close()

    page, errors, _ = open_home(browser, server, {"body": "not-json"})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    assert not errors, errors
    page.close()


def test_signed_in_user_sees_allowlisted_services_with_honest_status(browser, server):
    page, errors, calls = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    cards = page.locator("#padiemHomeGrid li")
    assert cards.count() == 2
    ids = [cards.nth(i).get_attribute("data-service") for i in range(2)]
    assert ids == ["chat", "claw"]
    assert page.locator('#padiemHomeGrid [data-access="available"]').count() == 2
    home = page.locator("body").inner_text()
    assert "이용 가능" in home
    assert "권한 없음" not in home
    # The account identity is shown, but not the email.
    assert page.locator("#padiemHomeAccountName").inner_text() == "김파디"
    assert "private@example.com" not in home
    assert calls == ["GET"]
    assert not errors, errors
    page.close()


def test_only_a_supported_destination_is_linked(browser, server):
    """Claw has no supported deep link, so it must not fake a launch action."""
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    chat = page.locator('#padiemHomeGrid li[data-service="chat"]')
    assert chat.locator("a").count() == 1
    assert chat.locator("a").get_attribute("href") == "./"
    assert chat.locator("a").inner_text() == "Padiem Chat 열기"
    claw = page.locator('#padiemHomeGrid li[data-service="claw"]')
    assert claw.locator("a").count() == 1
    assert claw.locator("a").get_attribute("href") == "./"
    assert claw.locator("a").inner_text() == "Chat에서 Claw 선택"
    # This is an honest two-step route to the existing sidebar, not a
    # fabricated Claw-specific deep link.
    assert "왼쪽 Claw 메뉴를 선택하세요" in claw.inner_text()
    assert not errors, errors
    page.close()


@pytest.mark.parametrize("access_status, access_payload", [
    (503, None),
    (200, {"version": "product-access-projection-v1", "products": [
        {"product_id": "b66", "access": "available",
         "authority": "padiem-chat-claw-bundle-v1", "reason": "server_allow_confirmed"},
    ]}),
    (200, {"version": "wrong", "products": []}),
])
def test_unverified_or_forged_bundle_cannot_unlock_chat_link(
    browser, server, access_status, access_payload
):
    page, errors, _ = open_home(
        browser, server, dict(SIGNED_IN),
        access_status=access_status, access_payload=access_payload,
    )
    wait_services(page)
    assert page.locator('#padiemHomeGrid [data-access="unverified"]').count() == 2
    assert page.locator("#padiemHomeGrid a").count() == 0
    assert "이용 가능" not in page.locator("#padiemHomeGrid").inner_text()
    assert not errors, errors
    page.close()


def test_b66_brand_is_absent_from_the_home_and_from_help(browser, server):
    """B66 must not appear even once the expandable Help is open."""
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    # Open the Help so its text becomes user-visible.
    page.locator("#padiemHomeHelp summary").click()
    page.wait_for_function("() => document.querySelector('#padiemHomeHelp').open === true")
    for marker in ("B66", "견적", "회원"):
        assert marker not in page.locator("body").inner_text(), marker
        assert marker not in page.evaluate("() => document.body.textContent"), marker
    hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.getAttribute('href'))")
    assert all("b66" not in (h or "").lower() for h in hrefs)
    # English Help too.
    page.evaluate("() => { document.documentElement.lang = 'en'; }")
    page.wait_for_function(
        "() => document.querySelector('#padiemHomeHelpSummary')"
        ".textContent.includes('Why access status')"
    )
    english = page.locator("body").inner_text()
    assert "B66" not in english
    assert "quote" not in english.lower()
    assert "member" not in english.lower()
    assert not errors, errors
    page.close()


def test_account_switch_removes_previous_identity(browser, server):
    fixture = {"body": json.dumps(status_body(
        True, "signed_in", name="계정 A"), ensure_ascii=False)}
    page, errors, _ = open_home(browser, server, fixture)
    wait_services(page)
    assert page.locator("#padiemHomeAccountName").inner_text() == "계정 A"
    fixture["body"] = json.dumps(status_body(
        True, "signed_in", name="계정 B"), ensure_ascii=False)
    page.evaluate('window.dispatchEvent(new Event("padiem:account-changed"))')
    page.wait_for_function(
        "() => document.querySelector('#padiemHomeAccountName').textContent === '계정 B'"
    )
    assert "계정 A" not in page.locator("body").inner_text()
    assert not errors, errors
    page.close()


def test_sign_out_clears_identity_before_the_request_completes(browser, server):
    """A slow logout must not leave the previous account on screen."""
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    page.evaluate("""() => {
      const original = window.fetch.bind(window);
      window.__logoutStarted = 0;
      window.fetch = (url, options = {}) => {
        if (String(url).includes("/api/auth/logout")) {
          window.__logoutStarted += 1;
          return new Promise(() => {});   // held open on purpose
        }
        return original(url, options);
      };
    }""")
    page.locator("#padiemHomeSignOut").click()
    page.wait_for_function("window.__logoutStarted === 1")
    assert page.locator("#padiemHomeAccount").is_hidden()
    assert page.locator("#padiemHomeGrid li").count() == 0
    assert "김파디" not in page.locator("body").inner_text()
    assert page.locator("#padiemHomeStatus").inner_text() == "로그아웃하는 중입니다."
    assert not errors, errors
    page.close()


def test_pending_sign_out_blocks_visibility_and_auth_event_refresh(browser, server):
    """An old cookie must not repaint the prior owner while logout is pending."""
    page, errors, calls = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    reads_before = len(calls)
    page.evaluate("""() => {
      const original = window.fetch.bind(window);
      window.__pendingLogoutCalls = 0;
      window.fetch = (url, options = {}) => {
        if (String(url).includes("/api/auth/logout")) {
          window.__pendingLogoutCalls += 1;
          return new Promise(() => {});
        }
        return original(url, options);
      };
    }""")
    page.locator("#padiemHomeSignOut").click()
    page.wait_for_function("window.__pendingLogoutCalls === 1")
    page.evaluate("""() => {
      // Every existing refresh route must stay inert until the logout settles.
      window.dispatchEvent(new Event("padiem:auth-changed"));
      window.dispatchEvent(new Event("padiem:account-changed"));
      window.dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true}));
      document.dispatchEvent(new Event("visibilitychange"));
    }""")
    page.wait_for_timeout(120)
    assert len(calls) == reads_before
    assert page.locator("#padiemHomeAccount").is_hidden()
    assert page.locator("#padiemHomeGrid li").count() == 0
    assert "김파디" not in page.locator("body").inner_text()
    assert page.locator("#padiemHomeStatus").inner_text() == "로그아웃하는 중입니다."
    assert not errors, errors
    page.close()


def test_refused_sign_out_is_not_misreported_as_signed_out(browser, server):
    """A failed logout must not claim the session was revoked."""
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN), logout_status=500)
    wait_services(page)
    page.locator("#padiemHomeSignOut").click()
    # The server still reports signed-in on the re-read, so the account returns
    # honestly rather than pretending the session ended.
    wait_services(page)
    page.wait_for_function(
        "() => document.querySelector('#padiemHomeStatus')"
        ".textContent.includes('로그아웃을 확인하지 못했습니다')"
    )
    assert page.locator("#padiemHomeAccountName").inner_text() == "김파디"
    assert not errors, errors
    page.close()


def test_sign_out_returns_to_the_gate(browser, server):
    fixture = {"body": json.dumps(status_body(
        True, "signed_in", name="계정 A"), ensure_ascii=False)}
    page, errors, _ = open_home(browser, server, fixture)
    wait_services(page)
    fixture["body"] = json.dumps(status_body(False, "guest"))
    page.locator("#padiemHomeSignOut").click()
    wait_gate(page)
    assert page.locator("#padiemHomeAccount").is_hidden()
    assert page.locator("#padiemHomeGrid li").count() == 0
    assert "계정 A" not in page.locator("body").inner_text()
    assert not errors, errors
    page.close()


def test_no_admin_surface_no_persistence_and_no_url_secret(browser, server):
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    home = page.locator("body").inner_text()
    for forbidden in ("관리자", "Admin", "운영 콘솔", "Portfolio"):
        assert forbidden not in home
    # Nothing is persisted and no credential enters the URL.
    assert page.evaluate("() => localStorage.length + sessionStorage.length") == 0
    url = page.url
    for marker in ("token", "session", "access_token", "email"):
        assert marker not in url.lower()
    assert not errors, errors
    page.close()


@pytest.mark.parametrize("width", [390, 768, 1280])
def test_responsive_layout_without_horizontal_scroll(browser, server, width):
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN), width=width)
    wait_services(page)
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, f"horizontal overflow {overflow}px at {width}px"
    # Primary controls keep a 44px minimum touch target.
    sizes = page.eval_on_selector_all(
        ".padiem-home-card-action, .padiem-home-account-menu, .padiem-home-signout",
        "els => els.map(e => e.getBoundingClientRect().height)",
    )
    assert sizes, "expected primary controls"
    assert min(sizes) >= 44, sizes
    assert not errors, errors
    page.close()


def test_keyboard_and_language_accessibility(browser, server):
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    # Landmarks, heading and a polite live region for the load state.
    assert page.locator("h1").count() == 1
    assert page.locator("#padiemHomeStatus").get_attribute("aria-live") == "polite"
    assert page.locator("main#padiemHomeMain").count() == 1
    # The skip link is the first focusable control.
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.className") == "padiem-home-skip"
    # The product link is reachable and named.
    link = page.locator('#padiemHomeGrid li[data-service="chat"] a')
    link.focus()
    assert page.evaluate("() => document.activeElement.tagName") == "A"
    assert link.inner_text().strip() != ""
    # English rendering is available and keeps the same honesty.
    page.evaluate("() => { document.documentElement.lang = 'en'; }")
    page.wait_for_function(
        "() => document.querySelector('#padiemHomeNotice').textContent.includes('not a permission result')"
    )
    assert "Unverified" in page.locator("body").inner_text()
    assert "Entry not linked" in page.locator("body").inner_text()
    assert not errors, errors
    page.close()
