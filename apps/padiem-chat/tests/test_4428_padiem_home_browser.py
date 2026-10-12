"""#4428 S1: PADIEM customer home — actual Chromium privacy and access contracts.

The home reads exactly one server fact (the canonical GET /api/auth/status) and
must fail closed on everything else. These tests mock that endpoint only.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

# Full B62 core runners intentionally do not install Playwright. Skip this
# optional browser suite there instead of aborting pytest collection.
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "static"
HOME = "padiem-home.html"
STATUS_ENDPOINT = "/api/auth/status"
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


def open_home(browser, server, fixture, width=1280):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    calls = route_status(page, fixture)
    page.route("**" + LOGOUT_ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"ok": true}',
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


def test_unverifiable_server_response_fails_closed(browser, server):
    """A 500, bad JSON or a contradiction must never render the catalog."""
    page, errors, _ = open_home(browser, server, {"status": 500, "body": "boom"})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    page.close()

    page, errors, _ = open_home(browser, server, {"body": "not-json"})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    page.close()

    # authenticated:true with a non-signed_in state is contradictory -> closed.
    page, errors, _ = open_home(browser, server, {"body": json.dumps(
        status_body(True, "expired", name="모순"))})
    wait_gate(page)
    assert page.locator("#padiemHomeServices").is_hidden()
    assert "모순" not in page.locator("body").inner_text()
    assert not errors, errors
    page.close()


def test_signed_in_user_sees_allowlisted_services_with_honest_status(browser, server):
    page, errors, calls = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    cards = page.locator("#padiemHomeGrid li")
    assert cards.count() == 3
    ids = [cards.nth(i).get_attribute("data-service") for i in range(3)]
    assert ids == ["chat", "claw", "engine"]
    # Every service is honestly unverified: the authority exposes no
    # per-product entitlement to the browser.
    assert page.locator('#padiemHomeGrid [data-access="unverified"]').count() == 3
    home = page.locator("body").inner_text()
    assert "확인 불가" in home
    # It must not claim availability or denial.
    assert "사용 가능" not in home
    assert "이용 가능" not in home
    assert "권한 없음" not in home
    # Engine has no customer screen, so it must not offer a launch action.
    engine = page.locator('#padiemHomeGrid li[data-service="engine"]')
    assert engine.locator("a").count() == 0
    assert engine.get_attribute("data-service") == "engine"
    # The account identity is shown, but not the email.
    assert page.locator("#padiemHomeAccountName").inner_text() == "김파디"
    assert "private@example.com" not in home
    assert calls == ["GET"]
    assert not errors, errors
    page.close()


def test_b66_brand_is_absent_from_the_home(browser, server):
    page, errors, _ = open_home(browser, server, dict(SIGNED_IN))
    wait_services(page)
    home = page.locator("body").inner_text()
    assert "B66" not in home
    assert "견적" not in home
    assert "회원" not in home
    hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.getAttribute('href'))")
    assert all("b66" not in (h or "").lower() for h in hrefs)
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
    # Product links are reachable and named.
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
    assert not errors, errors
    page.close()
