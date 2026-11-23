"""#8029 contract: when the Claw device directory is unconfigured, the Claw
connection card still reaches a truthful stage - from the connect flow's one
shared pairing read, never a parallel fetch, and never for a guest.

Production composes no broker device-directory source yet, so the directory
route refuses with device_directory_unconfigured and the card used to stay at
'확인 불가' forever while the #7964 guidance never opened. #8029 안2: inside
that one refusal branch only, an authenticated owner joins the shared read
(PadiemPcConnectFlow.read) and the card maps the account's own links:

  0 active links            -> unregistered + the #7964 guide dialog opens
  link observed online      -> CONNECTED row
  link without observation  -> ACTION_REQUIRED row (never a fake 'connected')

A configured directory keeps the existing determination untouched, a guest
keeps the #8011 zero-/api/pc contract, and tampering the card's guard away
still cannot re-introduce a guest fetch (the flow's own guest guard refuses
without a network call and the fallback fails closed).

The server-side route already projects linked rows when it can (#5573), so in
production the refusal reaches the fallback almost only for accounts without
links; the link-mapping branch below is the defensive half of the contract.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.claw_screen_source import app_js, claw_automation_store_py, claw_manager_js, claw_routes_py, read

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

# Optional browser suite: skip where Playwright is not installed.
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
MANAGER = STATIC / "claw-device-manager.js"

GUEST = {"ok": True, "authenticated": False, "ready": True, "user": None}
SIGNED_IN = {"ok": True, "authenticated": True, "ready": True,
             "user": {"name": "QA", "email": "qa@example.test"}}

DIRECTORY_REFUSAL = {"ok": True, "available": False,
                     "reason": "device_directory_unconfigured",
                     "scopeStatus": "not_configured",
                     "brokerScope": "product_fallback"}

LINK_ONLINE = {"link_id": "l1", "state": "active", "online": True,
               "mesh_node_id": "node//mesh-node-1", "label": "사무실 PC"}
LINK_UNSEEN = {"link_id": "l2", "state": "active", "online": False,
               "mesh_node_id": "node//mesh-node-2", "label": "집 PC"}


class _StaticServer:
    """Read-only http.server over the static tree."""

    def __init__(self):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(STATIC), **kwargs)

            def log_message(self, *args):
                pass

        self.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.web.server_address[1]}/index.html"

    def shutdown(self):
        self.web.shutdown()


def _stub_api(page):
    # Registration order matters: the generic answer first, then the specific
    # overrides — Playwright serves the LAST matching route.
    page.route(re.compile(r".*/api/.*$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json", body="{}"))


def _stub_auth(page, status_body):
    page.route(re.compile(r".*/api/auth/status$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps(status_body, ensure_ascii=False)))


def _stub_directory_unconfigured(page, gets):
    def handler(route):
        if route.request.method == "GET":
            gets.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(DIRECTORY_REFUSAL, ensure_ascii=False))
    page.route(re.compile(r".*/api/claw/local-access/devices$"), handler)


def _stub_directory_payload(page, gets, body):
    def handler(route):
        if route.request.method == "GET":
            gets.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))
    page.route(re.compile(r".*/api/claw/local-access/devices$"), handler)


def _stub_pairings(page, links):
    page.route(re.compile(r".*/api/pc/pairings$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps({"ok": True, "links": links, "codes": []},
                                   ensure_ascii=False)))


def _watch_pairings(cdp) -> list[str]:
    """Initiating script URL of every /api/pc/pairings request."""
    seen: list[str] = []

    def on_request(params):
        url = params["request"]["url"]
        if not url.endswith("/api/pc/pairings"):
            return
        stack = params.get("initiator", {}).get("stack", {}).get("callFrames", [])
        script = ""
        for frame in stack:
            frame_url = frame.get("url", "")
            if frame_url.endswith(".js"):
                script = frame_url.rsplit("/", 1)[-1]
                break
        seen.append(script or "?")

    cdp.on("Network.requestWillBeSent", on_request)
    return seen


def _open_claw(page, server, signed_in):
    """Load the static shell signed in/out and simulate the Claw home view.

    The guide's home() guard also requires the general view, which app.js owns
    in production; the test sets the same presentation state directly.
    """
    _stub_auth(page, SIGNED_IN if signed_in else GUEST)
    page.goto(server, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_function(
        "() => window.PadiemAuthGate?.authenticated() === "
        + ("true" if signed_in else "false"), timeout=15000)
    page.locator("#clawDeviceManagerToggle").wait_for(state="attached")
    page.evaluate("""() => {
      document.querySelector(".app-shell").setAttribute("data-state", "claw");
      const ws = document.getElementById("clawWorkspace");
      ws.hidden = false;
      ws.setAttribute("data-view", "general");
    }""")


def _open_manager(page):
    page.evaluate("document.getElementById('clawDeviceManagerToggle').click()")


def _status_text(page):
    return page.evaluate(
        "() => (document.querySelector('.claw-device-manager-status')||{})"
        ".textContent || ''")


def _guide_state(page):
    return page.evaluate("""() => {
      const d = document.getElementById('clawConnectionGuide');
      return d ? {open: d.open === true, marker: d.dataset.pcUnconnected || ""}
               : null;
    }""")


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_unconfigured_guest_keeps_zero_pc_calls():
    """#8011: a guest never reaches the fallback - runLoad returns before any
    directory read, so no /api/pc/* request and a clean console."""
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            _stub_directory_unconfigured(page, directory_gets)
            _stub_pairings(page, [])
            pc_calls: list[str] = []
            page.on("request", lambda req: pc_calls.append(req.url) if
                    "/api/pc/" in req.url else None)
            console_errors: list[tuple[str, str]] = []
            page.on("console", lambda m: console_errors.append(
                (m.location.get("url") or "", m.text[:120])) if
                m.type == "error" else None)
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            _open_claw(page, server.base, signed_in=False)
            _open_manager(page)
            page.wait_for_function(
                "() => (document.querySelector('.claw-device-manager-status')||{})"
                ".textContent?.includes('로그인한 뒤')", timeout=10000)
            page.wait_for_timeout(1000)
            browser.close()
    finally:
        server.shutdown()
    assert pc_calls == [], pc_calls[:3]
    assert directory_gets == [], directory_gets[:3]
    assert not page_errors, page_errors[:3]
    pc_console = [entry for entry in console_errors if "/api/pc/" in entry[0]]
    assert pc_console == [], pc_console[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_unconfigured_signed_in_no_links_shows_unregistered_and_opens_guide():
    """링크 0건 -> unregistered copy and the #7964 guide dialog open with the
    PC-unconnected marker (its action hands over to the connect flow)."""
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            _stub_directory_unconfigured(page, directory_gets)
            _stub_pairings(page, [])
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            attributed = _watch_pairings(cdp)
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            _open_claw(page, server.base, signed_in=True)
            _open_manager(page)
            page.wait_for_function(
                "() => (document.querySelector('.claw-device-manager-status')||{})"
                ".textContent?.includes('설치·연결 안내')", timeout=15000)
            page.wait_for_function(
                "() => document.getElementById('clawConnectionGuide')?.open === true",
                timeout=3000)
            guide = _guide_state(page)
            rows = page.evaluate(
                "() => document.querySelectorAll('.claw-device-manager-item').length")
            browser.close()
    finally:
        server.shutdown()
    assert guide == {"open": True, "marker": "true"}, guide
    assert rows == 0, rows
    # The read is the flow's shared one - never a request started by the card.
    assert attributed and set(attributed) == {"pc-connect-flow.js"}, attributed
    assert not page_errors, page_errors[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_unconfigured_signed_in_online_link_renders_connected():
    """링크 있음·online -> a CONNECTED row the owner can pick; no guide."""
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            _stub_directory_unconfigured(page, directory_gets)
            _stub_pairings(page, [LINK_ONLINE])
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            _open_claw(page, server.base, signed_in=True)
            _open_manager(page)
            page.wait_for_function(
                "() => document.querySelectorAll('.claw-device-manager-item').length === 1",
                timeout=15000)
            chip = page.evaluate("""() => {
              const item = document.querySelector('.claw-device-manager-item');
              const state = item?.querySelector('.claw-device-manager-state');
              const pick = item?.querySelector('.claw-device-manager-select');
              return {state: state?.dataset.state || "",
                      pickDisabled: pick ? pick.disabled : null};
            }""")
            page.wait_for_timeout(500)
            guide = _guide_state(page)
            browser.close()
    finally:
        server.shutdown()
    assert chip["state"] == "CONNECTED", chip
    assert chip["pickDisabled"] is False, chip
    assert guide == {"open": False, "marker": ""}, guide
    assert not page_errors, page_errors[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_unconfigured_signed_in_unseen_link_renders_action_required():
    """링크 있음·관측 없음 -> ACTION_REQUIRED, never a fake 'connected'."""
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            _stub_directory_unconfigured(page, directory_gets)
            _stub_pairings(page, [LINK_UNSEEN])
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            _open_claw(page, server.base, signed_in=True)
            _open_manager(page)
            page.wait_for_function(
                "() => document.querySelectorAll('.claw-device-manager-item').length === 1",
                timeout=15000)
            chip = page.evaluate("""() => {
              const item = document.querySelector('.claw-device-manager-item');
              const state = item?.querySelector('.claw-device-manager-state');
              const pick = item?.querySelector('.claw-device-manager-select');
              return {state: state?.dataset.state || "",
                      pickDisabled: pick ? pick.disabled : null};
            }""")
            page.wait_for_timeout(500)
            guide = _guide_state(page)
            browser.close()
    finally:
        server.shutdown()
    assert chip["state"] == "ACTION_REQUIRED", chip
    # #5573: a linked own PC stays selectable without an online observation.
    assert chip["pickDisabled"] is False, chip
    assert guide == {"open": False, "marker": ""}, guide
    assert not page_errors, page_errors[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_configured_directory_determination_unchanged():
    """구성 환경: the directory rows render as before and the card never
    touches the pairing read - the fallback is unreachable by construction."""
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            body = {"ok": True, "available": True, "ownerScoped": True,
                    "devices": [{"deviceId": "node//mesh-node-9",
                                 "deviceName": "구성된 PC", "platform": None,
                                 "state": "CONNECTED", "usable": True,
                                 "revoked": False, "expired": False,
                                 "executable": True, "selectable": True}]}
            _stub_directory_payload(page, directory_gets, body)
            _stub_pairings(page, [LINK_ONLINE])
            pc_calls: list[str] = []
            page.on("request", lambda req: pc_calls.append(req.url) if
                    "/api/pc/pairings" in req.url else None)
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            attributed = _watch_pairings(cdp)
            _open_claw(page, server.base, signed_in=True)
            # Let any boot-time read settle, then let the flow's dedupe window
            # expire so a wrongly-issued fallback read would be visible.
            for _ in range(50):
                if pc_calls:
                    break
                page.wait_for_timeout(100)
            before = len(pc_calls)
            page.wait_for_timeout(2500)
            _open_manager(page)
            page.wait_for_function(
                "() => document.querySelectorAll('.claw-device-manager-item').length === 1",
                timeout=15000)
            name = page.evaluate(
                "() => (document.querySelector('.claw-device-manager-item strong')||{})"
                ".textContent || ''")
            page.wait_for_timeout(500)
            guide = _guide_state(page)
            browser.close()
    finally:
        server.shutdown()
    assert name == "구성된 PC", name
    assert len(pc_calls) == before, (before, len(pc_calls))
    assert guide == {"open": False, "marker": ""}, guide
    assert not page_errors, page_errors[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_unconfigured_signed_in_shared_read_once():
    """공유 읽기 1회: opening the card adds exactly one pairings read through
    the flow, and a refresh inside the dedupe window adds none."""
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            _stub_directory_unconfigured(page, directory_gets)
            _stub_pairings(page, [LINK_ONLINE])
            pc_calls: list[str] = []
            page.on("request", lambda req: pc_calls.append(req.url) if
                    "/api/pc/pairings" in req.url else None)
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            _open_claw(page, server.base, signed_in=True)
            for _ in range(50):
                if pc_calls:
                    break
                page.wait_for_timeout(100)
            before = len(pc_calls)
            # Expire the flow's dedupe window so the fallback read is a real,
            # observable fetch instead of a cached join.
            page.wait_for_timeout(2500)
            _open_manager(page)
            page.wait_for_function(
                "() => document.querySelectorAll('.claw-device-manager-item').length === 1",
                timeout=15000)
            after_open = len(pc_calls)
            # The refresh re-runs the refusal branch and must join the cached
            # answer, not fire a second request.
            page.evaluate(
                "document.querySelector('.claw-device-manager-refresh').click()")
            deadline = 100
            while len(directory_gets) < 2 and deadline:
                page.wait_for_timeout(50)
                deadline -= 1
            page.wait_for_timeout(1500)
            browser.close()
    finally:
        server.shutdown()
    assert after_open == before + 1, (before, after_open)
    assert len(pc_calls) == after_open, (after_open, len(pc_calls))
    assert not page_errors, page_errors[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_card_guard_removed_guest_still_zero_pc_calls():
    """변조 1회: strip the card's own guards (runLoad guest gate + fallback
    gate). The guest contract must still hold - the flow's own guest guard
    refuses without a network call and the fallback fails closed."""
    source = claw_manager_js()
    run_gate = "if (window.PadiemAuthGate?.authenticated() === false) {"
    assert run_gate in source
    card_gate = "const flow = signedIn ? window.PadiemPcConnectFlow : null;"
    assert card_gate in source
    tampered = source.replace(run_gate, "if (false) {", 1).replace(
        card_gate, "const flow = window.PadiemPcConnectFlow;", 1)
    assert tampered != source

    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            directory_gets: list[str] = []
            _stub_directory_unconfigured(page, directory_gets)
            _stub_pairings(page, [])
            page.route(re.compile(r".*/claw-device-manager\.js$"),
                       lambda route, req: route.fulfill(
                           status=200, content_type="text/javascript",
                           body=tampered))
            pc_calls: list[str] = []
            page.on("request", lambda req: pc_calls.append(req.url) if
                    "/api/pc/" in req.url else None)
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            _open_claw(page, server.base, signed_in=False)
            _open_manager(page)
            # The tampered path really ran the fallback: the panel ended at
            # the unconfigured refusal (fail closed), not at the guest login
            # copy and not at unregistered.
            page.wait_for_function(
                "() => (document.querySelector('.claw-device-manager-status')||{})"
                ".textContent?.includes('아직 설정되지 않았습니다')", timeout=15000)
            page.wait_for_timeout(1000)
            browser.close()
    finally:
        server.shutdown()
    assert pc_calls == [], pc_calls[:3]
    assert directory_gets, "the tampered runLoad must reach the directory read"
    assert not page_errors, page_errors[:3]
