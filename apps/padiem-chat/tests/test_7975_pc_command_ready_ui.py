"""#7975 UI contract: the new badge module stays small, token-only and honest.

No browser is needed here: browser screenshots for the three states live in
padiem-reports/2026-11-18/7975-pc-command-ready/. This pins the source-level
contract that CI can always check.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
MODULE = STATIC / "pc-command-ready.js"
CARD_CSS = STATIC / "pc-pairing-card.css"
INDEX = STATIC / "index.html"


def test_new_module_is_its_own_small_file():
    source = MODULE.read_text(encoding="utf-8")
    assert len(source.splitlines()) < 1000
    assert '"/api/pc/pairings"' in source
    assert "command_ready" in source
    assert "innerHTML" not in source
    assert "eval(" not in source


def test_badge_copy_is_plain_korean_and_offers_the_remedy():
    source = MODULE.read_text(encoding="utf-8")
    assert 't("pc-command-ready-badge")' in source
    # #8211: the missing row reads its own word through the same call.
    assert 't(missing ? "pc-helper-missing-help" : "pc-command-ready-help")' in source
    # #7995: the copy now lives in the PC-connect locale group, ko and en.
    import locale_bundle
    ko = locale_bundle.group_text(locale_bundle.GROUP_PATHS[3], "ko")
    en = locale_bundle.group_text(locale_bundle.GROUP_PATHS[3], "en")
    assert '"pc-command-ready-badge": "연결됨 · 명령 준비 안 됨"' in ko
    assert "PC 도우미를 다시 설치해 주세요" in ko
    assert "reinstall the PC helper" in en
    # A link with no evidence is never given a warning.
    assert '!== "not_ready"' in source


def test_existing_theme_styles_are_reused_without_a_new_sheet():
    source = MODULE.read_text(encoding="utf-8")
    assert not (STATIC / "pc-command-ready.css").exists()
    assert 'element("p", "pc-pairing-help"' in source
    assert 'dataset.state !== "offline"' in source
    css = CARD_CSS.read_text(encoding="utf-8")
    assert ".pc-pairing-help {" in css
    assert '[data-state="offline"]' in css


def test_index_wires_module_after_the_pairing_card():
    html = INDEX.read_text(encoding="utf-8")
    card = html.index('./pc-pairing-card.js')
    module = html.index('./pc-command-ready.js')
    assert module > card


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_a_narrow_card_keeps_the_pc_name_readable():
    """#7975 CTO capture: at 260px the badge must not ellipsize the name."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, *args):
            pass

    link = {"link_id": "pclink_qa", "state": "active", "online": True,
            "label": "QA PC", "command_ready": "not_ready",
            "last_user_session_failure_at": "2026-11-18T02:41:00.000Z"}
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{web.server_address[1]}/index.html"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.route(re.compile(r".*/api/.*$"),
                       lambda route, req: route.fulfill(
                           status=404, content_type="application/json", body="{}"))
            page.route(re.compile(r".*/api/pc/pairings$"),
                       lambda route, req: route.fulfill(
                           status=200, content_type="application/json",
                           body=json.dumps({"ok": True, "links": [link], "codes": []},
                                           ensure_ascii=False)))
            signed_in = {"ok": True, "authenticated": True, "ready": True,
                         "user": {"name": "QA", "email": "qa@example.test"}}
            page.route(re.compile(r".*/api/auth/status$"),
                       lambda route, req: route.fulfill(
                           status=200, content_type="application/json",
                           body=json.dumps(signed_in, ensure_ascii=False)))
            directory = {"ok": True, "available": True, "ownerScoped": True, "devices": []}
            page.route(re.compile(r".*/api/claw/local-access/devices$"),
                       lambda route, req: route.fulfill(
                           status=200, content_type="application/json",
                           body=json.dumps(directory, ensure_ascii=False)))
            page.goto(base, wait_until="domcontentloaded")
            page.evaluate("""() => {
              const d = document.getElementById('connectorsDialog');
              if (d && !d.open) d.showModal();
              const s = document.getElementById('pcPairingSection');
              if (s) s.style.setProperty('display', 'block', 'important');
              const c = document.getElementById('connectorComputerCard');
              if (c) c.style.width = '260px';
            }""")
            row = page.locator("#pcPairingSection li.pc-pairing-link").first
            row.wait_for(state="visible", timeout=20000)
            page.wait_for_timeout(500)
            name = row.locator(".pc-pairing-name")
            metrics = name.evaluate("""el => ({
              text: el.textContent, scrollWidth: el.scrollWidth,
              clientWidth: el.clientWidth, badge: el.parentElement.dataset.commandReady
            })""")
            browser.close()
    finally:
        web.shutdown()
    assert metrics["text"] == "QA PC"
    assert metrics["badge"] == "not_ready"
    assert metrics["scrollWidth"] <= metrics["clientWidth"], metrics
