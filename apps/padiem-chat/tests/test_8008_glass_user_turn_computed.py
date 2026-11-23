"""#8008 첫 묶음 — glass 사용자 메시지 묶음의 계산 값 고정 시험.

padiem-glass-portrait.css 의 사용자 메시지 묶음(2026-10-17 설계, 같은 파일
#messageList Plan 4 블록)과 그 경쟁 시트(padiem-glass-gutter-alignment.css·
padiem-chat-ui-polish.css)에서 `!important` 를 걷어 낸 뒤에도, 실제 Chromium
계산 값이 이 시험이 고정한 값과 같아야 한다. 승자는 특이성(반복 클래스·
#messageList)으로 정해진다.

문자열 검사가 아니라 실행 검사다: 정적 서버 + 모의 API로 실제 시트를 전부
읽은 페이지에서 템플릿으로 사용자 메시지를 넣고 chat 상태를 강제한 뒤
getComputedStyle 값을 비교한다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.glass_contrast_source import a11y_css, chat_ui_polish_css, glass_css, glass_gutter_css, glass_portrait_css, index_html, mobile_legibility_css, rich_css, rich_response_css, surfaces_css, themes_css, tokens_css

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"

PORTRAIT = glass_portrait_css()
GUTTER = glass_gutter_css()
POLISH = chat_ui_polish_css()

GUEST_STATUS = {
    "ready": True, "authenticated": False, "user": None,
    "session_state": "guest", "shared_login_enabled": False,
    "shared_session_present": False, "status_reachable": True,
    "history_ready": False, "project_files_ready": False,
    "model_requires_session": False,
}

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
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    if (!url.includes('/api/')) return realFetch ? realFetch(input, init) : offline();
    if (url.includes('/api/auth/status')) return answer(AUTH_STATUS, 200);
    return offline();
  };
})();
""".replace("__AUTH__", json.dumps(GUEST_STATUS))

# 템플릿에서 사용자 메시지 한 통을 넣고 chat 상태로 강제한다(픽셀 비교 도구의
# conversation 조합과 같은 방법).
FILL_JS = """() => {
  const shell = document.querySelector('.app-shell');
  if (!shell) return { shell: false };
  shell.dataset.state = 'chat';
  const empty = document.getElementById('emptyState');
  if (empty) empty.style.display = 'none';
  const list = document.getElementById('messageList');
  if (!list) return { list: false };
  list.hidden = false;
  const tpl = document.getElementById('userMessageTemplate');
  if (!tpl) return { template: false };
  const node = tpl.content.firstElementChild.cloneNode(true);
  const bubble = node.querySelector('.message-bubble');
  if (bubble) bubble.textContent = '안녕하세요, 오늘 일정을 요약해 주세요.';
  list.appendChild(node);
  return { ready: true };
}"""

READ_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    message: read('.user-message', ['display', 'padding', 'padding-left', 'margin',
                                    'grid-template-columns', 'gap', 'column-gap',
                                    'justify-content', 'justify-items', 'align-items',
                                    'width']),
    avatar: read('.user-message .user-avatar', ['grid-column', 'grid-row', 'width', 'height',
                                                'border-radius', 'background-color', 'border',
                                                'box-shadow', 'color', 'display', 'font-weight',
                                                'overflow']),
    bubble: read('.user-message .message-bubble', ['grid-column', 'grid-row', 'justify-self',
                                                   'width', 'max-width', 'margin-left',
                                                   'margin-right', 'padding', 'border',
                                                   'border-radius', 'background-color',
                                                   'box-shadow', 'backdrop-filter',
                                                   'font-weight', 'font-size',
                                                   'line-height', 'color']),
    avatarSvg: read('.user-message .user-avatar svg', ['width', 'height']),
    chip: read('.user-message .user-profile-chip', ['display', 'grid-column', 'grid-row',
                                                    'align-self', 'font-size', 'font-weight',
                                                    'line-height', 'color', 'white-space']),
    actions: read('.user-message .user-actions', ['display', 'grid-column', 'grid-row',
                                                  'justify-self', 'margin', 'padding',
                                                  'align-items', 'gap', 'flex-wrap',
                                                  'max-width']),
    action: read('.user-message .user-action', ['appearance', 'min-width', 'min-height',
                                                'width', 'height', 'padding', 'display',
                                                'border-radius', 'background-color',
                                                'color', 'cursor']),
    actionTime: read('.user-message .user-action-time', ['color', 'white-space',
                                                         'margin-right']),
  };
}"""

# 실측 값(2026-11-19, 5테마 픽셀 비교 도구와 같은 안정화 장치). 너비·격자
# 트랙처럼 내용에 따라 달라지는 계산 값은 고정하지 않고, 이 묶음이 선언하는
# 값만 고정한다.
EXPECTED_DESKTOP = {
    "message": {"display": "grid", "padding": "3px 0px 0px", "padding-left": "0px",
                "margin": "0px", "gap": "2px 10px", "column-gap": "10px",
                "justify-content": "end", "justify-items": "end",
                "align-items": "start"},
    "avatar": {"grid-column": "3", "grid-row": "1", "width": "32px", "height": "32px",
               "border-radius": "10px",
               "background-color": "rgba(56, 65, 74, 0.72)",
               "border": "1px solid rgba(255, 255, 255, 0.56)",
               "box-shadow": "rgba(24, 33, 42, 0.14) 0px 8px 24px 0px, "
                             "rgba(255, 255, 255, 0.2) 0px 1px 0px 0px inset",
               "color": "rgb(255, 255, 255)", "display": "grid",
               "font-weight": "700", "overflow": "hidden"},
    "bubble": {"grid-column": "1 / span 3", "grid-row": "2", "justify-self": "end",
               "max-width": "none", "margin-left": "0px", "margin-right": "20px",
               "padding": "0px", "border": "0px none rgb(17, 26, 34)",
               "border-radius": "0px", "background-color": "rgba(0, 0, 0, 0)",
               "box-shadow": "none", "backdrop-filter": "none", "font-weight": "400",
               "font-size": "17px", "line-height": "29.92px", "color": "rgb(17, 26, 34)"},
    "avatarSvg": {"width": "17px", "height": "17px"},
    "chip": {"display": "block", "grid-column": "2", "grid-row": "1",
             "align-self": "center", "font-size": "13px", "font-weight": "700",
             "line-height": "13px", "color": "rgb(83, 96, 108)",
             "white-space": "nowrap"},
    "actions": {"display": "flex", "grid-column": "1 / span 3", "grid-row": "3",
                "justify-self": "end", "margin": "0px 20px 0px 0px", "padding": "0px",
                "align-items": "center", "gap": "4px", "flex-wrap": "wrap",
                "max-width": "100%"},
    "action": {"appearance": "none", "min-width": "0px", "min-height": "0px",
               "width": "26px", "height": "26px", "padding": "0px", "display": "grid",
               "border-radius": "6px", "background-color": "rgba(0, 0, 0, 0)",
               "color": "rgb(83, 96, 108)", "cursor": "pointer"},
    "actionTime": {"color": "rgb(123, 135, 146)", "white-space": "nowrap",
                   "margin-right": "2px"},
}
# 좁은 화면: 본문 글자만 16px/1.72로 내려간다(같은 파일의 좁은 화면 규칙).
# 플랫폼 모바일 하한(≤920px 전용 별도 시트)이 정하는 글자·터치 크기는 이 시험의
# 고정 대상이 아니므로(그 시트의 변경이 그 값을 움직인다) 여기서 고정하지
# 않는다 — 그 값들의 전후 동일성은 측정 기록과 픽셀 비교가 담당한다.
EXPECTED_NARROW = json.loads(json.dumps(EXPECTED_DESKTOP))
EXPECTED_NARROW["bubble"]["font-size"] = "16px"
EXPECTED_NARROW["bubble"]["line-height"] = "27.52px"
for group in ("chip", "action", "actionTime"):
    EXPECTED_NARROW.pop(group)


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


def _read_computed(playwright, url, width, height):
    browser = playwright.chromium.launch()
    try:
        page = browser.new_page(viewport={"width": width, "height": height},
                                reduced_motion="reduce")
        page.route("**/*", lambda route_obj: route_obj.continue_()
                   if "127.0.0.1" in route_obj.request.url else route_obj.abort())
        page.add_init_script(FETCH_STUB)
        page.goto(url + "?theme=padiem-glass", wait_until="load")
        page.wait_for_timeout(2500)
        marker = page.evaluate(FILL_JS)
        assert marker.get("ready") is True, marker
        page.wait_for_timeout(600)
        return page.evaluate(READ_JS)
    finally:
        browser.close()


@pytest.mark.parametrize("width,height,expected", [
    (1440, 950, EXPECTED_DESKTOP), (390, 844, EXPECTED_NARROW),
])
def test_glass_user_turn_keeps_its_computed_values_without_importance(
        site, width, height, expected):
    """!important 를 걷어 낸 뒤에도 묶음의 계산 값은 그대로다."""
    with sync_playwright() as playwright:
        observed = _read_computed(playwright, site, width, height)
    for group, props in expected.items():
        assert observed[group] is not None, group
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (group, prop, want, got)


def test_the_bundle_and_its_old_rivals_carry_no_importance() -> None:
    """묶음과 그 경쟁 규칙에 !important 가 돌아오면 다시 덮어쓰기 층이 생긴다.

    경쟁 규칙은 남아 있되(값 불변) importance 는 양쪽에서 뺐다. 이 시험은 그
    양쪽 모두를 지켜 #8008 의 층 제거를 되돌리지 못하게 한다. 2묶음(Plan 4
    블록)도 같은 규칙으로 지킨다.
    """
    regions = (
        PORTRAIT[PORTRAIT.index("Owner (2026-10-17), Glass theme only"):
                 PORTRAIT.index("/* Narrow phones")],
        PORTRAIT[PORTRAIT.index("/* Owner-confirmed Plan 4"):
                 PORTRAIT.index("/* Answer action bar")],
    )
    assert all("!important" not in region for region in regions)

    def block(source: str, marker: str) -> str:
        start = source.index(marker)
        return source[start:source.index("}", start)]

    for source, marker in (
        (GUTTER, 'body .app-shell[data-state="chat"] .user-message {\n  width:'),
        (GUTTER, ".user-message .message-bubble {\n  margin-left:"),
        (POLISH, 'body .app-shell[data-state="chat"] .user-message {\n  /* #8008'),
    ):
        assert "!important" not in block(source, marker), marker
