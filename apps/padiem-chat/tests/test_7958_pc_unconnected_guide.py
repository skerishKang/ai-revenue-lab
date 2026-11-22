"""#7958 — the Claw PC card must guide an owner with no connected PC.

An unconnected card click opens the canonical connection guide instead of
issuing an unknown custom URL scheme. The connected path still issues the
scheme and keeps its receiver/approval order.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        launched = pw.chromium.launch(headless=True)
        yield launched
        launched.close()


def _open_claw(browser, server, *, pc_phase):
    page = browser.new_page(viewport={"width": 1440, "height": 950})
    page.route("**/api/auth/status", lambda route: route.fulfill(json={
        "ready": True, "authenticated": True, "session_state": "signed_in",
        "user": {"name": "Synthetic User"}, "history_ready": True,
    }))
    devices = [] if pc_phase == "unregistered" else [
        {"deviceId": "device-synthetic", "state": "OFFLINE", "usable": False}
    ]
    page.route("**/api/claw/local-access/devices", lambda route: route.fulfill(json={
        "ok": True, "available": True, "ownerScoped": True,
        "usagePaused": False, "devices": devices,
    }))
    page.route("**/api/pc/pairings", lambda route: route.fulfill(json={
        "ok": True, "links": [],
    }))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_function("() => window.PadiemAuthGate?.authenticated() === true")
    page.wait_for_timeout(500)
    page.evaluate("""(phase) => {
      document.querySelector(".app-shell").setAttribute("data-state", "claw");
      document.querySelector(".sidebar-account").setAttribute("data-account-state", "signed_in");
      const workspace = document.getElementById("clawWorkspace");
      workspace.hidden = false;
      workspace.dataset.view = "general";
      document.querySelector('[data-claw-connection="pc"]').dataset.connectionState = "off";
      document.querySelector('[data-claw-card="computer"]').dataset.pcPhase = phase;
      window.__padiemPcConnectStages = [];
    }""", pc_phase)
    page.wait_for_function("""() => {
      const card = document.getElementById("clawComputerWorkspace");
      return Boolean(card && document.getElementById("clawConnectionGuide"));
    }""")
    return page


def test_unconnected_card_opens_guide_without_native_scheme(browser, server):
    page = _open_claw(browser, server, pc_phase="unregistered")
    page.locator("#clawComputerWorkspace").click()
    page.wait_for_function("() => document.getElementById('clawConnectionGuide').open === true")
    stages = page.evaluate("() => window.__padiemPcConnectStages || []")
    assert "native_uri_issued" not in stages
    assert page.locator("#clawConnectionGuideTitle").inner_text().strip()
    page.close()


def test_unconnected_guide_action_opens_install_flow_without_a_scheme(browser, server):
    page = _open_claw(browser, server, pc_phase="unregistered")
    page.locator("#clawComputerWorkspace").click()
    page.wait_for_function("() => document.getElementById('clawConnectionGuide').open === true")
    page.locator("#clawConnectionGuideAction").click()
    page.wait_for_function("""() => {
      const backdrop = document.querySelector('.pc-connect-backdrop');
      return Boolean(backdrop && backdrop.hidden === false);
    }""")
    stages = page.evaluate("() => window.__padiemPcConnectStages || []")
    assert "native_uri_issued" not in stages
    assert page.evaluate("() => document.getElementById('clawConnectionGuide').open") is False
    page.close()


def test_connected_card_keeps_the_existing_launch_path(browser, server):
    page = _open_claw(browser, server, pc_phase="online")
    page.locator("#clawComputerWorkspace").click()
    page.wait_for_function("""() => (window.__padiemPcConnectStages || [])
      .includes("native_uri_issued")""")
    assert page.locator("#clawConnectionGuide").get_attribute("open") is None
    page.close()
