"""B62 Padiem Chat / B54 Padiem Claw — the composer computer connection status.

Load-bearing regressions for the small status control that sits in the
top-right corner of the shared Chat/Claw message composer.

The contract this file pins:

* the control is a pure view over the EXISTING device directory module, so
  the server stays the only authority for the connection state and the
  directory endpoint keeps exactly one reader;
* the control opens the EXISTING computer connection management surface, so
  no new panel, pairing, registration or authentication is introduced;
* the control never covers the message text, the send control or the other
  composer controls, and it never changes the height of the fixed composer;
* nothing is displayed as connected before the server confirmed it.

The static contract tests below run everywhere (the required CI lane installs
no browser), so Playwright is optional here and only the real browser checks
are skipped when it is absent.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None


requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
INDEX = STATIC / "index.html"
STATUS_JS = STATIC / "claw-composer-connection-status.js"
STATUS_CSS = STATIC / "claw-composer-connection-status.css"
MANAGER_JS = STATIC / "claw-device-manager.js"

ENDPOINT = "/api/claw/local-access/devices"
WIDTHS = (320, 390)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # The composer opens many assets at once. The default 5 slot listen
    # backlog refuses connections in the middle of that burst, and a refused
    # script never runs, so the surfaces this file reads would be missing.
    request_queue_size = 128


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


def _directory(devices, selected: str | None = None) -> dict:
    payload: dict = {
        "ok": True,
        "available": True,
        "ownerScoped": True,
        "devices": devices,
    }
    if selected is not None:
        payload["selectedDeviceId"] = selected
    return payload


def _device(state: str, usable: bool, **extra) -> dict:
    row = {
        "deviceId": "home",
        "deviceName": "집 컴퓨터",
        "platform": "Windows",
        "state": state,
        "usable": usable,
        "expired": False,
        "revoked": False,
    }
    row.update(extra)
    return row


def _route_directory(page, payload, status: int = 200) -> None:
    page.route(
        re.compile(r".*/api/claw/local-access/devices$"),
        lambda route: route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        ),
    )


def _unroute_directory(page) -> None:
    page.unroute(re.compile(r".*/api/claw/local-access/devices$"))


def _ask_the_directory_module_to_read(page) -> None:
    """Ask the EXISTING device directory module for a fresh snapshot.

    The composer control has no request of its own: the device directory
    module stays the only reader of the canonical endpoint, and it publishes
    the confirmed snapshot for every consumer.
    """
    page.evaluate(
        "window.dispatchEvent(new CustomEvent('padiem:auth-state',"
        " { detail: { authenticated: true } }))"
    )


def _wait_state(page, state: str) -> None:
    """Wait for the composer control to show the expected server truth."""
    page.wait_for_function(
        """(expected) => {
          const button = document.getElementById('composerPcStatus');
          return button ? button.dataset.state === expected : false;
        }""",
        arg=state,
        timeout=10_000,
    )


def _open(page, server) -> None:
    """Open the composer and wait for the surfaces the assertions read.

    The static test server refuses connections during the asset burst, so a
    late script can arrive after the navigation. The assertions wait for the
    real surfaces instead of a fixed delay.
    """
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#composerPcStatus").wait_for(state="attached", timeout=15_000)
    page.locator("#clawDeviceManagerToggle").wait_for(state="attached", timeout=15_000)
    page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def test_the_control_is_a_view_over_the_existing_directory_snapshot() -> None:
    source = STATUS_JS.read_text(encoding="utf-8")
    # The published snapshot is the only input.
    assert "window.PadiemClawDeviceDirectory" in source
    assert "padiem:claw-device-directory" in source
    # No request of its own: the directory endpoint keeps exactly one reader.
    assert "fetch(" not in source
    assert ENDPOINT not in source
    for forbidden in (
        'method: "POST"',
        'method: "PUT"',
        'method: "DELETE"',
        "XMLHttpRequest",
    ):
        assert forbidden not in source
    # No new pairing, registration, identity or browser persistence.
    for forbidden in (
        "padiem-connector://",
        "BroadcastChannel",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert forbidden not in source


def test_the_existing_directory_module_publishes_the_confirmed_snapshot() -> None:
    source = MANAGER_JS.read_text(encoding="utf-8")
    # The module that already read the directory now publishes what it read.
    assert "window.PadiemClawDeviceDirectory = snapshot;" in source
    assert 'new CustomEvent("padiem:claw-device-directory"' in source
    # The published snapshot carries the reviewed facts only.
    assert "readCompleted:" in source
    assert "savedTargetId:" in source
    assert "canTarget:" in source
    # The directory endpoint is still read exactly once, by this module.
    assert f'const ENDPOINT = "{ENDPOINT}";' in source
    assert "deriveDeviceDirectory" in source


def test_the_control_opens_the_existing_management_surface() -> None:
    source = STATUS_JS.read_text(encoding="utf-8")
    # The existing device directory panel and its existing entry control.
    assert 'document.getElementById("clawDeviceManagerToggle")' in source
    # The existing Connectors computer card is the fallback surface.
    assert 'document.getElementById("connectorsNavButton")' in source
    assert 'document.getElementById("connectorComputerCard")' in source
    # The existing management panel is referenced, never built here. The
    # composer's control is the visible owner of that panel, so it carries the
    # expanded state and the control it points at.
    assert 'createElement("section")' not in source
    assert 'createElement("aside")' not in source
    assert 'createElement("dialog")' not in source
    assert "aria-expanded" in source
    assert "aria-controls" in source


def test_the_control_never_starts_a_polling_loop() -> None:
    source = STATUS_JS.read_text(encoding="utf-8")
    # The status is a view over the published snapshot: no timer, no request.
    assert "setInterval" not in source
    assert "requestAnimationFrame" not in source
    assert "setTimeout(refresh" not in source


def test_the_control_is_linked_into_the_shared_composer() -> None:
    index = INDEX.read_text(encoding="utf-8")
    assert 'href="./claw-composer-connection-status.css"' in index
    assert 'src="./claw-composer-connection-status.js"' in index
    source = STATUS_JS.read_text(encoding="utf-8")
    # Chat and Claw share one composer, so one control serves both lanes.
    assert 'document.getElementById("composerForm")' in source
    assert "form.append(button);" in source
    css = STATUS_CSS.read_text(encoding="utf-8")
    # The control is taken out of the flow, so the fixed composer keeps its
    # measured height.
    assert "position: absolute;" in css
    # The message text keeps the room the control occupies.
    assert "--composer-pc-status-gutter" in css
    assert "padding-right" in css
    # The theme sheets set the composer padding with !important, so the
    # reserved gutter rule has to outrank them.
    assert '#composerForm[data-pc-status="ready"] > #messageInput' in css


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------

MEASURE = """() => {
  const button = document.getElementById('composerPcStatus');
  const face = document.querySelector('.composer-pc-status-face');
  const input = document.getElementById('messageInput');
  const form = document.getElementById('composerForm');
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height,
             right: r.right, bottom: r.bottom, top: r.top, left: r.left };
  };
  const padding = input ? parseFloat(getComputedStyle(input).paddingRight) || 0 : 0;
  const inputRect = rect(input);
  return {
    present: Boolean(button),
    state: button ? button.dataset.state : null,
    label: document.querySelector('.composer-pc-status-label')
      ? document.querySelector('.composer-pc-status-label').textContent.trim() : null,
    ariaLabel: button ? button.getAttribute('aria-label') : null,
    tooltip: button ? button.getAttribute('data-padiem-tooltip') : null,
    button: rect(button),
    face: rect(face),
    input: inputRect,
    inputPaddingRight: padding,
    // The right edge the message text can actually reach.
    textRight: inputRect ? inputRect.right - padding : null,
    form: rect(form),
    formHeight: form ? form.getBoundingClientRect().height : null,
    send: rect(document.getElementById('sendButton')),
    attachment: rect(document.getElementById('attachmentButton')),
    search: rect(document.getElementById('webSearchButton')),
    model: rect(document.querySelector('.composer-tier-trigger')),
    mic: rect(document.getElementById('voiceMicButton')),
    horizontalOverflow:
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  };
}"""


def _overlaps(a, b) -> bool:
    if not a or not b:
        return False
    if a["width"] <= 0 or b["width"] <= 0:
        return False
    return not (
        a["right"] <= b["left"]
        or a["left"] >= b["right"]
        or a["bottom"] <= b["top"]
        or a["top"] >= b["bottom"]
    )


@requires_browser
@pytest.mark.parametrize("width", WIDTHS)
def test_the_control_reports_the_server_truth(browser, server, width) -> None:
    """Three states, and only the server decides which one is shown."""
    page = browser.new_page(viewport={"width": width, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    _route_directory(page, _directory([]))
    _open(page, server)
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "disconnected")
    measured = page.evaluate(MEASURE)
    assert measured["present"] is True
    assert measured["state"] == "disconnected"
    assert measured["label"] == "컴퓨터 미연결"
    assert "컴퓨터" in (measured["ariaLabel"] or "")
    assert measured["tooltip"] == measured["ariaLabel"]

    _unroute_directory(page)
    _route_directory(page, _directory([_device("CONNECTED", True)]))
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "connected")
    connected = page.evaluate(MEASURE)
    assert connected["state"] == "connected"
    assert connected["label"] == "PC 연결됨"

    _unroute_directory(page)
    _route_directory(page, _directory([_device("REVOKED", False, revoked=True)]))
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "unavailable")
    revoked = page.evaluate(MEASURE)
    assert revoked["state"] == "unavailable"
    assert revoked["label"] == "연결 확인 필요"

    # A server that cannot answer the directory is an "unavailable" state, never a
    # connected one.
    _unroute_directory(page)
    _route_directory(page, {"ok": False}, status=503)
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "unavailable")
    failed = page.evaluate(MEASURE)
    assert failed["state"] == "unavailable"
    assert failed["label"] == "연결 확인 필요"
    assert not errors, errors
    page.close()


@requires_browser
def test_the_claw_execution_target_decides_the_state(browser, server) -> None:
    """Claw already chose an execution target: that target's own state shows."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _route_directory(
        page,
        _directory(
            [
                _device("CONNECTED", True),
                {
                    "deviceId": "office",
                    "deviceName": "사무실 PC",
                    "platform": "Windows",
                    "state": "OFFLINE",
                    "usable": False,
                    "expired": False,
                    "revoked": False,
                },
            ],
            selected="office",
        ),
    )
    _open(page, server)
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "disconnected")
    measured = page.evaluate(MEASURE)
    assert measured["state"] == "disconnected"
    assert measured["label"] == "컴퓨터 미연결"
    assert not errors, errors
    page.close()


@requires_browser
def test_the_click_opens_the_existing_management_panel(browser, server) -> None:
    """One click reaches the existing computer connection management UI."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _route_directory(page, _directory([_device("CONNECTED", True)]))
    _open(page, server)
    page.click("#composerPcStatus")
    page.wait_for_timeout(900)
    opened = page.evaluate(
        """() => {
          const panel = document.getElementById('clawDeviceManagerPanel');
          const toggle = document.getElementById('clawDeviceManagerToggle');
          return {
            panelPresent: Boolean(panel),
            panelVisible: panel ? !panel.hidden : false,
            toggleExpanded: toggle ? toggle.getAttribute('aria-expanded') : null,
            rows: document.querySelectorAll('#clawDeviceManagerList li').length,
            state: document.getElementById('composerPcStatus').dataset.state,
          };
        }"""
    )
    assert opened["panelPresent"] is True
    assert opened["panelVisible"] is True
    assert opened["toggleExpanded"] == "true"
    # The confirmed PC is listed by the existing panel, and the composer
    # control shows the same confirmed state.
    assert opened["rows"] >= 1
    assert opened["state"] == "connected"
    assert not errors, errors
    page.close()


@requires_browser
@pytest.mark.parametrize("width", WIDTHS)
def test_the_control_covers_neither_the_text_nor_the_other_controls(browser, server, width) -> None:
    """The message text and the send control stay reachable."""
    page = browser.new_page(viewport={"width": width, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _route_directory(page, _directory([_device("CONNECTED", True)]))
    _open(page, server)
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "connected")
    measured = page.evaluate(MEASURE)
    button = measured["button"]
    assert button is not None
    # The message text stops before the control.
    assert measured["textRight"] <= button["left"] + 1, measured
    # The control never sits on the send, file, search, model or microphone
    # controls.
    for key in ("send", "attachment", "search", "model", "mic"):
        assert not _overlaps(button, measured[key]), (key, measured)
    assert not measured["horizontalOverflow"], measured
    assert not errors, errors
    page.close()


@requires_browser
@pytest.mark.parametrize("width", WIDTHS)
def test_the_control_does_not_change_the_fixed_composer_height(browser, server, width) -> None:
    """The composer clearance measured by #5014 must not move."""
    page = browser.new_page(viewport={"width": width, "height": 844})
    _route_directory(page, _directory([_device("CONNECTED", True)]))
    _open(page, server)
    before = page.evaluate(MEASURE)
    removed = page.evaluate(
        """() => {
          const button = document.getElementById('composerPcStatus');
          button.remove();
          const form = document.getElementById('composerForm');
          return form.getBoundingClientRect().height;
        }"""
    )
    page.wait_for_timeout(300)
    after = page.evaluate(
        """() => document.getElementById('composerForm').getBoundingClientRect().height"""
    )
    assert abs(before["formHeight"] - removed) <= 1, (before["formHeight"], removed)
    assert abs(before["formHeight"] - after) <= 1, (before["formHeight"], after)
    page.close()

@requires_browser
@pytest.mark.parametrize("width", [320, 390, 1440])
def test_a_mesh_execution_target_is_unconfirmed_not_disconnected(browser, server, width) -> None:
    """A server-confirmed execution target with no heartbeat is not "not connected".

    The Mesh grant says the server will route an approved task to this PC. It
    does not prove the PC is online right now, so the control must say the
    state needs confirmation instead of claiming the computer is disconnected.
    """
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _route_directory(
        page,
        _directory([
            _device(
                "ACTION_REQUIRED", False,
                deviceId="com1", executable=True, selectable=True,
            ),
        ]),
    )
    _open(page, server)
    _ask_the_directory_module_to_read(page)
    _wait_state(page, "unavailable")
    measured = page.evaluate(MEASURE)
    assert measured["state"] == "unavailable"
    assert measured["label"] == "연결 확인 필요"
    assert "온라인 상태는 확인되지 않았습니다" in (measured["ariaLabel"] or "")
    assert not errors, errors
    page.close()
