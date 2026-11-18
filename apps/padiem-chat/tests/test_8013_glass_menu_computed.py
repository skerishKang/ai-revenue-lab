"""#8013 — glass 대화 ⋮ 메뉴의 불투명 판·위치 회복 시험.

sidebar-unified.css:152 · sidebar-section-polish.css:28 ·
sidebar-history-scroll.css:100 의 공용 사이드바 규칙(0,3,2·0,4,2)이 뒤 시트에서
읽히면서 shared-six-panel-frame.css 의 glass 덮어쓰기(0,3,2)를 눌러 죽였다.
이 PR은 glass 규칙을 #historyList id 체인으로 올려 공용 규칙을 그대로 두고
이긴다(새 !important 없음). 메뉴의 세로 방향은 모듈이 목록의 실제 여유로
정한다(menu-opens-up / menu-opens-down 클래스, #8013 재계산).

문자열이 아니라 실행 검사: 정적 서버 + 모의 API(로그인 세션·대화 목록)로
실제 시트를 읽은 페이지에서 메뉴를 열고 계산 값·히트·클릭·호버를 관찰한다.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
FRAME = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-history-module.js").read_text(encoding="utf-8")

SIGNED_STATUS = {
    "ready": True, "authenticated": True,
    "user": {"email": "qa@padiem.local", "name": "QA"},
    "session_state": "active", "shared_login_enabled": False,
    "shared_session_present": False, "status_reachable": True,
    "history_ready": True, "project_files_ready": True,
    "model_requires_session": False,
}
# 여유 계산의 두 방향(위로·아래로)이 모두 관찰되도록 대화를 6개 넣는다.
CONVERSATIONS = {"conversations": [
    {"id": "chat_" + f"{i:032x}", "title": f"대화 {i}번", "pinned": i == 0}
    for i in range(1, 7)
]}

FETCH_STUB = """
(() => {
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  const JSON_HEADERS = { 'content-type': 'application/json' };
  const answer = (body, status) => Promise.resolve(new Response(JSON.stringify(body), {
    status: status, statusText: 'OK', headers: JSON_HEADERS,
  }));
  const offline = () => Promise.resolve(new Response('{"ok":false}', {
    status: 404, statusText: 'Not Found', headers: JSON_HEADERS,
  }));
  const AUTH_STATUS = __AUTH__;
  const CONVERSATIONS = __CONVERSATIONS__;
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    if (!url.includes('/api/')) return realFetch ? realFetch(input, init) : offline();
    if (url.includes('/api/auth/status')) return answer(AUTH_STATUS, 200);
    if (url.includes('/api/conversations')) return answer(CONVERSATIONS, 200);
    return offline();
  };
})();
""".replace("__AUTH__", json.dumps(SIGNED_STATUS)) \
   .replace("__CONVERSATIONS__", json.dumps(CONVERSATIONS))

OPEN_ROW_JS = """(index) => {
  const all = [...document.querySelectorAll('.sidebar #historyList details.history-actions')];
  for (const a of all) { a.open = false; a.removeAttribute('data-probe'); a.removeAttribute('data-menu-placed'); }
  const target = all[index];
  target.scrollIntoView({ block: 'end', behavior: 'instant' });
  target.dataset.probe = '1';
  target.open = true;
  return all.length;
}"""
WAIT_DIRECTION_JS = """() => {
  const details = document.querySelector('.sidebar #historyList details[data-probe="1"]');
  if (!details) return false;
  const menu = details.querySelector('.history-actions-menu');
  if (getComputedStyle(menu).getPropertyValue('--menu-direction') !== 'room-based') {
    return true;  // 이 판은 재계산 대상이 아니다(공용 배치 유지) — 기다릴 것이 없다.
  }
  return details.dataset.menuPlaced === '1';
}"""
READ_MENU_JS = """() => {
  const details = document.querySelector('.sidebar #historyList details[data-probe="1"]');
  if (!details) return null;
  const menu = details.querySelector('.history-actions-menu');
  const cs = getComputedStyle(menu);
  const row = {};
  for (const p of ['background-color', 'right', 'top', 'bottom', 'border-radius',
                   'position', 'z-index']) {
    row[p] = cs.getPropertyValue(p);
  }
  const rect = menu.getBoundingClientRect();
  row['__in_screen'] = rect.top >= 0 && rect.left >= 0
    && rect.bottom <= innerHeight && rect.right <= innerWidth;
  let clip = details.parentElement;
  while (clip && clip !== document.body) {
    const flow = getComputedStyle(clip).overflowY;
    if (flow === 'auto' || flow === 'scroll') break;
    clip = clip.parentElement;
  }
  const cRect = clip.getBoundingClientRect();
  row['__in_container'] = rect.top >= cRect.top - 1 && rect.bottom <= cRect.bottom + 1
    && rect.left >= cRect.left - 1 && rect.right <= cRect.right + 1;
  const hits = {};
  for (const name of ['history-menu-rename', 'history-menu-pin', 'history-menu-delete']) {
    const el = menu.querySelector('.' + name);
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    hits[name] = hit === el || (hit && el.contains(hit));
  }
  row['__hits'] = hits;
  row['__direction'] = cs.getPropertyValue('bottom') === '2px' ? 'up' : 'down';
  row['__wrapper_z'] = getComputedStyle(details).zIndex;
  return row;
}"""

# glass 판의 계산 값(#8013 회복 값).
GLASS_PLATE = {"background-color": "rgba(248, 250, 252, 0.98)", "right": "47px",
               "border-radius": "11px", "position": "absolute", "z-index": "12"}
# 공용 규칙이 그대로 이기는 네 테마의 판 값(이 PR로 변하지 않는다 —
# 2026-11-19 main 실측). 배경은 각 테마의 --sidebar 해석 값.
THEME_PLATE = {
    "light": "rgb(241, 241, 245)",
    "dark": "rgb(14, 20, 27)",
    "cinematic": "rgba(6, 9, 15, 0.88)",
    "padiem-home": "rgba(255, 255, 255, 0.62)",
}


class _StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):  # keep the test output quiet
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _page(playwright, url, theme, width=1440, height=950):
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": width, "height": height},
                            reduced_motion="reduce")
    page.route("**/*", lambda route_obj: route_obj.continue_()
               if "127.0.0.1" in route_obj.request.url else route_obj.abort())
    page.add_init_script(FETCH_STUB)
    page.goto(f"{url}?theme={theme}", wait_until="load")
    page.wait_for_timeout(2500)
    page.wait_for_function(
        "!!document.querySelector('.sidebar #historyList .history-actions-menu')",
        timeout=8000)
    return browser, page


@pytest.mark.parametrize("theme", list(THEME_PLATE) + ["padiem-glass"])
def test_menu_plate_computed_values_per_theme(site, theme):
    """glass는 불투명 밝은 판·행 안쪽 위치를 되찾고, 나머지 네 테마의 판은
    공용 규칙 값 그대로다(이 PR로 변하지 않음)."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site, theme)
        try:
            page.evaluate(OPEN_ROW_JS, 5)
            page.wait_for_function(WAIT_DIRECTION_JS, timeout=4000)
            row = page.evaluate(READ_MENU_JS)
        finally:
            browser.close()
    if theme == "padiem-glass":
        for prop, want in GLASS_PLATE.items():
            assert row[prop] == want, (prop, want, row[prop])
    else:
        assert row["background-color"] == THEME_PLATE[theme], (theme, row)
        assert row["right"] == "0px", (theme, row)
    assert row["__in_screen"] is True, row


def test_glass_menu_items_hit_and_rename_click_works(site):
    """재계산된 방향으로 열린 glass 판의 세 항목 모두 실제 클릭 지점이고,
    이름 바꾸기가 그 자리에서 시작된다(#7175). 판(≈128px)이 목록 컨테이너 안에
    온전히 들어가는 높이(1400)에서 검증한다 — 900·950 화면에서는 컨테이너가
    판보다 작아 어느 방향이든 일부가 잘리는데, 그 절단은 컨테이너 크기 문제지
    이 수정의 대상이 아니다."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site, "padiem-glass", 1440, 1400)
        try:
            chosen = None
            for index in (5, 4, 3, 2, 1, 0):
                page.evaluate(OPEN_ROW_JS, index)
                page.wait_for_function(WAIT_DIRECTION_JS, timeout=4000)
                page.wait_for_timeout(200)
                row = page.evaluate(READ_MENU_JS)
                if row["__in_container"] and all(row["__hits"].values()):
                    chosen = row
                    break
                if index > 0:
                    continue
            assert chosen is not None, "컨테이너 안에 온전히 열리는 행이 없다"
            assert chosen["__wrapper_z"] == "10", chosen  # #8009 자리(열린 details) 보존
            # 호버: 삭제 항목 위로 포인터를 옮겨도 히트가 유지된다.
            page.hover(".sidebar #historyList details[data-probe='1'] "
                       ".history-menu-delete")
            row_hover = page.evaluate(READ_MENU_JS)
            assert row_hover["__hits"]["history-menu-delete"] is True, row_hover
            # 클릭: 이름 바꾸기 → 같은 자리 입력 상자가 생긴다.
            page.click(".sidebar #historyList details[data-probe='1'] "
                       ".history-menu-rename")
            page.wait_for_selector(".sidebar #historyList .history-rename-input",
                                   timeout=3000)
        finally:
            browser.close()


def test_direction_classes_follow_the_list_room(site):
    """방향 클래스는 목록의 실제 여유(위 ≥ 아래 → 위)를 따른다. 클래스를
    소비하는 시트는 유리 시트뿐이고, 다른 테마의 판 위치는 무변화다. 아래로
    열린 판이 뒤 행에 눌리는 히트 문제는 #8009(열린 행 끌어올림)의 몫이다 —
    이 시험은 방향 판정만 고정한다."""
    with sync_playwright() as playwright:
        browser, page = _page(playwright, site, "padiem-glass", 1440, 1400)
        try:
            page.evaluate(OPEN_ROW_JS, 0)
            page.wait_for_function(WAIT_DIRECTION_JS, timeout=4000)
            first = page.evaluate(READ_MENU_JS)
            assert first["__direction"] == "down", first
            assert first["__in_container"] is True, first
        finally:
            browser.close()


def test_the_glass_rule_wins_by_specificity_without_importance() -> None:
    """id 체인 승리는 구조 결정이므로 문자열로 남긴다. 새 !important 없음,
    방향 재계산은 모듈의 몫(이 시트는 규칙을 더하지 않는다)."""
    assert "#historyList .history-row .history-actions-menu {" in FRAME
    rule = FRAME[FRAME.index("#historyList .history-row .history-actions-menu {"):]
    rule = rule[:rule.index("}")]
    assert rule.count("!important") == 0
    assert "roomAbove >= roomBelow" in MODULE
    assert 'menu.style.bottom = "2px"' in MODULE
