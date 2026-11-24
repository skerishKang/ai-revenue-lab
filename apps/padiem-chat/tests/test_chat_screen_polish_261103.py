"""11-03 chat screen polish: the nine audit items, each with one guard.

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

#7811 C4: the audit rules whose target already had a rule in its own sheet
were merged into that rule (send button → attachments.css, card description →
interaction-polish.css, Glass press box → padiem-glass-portrait.css, badge →
voice-composer.css, PC cell → claw-composer-connection-status.css, search →
sidebar-unified.css). The static guards below read the rule that now paints
each value; the browser guards are unchanged.

#8060 25차: the static guards read sheets through _support helpers
(css_rules declarations, html_tags attribute maps, locale_bundle values) and
assert parsed values; this module keeps no raw sheet text. The production
CSS and JS are untouched by this lane.
"""
from __future__ import annotations
import locale_bundle

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

# #8060 25차: 시트 원문 읽기는 _support 헬퍼(css_rules·claw_static·
# html_tags·locale_bundle)가 담당하고 시험은 파싱 값(규칙·선언·속성 맵·
# 로케일 값)을 단언한다. 운영 CSS·JS는 이 레인에서 손대지 않는다.
from _support import claw_static
from _support.html_tags import tags_for_page
from css_rules import (
    declaration,
    find_rules_with_selector,
    rules_for_sheet,
)

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"

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
    # #7811 C4: the pin lives in the composer sheet's own phone rule for the
    # send button. The polish sheet no longer repeats it.
    reserved = rules_for_sheet("attachments.css")
    phone = [rule for rule in reserved if rule.media == "(max-width: 620px)"]
    send = find_rules_with_selector(phone, ".send-button")
    assert len(send) == 1
    assert declaration(send[0], "margin-left") == "auto"
    assert declaration(send[0], "flex") == "0 0 44px"
    assert not find_rules_with_selector(
        rules_for_sheet("chat-screen-polish.css"), ".composer-actions .send-button")
    # The missing-microphone reservation stays, and still out-specifies the pin.
    missing_mic = find_rules_with_selector(
        phone, ".composer-actions:not(:has(> #voiceMicButton)) #sendButton")
    assert [declaration(rule, "margin-left") for rule in missing_mic] == ["calc(44px + 10px)"]
    # The first-screen reservations belong to attachments.css and are
    # untouched by this lane.
    assert any(declaration(rule, "width") == "116px" for rule in reserved)
    assert any(declaration(rule, "width") == "112px"
               and declaration(rule, "min-width") == "112px"
               and declaration(rule, "height") == "44px"
               for rule in reserved)
    assert "0 0 44px" in [declaration(rule, "flex") for rule in
                          find_rules_with_selector(reserved, ".send-button")]


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
# 2. phone home cards: two description lines, badge clear of the content
# ---------------------------------------------------------------------------


def test_phone_home_cards_keep_two_description_lines() -> None:
    # #7827: one clipped line cut the copy short on every theme, so the
    # description now shows up to two lines (line-clamp 2).
    # #7811 C4: the phone rule that used to hide the description
    # (interaction-polish.css) now carries the two-line clamp itself, so the
    # description has one rule instead of a hide and a later un-hide.
    landing = [rule for rule in rules_for_sheet("interaction-polish.css")
               if rule.media == "(max-width: 620px)"]
    clamp = [rule for rule in landing
             if any(".starter small" in selector for selector in rule.selectors)]
    assert len(clamp) == 1
    assert declaration(clamp[0], "display") == "-webkit-box"
    assert declaration(clamp[0], "-webkit-line-clamp") == "2"
    assert declaration(clamp[0], "line-clamp") == "2"
    # 한 줄 절삭(ellipsis·nowrap)은 이 구역에 없다 — 두 줄 클램프가 유일한 형태다.
    assert declaration(clamp[0], "text-overflow") is None
    assert declaration(clamp[0], "white-space") is None
    phone = [rule for rule in rules_for_sheet("chat-screen-polish.css")
             if rule.media == "(max-width: 620px)"]
    assert all(declaration(rule, "text-overflow") is None
               and declaration(rule, "white-space") is None
               for rule in phone)
    assert not [rule for rule in phone
                if any(".starter small" in selector for selector in rule.selectors)]
    assert [rule for rule in phone
            if declaration(rule, "padding-top") == "60px !important"]


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
            twoLines: copy.height <= parseFloat(getComputedStyle(other.querySelector('small')).lineHeight) * 2 + 1,
            overIcon: hits(badge, icon), overTitle: hits(badge, title), overCopy: hits(badge, copy),
            insideCard: badge.right <= card.right && badge.bottom <= card.bottom,
            overflow: document.documentElement.scrollWidth > innerWidth + 1,
          };
        }"""
    )
    assert measured["copyVisible"], measured
    assert measured["twoLines"], measured
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
    rules = rules_for_sheet("calendar.css")
    # 선택되지 않은 항목: base 규칙(#calendarNavButton)은 칠하기·테두리를
    # 선언하지 않는다.
    base = find_rules_with_selector(rules, "#calendarNavButton")
    assert base
    assert all(not any(key.startswith(("background", "border"))
                       for key in rule.declarations)
               for rule in base)
    current = find_rules_with_selector(rules, '#calendarNavButton[aria-current="page"]')
    assert current
    assert all(any(key.startswith("background") for key in rule.declarations)
               for rule in current)
    glass_current = find_rules_with_selector(
        rules, 'html[data-theme="padiem-glass"] #calendarNavButton[aria-current="page"]')
    assert glass_current
    assert all(any(key.startswith("background") for key in rule.declarations)
               for rule in glass_current)
    # A glass rule must not exist for the unselected entry any more.
    assert not find_rules_with_selector(
        rules, 'html[data-theme="padiem-glass"] #calendarNavButton')


def test_new_chat_stops_claiming_the_calendar_and_library_screens() -> None:
    # R5 A10: the aria-current rows moved to chat-nav-module.js with setNavActive.
    nav = claw_static.sheet("chat-nav-module.js")
    lines = [line for line in nav.splitlines()
             if 'chatNav.setAttribute("aria-current"' in line]
    assert len(lines) == 2, lines
    assert '"calendar"' in lines[1] and '"library"' in lines[1], lines
    assert 'chatNav.setAttribute("aria-current"' not in claw_static.sheet("app.js")


def test_every_panel_screen_names_its_own_fragment() -> None:
    app = claw_static.sheet("app.js")
    for fragment in ("#padiem-calendar", "#padiem-library", "#padiem-meeting"):
        assert fragment in app, fragment
    # R5 B2-4: 조각 표는 chat-nav-module.js 로 옮겼다(app.js 는 공유 조각 상수만 보관).
    assert "PANEL_ROUTE_HASH_BY_STATE" not in app
    table = dict(re.findall(r"(\w+):\s*deps\.(\w+_ROUTE_HASH),",
                            claw_static.sheet("chat-nav-module.js")))
    assert table == {
        "calendar": "CALENDAR_ROUTE_HASH",
        "library": "LIBRARY_ROUTE_HASH",
        "meeting": "MEETING_ROUTE_HASH",
        "settings": "ADVANCED_SETTINGS_ROUTE_HASH",
    }
    assert ("window.PadiemChatRouting = Object.freeze("
            "{ syncRouteHash: navModuleInstance.syncRouteHash });") in app
    assert "restoreShellRouteFromHash" in app
    # The module-owned entries stay module-owned: app.js publishes the request
    # and the fragment table, it does not drive the other modules' DOM, and it
    # adds no browser-side watcher (#3232 entry contract, #1728/#2340/#54
    # interception boundary).
    assert 'getElementById("filesNavButton")' not in app
    assert 'getElementById("calendarNavButton")' not in app
    assert "MutationObserver" not in app
    for module_name in ("calendar.js", "library.js"):
        source = claw_static.sheet(module_name)
        assert '"padiem:route-restore"' in source, module_name
        assert "window.PadiemChatRouting?.syncRouteHash?.()" in source, module_name


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
    # #7811 C4: the Glass sheet's own answer-action rule carries the press box.
    selector = ('html[data-theme="padiem-glass"] body .assistant-message '
                '.answer-actions .answer-action')
    glass = find_rules_with_selector(rules_for_sheet("padiem-glass-portrait.css"), selector)
    assert glass
    # #8008 13차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
    assert [declaration(rule, "width") for rule in glass] == ["40px"]
    assert [declaration(rule, "height") for rule in glass] == ["40px"]
    assert [declaration(rule, "min-width") for rule in glass] == ["40px"]
    assert [declaration(rule, "min-height") for rule in glass] == ["40px"]
    assert not find_rules_with_selector(rules_for_sheet("chat-screen-polish.css"), selector)
    # The hints are locale keys, never literals in the builder.
    assert 'button.setAttribute("data-padiem-tooltip", label);' in claw_static.sheet("outputs.js")
    for key in ("answer-copy", "answer-regenerate"):
        assert key in locale_bundle.keys("ko")
        assert key in locale_bundle.keys("en")


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
    icons = [attrs for _tag, attrs in tags_for_page("index.html")
             if attrs.get("class") == "starter-card-icon"]
    assert len(icons) == 4, icons
    for attrs in icons:
        # html.parser는 속성 이름을 소문자로 정규화하고, 브라우저의 SVG 속성
        # 조정도 viewBox 대소문자를 되돌리므로 파싱 값은 같은 계약이다.
        assert attrs.get("viewbox") == "0 0 24 24"
        assert attrs.get("width") == "20" and attrs.get("height") == "20"
        assert attrs.get("stroke") == "currentColor"
        assert attrs.get("stroke-width") == "1.8"
        assert attrs.get("stroke-linecap") == "round"
        assert attrs.get("stroke-linejoin") == "round"
    assert all("status-spark" not in (attrs.get("class") or "")
               for _tag, attrs in tags_for_page("index.html"))
    plates = {(declaration(rule, "background"), declaration(rule, "color"))
              for rule in rules_for_sheet("chat-screen-polish.css")}
    assert ("#eef3f7", "#2d4557") in plates
    assert ("#29485f", "#e5f3fd") in plates


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
    hero = [rule for rule in rules_for_sheet("chat-screen-polish.css")
            if rule.media == "(min-width: 621px)"
            and declaration(rule, "font-size") == "clamp(36px, 4.1vw, 60px)"]
    assert hero


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
    polish = rules_for_sheet("chat-screen-polish.css")
    # #7811 C4: each floor now lives in the rule of the sheet that owns the
    # control, and the polish sheet no longer repeats it.
    badge = [rule for rule in find_rules_with_selector(
        rules_for_sheet("voice-composer.css"), ".starter-grid .document-formats-toggle")
        if declaration(rule, "min-height") is not None]
    assert [declaration(rule, "min-height") for rule in badge] == ["32px"]
    assert not find_rules_with_selector(polish, ".starter-grid .document-formats-toggle")
    face = find_rules_with_selector(
        rules_for_sheet("claw-composer-connection-status.css"), ".composer-pc-status-face")
    # One height for every width: the phone rule no longer lowers the cell.
    assert [declaration(rule, "height") for rule in face
            if declaration(rule, "height") is not None] == ["32px"]
    assert [rule.media for rule in face if declaration(rule, "height") is not None] == [None]
    assert not find_rules_with_selector(polish, ".composer-pc-status-face")
    search_selector = (
        ".sidebar .sidebar-actions-row.sidebar-unified-row > .sidebar-search-item:disabled")
    search = find_rules_with_selector(rules_for_sheet("sidebar-unified.css"), search_selector)
    assert [declaration(rule, "opacity") for rule in search] == [".78"]
    assert not find_rules_with_selector(polish, search_selector)
    # The project "+" was never painted by the polish sheet's 32px rule: the
    # sidebar's own id-scoped rule sizes the only `.section-add-button` in the
    # document. The rule that paints is the one read here.
    assert not find_rules_with_selector(polish, ".sidebar .section-add-button")
    add_button = find_rules_with_selector(
        rules_for_sheet("sidebar-section-polish.css"),
        "html body .app-shell .sidebar #projectsSection #projectCreateButton")
    assert [(declaration(rule, "width"), declaration(rule, "height"))
            for rule in add_button if declaration(rule, "width") is not None] == [("28px", "28px")]
    files_base = [rule for rule in find_rules_with_selector(
        rules_for_sheet("library.css"), "#filesNavButton") if rule.media is None]
    assert len(files_base) == 1
    assert files_base[0].declarations == {"position": "relative", "min-height": "44px"}


def test_polish_sheet_keeps_only_the_rules_that_cannot_move_yet() -> None:
    # #7811 C4: every other audit rule was merged into the sheet that owns its
    # target, or removed because it never painted. The four that stay are
    # listed in the sheet header, each with what it is waiting for.
    polish = rules_for_sheet("chat-screen-polish.css")
    assert sorted(rule.media or "" for rule in polish) == [
        "", "", "(max-width: 620px)", "(min-width: 621px)"]
    assert sum(value.endswith("!important")
               for rule in polish for value in rule.declarations.values()) == 1
    # Removed as dead: Glass menu items sit inside the answer-action row, so the
    # row rule (higher specificity, same 40px) always sized them.
    assert not find_rules_with_selector(
        polish, 'html[data-theme="padiem-glass"] .answer-more-menu .answer-action')


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
    assert claw_static.locale_value("nav-connectors", "ko") == "앱 연결"
    assert claw_static.locale_value("nav-connectors", "en") == "Connected apps"
    assert claw_static.locale_value(
        "pc-delegation-send-note", "ko") == "메일·메시지 보내기와 외부 서비스에 기록할 때는 항상 확인합니다."
    assert (claw_static.locale_value("stored-conversation-hint", "ko") or "").startswith(
        "이전에 저장한 대화를 불러왔습니다.")
    assert (claw_static.locale_value("stored-conversation-hint", "en") or "").startswith(
        "Loaded from a conversation you saved earlier.")
    # The static fallbacks agree with the keys, and the guide lost its typo.
    index = claw_static.sheet("index.html")
    assert 'data-locale-key="nav-connectors">앱 연결<' in index
    assert "외부 서비스에 기록할 때는 항상 확인합니다." in index
    help_text = claw_static.sheet("help.html")
    assert "채트로 돌아가기" not in help_text
    assert "채팅으로 돌아가기" not in help_text
    # #7174: the guide returns through the app's own wording, not a web-page back link.
    assert help_text.count("채팅 화면 열기") == 2


def test_stored_conversation_hint_is_a_key_not_a_literal() -> None:
    app = claw_static.sheet("app.js")
    assert 'uiT("stored-conversation-hint")' in app
    assert 'chip.dataset.localeTitle = "stored-conversation-hint"' in app
    assert "이전에 저장한 대화를 불러왔습니다" not in app


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
