"""#4139: Claw "내 컴퓨터" pre-connection guidance, state legend and recovery UX.

These are Chromium presentation contracts for the zero-network guidance module.
They assert the guide issues no directory read of its own, never asserts ONLINE
without server rows, and never echoes server text or persists anything.
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
ENDPOINT = "/api/claw/local-access/devices"


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
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def open_claw(browser, server, width=1280):
    page = browser.new_page(viewport={"width": width, "height": 850})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#clawDeviceGuidanceToggle").wait_for(state="attached")
    assert page.locator("#clawDeviceGuidance").is_hidden()
    # Simulate the Claw presentation state without invoking authenticated
    # backend activation; app.js owns actual navigation and session gates.
    page.evaluate("""() => {
      document.querySelector(".app-shell").setAttribute("data-state", "claw");
      document.getElementById("clawWorkspace").hidden = false;
    }""")
    page.locator("#clawWorkspace").wait_for(state="visible", timeout=5000)
    page.locator("#clawDeviceGuidanceToggle").wait_for(state="visible", timeout=10000)
    return page, errors


def payload(items):
    return {"ok": True, "available": True, "ownerScoped": True, "devices": items}


def device(device_id, name, state):
    return {
        "deviceId": device_id, "deviceName": name, "platform": "Windows",
        "state": state, "usable": state == "CONNECTED",
        "revoked": state == "REVOKED", "expired": False,
    }


def route_directory(page, fixture):
    requests = []

    def mock(route):
        requests.append(route.request.method)
        route.fulfill(
            status=fixture.get("status", 200),
            content_type="application/json",
            body=fixture["body"],
        )

    page.route("**" + ENDPOINT, mock)
    return requests


def open_guidance(page):
    page.locator("#clawDeviceGuidanceToggle").click()
    page.locator("#clawDeviceGuidancePanel").wait_for(state="visible", timeout=5000)


def open_directory(page):
    page.locator("#clawDeviceManagerToggle").click()
    page.locator("#clawDeviceManagerList li").first.wait_for(timeout=5000)


def open_directory_without_rows(page):
    """Open the directory when it is expected to answer with no rows at all."""
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 서비스가 아직 준비되지 않았습니다", exact=False).wait_for(timeout=5000)


@pytest.mark.parametrize("width", [390, 873, 1280])
def test_guidance_visible_before_connection_without_any_read(browser, server, width):
    """The feature must be explainable before any PC is connected, with no read."""
    page, errors = open_claw(browser, server, width)
    requests = route_directory(page, {"body": json.dumps(payload([]))})
    # Collapsed by default: visible affordance, no noise.
    assert page.locator("#clawDeviceGuidanceToggle").get_attribute("aria-expanded") == "false"
    assert page.locator("#clawDeviceGuidancePanel").is_hidden()
    open_guidance(page)
    panel = page.locator("#clawDeviceGuidancePanel").inner_text()
    # Registration steps and the state legend are present.
    assert "Padiem 데스크톱을 설치" in panel
    assert "같은 계정으로 로그인" in panel
    assert "컴퓨터 연결을 승인" in panel
    assert "연결됨" in panel and "오프라인" in panel and "연결 해제" in panel
    # Opening the guide performs no directory read at all.
    assert requests == []
    # And no summary is invented before the directory has confirmed anything.
    assert page.locator("#clawDeviceGuidanceSummary").is_hidden()
    assert not errors, errors
    page.close()


def test_guidance_adds_no_second_directory_read(browser, server):
    """The guide must not become a second reader of the owner directory."""
    page, errors = open_claw(browser, server)
    requests = route_directory(page, {"body": json.dumps(payload([
        device("home", "집 컴퓨터", "CONNECTED"),
    ]))})
    open_directory(page)
    open_guidance(page)
    page.locator("#clawDeviceGuidanceSummary").wait_for(state="visible")
    assert requests == ["GET"]
    page.locator(".claw-device-manager-refresh").click()
    page.wait_for_function("""() => document.querySelectorAll(
        '#clawDeviceManagerList .claw-device-manager-state[data-state]').length === 1""")
    assert requests == ["GET", "GET"]
    assert not errors, errors
    page.close()


def test_summary_and_recovery_follow_server_evidence(browser, server):
    """Counts and recovery hints come only from rendered, verified states."""
    page, errors = open_claw(browser, server)
    fixture = {"body": json.dumps(payload([
        device("home", "집 컴퓨터", "CONNECTED"),
        device("office", "사무실 PC", "CONNECTED"),
        device("laptop", "노트북", "OFFLINE"),
    ]), ensure_ascii=False)}
    route_directory(page, fixture)
    open_directory(page)
    open_guidance(page)
    summary = page.locator("#clawDeviceGuidanceSummaryList").inner_text()
    assert "연결됨 2" in summary
    assert "오프라인 1" in summary
    recovery = page.locator("#clawDeviceGuidanceRecovery")
    assert recovery.is_visible()
    assert "PC 전원" in recovery.inner_text()
    # A revoked device switches the recovery hint to the re-approval path.
    fixture["body"] = json.dumps(payload([
        device("home", "집 컴퓨터", "CONNECTED"),
        device("laptop", "노트북", "REVOKED"),
    ]), ensure_ascii=False)
    page.locator(".claw-device-manager-refresh").click()
    page.wait_for_function("""() => {
      const chips = document.querySelectorAll(
        '#clawDeviceManagerList .claw-device-manager-state[data-state="REVOKED"]');
      return chips.length === 1;
    }""")
    assert "다시 승인" in recovery.inner_text()
    assert not errors, errors
    page.close()


def test_unavailable_directory_never_becomes_a_fake_online_claim(browser, server):
    """An unconfigured/unreadable server must leave the summary honest and empty."""
    page, errors = open_claw(browser, server)
    requests = route_directory(page, {"status": 404, "body": "missing"})
    open_directory_without_rows(page)
    open_guidance(page)
    assert page.locator("#clawDeviceGuidanceSummary").is_hidden()
    assert page.locator("#clawDeviceGuidanceRecovery").is_hidden()
    assert requests == ["GET"]
    assert not errors, errors
    page.close()


def test_guidance_never_echoes_server_text_and_persists_nothing(browser, server):
    """Injected markup, credentials and owner refs must not reach the guide."""
    page, errors = open_claw(browser, server)
    name = '<img src=x onerror="window.pwned=true">'
    secret = "do-not-render-secret"
    body = json.dumps(payload([
        {**device("pc1", name, "CONNECTED"), "token": secret, "credential": secret,
         "stdout": secret, "account_ref": "private-account"},
    ]))
    route_directory(page, {"body": body})
    open_directory(page)
    open_guidance(page)
    page.locator("#clawDeviceGuidanceSummary").wait_for(state="visible")
    guide = page.locator("#clawDeviceGuidancePanel")
    assert secret not in guide.inner_text()
    assert name not in guide.inner_text()
    assert guide.locator("img").count() == 0
    assert page.evaluate("window.pwned === true") is False
    assert page.evaluate("() => localStorage.length + sessionStorage.length") == 0
    assert not errors, errors
    page.close()


def test_escape_closes_and_leaving_claw_hides_guidance(browser, server):
    page, errors = open_claw(browser, server)
    route_directory(page, {"body": json.dumps(payload([]))})
    open_guidance(page)
    page.locator("#clawDeviceGuidanceToggle").press("Escape")
    assert page.locator("#clawDeviceGuidancePanel").is_hidden()
    assert page.locator("#clawDeviceGuidanceToggle").get_attribute("aria-expanded") == "false"
    # Navigating out of Claw hides the whole guidance surface.
    page.evaluate("""() => {
      document.querySelector(".app-shell").setAttribute("data-state", "chat");
    }""")
    page.locator("#clawDeviceGuidance").wait_for(state="hidden")
    assert not errors, errors
    page.close()


def test_korean_copy_never_implies_execution_authority(browser, server):
    """'Connected' must not read as 'work can run now'."""
    page, errors = open_claw(browser, server)
    route_directory(page, {"body": json.dumps(payload([]))})
    open_guidance(page)
    guide = page.locator("#clawDeviceGuidancePanel").inner_text()
    # The removed claim must be gone.
    assert "지금 작업을 진행할 수 있는" not in guide
    # Connection status and execution authority are stated as separate things.
    assert "실행 권한이 아닙니다" in guide
    assert "제품별 권한" in guide
    assert "별도의 승인" in guide
    assert "실행 권한을 부여하지 않습니다" in guide
    # The desktop install/registration path is not advertised as available now.
    assert "정식 공개 전" in guide
    assert not errors, errors
    page.close()


def test_english_copy_never_implies_execution_authority(browser, server):
    """The English guide carries the same separation."""
    page, errors = open_claw(browser, server)
    route_directory(page, {"body": json.dumps(payload([]))})
    open_guidance(page)
    # Language switching re-renders the guide from the same contract.
    page.evaluate("() => { document.documentElement.lang = 'en'; }")
    page.wait_for_function(
        "() => document.querySelector('#clawDeviceGuidancePanel')"
        ".innerText.includes('not execution authority')"
    )
    guide = page.locator("#clawDeviceGuidancePanel").inner_text()
    assert "can run work now" not in guide
    assert "not execution authority" in guide
    assert "product-specific permission" in guide
    assert "separate approval" in guide
    assert "not publicly available yet" in guide
    assert not errors, errors
    page.close()


def test_language_switch_keeps_zero_network_and_no_authority(browser, server):
    """Re-rendering for a language change must not add a read or any grant."""
    page, errors = open_claw(browser, server)
    requests = route_directory(page, {"body": json.dumps(payload([
        device("home", "집 컴퓨터", "CONNECTED"),
    ]))})
    open_directory(page)
    open_guidance(page)
    page.locator("#clawDeviceGuidanceSummary").wait_for(state="visible")
    assert requests == ["GET"]
    page.evaluate("() => { document.documentElement.lang = 'en'; }")
    page.evaluate("() => { document.documentElement.lang = 'ko'; }")
    page.wait_for_function(
        "() => document.querySelector('#clawDeviceGuidancePanel')"
        ".innerText.includes('실행 권한이 아닙니다')"
    )
    # Still exactly the one directory read, no selection, nothing persisted.
    assert requests == ["GET"]
    assert page.locator('#clawDeviceManagerList [aria-pressed="true"]').count() == 0
    assert page.evaluate("() => localStorage.length + sessionStorage.length") == 0
    assert not errors, errors
    page.close()
