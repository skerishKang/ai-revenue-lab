"""#5553 — the handoff page closes only after the approval settles.

The intermediate connector page forwards one `pc_offer_ready` message and
performs no approval. Chromium verifies the close contract:

* launching the app is not a connection: the page stays open while the owner
  approval is still pending;
* an approved settlement closes the page;
* a failed settlement closes the page too, so Claw shows the failure;
* a window the browser did not open cannot close itself, so only then the
  manual "Claw로 돌아가기" way back appears.

The real page markup and script are served by a local HTTP server; the real
route authorization stays covered by test_4139_owner_setup_page.py.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pytest

from app import connector_owner_setup_page as setup

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed"
)

REF = "link." + "a" * 32
SETUP_PATH = "/api/claw/connector/enrollments/setup"
SCRIPT_PATH = "/api/claw/connector/enrollments/setup.js"

PARENT_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Claw</title></head><body>
<button id="open" type="button">open</button>
<script>
  const ref = new URL(location.href).searchParams.get("ref");
  let channel = null;
  window.openSetup = () => {
    channel = new BroadcastChannel("padiem-claw-pc-connect-v1");
    channel.onmessage = (event) => { window.__offer = event.data; };
    window.__popup = window.open(
      "/api/claw/connector/enrollments/setup?request_ref=" + ref, "pc-handoff");
  };
  window.reply = (type) => {
    if (channel) channel.postMessage({type: type, request_ref: ref});
  };
</script>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server contract
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PARENT_HTML.replace(
                "<title>Claw</title>",
                "<title>Claw</title>",
            )
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == SETUP_PATH:
            query = parse_qs(parsed.query)
            if query.get("request_ref") != [REF]:
                self.send_error(400)
                return
            payload = setup._HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == SCRIPT_PATH:
            payload = setup._SCRIPT.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def log_message(self, *args):  # keep the test output quiet
        return


@pytest.fixture(scope="module")
def handoff_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:  # pragma: no cover - skipped by the marker
        pytest.skip("playwright is not installed")
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()


def _open_handoff(browser, base):
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{base}/?ref={REF}")
    with page.expect_popup() as popup_info:
        page.evaluate("window.openSetup()")
    popup = popup_info.value
    popup.wait_for_load_state()
    page.wait_for_function("() => window.__offer && window.__offer.type === 'pc_offer_ready'")
    return context, page, popup


@requires_browser
def test_the_page_stays_open_while_the_approval_is_pending(browser, handoff_server):
    context, page, popup = _open_handoff(browser, handoff_server)
    try:
        assert "Padiem Claw 연결 승인을 기다리는 중입니다." in popup.inner_text("#pending-state")
        # An app launch is not a settlement: nothing closes on its own.
        popup.wait_for_timeout(1500)
        assert popup.is_closed() is False
        assert "처리되었습니다" not in popup.inner_text("#pending-state")
        assert popup.is_visible("#pending-return") is False
    finally:
        context.close()


@requires_browser
def test_an_approved_settlement_closes_the_page(browser, handoff_server):
    context, page, popup = _open_handoff(browser, handoff_server)
    try:
        page.evaluate("window.reply('pc_offer_approved')")
        popup.wait_for_event("close", timeout=5000)
        assert popup.is_closed() is True
    finally:
        context.close()


@requires_browser
def test_a_failed_settlement_closes_the_page_too(browser, handoff_server):
    context, page, popup = _open_handoff(browser, handoff_server)
    try:
        page.evaluate("window.reply('pc_offer_failed')")
        popup.wait_for_event("close", timeout=5000)
        assert popup.is_closed() is True
    finally:
        context.close()


@requires_browser
def test_a_blocked_close_shows_the_way_back(browser, handoff_server):
    context = browser.new_context()
    page = context.new_page()
    try:
        # This tab was not opened by script, so the browser refuses window.close().
        page.goto(f"{handoff_server}{SETUP_PATH}?request_ref={REF}")
        page.evaluate(
            """() => {
              const channel = new BroadcastChannel("padiem-claw-pc-connect-v1");
              channel.postMessage({type: "pc_offer_approved", request_ref: %r});
              channel.close();
            }""" % REF
        )
        page.wait_for_selector("#pending-return", state="visible", timeout=5000)
        assert page.is_closed() is False
        assert "Claw로 돌아가기" in page.inner_text("#pending-return")
    finally:
        context.close()


HOME_JS = (Path(__file__).resolve().parents[1] / "static" / "claw-home-choices.js").read_text(
    encoding="utf-8"
)


def test_the_original_claw_tab_reports_the_settlement_after_the_one_post():
    # The reply is sent only after the single approve attempt resolved, and it
    # carries the same opaque request ref the offer arrived with.
    assert "void approveReadyPc(data.request_ref).then((approved) => {" in HOME_JS
    assert "replyPcSettlement(data.request_ref, approved === true);" in HOME_JS
    assert 'type: approved ? "pc_offer_approved" : "pc_offer_failed",' in HOME_JS
    # A rejected context cannot approve, so it settles as a failure instead of
    # leaving the handoff page waiting for a reply that will never come.
    rejected = HOME_JS.index('pcStage("offer_context_rejected")')
    assert "replyPcSettlement(data.request_ref, false);" in HOME_JS[rejected:rejected + 160]
    # A rejected promise is also a settled failure, never a silent wait.
    assert "}).catch(() => {" in HOME_JS
    assert '"request_ref": requestRef' in HOME_JS or "request_ref: requestRef" in HOME_JS
    # The handoff page itself still performs no approval request.
    assert "/api/claw/connector/enrollments/approve-link" not in setup._SCRIPT


def test_the_settlement_messages_are_the_only_close_signal():
    assert "pc_offer_approved" in setup._SCRIPT and "pc_offer_failed" in setup._SCRIPT
    assert "pc_offer_ready" in setup._SCRIPT
    # Launching the connector is never a settlement: the close runs from the
    # one settlement call site, and the only close call is that one.
    assert setup._SCRIPT.count("settle(data.type);") == 1
    assert setup._SCRIPT.count("window.close()") == 1
