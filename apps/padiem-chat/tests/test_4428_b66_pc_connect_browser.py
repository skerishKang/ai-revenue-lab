"""#4428 B66 Connect: opt-in, read-only device visibility in real Chromium."""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "static"
DEVICE_ENDPOINT = "/api/claw/local-access/devices"


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/__b66_pc_fixture.html":
            # Isolated B66 component test: production index/load order is
            # independently pinned by the static contract test. Running
            # unrelated Chat auth bootstrap races here is not B66 coverage.
            body = (
                '<!doctype html><html lang="ko"><head>'
                '<meta charset="utf-8">'
                '<link rel="stylesheet" href="/b66-quote-runtime.css">'
                '</head><body>'
                '<nav class="side-nav"><button id="clawNavButton">Claw</button></nav>'
                '<script src="/claw-local-handoff.js"></script>'
                '<script src="/b66-quote-runtime.js"></script>'
                '</body></html>'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), StaticHandler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/__b66_pc_fixture.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


def envelope(devices):
    return {"ok": True, "available": True, "ownerScoped": True, "devices": devices}


def pc(device_id, name, *, online=True, revoked=False):
    return {
        "deviceId": device_id, "deviceName": name, "platform": "Windows",
        "state": "REVOKED" if revoked else "CONNECTED" if online else "OFFLINE",
        "usable": online and not revoked, "revoked": revoked,
    }


def ready_page(browser, server, width=1280):
    page = browser.new_page(viewport={"width": width, "height": 800})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/b66/runtime-config", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "ok": True, "enabled": True, "embed_url": "https://quote.example.test/embed.html",
            "origin": "https://quote.example.test",
            # Simulated future server-approved B66 device.list product grant.
            # Current Production B66 runtime-config omits this; default OFF.
            "pc_device_list_enabled": True,
        }),
    ))
    page.route("**/api/b66/saved-skills?limit=20", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({
            "ok": True,
            "skills": [{"saved_skill_id": "b66skill_" + "a" * 32, "skill_name": "Template"}],
        }),
    ))
    page.route("**/api/b66/quote/models", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "default_model_id": "test/model",
                         "models": [{"model_id": "test/model", "name": "Test Model"}]}),
    ))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#b66QuoteNavButton").wait_for(state="attached")
    page.evaluate("""() => window.dispatchEvent(
      new CustomEvent("padiem:capabilitychange", {detail:{auth:{authenticated:true}}})
    )""")
    page.locator("#b66QuoteNavButton").wait_for(state="visible")
    if width <= 640:
        # Isolate dialog behavior at mobile width from the separately tested
        # responsive sidebar overlay; this is not a mobile nav acceptance.
        page.locator("#b66QuoteNavButton").evaluate("(node) => node.click()")
    else:
        page.locator("#b66QuoteNavButton").click()
    page.locator("#b66QuotePcToggle").wait_for(state="visible")
    return page, errors


@pytest.mark.parametrize("width", [390, 1280])
def test_b66_opt_in_pc_list_and_refresh_revoked_no_commands(browser, server, width):
    page, errors = ready_page(browser, server, width)
    request_log = []
    fixture = {"payload": envelope([
        pc("home", "집 PC"),
        pc("office", "사무실 PC", online=False),
    ])}

    def mock(route):
        request_log.append((route.request.method, route.request.url))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(fixture["payload"], ensure_ascii=False))

    page.route("**" + DEVICE_ENDPOINT, mock)
    assert not request_log
    page.locator("#b66QuotePcToggle").click()
    page.get_by_text("집 PC", exact=True).wait_for()
    assert page.locator("#b66QuotePcList li").count() == 2
    assert len(request_log) == 1 and request_log[0][0] == "GET"
    assert page.locator("#b66QuotePcList").get_by_role("button").count() == 0
    fixture["payload"] = envelope([pc("home", "집 PC", online=False),
                                   pc("office", "사무실 PC", revoked=True)])
    page.locator("#b66QuotePcRefresh").click()
    page.get_by_text("연결 해제", exact=True).wait_for()
    assert page.locator("#b66QuotePcList [data-state='online']").count() == 0
    assert len(request_log) == 2 and all(m == "GET" for m, _ in request_log)
    assert not errors, errors
    page.close()


def test_b66_fail_closed_logout_and_injection(browser, server):
    page, errors = ready_page(browser, server)
    fixture = {"status": 200, "body": json.dumps(envelope([
        {**pc("home", '<img src=x onerror="window.hacked=true">'),
         "credential": "SUPER_PRIVATE_TOKEN", "stdout": "SUPER_PRIVATE_TOKEN"},
    ]))}
    requests = []

    def mock(route):
        requests.append(route.request.method)
        route.fulfill(status=fixture["status"], content_type="application/json",
                      body=fixture["body"])

    page.route("**" + DEVICE_ENDPOINT, mock)
    page.locator("#b66QuotePcToggle").click()
    page.locator("#b66QuotePcList li").first.wait_for()
    assert page.locator("#b66QuotePcList img").count() == 0
    assert page.evaluate("window.hacked === true") is False
    assert "SUPER_PRIVATE_TOKEN" not in page.locator("#b66QuotePcPanel").inner_text()

    fixture["body"] = json.dumps({"ok": True, "available": True, "ownerScoped": False,
                                  "devices": [pc("foreign", "Other user PC")]})
    page.locator("#b66QuotePcRefresh").click()
    page.get_by_text("PC 연결 서비스가 아직 준비되지 않았습니다", exact=False).wait_for()
    assert page.locator("#b66QuotePcList li").count() == 0

    fixture["status"] = 401
    page.locator("#b66QuotePcRefresh").click()
    page.get_by_text("PADIEM 계정에 로그인한 뒤", exact=False).wait_for()
    assert page.locator("#b66QuotePcList li").count() == 0
    page.evaluate("""() => window.dispatchEvent(new CustomEvent(
      "padiem:account-changed", {detail:{account:"different"}}))""")
    assert page.locator("#b66QuotePcPanel").is_hidden()
    assert page.locator("#b66QuotePcToggle").get_attribute("aria-expanded") == "false"
    assert all(x == "GET" for x in requests)
    assert not errors, errors
    page.close()
