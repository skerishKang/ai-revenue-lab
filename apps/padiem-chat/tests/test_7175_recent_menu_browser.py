"""#7175: 최근 대화 ⋮ 메뉴 — 이름 변경·상단 고정 (브라우저 계약).

실제 index.html·CSS·JS를 정적 서버로 열고 /api만 상태 있는 mock으로 대체한다.
mock은 서버처럼 pinned 먼저 → 최근 순으로 정렬하고 PATCH를 상태에 반영하므로,
새로고침 후 유지(기기 간 유지의 브라우저 측 표현)까지 검사할 수 있다.

검사:
  - 메뉴에 이름 변경·고정/해제·삭제 3개, ko/en 문구는 locale 키에서.
  - 이름 변경: 그 자리 입력, Enter 저장·즉시 반영, Esc 취소(저장 없음), 빈 값 거부.
  - 고정: '고정됨' 묶음이 맨 위, 해제 시 묶음 사라짐, 새로고침 후 유지.
  - 키보드: Tab으로 메뉴 진입, Enter로 실행, Esc로 닫기/취소.
  - 4테마 × 1440/390: 가로 넘침 없음, 메뉴 3항목 가독(대비), 입력 칸이 행 안에 들어감.
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

SIGNED_IN = {"ok": True, "authenticated": True, "ready": True, "history_ready": True,
             "user": {"name": "대표", "email": "owner@example.com"}}
BASE = [
    {"id": "chat_" + "a" * 32, "title": "분기 예산 정리", "pinned": True, "project_id": None,
     "created_at": "2026-11-08T09:00:00Z", "updated_at": "2026-11-08T12:00:00Z"},
    {"id": "chat_" + "b" * 32, "title": "견적서 초안 검토", "pinned": False, "project_id": None,
     "created_at": "2026-11-08T10:00:00Z", "updated_at": "2026-11-08T11:00:00Z"},
    {"id": "chat_" + "c" * 32, "title": "회의록 요약", "pinned": False, "project_id": None,
     "created_at": "2026-11-08T11:00:00Z", "updated_at": "2026-11-08T10:00:00Z"},
]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

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


@pytest.fixture()
def state():
    return {"rows": [dict(r) for r in BASE], "patches": []}


def make_router(state):
    def handler(route):
        request = route.request
        url = request.url
        if url.endswith("/api/auth/status"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(SIGNED_IN))
        elif "/api/conversations/search" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"conversations": [], "query": ""}))
        elif url.rstrip("/").endswith("/api/conversations"):
            rows = sorted(state["rows"], key=lambda c: c["updated_at"], reverse=True)
            rows = sorted(rows, key=lambda c: not c["pinned"])
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"conversations": rows}))
        elif "/api/conversations/" in url and request.method == "PATCH":
            cid = url.rsplit("/", 1)[-1].split("?")[0]
            body = json.loads(request.post_data or "{}")
            state["patches"].append({"id": cid, **body})
            row = next((c for c in state["rows"] if c["id"] == cid), None)
            if row is None:
                route.fulfill(status=404, content_type="application/json", body="{}")
            else:
                row.update({k: body[k] for k in ("title", "pinned") if k in body})
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"updated": True, "conversation": row}))
        elif "/api/claw/runs" in url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "runs": []}))
        elif "/api/" in url:
            route.fulfill(status=404, content_type="application/json", body="{}")
        else:
            route.continue_()
    return handler


def open_page(browser, server, state, width=1440, height=1000, theme="light"):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.route("**/*", make_router(state))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#historyList .history-row").first.wait_for(state="visible", timeout=15_000)
    page.evaluate("(t) => { document.documentElement.setAttribute('data-theme', t);"
                  "document.body.setAttribute('data-theme', t); }", theme)
    page.wait_for_timeout(250)
    return ctx, page, errors


def row(page, index):
    return page.locator("#historyList .history-row").nth(index)


def titles(page):
    return page.locator("#historyList .history-item").all_inner_texts()


def locale_copy(key, lang="ko"):
    source = (STATIC / "locale.js").read_text(encoding="utf-8")
    if lang == "ko":
        block = source[source.index("ko: {"):source.index("en: {")]
    else:
        block = source[source.index("en: {"):]
        block = block[:block.index("\n    }")]
    match = re.search(rf'"{re.escape(key)}":\s*"([^"]*)"', block)
    assert match, key
    return match.group(1)


# ---------------------------------------------------------------- 소스 계약


def test_menu_copy_is_locale_keys_in_both_languages():
    for key in ("conversation-rename", "conversation-pin", "conversation-unpin",
                "conversation-pinned-group", "conversation-title-required",
                "conversation-update-failed"):
        assert locale_copy(key, "ko")
        assert locale_copy(key, "en")
    assert locale_copy("conversation-rename", "ko") != locale_copy("conversation-rename", "en")


# ---------------------------------------------------------------- 브라우저 계약


@requires_browser
def test_menu_has_rename_pin_delete_and_rename_saves_on_enter(browser, server, state):
    ctx, page, errors = open_page(browser, server, state)
    row(page, 0).locator("summary").click()
    menu = row(page, 0).locator(".history-actions-menu")
    assert menu.locator(".history-menu-rename").inner_text() == locale_copy("conversation-rename")
    assert menu.locator(".history-menu-pin").inner_text() == locale_copy("conversation-unpin")
    assert menu.locator(".history-menu-delete").count() == 1

    menu.locator(".history-menu-rename").click()
    field = page.locator(".history-rename-input")
    assert field.input_value() == "분기 예산 정리"
    field.fill("분기 예산 정리 v2")
    field.press("Enter")
    page.wait_for_timeout(700)
    assert titles(page)[0] == "분기 예산 정리 v2"
    assert state["patches"][-1] == {"id": BASE[0]["id"], "title": "분기 예산 정리 v2"}

    # 새로고침 후에도 서버 상태가 그대로 보인다.
    page.reload(wait_until="domcontentloaded")
    page.locator("#historyList .history-row").first.wait_for(state="visible", timeout=15_000)
    assert titles(page)[0] == "분기 예산 정리 v2"
    assert not errors, errors
    ctx.close()


@requires_browser
def test_escape_cancels_rename_without_saving(browser, server, state):
    ctx, page, errors = open_page(browser, server, state)
    row(page, 0).locator("summary").click()
    row(page, 0).locator(".history-menu-rename").click()
    field = page.locator(".history-rename-input")
    field.fill("버려질 제목")
    field.press("Escape")
    page.wait_for_timeout(300)
    assert page.locator(".history-rename-input").count() == 0
    assert titles(page)[0] == "분기 예산 정리"
    assert state["patches"] == []
    assert not errors, errors
    ctx.close()


@requires_browser
def test_empty_title_is_refused_in_place(browser, server, state):
    ctx, page, errors = open_page(browser, server, state)
    row(page, 0).locator("summary").click()
    row(page, 0).locator(".history-menu-rename").click()
    field = page.locator(".history-rename-input")
    field.fill("   ")
    field.press("Enter")
    page.wait_for_timeout(300)
    assert field.get_attribute("aria-invalid") == "true"
    assert page.locator("#historyActionStatus").is_visible()
    assert page.locator("#historyActionStatus").inner_text() == locale_copy("conversation-title-required")
    assert state["patches"] == []
    assert not errors, errors
    ctx.close()


@requires_browser
def test_pin_groups_on_top_and_unpin_removes_group_and_persists(browser, server, state):
    ctx, page, errors = open_page(browser, server, state)
    assert page.locator(".history-group-label").count() == 1
    assert page.locator(".history-group-label").inner_text() == locale_copy("conversation-pinned-group")
    assert titles(page)[0] == "분기 예산 정리"

    # 두 번째(미고정) 행을 고정하면 묶음 안 두 번째로 올라간다.
    row(page, 1).locator("summary").click()
    row(page, 1).locator(".history-menu-pin").click()
    page.wait_for_timeout(700)
    assert titles(page)[:2] == ["분기 예산 정리", "견적서 초안 검토"]
    assert page.locator(".history-row-pinned").count() == 2

    page.reload(wait_until="domcontentloaded")
    page.locator("#historyList .history-row").first.wait_for(state="visible", timeout=15_000)
    assert page.locator(".history-row-pinned").count() == 2

    # 첫 행 고정 해제 → 묶음에는 견적서만 남는다.
    row(page, 0).locator("summary").click()
    assert row(page, 0).locator(".history-menu-pin").inner_text() == locale_copy("conversation-unpin")
    row(page, 0).locator(".history-menu-pin").click()
    page.wait_for_timeout(700)
    assert page.locator(".history-row-pinned").count() == 1
    assert titles(page)[0] == "견적서 초안 검토"
    assert not errors, errors
    ctx.close()


@requires_browser
def test_keyboard_tab_enter_escape_drive_the_menu(browser, server, state):
    ctx, page, errors = open_page(browser, server, state)
    summary = row(page, 0).locator("summary")
    summary.focus()
    summary.press("Enter")  # native details opens on Enter
    page.wait_for_timeout(200)
    assert row(page, 0).locator(".history-actions").get_attribute("open") is not None
    page.keyboard.press("Tab")
    focused = page.evaluate("() => document.activeElement.className")
    assert "history-menu-rename" in focused
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    assert page.locator(".history-rename-input").count() == 1
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.locator(".history-rename-input").count() == 0
    # Esc once more closes the open menu and returns focus to the trigger.
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert row(page, 0).locator(".history-actions").get_attribute("open") is None
    assert not errors, errors
    ctx.close()


def _contrast(a, b):
    def lum(rgb):
        vals = [int(x) / 255 for x in re.findall(r"\d+", rgb)[:3]]
        vals = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in vals]
        return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@requires_browser
@pytest.mark.parametrize("theme", ["light", "dark", "cinematic", "padiem-home"])
@pytest.mark.parametrize("width", [1440, 390])
def test_menu_and_rename_fit_and_read_in_every_theme(browser, server, state, theme, width):
    ctx, page, errors = open_page(browser, server, state, width=width, height=1000 if width > 620 else 844, theme=theme)
    if width <= 620:
        page.click("#mobileMenu")
        page.wait_for_timeout(300)
    row(page, 0).locator("summary").click()
    page.wait_for_timeout(200)
    info = page.evaluate("""() => {
      const menu = document.querySelector('#historyList .history-actions[open] .history-actions-menu');
      const bg = getComputedStyle(menu).backgroundColor;
      const items = [...menu.querySelectorAll('button')].map(b => {
        const r = b.getBoundingClientRect();
        return {text: b.innerText.trim(), color: getComputedStyle(b).color,
                w: r.width, h: r.height, x: r.x, y: r.y};
      });
      return {bg, items, scrollW: document.documentElement.scrollWidth,
              clientW: document.documentElement.clientWidth,
              sidebarW: document.getElementById('sidebar').getBoundingClientRect().width};
    }""")
    assert info["scrollW"] <= info["clientW"] + 1, info
    assert len(info["items"]) == 3
    for item in info["items"]:
        assert item["text"], item
        assert item["h"] >= 32, item
        assert _contrast(item["color"], info["bg"]) >= 3.0, (theme, item, info["bg"])
    # rename field stays inside its row.
    row(page, 0).locator(".history-menu-rename").click()
    fit = page.evaluate("""() => {
      const input = document.querySelector('.history-rename-input');
      const r = input.getBoundingClientRect();
      const row = input.closest('.history-row').getBoundingClientRect();
      return {inputW: r.width, rowW: row.width, left: r.x >= row.x - 1, right: r.right <= row.right + 1};
    }""")
    assert fit["left"] and fit["right"] and fit["inputW"] <= fit["rowW"], fit
    assert not errors, errors
    ctx.close()
