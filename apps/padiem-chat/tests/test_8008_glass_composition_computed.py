"""#8008 3차 — glass 배치·모션 묶음의 계산 값 고정 시험.

padiem-glass-portrait.css에서 `!important`를 걷어 낸 18개 선언(모션 감소 2,
컴포저 안내 1, ≥1280 배치 5, 1024–1279 배치 10)이 실제 Chromium에서 같은
계산 값을 내는지 본다. 승자는 특정성·시트 순서로 정해진다.

문자열 검사가 아니라 실행 검사다: 정적 서버 + 모의 API로 실제 시트를 전부 읽은
페이지에서 chat 상태를 강제하고 getComputedStyle 값을 비교한다. 폭은 세 구간
(넓은 데스크톱 ≥1280, 압축 데스크톱 1024–1279, 좁은 창 ≤920)을 모두 지나간다.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError:  # UI-focused lanes without a browser still collect these tests.
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None,
                                reason="playwright is not installed in this lane")

STATIC = Path(__file__).resolve().parents[1] / "static"

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
  const read = (sel, pseudo, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el, pseudo || undefined);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    conversation: read('.conversation', null, ['width', 'margin-left', 'margin-right']),
    composerWrap: read('.composer-wrap', null, ['left', 'width', 'transform']),
    composerNote: read('.composer-note', null, ['color']),
    art: read('.main-panel', '::before',
              ['right', 'width', 'background-size', 'opacity', 'transform',
               'transition-property', 'transition-duration']),
  };
}"""


class _StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
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


def _read_computed(url, width, height):
    with sync_playwright() as playwright:
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


# 계산 값은 폭에 따라 달라지는 배치값이다. 세 구간에서 실측한 값을 그대로 고정한다.
# 이 값들은 중요도를 걷어 내기 전(main)과 후가 같다 — 픽셀 비교가 전후 동일성을 본다.
# 일부 선언은 후행 시트(공용 프레임·리딩 층)가 이미 이기고 있었고, 그런 죽은 캡도
# 함께 걷어 냈다(값 불변, 층 제거).
EXPECTED = {
    (1440, 950): {
        "conversation": {"width": "621.594px", "margin-left": "57.6px", "margin-right": "0px"},
        "composerWrap": {"left": "323.6px", "width": "593.594px", "transform": "none"},
        "composerNote": {"color": "rgba(255, 255, 255, 0.3)"},
        "art": {"right": "0px", "width": "516.797px", "background-size": "auto 836px",
                "opacity": "0.7", "transition-property": "none", "transition-duration": "0s"},
    },
    (1100, 900): {
        "conversation": {"width": "448px", "margin-left": "24px", "margin-right": "0px"},
        "composerWrap": {"left": "290px", "width": "420px", "transform": "none"},
        "art": {"right": "0px", "width": "408px", "background-size": "auto 702px",
                "opacity": "0.7", "transition-property": "none", "transition-duration": "0s"},
    },
    (390, 844): {
        "conversation": {"width": "366px", "margin-left": "12px", "margin-right": "12px"},
        "composerWrap": {"left": "195px", "width": "362px"},
        "composerNote": {"color": "rgba(255, 255, 255, 0.3)"},
        "art": {"right": "-132.6px", "opacity": "0.16",
                "transition-property": "none", "transition-duration": "0s"},
    },
}


@pytest.mark.parametrize("width,height", sorted(EXPECTED))
def test_the_composition_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_computed(site, width, height)
    for group, props in EXPECTED[(width, height)].items():
        assert observed[group] is not None, group
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


def test_the_reduced_motion_art_stays_frozen(site):
    """모션 감소에서 그림은 움직이지 않는다 — 중요도 없이도 같은 계산 값."""
    observed = _read_computed(site, 1440, 950)
    art = observed["art"]
    assert art["transition-property"] == "none", art
    assert art["transition-duration"] == "0s", art

# #8008 4차 — F·N·B·E·I 묶음 12개 캡을 걷어 낸 뒤의 계산 값.
FILL_CHAT_JS = """() => {
  const shell = document.querySelector('.app-shell');
  if (!shell) return { shell: false };
  shell.dataset.state = 'chat';
  const empty = document.getElementById('emptyState');
  if (empty) empty.style.display = 'none';
  const list = document.getElementById('messageList');
  if (!list) return { list: false };
  list.hidden = false;
  for (const tplId of ['userMessageTemplate', 'assistantMessageTemplate']) {
    const tpl = document.getElementById(tplId);
    if (!tpl) return { template: tplId };
    const node = tpl.content.firstElementChild.cloneNode(true);
    if (tplId === 'assistantMessageTemplate') {
      const content = node.querySelector('.assistant-content');
      if (content) {
        const p = document.createElement('p');
        p.textContent = '오늘 일정을 정리해 드릴게요.';
        content.appendChild(p);
      }
      node.dataset.lifecycle = 'completed';
    } else {
      const bubble = node.querySelector('.message-bubble');
      if (bubble) bubble.textContent = '안녕하세요, 오늘 일정을 요약해 주세요.';
    }
    list.appendChild(node);
  }
  list.dispatchEvent(new Event('padiem:message-lifecycle', { bubbles: true }));
  return { ready: true };
}"""

READ_CHAT_JS = """() => {
  const read = (sel, props) => {
    const els = [...document.querySelectorAll(sel)];
    const el = els[els.length - 1];
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    meta: read('.assistant-meta', ['text-transform']),
    actions: read('.answer-actions', ['gap', 'margin-top']),
    sibling: read('.answer-action + .answer-action', ['margin-left']),
    composer: read('.composer-wrap', ['background-color']),
    avatar: read('.assistant-avatar', ['border', 'background-color', 'color', 'box-shadow']),
    action: read('.answer-action', ['border-color', 'background-color', 'color']),
  };
}"""

CHROME_EXPECTED = {
    "meta": {"text-transform": "none"},
    "actions": {"gap": "4px", "margin-top": "2px"},
    "sibling": {"margin-left": "0px"},
    "composer": {"background-color": "rgba(0, 0, 0, 0)"},
    "avatar": {
        "border": "1px solid rgba(255, 255, 255, 0.48)",
        "background-color": "rgba(73, 84, 94, 0.52)",
        "color": "rgb(255, 255, 255)",
        "box-shadow": "rgba(17, 25, 33, 0.12) 0px 10px 26px 0px, "
                      "rgba(255, 255, 255, 0.16) 0px 1px 0px 0px inset",
    },
    "action": {
        "border-color": "rgb(83, 96, 108)",
        "background-color": "rgba(0, 0, 0, 0)",
        "color": "rgb(83, 96, 108)",
    },
}


def _read_chat_chrome(url, width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height},
                                    reduced_motion="reduce")
            page.route("**/*", lambda route_obj: route_obj.continue_()
                       if "127.0.0.1" in route_obj.request.url else route_obj.abort())
            page.add_init_script(FETCH_STUB)
            page.goto(url + "?theme=padiem-glass", wait_until="load")
            page.wait_for_timeout(2500)
            marker = page.evaluate(FILL_CHAT_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_CHAT_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_answer_chrome_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_chat_chrome(site, width, height)
    for group, props in CHROME_EXPECTED.items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)
