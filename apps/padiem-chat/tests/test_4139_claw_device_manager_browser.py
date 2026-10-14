"""#4139: optional Claw multi-device manager — actual Chromium browser contracts.

Server-authoritative directory still belongs to LOCAL1. These tests mock only
the future GET and verify no pairing, command, work ticket or approval is sent.
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
    page.locator("#clawDeviceManagerToggle").wait_for(state="attached")
    assert page.locator("#clawDeviceManager").is_hidden()
    # Simulate the Claw presentation state without invoking authenticated
    # backend activation; app.js owns actual navigation and session gates.
    page.evaluate("""() => {
      document.querySelector(".app-shell").setAttribute("data-state", "claw");
      document.getElementById("clawWorkspace").hidden = false;
    }""")
    page.locator("#clawWorkspace").wait_for(state="visible", timeout=5000)
    page.locator("#clawDeviceManagerToggle").wait_for(state="visible", timeout=10000)
    return page, errors


def payload(items):
    return {"ok": True, "available": True, "ownerScoped": True, "devices": items}


def online(device_id, name):
    return {
        "deviceId": device_id, "deviceName": name, "platform": "Windows",
        "state": "CONNECTED", "usable": True,
    }


def offline(device_id, name):
    return {
        "deviceId": device_id, "deviceName": name, "platform": "Windows",
        "state": "OFFLINE", "usable": False,
    }


@pytest.mark.parametrize("width", [390, 873, 1280])
def test_device_list_choice_refresh_and_approval_boundary(browser, server, width):
    page, errors = open_claw(browser, server, width)
    requests = []
    fixture = {"devices": payload([
        online("home", "집 컴퓨터"),
        offline("laptop", "노트북"),
        online("office", "사무실 PC"),
    ])}

    def mock(route):
        requests.append((route.request.method, route.request.url))
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(fixture["devices"], ensure_ascii=False),
        )

    page.route("**" + ENDPOINT, mock)
    # No automatic device lookup in the background.
    assert not requests
    page.locator("#clawDeviceManagerToggle").click()
    page.locator("#clawDeviceManagerList li").first.wait_for()
    assert len(requests) == 1
    assert requests[0][0] == "GET"
    assert page.locator("#clawDeviceManagerList li").count() == 3
    assert page.locator("#clawDeviceManagerList li").nth(1).locator("button").is_disabled()
    # Even if a PC is online, the app never picks it without a click.
    assert page.locator('#clawDeviceManagerList [aria-pressed="true"]').count() == 0
    page.locator("#clawDeviceManagerList li").nth(2).locator("button").click()
    assert page.locator('#clawDeviceManagerList [aria-pressed="true"]').count() == 1
    assert page.locator("#clawDeviceManagerStatus").inner_text().startswith(
        "선택됨."
    )
    # One device goes offline: re-read and invalidate the old choice.
    fixture["devices"] = payload([
        offline("office", "사무실 PC"),
        online("home", "집 컴퓨터"),
    ])
    page.locator(".claw-device-manager-refresh").click()
    page.wait_for_function("""() => {
       const list = document.querySelector("#clawDeviceManagerList");
       return list.children.length === 2 &&
         list.children[0].querySelector("strong").textContent === "사무실 PC";
    }""")
    assert page.locator('#clawDeviceManagerList [aria-pressed="true"]').count() == 0
    assert page.locator("#clawDeviceManagerList li").first.locator("button").is_disabled()
    assert len(requests) == 2 and all(m == "GET" for m, _ in requests)
    assert not errors, errors
    page.close()


def test_unconfigured_server_is_honest_and_no_fake_online(browser, server):
    page, errors = open_claw(browser, server)

    def no_route(route):
        route.fulfill(status=404, body="missing")

    page.route("**" + ENDPOINT, no_route)
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 서비스가 아직 준비되지 않았습니다", exact=False).wait_for()
    assert page.locator("#clawDeviceManagerList").is_hidden()
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert not errors
    page.close()


def test_bad_json_unscoped_directory_and_revocation_never_show_online(browser, server):
    page, errors = open_claw(browser, server)
    fixture = {"body": "not-json"}

    def mock(route):
        route.fulfill(status=200, content_type="application/json", body=fixture["body"])

    page.route("**" + ENDPOINT, mock)
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 상태를 확인하지 못했습니다", exact=False).wait_for()
    assert page.locator("#clawDeviceManagerList li").count() == 0
    fixture["body"] = json.dumps({
        "ok": True, "available": True, "ownerScoped": False,
        "devices": [online("other-account", "비공개 사무실")],
    }, ensure_ascii=False)
    page.locator(".claw-device-manager-refresh").click()
    page.get_by_text("연결 서비스가 아직 준비되지 않았습니다", exact=False).wait_for()
    assert page.locator("#clawDeviceManagerList li").count() == 0
    fixture["body"] = json.dumps(payload([{
        **online("office", "사무실"), "revoked": True,
    }]), ensure_ascii=False)
    page.locator(".claw-device-manager-refresh").click()
    page.locator("#clawDeviceManagerList li").first.wait_for()
    assert page.locator("#clawDeviceManagerList li button").is_disabled()
    assert not errors
    page.close()


def test_credential_and_markup_never_injected(browser, server):
    page, errors = open_claw(browser, server)
    name = '<img src=x onerror="window.pwned=true">'
    secret = "do-not-render-secret"
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(payload([{
            **online("pc1", name), "token": secret, "credential": secret,
            "stdout": secret, "account_ref": "private-account",
        }])),
    ))
    page.locator("#clawDeviceManagerToggle").click()
    page.locator("#clawDeviceManagerList li").first.wait_for()
    assert page.locator("#clawDeviceManagerList li img").count() == 0
    assert page.locator("#clawDeviceManagerList li strong").inner_text() == name
    assert secret not in page.locator("#clawDeviceManagerPanel").inner_text()
    assert page.evaluate("window.pwned === true") is False
    assert not errors
    page.close()


def test_owner_switch_hides_previous_devices_and_clear_on_navigation(browser, server):
    page, errors = open_claw(browser, server)
    fixture = {"body": payload([online("pc1", "계정 A PC")])}
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(fixture["body"], ensure_ascii=False),
    ))
    page.locator("#clawDeviceManagerToggle").click()
    page.locator("#clawDeviceManagerList li").first.wait_for()
    page.locator("#clawDeviceManagerList li button").click()
    fixture["body"] = payload([offline("pc2", "계정 B PC")])
    page.evaluate('window.dispatchEvent(new CustomEvent("padiem:auth-state", {detail: {authenticated: true}}))')
    page.get_by_text("계정 B PC").wait_for()
    assert page.get_by_text("계정 A PC").count() == 0
    assert page.locator("#clawDeviceManagerList li button").is_disabled()
    # Navigating out of Claw always closes and invalidates the snapshot.
    page.evaluate("""() => {
        document.querySelector(".app-shell").setAttribute("data-state", "chat");
    }""")
    page.locator("#clawDeviceManager").wait_for(state="hidden")
    assert page.locator("#clawDeviceManagerPanel").is_hidden()
    assert page.locator("#clawDeviceManagerToggle").get_attribute("aria-expanded") == "false"
    assert not errors
    page.close()


def test_keyboard_escape_closes_without_side_effect(browser, server):
    page, errors = open_claw(browser, server)
    page.route("**" + ENDPOINT, lambda route: route.fulfill(status=503, body="disabled"))
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 서비스가 아직 준비되지 않았습니다", exact=False).wait_for()
    page.locator("#clawDeviceManagerToggle").press("Escape")
    assert page.locator("#clawDeviceManagerPanel").is_hidden()
    assert page.locator("#clawDeviceManagerToggle").get_attribute("aria-expanded") == "false"
    assert not errors
    page.close()


def test_authoritative_empty_directory_and_logged_out_are_distinct(browser, server):
    page, errors = open_claw(browser, server)
    fixture = {"status": 200, "body": json.dumps(payload([]))}

    def mock(route):
        route.fulfill(
            status=fixture["status"], content_type="application/json",
            body=fixture["body"],
        )

    page.route("**" + ENDPOINT, mock)
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("현재 계정에서 확인된 컴퓨터가 없습니다", exact=False).wait_for()
    assert page.locator("#clawDeviceManagerList").is_hidden()
    fixture["status"] = 401
    fixture["body"] = "{}"
    page.locator(".claw-device-manager-refresh").click()
    page.get_by_text("로그인한 뒤", exact=False).wait_for()
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert not errors
    page.close()


def test_pending_device_read_is_aborted_on_close(browser, server):
    """Closing the view must cancel a pending owner GET, not just hide its rows."""
    page, errors = open_claw(browser, server)
    page.evaluate("""() => {
      const original = window.fetch.bind(window);
      window.__deviceReads = 0;
      window.__deviceAborts = 0;
      window.fetch = (url, options = {}) => {
        if (!String(url).includes("/api/claw/local-access/devices"))
          return original(url, options);
        window.__deviceReads += 1;
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () => {
            window.__deviceAborts += 1;
            reject(new DOMException("aborted", "AbortError"));
          }, {once: true});
        });
      };
    }""")
    page.locator("#clawDeviceManagerToggle").click()
    page.wait_for_function("window.__deviceReads === 1")
    assert page.locator("#clawDeviceManagerPanel").get_attribute("aria-busy") == "true"
    page.locator(".claw-device-manager-close").click()
    page.wait_for_function("window.__deviceAborts === 1")
    assert page.locator("#clawDeviceManagerPanel").get_attribute("aria-busy") is None
    assert page.locator("#clawDeviceManagerPanel").is_hidden()
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert not errors, errors
    page.close()


def test_hung_device_read_recovers_without_false_online(browser, server):
    """A stalled directory cannot leave a permanent busy indicator or PC row."""
    page, errors = open_claw(browser, server)
    page.evaluate("""() => {
      const originalFetch = window.fetch.bind(window);
      const originalTimer = window.setTimeout.bind(window);
      window.__deviceAborts = 0;
      window.fetch = (url, options = {}) => {
        if (!String(url).includes("/api/claw/local-access/devices"))
          return originalFetch(url, options);
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () => {
            window.__deviceAborts += 1;
            reject(new DOMException("aborted", "AbortError"));
          }, {once: true});
        });
      };
      // Run the actual 12-second timeout branch without slowing the test.
      window.setTimeout = (fn, ms, ...args) =>
        originalTimer(fn, ms === 12000 ? 25 : ms, ...args);
    }""")
    page.locator("#clawDeviceManagerToggle").click()
    page.wait_for_function("window.__deviceAborts === 1")
    assert page.locator("#clawDeviceManagerPanel").get_attribute("aria-busy") is None
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert page.locator("#clawDeviceManagerList").is_hidden()
    assert "\uB2E4\uC2DC \uC2DC\uB3C4" in page.locator("#clawDeviceManagerStatus").inner_text()
    assert not errors, errors
    page.close()


def test_owner_change_cancels_old_read_before_new_owner_status(browser, server):
    """Owner-change events cancel outstanding requests and never show old PCs."""
    page, errors = open_claw(browser, server)
    page.evaluate("""() => {
      const original = window.fetch.bind(window);
      window.__calls = 0;
      window.__aborts = 0;
      window.fetch = (url, options = {}) => {
        if (!String(url).includes("/api/claw/local-access/devices"))
          return original(url, options);
        window.__calls++;
        if (window.__calls === 1) return new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () => {
            window.__aborts++;
            reject(new DOMException("aborted", "AbortError"));
          }, {once: true});
        });
        return Promise.resolve(new Response(
          JSON.stringify({ok:true, available:true, ownerScoped:true,
            devices:[{deviceId:"new-owner",deviceName:"Account B",
              platform:"Windows",state:"OFFLINE",usable:false}]}),
          {status:200,headers:{"Content-Type":"application/json"}}));
      };
    }""")
    page.locator("#clawDeviceManagerToggle").click()
    page.wait_for_function("window.__calls === 1")
    page.evaluate('window.dispatchEvent(new Event("padiem:account-changed"))')
    page.wait_for_function("window.__calls === 2 && window.__aborts === 1")
    page.get_by_text("Account B", exact=True).wait_for()
    assert page.locator("#clawDeviceManagerList li").count() == 1
    assert     page.locator("#clawDeviceManagerList li button").is_disabled()
    assert page.locator("#clawDeviceManagerPanel").get_attribute("aria-busy") is None
    assert not errors, errors
    page.close()


def unavailable_envelope(reason):
    """The reviewed HTTP 200 unavailable envelope from the server route."""
    return {"ok": True, "available": False, "reason": reason}


def test_unconfigured_and_read_failed_reasons_are_distinct(browser, server):
    """The two reviewed reason codes must not collapse into one message."""
    page, errors = open_claw(browser, server)
    fixture = {"body": json.dumps(unavailable_envelope("device_directory_unconfigured"))}
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json", body=fixture["body"],
    ))
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 서비스가 아직 설정되지 않았습니다", exact=False).wait_for()
    status = page.locator("#clawDeviceManagerStatus").inner_text()
    assert "조회 중 문제가 발생했습니다" not in status
    assert page.locator("#clawDeviceManagerList li").count() == 0
    # A transient read failure is a different, retry-oriented message.
    fixture["body"] = json.dumps(unavailable_envelope("device_directory_read_failed"))
    page.locator(".claw-device-manager-refresh").click()
    page.get_by_text("연결 서비스 조회 중 문제가 발생했습니다", exact=False).wait_for()
    status = page.locator("#clawDeviceManagerStatus").inner_text()
    assert "설정되지 않았습니다" not in status
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert not errors, errors
    page.close()


def test_read_failure_recovers_on_retry(browser, server):
    """A read failure must be recoverable rather than sticky."""
    page, errors = open_claw(browser, server)
    fixture = {"body": json.dumps(unavailable_envelope("device_directory_read_failed"))}
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json", body=fixture["body"],
    ))
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 서비스 조회 중 문제가 발생했습니다", exact=False).wait_for()
    fixture["body"] = json.dumps(payload([online("home", "집 컴퓨터")]), ensure_ascii=False)
    page.locator(".claw-device-manager-refresh").click()
    page.locator("#clawDeviceManagerList li").first.wait_for()
    assert page.locator("#clawDeviceManagerList li").count() == 1
    assert "조회 중 문제가 발생했습니다" not in page.locator(
        "#clawDeviceManagerStatus"
    ).inner_text()
    assert not errors, errors
    page.close()


def test_unknown_reason_and_server_text_never_reach_the_ui(browser, server):
    """Only reviewed reason codes are interpreted; no server text is rendered."""
    page, errors = open_claw(browser, server)
    secret = "internal-broker-detail-9931"
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "ok": True, "available": False,
            "reason": "device_directory_unknown_internal",
            "message": secret, "detail": secret,
        }),
    ))
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("연결 서비스가 아직 준비되지 않았습니다", exact=False).wait_for()
    panel = page.locator("#clawDeviceManagerPanel").inner_text()
    assert secret not in panel
    # Neither of the two reviewed messages is claimed for an unknown reason.
    assert "설정되지 않았습니다" not in panel
    assert "조회 중 문제가 발생했습니다" not in panel
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert not errors, errors
    page.close()


def test_error_response_message_is_never_echoed(browser, server):
    """An error body must not be displayed; auth keeps the safe refusal."""
    page, errors = open_claw(browser, server)
    secret = "upstream-token-abc"
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=401, content_type="application/json",
        body=json.dumps({
            "ok": False,
            "error": {"code": "device_directory_auth_required", "message": secret},
        }),
    ))
    page.locator("#clawDeviceManagerToggle").click()
    page.get_by_text("로그인한 뒤", exact=False).wait_for()
    assert secret not in page.locator("#clawDeviceManagerPanel").inner_text()
    assert page.locator("#clawDeviceManagerList li").count() == 0
    assert not errors, errors
    page.close()
