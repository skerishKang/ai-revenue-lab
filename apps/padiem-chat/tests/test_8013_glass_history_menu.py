"""#8013: glass 대화 ⋮ 메뉴 — 불투명 판·행 아래/위 기하 계약.

공용 sidebar 규칙(`sidebar-history-scroll`·`sidebar-section-polish`·
`sidebar-unified`)은 다른 4테마를 위해 그대로 두고, glass 전용 선택자를
그보다 높은 특이성으로 올려 `background`·`top/right`를 되살린다. 화면 아래
공간이 없을 때만 JS가 `data-menu-placement="above"`를 달고, CSS가 행 위로
뒤집는다. #8009의 열린 행 z-index 30과 `--control-wash-hover`는 유지한다.

브라우저 계약은 playwright가 있는 로컬 실행기에서 실제 클릭·호버·기하를
검사한다. B62 CI venv에는 playwright가 없으므로 그 레인에서는 사유 표시
SKIP이며, 정적 계약은 항상 돈다.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

from css_rules import declaration, find_rules_with_selector, parse_rules

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

# #8060: the raw read lives in _support; the CSS and browser checks stay.
from _support import glass_history_menu_source as sheets

SHARED = sheets.shared_frame_css()

GLASS_MENU = (
    'html[data-theme="padiem-glass"] body .app-shell .sidebar '
    ".history-row .history-actions .history-actions-menu"
)
GLASS_ABOVE = (
    'html[data-theme="padiem-glass"] body .app-shell .sidebar '
    '.history-row .history-actions[data-menu-placement="above"] '
    "> .history-actions-menu"
)
GLASS_OPEN_ROW = (
    'html[data-theme="padiem-glass"] body .app-shell .sidebar '
    ".history-row:has(.history-actions[open])"
)
GLASS_ACTION_HOVER = (
    'html[data-theme="padiem-glass"] body .sidebar .history-actions-menu '
    ".history-menu-action:is(:hover,:focus-visible)"
)
GLASS_DELETE_HOVER = (
    'html[data-theme="padiem-glass"] body .sidebar .history-actions-menu '
    ".history-menu-delete:is(:hover,:focus-visible)"
)

SIGNED_IN = {
    "ok": True,
    "authenticated": True,
    "ready": True,
    "history_ready": True,
    "user": {"name": "대표", "email": "owner@example.com"},
}
BASE = [
    {
        "id": "chat_" + (chr(97 + i) * 32),
        "title": f"대화 {i + 1} — 분기 예산 정리",
        "pinned": False,
        "project_id": None,
        "created_at": "2026-11-08T09:00:00Z",
        "updated_at": f"2026-11-08T{12 - i:02d}:00:00Z",
    }
    for i in range(10)
]
OTHER_THEMES = {
    "light": "rgb(241, 241, 245)",
    "dark": "rgb(14, 20, 27)",
    "cinematic": "rgba(6, 9, 15, 0.88)",
    "padiem-home": "rgba(255, 255, 255, 0.62)",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=sheets.static_dir(), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        threading.Thread(target=web.serve_forever, daemon=True).start()
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


def make_router():
    def handler(route):
        request = route.request
        url = request.url
        if url.endswith("/api/auth/status"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(SIGNED_IN))
        elif "/api/conversations/search" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"conversations": [], "query": ""}),
            )
        elif url.rstrip("/").endswith("/api/conversations"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"conversations": BASE}),
            )
        elif "/api/claw/runs" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "runs": []}),
            )
        elif "/api/" in url:
            route.fulfill(status=404, content_type="application/json", body="{}")
        else:
            route.continue_()

    return handler


def open_page(browser, server, width=1440, height=900, theme="padiem-glass"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR")
    ctx.route("**/*", make_router())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#historyList .history-row").first.wait_for(state="visible", timeout=20_000)
    page.evaluate(
        "(t) => { document.documentElement.dataset.theme = t;"
        "document.body.dataset.theme = t; }",
        theme,
    )
    page.wait_for_timeout(300)
    return ctx, page, errors


def open_menu(page, width, index=0):
    if width <= 620:
        page.click("#mobileMenu")
        page.wait_for_timeout(350)
    page.locator("#historyList .history-row").nth(index).locator("summary").click()
    page.wait_for_timeout(400)


def menu_metrics(page, index=0):
    return page.evaluate(
        """(idx) => {
          const rows = document.querySelectorAll('#historyList .history-row');
          const row = rows[idx < 0 ? rows.length - 1 : idx];
          const actions = row.querySelector('.history-actions');
          const menu = actions.querySelector('.history-actions-menu');
          const mr = menu.getBoundingClientRect();
          const rr = row.getBoundingClientRect();
          return {
            bg: getComputedStyle(menu).backgroundColor,
            position: getComputedStyle(menu).position,
            top: getComputedStyle(menu).top,
            bottom: getComputedStyle(menu).bottom,
            menu: {top: mr.top, bottom: mr.bottom, left: mr.left, right: mr.right},
            row: {top: rr.top, bottom: rr.bottom},
            rowZ: getComputedStyle(row).zIndex,
            menuZ: getComputedStyle(menu).zIndex,
            placement: actions.getAttribute('data-menu-placement'),
          };
        }""",
        index,
    )


def hover_background(page, selector):
    page.locator(selector).hover()
    page.wait_for_timeout(350)
    return page.evaluate(
        """(sel) => {
          const cell = document.querySelector(sel);
          const probe = document.createElement('span');
          probe.style.cssText = 'display:block;width:1px;height:1px;background:var(--control-wash-hover)';
          document.body.appendChild(probe);
          const probeBg = getComputedStyle(probe).backgroundColor;
          probe.remove();
          return {cell: getComputedStyle(cell).backgroundColor, token: probeBg};
        }""",
        selector,
    )


def specificity(selector: str):
    """Return (id, class/attribute/pseudo-class, element) for these simple selectors."""
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = (
        len(re.findall(r"\.[A-Za-z_][\w-]*", selector))
        + len(re.findall(r"\[[^\]]+\]", selector))
        + len(re.findall(r"(?<!:):(?!:)[\w-]+", selector))
    )
    elements = len(re.findall(r"(?<![\w-])(?:html|body)(?![\w-])", selector))
    return ids, classes, elements


# ---------------------------------------------------------------- 정적 계약


def test_glass_menu_beats_the_generic_sidebar_background_rules():
    rules = parse_rules(SHARED)
    menu = [r for r in find_rules_with_selector(rules, GLASS_MENU) if r.media is None]
    assert len(menu) == 1, f"glass 메뉴 규칙 {len(menu)}개"
    assert declaration(menu[0], "background") == "rgba(248,250,252,.98)"
    assert declaration(menu[0], "right") == "0"
    assert declaration(menu[0], "top") == "calc(100% + 4px)"
    for prop in ("background", "right", "top", "position"):
        assert "!important" not in (declaration(menu[0], prop) or ""), prop

    generic = [
        "html body .app-shell .sidebar .history-actions-menu",
        "html body .app-shell .sidebar .history-row .history-actions-menu",
    ]
    assert specificity(GLASS_MENU) > specificity(generic[0])
    assert specificity(GLASS_MENU) > specificity(generic[1])
    # 이슈 표기(0,5,2)와 무관하게, 실제 선택자는 0,6,2로 공용 규칙을 이긴다.
    assert specificity(GLASS_MENU) == (0, 6, 2)


def test_above_flip_is_scoped_to_glass_and_has_no_important():
    rules = parse_rules(SHARED)
    above = [r for r in find_rules_with_selector(rules, GLASS_ABOVE) if r.media is None]
    assert len(above) == 1, f"glass 위쪽 뒤집기 규칙 {len(above)}개"
    assert declaration(above[0], "top") == "auto"
    assert declaration(above[0], "bottom") == "calc(100% + 4px)"
    for prop in ("top", "bottom"):
        assert "!important" not in (declaration(above[0], prop) or ""), prop


def test_open_row_lift_and_hover_token_are_kept():
    rules = parse_rules(SHARED)
    row = [r for r in find_rules_with_selector(rules, GLASS_OPEN_ROW) if r.media is None]
    assert len(row) == 1
    assert declaration(row[0], "z-index") == "30"
    assert declaration(row[0], "position") == "relative"
    for selector in (GLASS_ACTION_HOVER, GLASS_DELETE_HOVER):
        hover = [r for r in find_rules_with_selector(rules, selector) if r.media is None]
        assert len(hover) == 1, selector
        assert declaration(hover[0], "background") == "var(--control-wash-hover)"


# ---------------------------------------------------------------- 브라우저 계약


@requires_browser
def test_glass_menu_is_opaque_opens_below_and_clicks_hovers(browser, server):
    for width, height in ((1440, 900), (390, 844)):
        ctx, page, errors = open_page(browser, server, width, height)
        try:
            open_menu(page, width)
            info = menu_metrics(page)
            assert info["bg"] == "rgba(248, 250, 252, 0.98)", (width, info)
            assert info["position"] == "absolute", info
            assert info["menu"]["top"] >= info["row"]["bottom"] - 1, (width, info)
            assert info["rowZ"] == "30", (width, info)
            assert info["menuZ"] == "12", (width, info)
            assert info["placement"] is None, (width, info)

            hover = hover_background(
                page, ".history-actions[open] > .history-actions-menu .history-menu-rename"
            )
            assert hover["cell"] == hover["token"], hover

            page.locator(
                ".history-actions[open] > .history-actions-menu .history-menu-rename"
            ).click()
            page.wait_for_timeout(180)
            assert page.locator(".history-rename-input").count() == 1
            page.keyboard.press("Escape")
            page.wait_for_timeout(180)
            assert page.locator(".history-rename-input").count() == 0
            assert not errors, errors
        finally:
            ctx.close()


@requires_browser
def test_glass_menu_flips_above_when_the_viewport_has_no_space(browser, server):
    ctx, page, errors = open_page(browser, server, 390, 360)
    try:
        open_menu(page, 390)
        page.locator("#historyList").evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.wait_for_timeout(200)
        last = page.locator("#historyList .history-row").last
        last.locator("summary").click()
        page.wait_for_timeout(400)
        info = menu_metrics(page, -1)
        assert info["placement"] == "above", info
        assert info["menu"]["bottom"] <= info["row"]["top"] + 1, info
        assert info["menu"]["top"] >= 0, info
        assert not errors, errors
    finally:
        ctx.close()


@requires_browser
def test_other_four_themes_keep_their_menu_surface_and_below_geometry(browser, server):
    for theme, expected in OTHER_THEMES.items():
        ctx, page, errors = open_page(browser, server, 1440, 900, theme)
        try:
            open_menu(page, 1440)
            info = menu_metrics(page)
            assert info["bg"] == expected, (theme, info)
            assert info["menu"]["top"] >= info["row"]["bottom"] - 1, (theme, info)
            assert info["placement"] is None, (theme, info)
            assert not errors, errors
        finally:
            ctx.close()
