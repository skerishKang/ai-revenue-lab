"""B62: mobile composer must not cover the last home card, and the shared
"My computers" entry must show the connection guidance before a PC is
confirmed and the real PC name plus its state afterwards.

Load-bearing regressions for the mobile Chat/Claw composer and the computer
connection entry. The assertions reuse the EXISTING conversation clearance
(`--padiem-composer-clearance`) and the EXISTING device directory endpoint
(`/api/claw/local-access/devices`); no new endpoint, screen or authority.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

# The static contract tests below must run everywhere (the required CI lane
# installs no browser), so Playwright is optional here and only the real
# browser checks are skipped when it is absent.
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
ENDPOINT = "/api/claw/local-access/devices"
POLISH_CSS = STATIC / "interaction-polish.css"
UI_POLISH_CSS = STATIC / "padiem-chat-ui-polish.css"
STYLES_CSS = STATIC / "styles.css"
MANAGER_JS = STATIC / "claw-device-manager.js"
MANAGER_CSS = STATIC / "claw-device-manager.css"
FOCUS_CSS = STATIC / "claw-focus-layout.css"

WIDTHS = (360, 390, 430)


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
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


def test_conversation_clearance_follows_the_measured_composer_in_every_state():
    """The home state used a fixed inset that was smaller than the composer."""
    polish = POLISH_CSS.read_text(encoding="utf-8")
    assert '.app-shell:is([data-state="home"], [data-state="chat"]) .conversation' in polish
    assert "var(--padiem-composer-clearance, 230px)" in polish
    # The software keyboard raises the fixed composer by its own inset, so the
    # reserved body space has to grow by the same amount.
    assert "var(--padiem-visual-keyboard-inset, 0px)" in polish
    assert "scroll-padding-bottom" in polish
    # The Claw first-use landing keeps its own measured clearance and gap.
    focus = FOCUS_CSS.read_text(encoding="utf-8")
    assert "var(--padiem-visual-keyboard-inset, 0px)" in focus
    assert "var(--padiem-composer-clearance, 218px)" in focus


def test_mobile_shell_uses_the_dynamic_viewport_height():
    """100vh is the largest viewport height; a phone address bar needs dvh."""
    polish = UI_POLISH_CSS.read_text(encoding="utf-8")
    assert "min-height: 100dvh;" in polish
    assert re.search(
        r"@media \(max-width: 920px\) \{.*?min-height: 100dvh;", polish, re.S
    )
    # static/styles.css is byte-pinned to the product reference mirror, so the
    # mobile shell height belongs to a sheet that is not mirrored.
    styles = STYLES_CSS.read_text(encoding="utf-8")
    assert "min-height: 100dvh;" not in styles


def test_computer_entry_reuses_the_existing_directory_endpoint_and_copy():
    source = MANAGER_JS.read_text(encoding="utf-8")
    assert 'const ENDPOINT = "/api/claw/local-access/devices";' in source
    assert "컴퓨터와 연결해 보세요" in source
    assert "내 컴퓨터의 파일과 프로그램을 PADIEM에서 사용할 수 있어요." in source
    # The connected state names the real PC and reuses the existing state copy.
    assert "toggleTitle.textContent = device.deviceName || device.deviceId;" in source
    assert "toggleState.textContent = deviceLabel(device);" in source
    # The action opens the EXISTING Claw computer connect screen.
    assert 'document.getElementById("connectorsNavButton")' in source
    assert 'document.getElementById("connectorComputerCard")' in source
    # No new pairing, registration or connection authority.
    for forbidden in ("padiem-connector://", "BroadcastChannel", "localStorage"):
        assert forbidden not in source
    css = MANAGER_CSS.read_text(encoding="utf-8")
    assert ".claw-device-manager-toggle-title" in css
    assert ".claw-device-manager-connect-action" in css


MEASURE = """() => {
  const wrap = document.querySelector('.composer-wrap');
  const conv = document.querySelector('.conversation');
  const wrapRect = wrap ? wrap.getBoundingClientRect() : null;
  const cs = conv ? getComputedStyle(conv) : null;
  const root = getComputedStyle(document.documentElement);
  // The last thing the reader can see inside the conversation surface.
  const candidates = [...document.querySelectorAll(
    '#emptyState .starter-grid > *, #emptyState > *'
  )].filter((el) => el.getBoundingClientRect().height > 0);
  const last = candidates[candidates.length - 1] || null;
  const lastRect = last ? last.getBoundingClientRect() : null;
  const toggle = document.getElementById('clawDeviceManagerToggle');
  return {
    wrapTop: wrapRect ? Math.round(wrapRect.top) : null,
    wrapHeight: wrapRect ? Math.round(wrapRect.height) : null,
    convPadBottom: cs ? cs.paddingBottom : null,
    clearance: root.getPropertyValue('--padiem-composer-clearance').trim(),
    keyboardInset: root.getPropertyValue('--padiem-visual-keyboard-inset').trim(),
    lastText: last ? last.innerText.replace(/\\s+/g, ' ').trim().slice(0, 30) : null,
    lastBottom: lastRect ? Math.round(lastRect.bottom) : null,
    scrollY: Math.round(window.scrollY),
    maxScrollY: Math.round(document.documentElement.scrollHeight - window.innerHeight),
    entryTitle: toggle ? toggle.querySelector('.claw-device-manager-toggle-title')?.textContent : null,
    entryHint: toggle ? toggle.querySelector('.claw-device-manager-toggle-hint')?.textContent : null,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  };
}"""


@requires_browser
@pytest.mark.parametrize("width", WIDTHS)
def test_last_home_card_is_never_covered_by_the_fixed_composer(browser, server, width):
    """The reported defect: the bottom input sat on top of the last card."""
    page = browser.new_page(viewport={"width": width, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(400)
    measured = page.evaluate(MEASURE)
    assert measured["lastBottom"] is not None, "the home surface must render cards"
    assert measured["maxScrollY"] >= 0
    # The composer itself is still measured, and the reserved body space is at
    # least the composer's own height.
    clearance = int(float(measured["clearance"].replace("px", "")))
    assert clearance >= measured["wrapHeight"]
    assert int(float(measured["convPadBottom"].replace("px", ""))) >= measured["wrapHeight"]
    # The last card ends above the fixed composer once the page is scrolled to
    # the end. This is the regression that used to fail.
    assert measured["lastBottom"] <= measured["wrapTop"], measured
    assert not measured["horizontalOverflow"], measured
    assert not errors, errors
    page.close()


@requires_browser
@pytest.mark.parametrize("width", WIDTHS)
def test_software_keyboard_inset_moves_the_composer_and_its_reserved_space(browser, server, width):
    """A software keyboard raises the fixed composer; the body space follows."""
    page = browser.new_page(viewport={"width": width, "height": 844})
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    before = page.evaluate(MEASURE)
    page.evaluate("() => {"
                  "  document.documentElement.style.setProperty("
                  "    '--padiem-visual-keyboard-inset', '300px');"
                  "}")
    page.wait_for_timeout(200)
    after = page.evaluate(MEASURE)
    base = int(float(before["convPadBottom"].replace("px", "")))
    raised = int(float(after["convPadBottom"].replace("px", "")))
    assert raised == base + 300, (before, after)
    bottom = page.evaluate(
        """() => getComputedStyle(document.querySelector('.composer-wrap')).bottom"""
    )
    assert int(float(bottom.replace("px", ""))) == 300
    page.close()


def _directory(device_name: str, state: str) -> dict:
    return {
        "ok": True, "available": True, "ownerScoped": True,
        "devices": [{
            "deviceId": "home", "deviceName": device_name, "platform": "Windows",
            "state": state, "usable": state == "CONNECTED",
        }],
    }


@requires_browser
def test_computer_entry_shows_the_guidance_before_and_the_pc_name_after(browser, server):
    """One shared entry, one server-confirmed snapshot, both product lanes."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#clawDeviceManagerToggle").wait_for(state="attached")
    page.wait_for_timeout(800)
    entry = page.locator("#clawDeviceManagerToggle")
    # Before any confirmed PC: the connection guidance, not a fake state.
    assert entry.locator(".claw-device-manager-toggle-title").inner_text() == "컴퓨터와 연결해 보세요"
    assert entry.locator(".claw-device-manager-state").is_hidden()
    # The click keeps the EXISTING management panel (B안).
    page.route(re.compile(r".*/api/claw/local-access/devices$"), lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_directory("집 컴퓨터", "CONNECTED"), ensure_ascii=False),
    ))
    entry.click()
    page.locator("#clawDeviceManagerPanel").wait_for(state="visible")
    page.locator("#clawDeviceManagerList li").first.wait_for()
    # After the server confirms a PC: the real name and its state.
    assert entry.locator(".claw-device-manager-toggle-title").inner_text() == "집 컴퓨터"
    assert "온라인" in entry.locator(".claw-device-manager-state").inner_text()
    assert entry.locator(".claw-device-manager-state").get_attribute("data-state") == "CONNECTED"
    # The panel keeps the real device name and the honest state chip.
    assert page.locator("#clawDeviceManagerList li strong").first.inner_text() == "집 컴퓨터"
    assert page.locator("#clawDeviceManagerList .claw-device-manager-state").first.get_attribute(
        "data-state") == "CONNECTED"
    assert not errors, errors
    page.close()


@requires_browser
def test_not_connected_panel_offers_the_existing_claw_computer_connect_screen(browser, server):
    """The guidance offers one action into the EXISTING connect screen."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#clawDeviceManagerToggle").wait_for(state="attached")
    page.wait_for_timeout(800)
    page.route(re.compile(r".*/api/claw/local-access/devices$"), lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ok": True, "available": True, "ownerScoped": True, "devices": []}),
    ))
    page.locator("#clawDeviceManagerToggle").click()
    action = page.locator("#clawDeviceManagerConnectAction")
    action.wait_for(state="visible")
    assert "컴퓨터 연결하기" in action.inner_text()
    # The action opens the existing Connectors surface, and nothing else.
    opened = page.evaluate("""() => {
      const opener = document.getElementById('connectorsNavButton');
      let clicked = false;
      opener.addEventListener('click', () => { clicked = true; }, { once: true });
      document.getElementById('clawDeviceManagerConnectAction').click();
      const view = document.getElementById('connectorsView');
      const card = document.getElementById('connectorComputerCard');
      return {
        clicked,
        state: document.querySelector('.app-shell').getAttribute('data-state'),
        viewVisible: view ? !view.hidden : false,
        cardPresent: Boolean(card),
        cardInView: Boolean(view && card && view.contains(card)),
      };
    }""")
    assert opened["clicked"] is True
    assert opened["state"] == "connectors"
    assert opened["viewVisible"] is True
    assert opened["cardPresent"] is True
    assert opened["cardInView"] is True
    assert not errors, errors
    page.close()
