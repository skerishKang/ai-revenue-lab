"""#7987 UI contract: three words on the PC row, in the existing badge module.

The source-level checks always run. The browser check (three states on one
card, and a helper coming up without the row being redrawn) runs where
Playwright is installed; the captures for the PR live in
padiem-reports/2026-11-19/7987-pc-command-ready/.
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

from _support.pc_command_ready_source import module_js, card_js, locale_js

STATIC = Path(__file__).resolve().parents[1] / "static"
READY_BADGE = "연결됨 · 명령 가능"
NOT_READY_BADGE = "연결됨 · 명령 준비 안 됨"
HELP = "이 PC 에 Windows 로 로그인돼 있는지 확인하고, PC 도우미를 다시 설치해 주세요."


def test_copy_for_the_three_words_has_one_owner_each():
    source = module_js()
    # #8003's ready word stays local by Owner decision; the two #7990 strings
    # live in the PC-connect locale group and are read through uiT.
    assert READY_BADGE in source and "Connected · commands ready" in source
    assert 'uiText("pc-command-ready-badge")' in source
    # #8211: the missing-helper row reads its own word; other rows keep the
    # shared help sentence, so both keys appear in the branch.
    # #8211: the missing-helper row reads its own word; other not-ready rows
    # keep the shared help sentence — both keys ride the same uiT call.
    assert ('uiText(missing ? "pc-helper-missing-help" : "pc-command-ready-help")'
            in source)
    copy_block = source.split("var COPY = {", 1)[1].split("};", 1)[0]
    assert "badge:" not in copy_block and "help:" not in copy_block
    # No second wording was added anywhere.
    import locale_bundle
    assert locale_bundle.source().count("Windows 로 로그인돼 있는지") == 1
    pc = locale_bundle.group_text(locale_bundle.GROUP_PATHS[3], "ko")
    assert '"pc-command-ready-badge": "%s"' % NOT_READY_BADGE in pc
    assert '"pc-command-ready-help": "%s"' % HELP in pc
    assert "명령 가능" not in locale_bundle.source()


def test_only_a_connected_pc_is_annotated_and_unknown_is_left_alone():
    source = module_js()
    assert 'link.online === true ? link.command_ready : "unknown"' in source
    assert 'state !== "not_ready" && state !== "ready"' in source
    # A redraw by the card is noticed by what the rows say, not by their count.
    assert "rowCount" not in source and "stale(lastBody)" in source


def test_the_module_takes_the_list_from_the_shared_reader_and_never_reads_at_boot():
    source = module_js()
    # #7073: the connect flow owns the one first-screen read of this list.
    assert "window.PadiemPcConnectFlow" in source
    assert 'detail.read === "ok" && Array.isArray(detail.links)' in source
    start = source[source.index("function start()"):source.index("function boot()")]
    assert "refresh(" not in start.replace("refresh(false)", "") and "fetch(" not in start
    # Its own fetch remains only as the fallback for a page without that reader.
    assert source.count("fetch(PAIRINGS") == 1
    # Ready keeps the card's own colour; not ready reuses the muted one. No new
    # sheet, rule or colour literal comes with either.
    assert "badge.dataset.previousState" in source
    assert 'dataset.state !== "offline"' in source
    assert not (STATIC / "pc-command-ready.css").exists()
    assert re.search(r"""["']#[0-9a-fA-F]{3,8}["']|rgba?\(|hsla?\(""", source) is None
    assert "innerHTML" not in source and "eval(" not in source


def test_the_card_and_locale_files_stay_where_they_were():
    # #8915: the install deadline is judged in server time (skew capture plus
    # the no-paint-over guard) — 995 → 999, measured.
    assert len(card_js().splitlines()) == 999
    assert len(locale_js().splitlines()) <= 1217
    assert len(module_js().splitlines()) < 500


LINKS = [
    {"link_id": "pclink_ready", "state": "active", "online": True, "label": "READY PC",
     "command_ready": "ready", "command_ready_reason": None,
     "last_user_session_failure_at": None},
    {"link_id": "pclink_missing", "state": "active", "online": True, "label": "MISSING PC",
     "command_ready": "not_ready", "command_ready_reason": "helper_missing",
     "last_user_session_failure_at": "2026-11-19T00:10:00.000Z"},
    {"link_id": "pclink_unknown", "state": "active", "online": True, "label": "UNKNOWN PC",
     "command_ready": "unknown", "command_ready_reason": None,
     "last_user_session_failure_at": None},
    # A PC that is not connected now is never annotated, whatever the answer says.
    {"link_id": "pclink_offline", "state": "active", "online": False, "label": "OFFLINE PC",
     "last_seen_at": "2026-11-18T03:00:00.000Z", "command_ready": "ready",
     "command_ready_reason": None, "last_user_session_failure_at": None},
]


class _Static(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


def open_card(page, base: str, answer: dict, *, width: str | None = None) -> None:
    """Open the settings card on mocked answers; ``answer['links']`` may change later."""
    def fulfill(body):
        return lambda route, request: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(body() if callable(body) else body, ensure_ascii=False))

    page.route(re.compile(r".*/api/.*$"), lambda route, request: route.fulfill(
        status=404, content_type="application/json", body="{}"))
    page.route(re.compile(r".*/api/pc/pairings$"), fulfill(
        lambda: {"ok": True, "links": answer["links"], "codes": []}))
    page.route(re.compile(r".*/api/auth/status$"), fulfill(
        {"ok": True, "authenticated": True, "ready": True,
         "user": {"name": "QA", "email": "qa@example.test"}}))
    page.route(re.compile(r".*/api/claw/local-access/devices$"), fulfill(
        {"ok": True, "available": True, "ownerScoped": True, "devices": []}))
    page.goto(base, wait_until="domcontentloaded")
    page.evaluate("""(width) => {
      const d = document.getElementById('connectorsDialog');
      if (d && !d.open) d.showModal();
      const s = document.getElementById('pcPairingSection');
      if (s) s.style.setProperty('display', 'block', 'important');
      const c = document.getElementById('connectorComputerCard');
      if (c && width) c.style.width = width;
    }""", width)
    page.locator("#pcPairingSection li.pc-pairing-link").first.wait_for(
        state="visible", timeout=20000)
    page.wait_for_timeout(500)


def read_rows(page) -> dict:
    return page.evaluate("""() => {
      const section = document.getElementById('pcPairingSection');
      const rows = {};
      for (const row of section.querySelectorAll('ul.pc-pairing-list > li.pc-pairing-link')) {
        const name = row.querySelector('.pc-pairing-name');
        const badge = row.querySelector('.pc-pairing-state');
        rows[name.textContent] = {badge: badge.textContent, state: badge.dataset.state || '',
          mark: row.dataset.commandReady || '',
          nameFits: name.scrollWidth <= name.clientWidth};
      }
      const help = Array.from(section.querySelectorAll('[data-pc-command-ready="1"]'))
        .map(node => node.textContent);
      return {rows, help};
    }""")


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_three_words_on_one_card_and_a_helper_coming_up_repaints_the_same_row():
    answer = {"links": [dict(link) for link in LINKS]}
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Static)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{web.server_address[1]}/index.html"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            open_card(page, base, answer)
            first = read_rows(page)
            # The card redraws its own rows (here: the tab becoming visible again).
            # The new rows must carry the same words, with nothing else changed.
            page.evaluate("""() => {
              for (const row of document.querySelectorAll('#pcPairingSection li.pc-pairing-link')) {
                row.dataset.beforeRedraw = '1';
              }
              document.dispatchEvent(new Event('visibilitychange'));
            }""")
            page.wait_for_function(
                """() => { const rows = Array.from(document.querySelectorAll(
                     '#pcPairingSection li.pc-pairing-link'));
                   return rows.length === 4 && rows.every(row => !row.dataset.beforeRedraw) &&
                     rows.filter(row => row.dataset.commandReady).length === 2; }""", timeout=10000)
            page.wait_for_timeout(600)
            redrawn = read_rows(page)
            # The helper is installed on the second PC and stops on the first. No
            # pairing event announces it: the card simply redraws again.
            answer["links"][1].update(command_ready="ready", command_ready_reason=None,
                                      last_user_session_failure_at=None)
            answer["links"][0].update(command_ready="not_ready",
                                      command_ready_reason="helper_stopped",
                                      last_user_session_failure_at="2026-11-19T00:20:00.000Z")
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function(
                """() => { const row = Array.from(document.querySelectorAll(
                     '#pcPairingSection li.pc-pairing-link')).find(node =>
                       node.querySelector('.pc-pairing-name').textContent === 'MISSING PC');
                   return row && row.dataset.commandReady === 'ready'; }""", timeout=10000)
            page.wait_for_timeout(600)
            second = read_rows(page)
            # Nothing reported at all any more: every row goes back to the card's own text.
            for link in answer["links"]:
                link.update(command_ready="unknown")
            # The shared reader reads again and announces it; no row is redrawn.
            page.evaluate("window.PadiemPcConnectFlow.refresh()")
            page.wait_for_function(
                """() => !document.querySelector(
                     '#pcPairingSection li.pc-pairing-link[data-command-ready="ready"],' +
                     '#pcPairingSection li.pc-pairing-link[data-command-ready="not_ready"]')""",
                timeout=10000)
            third = read_rows(page)
            browser.close()
    finally:
        web.shutdown()
    assert errors == []
    rows = first["rows"]
    assert rows["READY PC"] == {"badge": READY_BADGE, "state": "active", "mark": "ready",
                                "nameFits": True}
    assert rows["MISSING PC"] == {"badge": NOT_READY_BADGE, "state": "offline",
                                  "mark": "not_ready", "nameFits": True}
    assert rows["UNKNOWN PC"]["badge"] == "연결됨" and rows["UNKNOWN PC"]["mark"] == ""
    assert rows["UNKNOWN PC"]["state"] == "active"
    assert rows["OFFLINE PC"]["mark"] == "" and rows["OFFLINE PC"]["state"] == "offline"
    assert "명령" not in rows["OFFLINE PC"]["badge"]
    assert first["help"] == ["MISSING PC: " + HELP]  # Only the not-ready PC gets the remedy.
    # A badge and its remedy line never part ways when the card redraws.
    assert redrawn == first

    rows = second["rows"]
    assert rows["MISSING PC"] == {"badge": READY_BADGE, "state": "active", "mark": "ready",
                                  "nameFits": True}
    assert rows["READY PC"]["badge"] == NOT_READY_BADGE and rows["READY PC"]["state"] == "offline"
    assert second["help"] == ["READY PC: " + HELP]

    for name in ("READY PC", "MISSING PC", "UNKNOWN PC"):
        assert third["rows"][name] == {"badge": "연결됨", "state": "active", "mark": "",
                                       "nameFits": True}
    assert third["help"] == []


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_a_narrow_card_keeps_the_pc_name_readable_beside_the_ready_badge():
    answer = {"links": [dict(LINKS[0], label="QA PC")]}
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Static)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{web.server_address[1]}/index.html"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            open_card(page, base, answer, width="260px")
            seen = read_rows(page)
            browser.close()
    finally:
        web.shutdown()
    assert seen["rows"]["QA PC"] == {"badge": READY_BADGE, "state": "active", "mark": "ready",
                                     "nameFits": True}
