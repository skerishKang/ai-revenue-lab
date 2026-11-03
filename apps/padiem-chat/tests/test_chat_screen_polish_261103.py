"""11-03 chat screen polish (컴1로컬3): the nine audit items, each with one guard.

Every assertion below is the measured defect from the 2026-11-03 UX audit
captures, not a restatement of the report:

  1. phone composer — send was painted at the LEFT of the wrapped second line,
  2. phone home cards — the description was removed and the format badge shared
     the card's top band with the title,
  3. left menu — 캘린더 stayed tinted on every screen and Calendar, Library and
     Meeting had no URL of their own,
  4. answer actions — the Glass theme pinned the five buttons to a 26px press
     box,
  5. "글쓰기 도움" — its icon was white on a white plate,
  6. desktop greeting — 88px type broke "무엇을 도와드릴까요?" over two lines,
  7. small controls — 28px "+", 24px badge, 26px PC cell, dim search,
  8. copy — three wordings,
  9. the "저장된 대화" chip named itself without saying why it is there.

The phone press floor in mobile-target-legibility.css is deliberately NOT
weakened: the polish sheet is linked before it, and the browser checks measure
the resolved value on a phone.
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
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
HELP = (STATIC / "help.html").read_text(encoding="utf-8")
POLISH = (STATIC / "chat-screen-polish.css").read_text(encoding="utf-8")
CALENDAR_CSS = (STATIC / "calendar.css").read_text(encoding="utf-8")
LIBRARY_CSS = (STATIC / "library.css").read_text(encoding="utf-8")

# The Library surface closes itself when the session is signed out, so the
# browser checks run against a signed-in projection.
AUTH = {
    "ready": True,
    "authenticated": True,
    "user": {"name": "Padiem Owner", "email": "owner@example.invalid"},
    "session_state": "active",
    "history_ready": True,
    "project_files_ready": True,
    "methods": {"google": True, "password": False},
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/api/auth/status":
            return self._json(AUTH)
        if path.startswith("/api/") or path.startswith("/auth/"):
            return self._json({})
        return super().do_GET()

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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


def _open(browser, url, width, height, mobile):
    page = browser.new_page(
        viewport={"width": width, "height": height},
        is_mobile=mobile,
        has_touch=mobile,
        device_scale_factor=1,
    )
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    return page


# ---------------------------------------------------------------------------
# 1. phone composer: send keeps the input's right edge
# ---------------------------------------------------------------------------


def test_send_button_is_right_aligned_on_the_phone() -> None:
    assert "@media (max-width: 620px)" in POLISH
    assert ".composer-actions .send-button" in POLISH
    assert "margin-left: auto" in POLISH
    # The first-screen reservations belong to owner-model-preview.css and are
    # untouched by this lane.
    preview = (STATIC / "owner-model-preview.css").read_text(encoding="utf-8")
    assert "width: 116px" in preview
    assert "width: 112px; min-width: 112px; height: 44px;" in preview
    assert ".send-button { flex: 0 0 44px;" in preview


@requires_browser
def test_send_button_sits_on_the_composer_right_edge_at_390(browser, server) -> None:
    page = _open(browser, server, 390, 844, True)
    measured = page.evaluate(
        """() => {
          const rect = (sel) => { const b = document.querySelector(sel).getBoundingClientRect();
            return {left: Math.round(b.left), right: Math.round(b.right), top: Math.round(b.top)}; };
          return {actions: rect('.composer-actions'), send: rect('#sendButton'),
                  overflow: document.documentElement.scrollWidth > innerWidth + 1};
        }"""
    )
    assert measured["send"]["right"] == measured["actions"]["right"], measured
    assert measured["send"]["left"] > measured["actions"]["left"], measured
    assert not measured["overflow"], measured
    page.close()


# ---------------------------------------------------------------------------
# 2. phone home cards: one description line, badge clear of the content
# ---------------------------------------------------------------------------


def test_phone_home_cards_keep_one_description_line() -> None:
    block = POLISH.split("@media (max-width: 620px)", 1)[1]
    assert ".starter small" in block
    assert "display: block" in block
    assert "text-overflow: ellipsis" in block
    assert "padding-top: 60px !important" in block


@requires_browser
def test_badge_does_not_cover_the_card_content_on_a_phone(browser, server) -> None:
    page = _open(browser, server, 390, 844, True)
    measured = page.evaluate(
        """() => {
          const rect = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
            return {x: b.x, y: b.y, right: b.right, bottom: b.bottom, height: b.height}; };
          const shell = document.querySelector('.document-starter-shell');
          const badge = rect(shell.querySelector('.document-formats-toggle'));
          const icon = rect(shell.querySelector('.starter-icon'));
          const title = rect(shell.querySelector('strong'));
          const copy = rect(shell.querySelector('small'));
          const card = rect(shell);
          const hits = (a, b) => !(a.right <= b.x || a.x >= b.right || a.bottom <= b.y || a.top >= b.bottom);
          const other = document.getElementById('writingStarterButton');
          const menu = document.getElementById('mobileMenu').getBoundingClientRect();
          const first = document.querySelector('#emptyState .starter-grid > *').getBoundingClientRect();
          const menuHitsCard = !(menu.bottom <= first.top || menu.top >= first.bottom
            || menu.right <= first.left || menu.left >= first.right);
          return {
            badge, icon, title, copy,
            menuCoversCard: menuHitsCard,
            copyVisible: copy.height > 0 && getComputedStyle(other.querySelector('small')).display !== 'none',
            oneLine: copy.height < parseFloat(getComputedStyle(other.querySelector('small')).lineHeight) * 2,
            overIcon: hits(badge, icon), overTitle: hits(badge, title), overCopy: hits(badge, copy),
            insideCard: badge.right <= card.right && badge.bottom <= card.bottom,
            overflow: document.documentElement.scrollWidth > innerWidth + 1,
          };
        }"""
    )
    assert measured["copyVisible"], measured
    assert measured["oneLine"], measured
    assert not measured["overIcon"], measured
    assert not measured["overTitle"], measured
    assert not measured["overCopy"], measured
    assert measured["insideCard"], measured
    assert not measured["menuCoversCard"], measured
    assert not measured["overflow"], measured
    page.close()


# ---------------------------------------------------------------------------
# 3. left menu: one selected row, one URL per screen
# ---------------------------------------------------------------------------


def test_calendar_entry_is_tinted_only_while_it_is_current() -> None:
    base = CALENDAR_CSS.split("#calendarNavButton {", 1)[1].split("}", 1)[0]
    assert "background" not in base, base
    assert "border" not in base, base
    current = CALENDAR_CSS.split('#calendarNavButton[aria-current="page"] {', 1)[1].split("}", 1)[0]
    assert "background" in current, current
    glass_current = CALENDAR_CSS.split(
        'html[data-theme="padiem-glass"] #calendarNavButton[aria-current="page"] {', 1
    )[1].split("}", 1)[0]
    assert "background" in glass_current, glass_current
    # A glass rule must not exist for the unselected entry any more.
    assert 'html[data-theme="padiem-glass"] #calendarNavButton {' not in CALENDAR_CSS


def test_new_chat_stops_claiming_the_calendar_and_library_screens() -> None:
    lines = [l for l in APP.splitlines() if 'chatNav.setAttribute("aria-current"' in l]
    assert len(lines) == 2, lines
    assert '"calendar"' in lines[1] and '"library"' in lines[1], lines


def test_every_panel_screen_names_its_own_fragment() -> None:
    for fragment in ("#padiem-calendar", "#padiem-library", "#padiem-meeting"):
        assert fragment in APP, fragment
    assert "PANEL_ROUTE_HASH_BY_STATE" in APP
    assert "window.PadiemChatRouting = Object.freeze({ syncRouteHash });" in APP
    assert "restoreShellRouteFromHash" in APP
    # The module-owned entries stay module-owned: app.js publishes the request
    # and the fragment table, it does not drive the other modules' DOM, and it
    # adds no browser-side watcher (#3232 entry contract, #1728/#2340/#54
    # interception boundary).
    assert 'getElementById("filesNavButton")' not in APP
    assert 'getElementById("calendarNavButton")' not in APP
    assert "MutationObserver" not in APP
    for module in ("calendar.js", "library.js"):
        source = (STATIC / module).read_text(encoding="utf-8")
        assert '"padiem:route-restore"' in source, module
        assert "window.PadiemChatRouting?.syncRouteHash?.()" in source, module


@requires_browser
def test_menu_selection_and_url_follow_the_screen(browser, server) -> None:
    page = _open(browser, server, 1440, 900, False)
    steps = (
        ("calendarNavButton", "#padiem-calendar"),
        ("filesNavButton", "#padiem-library"),
        ("automationNavButton", "#padiem-automation"),
    )
    for element_id, expected_hash in steps:
        page.evaluate(f"() => document.getElementById('{element_id}').click()")
        page.wait_for_timeout(250)
        state = page.evaluate(
            """() => ({
                 hash: location.hash,
                 selected: Array.from(document.querySelectorAll('.side-item, .new-chat'))
                   .filter((el) => el.getAttribute('aria-current') === 'page')
                   .map((el) => el.id),
               })"""
        )
        assert state["hash"] == expected_hash, (element_id, state)
        assert state["selected"] and all(
            el != "newChatButton" for el in state["selected"]
        ), (element_id, state)
    page.evaluate("() => document.getElementById('newChatButton').click()")
    page.wait_for_timeout(250)
    assert page.evaluate("() => location.hash") == ""
    page.close()


@requires_browser
@pytest.mark.parametrize("fragment", ["#padiem-calendar", "#padiem-library"])
def test_a_shared_fragment_opens_the_screen_it_names(browser, server, fragment) -> None:
    page = _open(browser, f"{server}{fragment}", 1440, 900, False)
    # The named screen opens at DOMContentLoaded and, for Library, is applied
    # again once the session is known. Wait for that to settle instead of a
    # fixed pause.
    page.wait_for_function(
        """() => document.querySelector('.app-shell').dataset.state === location.hash.replace('#padiem-', '')""",
        timeout=20_000,
    )
    state = page.evaluate(
        """() => ({
          state: document.querySelector('.app-shell').dataset.state,
          calendarOpen: !document.querySelector('.calendar-view')?.hidden,
          libraryOpen: !document.getElementById('libraryView')?.hidden,
        })"""
    )
    if fragment == "#padiem-calendar":
        assert state["state"] == "calendar", state
        assert state["calendarOpen"], state
    else:
        assert state["state"] == "library", state
        assert state["libraryOpen"], state
    page.close()


# ---------------------------------------------------------------------------
# 4. answer actions: a 40px press box, tooltips already localised
# ---------------------------------------------------------------------------


def test_answer_actions_get_a_40px_press_box() -> None:
    assert (
        "html[data-theme=\"padiem-glass\"] body .assistant-message .answer-actions .answer-action"
        in POLISH
    )
    assert "width: 40px !important" in POLISH
    assert "min-height: 40px" in POLISH
    # The hints are locale keys, never literals in the builder.
    outputs = (STATIC / "outputs.js").read_text(encoding="utf-8")
    assert 'button.setAttribute("data-padiem-tooltip", label);' in outputs
    assert "answer-copy" in LOCALE and "answer-regenerate" in LOCALE


@requires_browser
@pytest.mark.parametrize(
    "width,height,expected", [(1440, 900, 40), (390, 844, 44)]
)
def test_answer_action_press_box_measures_the_floor(browser, server, width, height, expected) -> None:
    page = _open(browser, server, width, height, width < 921)
    measured = page.evaluate(
        """() => {
          const tpl = document.getElementById('assistantMessageTemplate').content.cloneNode(true);
          const article = tpl.querySelector('.assistant-message');
          const bar = document.createElement('div');
          bar.className = 'answer-actions';
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'answer-action answer-copy';
          button.innerHTML = '<span class="answer-action-glyph">⧉</span>';
          bar.appendChild(button);
          article.querySelector('.assistant-body').appendChild(bar);
          document.querySelector('.conversation').appendChild(article);
          const b = button.getBoundingClientRect();
          const out = {w: Math.round(b.width), h: Math.round(b.height)};
          article.remove();
          return out;
        }"""
    )
    assert measured["w"] == expected, measured
    assert measured["h"] == expected, measured
    page.close()


# ---------------------------------------------------------------------------
# 5. the writing card icon is visible
# ---------------------------------------------------------------------------


def test_home_card_icons_share_svg_stroke_and_theme_plates() -> None:
    icon_attributes = re.findall(r'<svg class="starter-card-icon"([^>]*)>', INDEX)
    assert len(icon_attributes) == 4, icon_attributes
    for attributes in icon_attributes:
        assert 'viewBox="0 0 24 24"' in attributes
        assert 'width="20"' in attributes and 'height="20"' in attributes
        assert 'stroke="currentColor"' in attributes
        assert 'stroke-width="1.8"' in attributes
        assert 'stroke-linecap="round"' in attributes
        assert 'stroke-linejoin="round"' in attributes
    assert 'class="status-spark"' not in INDEX
    assert 'background: #eef3f7;' in POLISH
    assert 'color: #2d4557;' in POLISH
    assert 'background: #29485f;' in POLISH
    assert 'color: #e5f3fd;' in POLISH


@requires_browser
def test_home_card_icons_have_uniform_boxes_and_3_to_1_contrast_in_all_themes(browser, server) -> None:
    page = _open(browser, server, 1440, 900, False)
    for theme in ("padiem-home", "light", "dark", "padiem-glass"):
        page.evaluate("(value) => { document.documentElement.dataset.theme = value; }", theme)
        page.wait_for_timeout(50)
        measured = page.evaluate(
        """() => {
          const buttons = ['#pcConnectStarter', '.starter[data-skill="plan"]',
            '#documentStarterButton', '#writingStarterButton'];
          const linear = (v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
          const rgb = (value) => value.match(/[0-9.]+/g).slice(0, 3).map(Number).map((v) => linear(v / 255));
          const contrast = (a, b) => {
            const luminance = (value) => { const c = rgb(value); return .2126*c[0] + .7152*c[1] + .0722*c[2]; };
            const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
            return (values[0] + .05) / (values[1] + .05);
          };
          return buttons.map((selector) => {
            const box = document.querySelector(selector + ' .starter-icon');
            const svg = box.querySelector('svg');
            const style = getComputedStyle(box);
            const rect = box.getBoundingClientRect();
            const svgStyle = getComputedStyle(svg);
            return {
              width: rect.width, height: rect.height, color: style.color,
              background: style.backgroundColor, border: style.borderTopWidth,
              stroke: svgStyle.color, strokeWidth: svg.getAttribute('stroke-width'),
              ratio: contrast(style.color, style.backgroundColor)
            };
          });
        }"""
        )
        assert len({(item["width"], item["height"]) for item in measured}) == 1, (theme, measured)
        assert len({(item["color"], item["background"], item["border"], item["strokeWidth"]) for item in measured}) == 1, (theme, measured)
        assert all(item["stroke"] == item["color"] for item in measured), (theme, measured)
        assert all(float(item["ratio"]) >= 3 for item in measured), (theme, measured)
    page.close()


@requires_browser
@pytest.mark.parametrize(("width", "height", "mobile", "slot"), [
    (1440, 900, False, 116),
    (390, 844, True, 112),
])
def test_tier_chip_text_is_centered_without_spark_and_stays_in_reserved_slot(
    browser, server, width, height, mobile, slot
) -> None:
    page = _open(browser, server, width, height, mobile)
    measured = page.evaluate(
        """() => {
          const pill = document.querySelector('#composerForm .composer-tools .model-pill');
          const label = pill.querySelector('span:last-child');
          const box = pill.getBoundingClientRect();
          const text = label.getBoundingClientRect();
          return {
            text: label.textContent.trim(),
            left: text.left - box.left,
            right: box.right - text.right,
            width: box.width,
            spark: Boolean(pill.querySelector('.status-spark')),
            actionHeight: document.querySelector('.composer-actions').getBoundingClientRect().height
          };
        }"""
    )
    assert measured["spark"] is False, measured
    assert abs(measured["left"] - measured["right"]) <= 1.5, measured
    assert measured["width"] <= slot, measured
    assert measured["actionHeight"] > 0, measured
    page.close()


# ---------------------------------------------------------------------------
# 6. the desktop greeting fits two lines
# ---------------------------------------------------------------------------


def test_desktop_hero_size_is_capped() -> None:
    assert "@media (min-width: 621px)" in POLISH
    assert "clamp(36px, 4.1vw, 60px)" in POLISH


@requires_browser
def test_desktop_greeting_renders_two_lines(browser, server) -> None:
    page = _open(browser, server, 1440, 900, False)
    measured = page.evaluate(
        """() => {
          const h1 = document.querySelector('#emptyState h1');
          const cs = getComputedStyle(h1);
          const lines = [...h1.querySelectorAll("span.chat-hero-line")]
            .filter((el) => el.getBoundingClientRect().height > 0)
            .map((el) => Math.round(el.getBoundingClientRect().height / parseFloat(cs.lineHeight)));
          return {lines, total: Math.round(h1.getBoundingClientRect().height / parseFloat(cs.lineHeight)),
                  fontSize: cs.fontSize};
        }"""
    )
    assert measured["total"] == 2, measured
    assert measured["lines"] == [1, 1], measured
    page.close()


# ---------------------------------------------------------------------------
# 7. the small controls reach the 32px floor and the search icon reads as a control
# ---------------------------------------------------------------------------


def test_small_control_floors_are_raised() -> None:
    assert ".sidebar .section-add-button" in POLISH
    assert "width: 32px" in POLISH
    assert ".starter-grid .document-formats-toggle" in POLISH
    assert ".composer-pc-status-face" in POLISH
    assert "height: 32px" in POLISH
    assert "opacity: .78" in POLISH
    assert "#filesNavButton {\n  position: relative;\n  min-height: 44px;\n}" in LIBRARY_CSS


@requires_browser
def test_raised_controls_measure_their_floor(browser, server) -> None:
    page = _open(browser, server, 1440, 900, False)
    measured = page.evaluate(
        """() => {
          const size = (sel) => { const el = document.querySelector(sel); if (!el) return null;
            const b = el.getBoundingClientRect(); return {w: Math.round(b.width), h: Math.round(b.height)}; };
          const fmt = document.getElementById('documentFormatsToggle');
          const pc = document.querySelector('.composer-pc-status-face');
          const search = document.getElementById('sidebarSearchButton');
          // The search entry is only dim while the server capability is absent;
          // a signed-in session enables it and the floor does not apply.
          search.disabled = true;
          const out = {
            formats: size('#documentFormatsToggle'),
            formatsMin: getComputedStyle(fmt).minHeight,
            pc: pc ? size('.composer-pc-status-face') : null,
            searchOpacity: getComputedStyle(search).opacity,
            filesNav: size('#filesNavButton'),
            calendarNav: size('#calendarNavButton'),
          };
          search.disabled = false;
          return out;
        }"""
    )
    assert measured["formats"]["h"] >= 32, measured
    assert measured["formatsMin"] == "32px", measured
    if measured["pc"] is not None:
        assert measured["pc"]["h"] >= 32, measured
    assert measured["searchOpacity"] == "0.78", measured
    assert measured["filesNav"]["h"] >= 44, measured
    assert measured["calendarNav"]["h"] >= 44, measured
    page.close()


# ---------------------------------------------------------------------------
# 8 and 9. copy
# ---------------------------------------------------------------------------


def test_copy_corrections_live_in_locale_keys() -> None:
    assert '"nav-connectors": "앱 연결"' in LOCALE
    assert '"nav-connectors": "Connected apps"' in LOCALE
    assert '"pc-delegation-send-note": "메일·메시지 보내기와 외부 서비스에 기록할 때는 항상 확인합니다."' in LOCALE
    assert '"stored-conversation-hint": "이전에 저장한 대화를 불러왔습니다.' in LOCALE
    assert '"stored-conversation-hint": "Loaded from a conversation you saved earlier.' in LOCALE
    # The static fallbacks agree with the keys, and the guide lost its typo.
    assert 'data-locale-key="nav-connectors">앱 연결<' in INDEX
    assert "외부 서비스에 기록할 때는 항상 확인합니다." in INDEX
    assert "채트로 돌아가기" not in HELP
    assert HELP.count("채팅으로 돌아가기") == 2


def test_stored_conversation_hint_is_a_key_not_a_literal() -> None:
    assert 'uiT("stored-conversation-hint")' in APP
    assert 'chip.dataset.localeTitle = "stored-conversation-hint"' in APP
    assert "이전에 저장한 대화를 불러왔습니다" not in APP


@requires_browser
def test_stored_conversation_hint_follows_the_language(browser, server) -> None:
    """The chip is rendered per message, so its hint must survive a language
    switch the same way the rest of the screen does."""
    page = _open(browser, server, 1440, 900, False)
    measured = page.evaluate(
        """() => {
          const article = document.getElementById('assistantMessageTemplate')
            .content.cloneNode(true).querySelector('.assistant-message');
          const chip = article.querySelector('[data-runtime-label]');
          chip.dataset.localeTitle = 'stored-conversation-hint';
          window.PadiemSharedTooltip.label(chip, window.__padiemLocale.text('stored-conversation-hint'));
          document.querySelector('.conversation').appendChild(article);
          const ko = chip.getAttribute('data-padiem-tooltip');
          window.__padiemLocale.apply('en');
          const en = chip.getAttribute('data-padiem-tooltip');
          window.__padiemLocale.apply('ko');
          const back = chip.getAttribute('data-padiem-tooltip');
          article.remove();
          return {ko, en, back};
        }"""
    )
    assert measured["ko"] and measured["ko"] == measured["back"], measured
    assert measured["en"].startswith("Loaded from a conversation"), measured
    assert measured["en"] != measured["ko"], measured
    page.close()
