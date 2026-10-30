"""#4816: the microphone and the voice waveform are two persistent icons.

Owner decision 2026-10-31 (A안). The earlier #5561 shape let the waveform borrow
the send slot, so it vanished the moment the composer held text — the exact
report that reopened #4816. This suite loads the REAL ``static/index.html`` (not a
hand-built composer fixture) and measures what is painted.

Authentication, voice availability and the voice identity are supplied as stubbed
server responses so the app's own code path decides the control state; nothing is
injected into the DOM. Skipped when Playwright is not installed, like the other
browser suites in this directory.
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"

SIGNED_IN = {
    "ready": True, "authenticated": True, "history_ready": True,
    "user": {"name": "Padiem", "email": "owner", "tier": "plus"},
    "model_requires_session": False,
}
GUEST = {
    "ready": True, "authenticated": False, "history_ready": False,
    "user": None, "model_requires_session": False,
}

MEASURE = """() => {
  const box = (sel) => {
    const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
            painted: r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'};
  };
  const send = document.getElementById('sendButton');
  const wave = document.getElementById('voiceWaveformButton');
  const actions = document.querySelector('#composerForm .composer-actions');
  return {
    mic: box('#voiceMicButton'),
    waveform_button: box('#voiceWaveformButton'),
    send_button: box('#sendButton'),
    attach_button: box('#attachmentButton'),
    arrow_face: send ? box(send.querySelector('.send-arrow-icon')) : null,
    inner_wave_face: send ? box(send.querySelector('.send-waveform-icon')) : null,
    send_primary_action: send ? send.dataset.primaryAction || '' : '',
    waveform_state: wave ? wave.getAttribute('data-voice-state') : '',
    waveform_aria_disabled: wave ? wave.getAttribute('aria-disabled') : '',
    waveform_tooltip: wave ? wave.getAttribute('data-padiem-tooltip') : '',
    waveform_label: wave ? wave.getAttribute('aria-label') : '',
    waveform_expanded: wave ? wave.getAttribute('aria-expanded') : '',
    overflow: actions ? actions.scrollWidth > actions.clientWidth + 1 : null,
    active_element_id: document.activeElement ? document.activeElement.id : '',
  };
}"""

MENU_STATE = """() => {
  const menu = document.getElementById('voiceModeMenu');
  if (!menu) return {present: false};
  const cs = getComputedStyle(menu);
  return {
    present: true,
    open: !menu.hasAttribute('hidden') && cs.display !== 'none',
    items: Array.from(menu.querySelectorAll('[data-mode]')).map((n) => n.textContent.trim()),
    modes: Array.from(menu.querySelectorAll('[data-mode]')).map((n) => n.getAttribute('data-mode')),
    roles: Array.from(menu.querySelectorAll('[data-mode]')).map((n) => n.getAttribute('role')),
    tabindex: Array.from(menu.querySelectorAll('[data-mode]')).map((n) => n.getAttribute('tabindex')),
    active_mode: (document.activeElement && document.activeElement.getAttribute)
      ? document.activeElement.getAttribute('data-mode') : null,
  };
}"""


@pytest.fixture(scope="module")
def static_url():
    handler = partial(SimpleHTTPRequestHandler, directory=str(STATIC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _stub(page, *, signed_in: bool, voice_ready: bool):
    health = {"status": "ok", "app": "padiem-chat", "runtime": "mock",
              "voice_stt_available": voice_ready, "auth_configured": signed_in}

    def handle(route):
        url = route.request.url
        if "/api/auth/status" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(SIGNED_IN if signed_in else GUEST))
        elif "/api/voice/identity" in url or "/api/claw/voice/identity" in url:
            if voice_ready:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"identity_key": "acct_probe_key"}))
            else:
                route.fulfill(status=403, content_type="application/json", body="{}")
        elif url.endswith("/health"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(health))
        elif any(k in url for k in ("/api/conversations", "/api/projects", "/api/connectors")):
            route.fulfill(status=200, content_type="application/json", body='{"items":[]}')
        else:
            route.continue_()

    page.route("**/*", handle)


def _open(browser, static_url, width, height, *, signed_in=True, voice_ready=True, clad=False):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    _stub(page, signed_in=signed_in, voice_ready=voice_ready)
    page.goto(static_url + "/", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(800)
    if clad:
        page.evaluate("() => document.getElementById('clawNavButton').click()")
        page.wait_for_timeout(600)
    return ctx, page


VIEWPORTS = [(1440, 900), (820, 1180), (390, 844)]


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_both_voice_icons_are_painted_with_an_empty_composer(static_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, width, height)
        state = page.evaluate(MEASURE)
        ctx.close()
        browser.close()

    assert state["mic"] and state["mic"]["painted"], state
    assert state["waveform_button"] and state["waveform_button"]["painted"], state
    assert state["mic"]["w"] >= 44 and state["mic"]["h"] >= 44, state["mic"]
    assert state["waveform_button"]["w"] >= 44 and state["waveform_button"]["h"] >= 44, state["waveform_button"]
    assert state["waveform_state"] in {"ready", "active"}, state
    assert state["waveform_aria_disabled"] == "false", state
    assert state["overflow"] is False, state


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_typing_text_does_not_remove_the_waveform(static_url, width, height):
    """The regression #4816 was reopened for: text in the box hid the icon."""

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, width, height)
        empty = page.evaluate(MEASURE)
        page.fill("#messageInput", "견적서 정리해줘")
        page.wait_for_timeout(250)
        typed = page.evaluate(MEASURE)
        ctx.close()
        browser.close()

    assert empty["waveform_button"]["painted"] is True
    assert typed["waveform_button"]["painted"] is True, typed
    assert typed["mic"]["painted"] is True, typed
    # The send slot keeps its own face: the arrow returns, nothing else moved.
    assert typed["send_button"]["painted"] is True, typed
    assert typed["arrow_face"]["painted"] is True, typed
    assert typed["inner_wave_face"]["painted"] is False, typed
    assert typed["send_primary_action"] == "send", typed
    assert typed["overflow"] is False, typed


def test_claw_composer_shows_the_same_two_icons(static_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, 1440, 900, clad=True)
        shell = page.evaluate("() => document.querySelector('.app-shell').dataset.state")
        state = page.evaluate(MEASURE)
        ctx.close()
        browser.close()

    assert shell == "claw"
    assert state["mic"]["painted"] is True, state
    assert state["waveform_button"]["painted"] is True, state


def test_a_guest_sees_the_waveform_but_it_explains_why_it_cannot_run(static_url):
    """Hidden is not an acceptable state: the icon stays, inactive, with a reason."""

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, 1440, 900, signed_in=False, voice_ready=False)
        state = page.evaluate(MEASURE)
        page.click("#voiceWaveformButton")
        page.wait_for_timeout(200)
        menu = page.evaluate(MENU_STATE)
        notice = page.evaluate("() => document.getElementById('voiceWaveformNotice').textContent")
        ctx.close()
        browser.close()

    assert state["waveform_button"]["painted"] is True, state
    assert state["waveform_state"] == "unavailable", state
    # Same rule as the microphone: pressable, explains itself, never a dead
    # control whose only explanation is a hover tooltip.
    assert state["waveform_aria_disabled"] == "false", state
    assert state["waveform_tooltip"], state
    assert "로그인" in state["waveform_tooltip"] or "Sign in" in state["waveform_tooltip"], state
    assert menu["open"] is False, menu
    assert notice.strip(), "an unavailable control must say why when pressed"


def test_the_picker_opens_closes_and_keeps_its_three_modes(static_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, 1440, 900)
        page.click("#voiceWaveformButton")
        page.wait_for_timeout(250)
        opened = page.evaluate(MENU_STATE)
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        closed = page.evaluate(MENU_STATE)
        state = page.evaluate(MEASURE)
        ctx.close()
        browser.close()

    assert opened["open"] is True, opened
    assert opened["modes"] == ["text", "tts", "call"], opened
    assert all(role == "menuitemradio" for role in opened["roles"]), opened
    assert closed["open"] is False, closed
    # Escape hands focus back to the control that opened the picker.
    assert state["active_element_id"] == "voiceWaveformButton", state


def test_the_picker_is_operable_from_the_keyboard(static_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, 1440, 900)
        page.focus("#voiceWaveformButton")
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)
        opened = page.evaluate(MENU_STATE)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(150)
        moved = page.evaluate(MENU_STATE)
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)
        after = page.evaluate(MENU_STATE)
        state = page.evaluate(MEASURE)
        mode = page.evaluate("() => window.PadiemVoiceMenu.getState().mode")
        ctx.close()
        browser.close()

    assert opened["open"] is True, opened
    # Enter opens with focus already on the first item, so the arrows work.
    assert opened["active_mode"] == "text", opened
    assert moved["active_mode"] == "tts", moved
    assert after["open"] is False, after
    assert state["active_element_id"] == "voiceWaveformButton", state
    assert mode == "live", mode
