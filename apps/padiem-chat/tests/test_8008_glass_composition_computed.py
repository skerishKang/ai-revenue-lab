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


# #8008 5차 — G·H·M 묶음 8개 캡을 걷어 낸 뒤의 계산 값. 값은 전(main)과 후가 같다.
FILL_R5_JS = """() => {
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
        const rich = document.createElement('div');
        rich.className = 'rich-response';
        rich.textContent = 'rich';
        content.appendChild(rich);
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

READ_R5_JS = """() => {
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
    demo: read('.demo-label', ['border-color', 'background-color', 'text-transform']),
    bodyP: read('.assistant-content > p', ['padding', 'border-radius']),
    bodyRich: read('.assistant-content > .rich-response', ['padding', 'border-radius']),
    icon: read('.assistant-message .answer-actions .answer-action',
               ['border', 'border-radius', 'background-color']),
  };
}"""

EXPECTED_R5 = {
    "demo": {
        "border-color": "rgba(54, 68, 79, 0.1)",
        "background-color": "rgba(72, 84, 94, 0.08)",
        "text-transform": "none",
    },
    "bodyP": {"padding": "0px", "border-radius": "0px"},
    "bodyRich": {"padding": "0px", "border-radius": "0px"},
    "icon": {
        "border": "0px none rgb(83, 96, 108)",
        "border-radius": "6px",
        "background-color": "rgba(0, 0, 0, 0)",
    },
}


def _read_r5(url, width, height):
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
            marker = page.evaluate(FILL_R5_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R5_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r5_cells_keep_their_computed_values_without_importance(site, width, height):
    observed = _read_r5(site, width, height)
    for group, props in EXPECTED_R5.items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 6차 — brand polish 오류 카드·도구 단추·안내·목록 캡 15개를 걷어 낸 뒤의 계산 값.
FILL_R6_JS = """() => {
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
  const err = document.createElement('div');
  err.className = 'error-box';
  err.innerHTML = '<strong>문제가 발생했습니다</strong><p>다시 시도해 주세요.</p><button class="retry-button">다시 시도</button>';
  list.appendChild(err);
  list.dispatchEvent(new Event('padiem:message-lifecycle', { bubbles: true }));
  return { ready: true };
}"""

READ_R6_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    errorBox: read('.error-box', ['border', 'background-image', 'color', 'box-shadow']),
    errorStrong: read('.error-box strong', ['color']),
    errorP: read('.error-box p', ['color']),
    retry: read('.error-box .retry-button', ['border', 'background-color', 'color', 'box-shadow']),
    toolButton: read('.composer .tool-button', ['background-color', 'color', 'border-color']),
    composerNote: read('.composer-note', ['display']),
    messageList: read('.message-list', ['padding-top', 'gap']),
  };
}"""

EXPECTED_R6 = {
    "errorBox": {
        "border": "1px solid rgba(126, 48, 48, 0.24)",
        "background-image": "linear-gradient(155deg, rgba(255, 249, 249, 0.96), rgba(246, 229, 229, 0.9))",
        "color": "rgb(95, 41, 41)",
        "box-shadow": "rgba(73, 35, 35, 0.08) 0px 12px 28px 0px",
    },
    "errorStrong": {"color": "rgb(127, 40, 40)"},
    "errorP": {"color": "rgb(99, 51, 51)"},
    "retry": {
        "border": "1px solid rgba(126, 48, 48, 0.28)",
        "background-color": "rgba(255, 255, 255, 0.82)",
        "color": "rgb(118, 38, 38)",
        "box-shadow": "rgba(255, 255, 255, 0.8) 0px 1px 0px 0px inset",
    },
    "toolButton": {
        "background-color": "rgba(255, 255, 255, 0.26)",
        "color": "rgb(37, 51, 62)",
        "border-color": "rgba(45, 69, 87, 0.08)",
    },
    "composerNote": {"display": "none"},
    "messageList": {"padding-top": "2px", "gap": "22px"},
}


def _read_r6(url, width, height):
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
            marker = page.evaluate(FILL_R6_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R6_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r6_cells_keep_their_computed_values_without_importance(site, width, height):
    observed = _read_r6(site, width, height)
    for group, props in EXPECTED_R6.items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 7차 — brand polish 텍스트 입력·포커스·자리표시자 캡 11개를 걷어 낸 뒤의 계산 값.
READ_R7_JS = """() => {
  const el = document.querySelector('.composer textarea');
  const composer = document.querySelector('.composer');
  const read = (e, props) => {
    if (!e) return null;
    const cs = getComputedStyle(e);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    text: read(el, ['min-height', 'font-size', 'border', 'border-radius',
                    'background-color', 'box-shadow', 'color', 'caret-color', 'outline-style']),
    placeholder: el ? getComputedStyle(el, '::placeholder').getPropertyValue('color') : null,
    composer: read(composer, ['border-color', 'box-shadow']),
  };
}"""

EXPECTED_R7 = {
    "text": {
        "min-height": "50px",
        "font-size": "17px",
        "border": "0px none rgb(23, 32, 42)",
        "border-radius": "0px",
        "background-color": "rgba(0, 0, 0, 0)",
        "box-shadow": "none",
        "color": "rgb(23, 32, 42)",
        "caret-color": "rgb(23, 32, 42)",
        "outline-style": "none",
    },
    "placeholder": "rgba(37, 48, 58, 0.48)",
    "composerPlain": {
        "border-color": "rgba(255, 255, 255, 0.22)",
        "box-shadow": "rgba(255, 255, 255, 0.07) 0px 1px 0px 0px inset, "
                      "rgba(0, 0, 0, 0.22) 0px 22px 64px 0px, "
                      "rgba(136, 201, 255, 0.035) 0px 0px 0px 1px",
    },
    "composerFocus": {
        "border-color": "rgba(79, 91, 101, 0.22)",
        "box-shadow": "rgba(28, 36, 44, 0.16) 0px 20px 54px 0px, "
                      "rgba(255, 255, 255, 0.8) 0px 1px 0px 0px inset, "
                      "rgba(255, 255, 255, 0.34) 0px 0px 0px 1px",
    },
}


def _read_r7(url, width, height):
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
            page.wait_for_timeout(1000)
            plain = page.evaluate(READ_R7_JS)
            page.evaluate("() => { const t = document.querySelector('.composer textarea'); if (t) t.focus(); }")
            page.wait_for_timeout(500)
            focus = page.evaluate(READ_R7_JS)
            return {"text": focus["text"], "placeholder": plain["placeholder"],
                    "composerPlain": plain["composer"], "composerFocus": focus["composer"]}
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r7_input_and_focus_keep_their_computed_values_without_importance(site, width, height):
    observed = _read_r7(site, width, height)
    for group, props in EXPECTED_R7.items():
        got = observed[group]
        if isinstance(props, str):
            assert got == props, (width, height, group, props, got)
            continue
        assert got is not None, (width, height, group)
        for prop, want in props.items():
            assert got[prop] == want, (width, height, group, prop, want, got[prop])


# #8008 8차 — gutter 정렬 시트 13개 캡을 걷어 낸 뒤의 계산 값.
FILL_R8_JS = """() => {
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
        const rr = document.createElement('div');
        rr.className = 'rich-response';
        rr.textContent = 'rich';
        content.appendChild(rr);
        const eb = document.createElement('div');
        eb.className = 'error-box';
        eb.textContent = '오류';
        content.appendChild(eb);
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

READ_R8_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    conversation: read('.conversation', ['padding-inline-start']),
    messageList: read('.message-list', ['width', 'margin-inline-start', 'margin-inline-end']),
    assistantContent: read('.assistant-content', ['width', 'max-width']),
    assistantMessage: read('.assistant-message', ['grid-template-columns', 'gap']),
    assistantMeta: read('.assistant-meta', ['margin-bottom']),
    errorBox: read('.error-box', ['max-width']),
    richResponse: read('.assistant-content > .rich-response', ['width', 'max-width']),
    contentError: read('.assistant-content > .error-box', ['width', 'max-width']),
  };
}"""

EXPECTED_R8 = {
    (1440, 950): {
        "conversation": {"padding-inline-start": "35px"},
        "messageList": {"width": "539.594px", "margin-inline-start": "0px", "margin-inline-end": "0px"},
        "assistantContent": {"width": "495.594px", "max-width": "none"},
        "assistantMessage": {"grid-template-columns": "32px 495.594px", "gap": "12px"},
        "assistantMeta": {"margin-bottom": "6px"},
        "errorBox": {"max-width": "100%"},
        "richResponse": {"width": "530.594px", "max-width": "none"},
        "contentError": {"width": "451.594px", "max-width": "100%"},
    },
    (1100, 900): {
        "conversation": {"padding-inline-start": "27.5px"},
        "messageList": {"width": "381px", "margin-inline-start": "0px", "margin-inline-end": "0px"},
        "assistantContent": {"width": "337px", "max-width": "none"},
        "assistantMessage": {"grid-template-columns": "32px 337px", "gap": "12px"},
        "assistantMeta": {"margin-bottom": "6px"},
        "errorBox": {"max-width": "100%"},
        "richResponse": {"width": "364.5px", "max-width": "none"},
        "contentError": {"width": "293px", "max-width": "100%"},
    },
    (390, 844): {
        "conversation": {"padding-inline-start": "15.6px"},
        "messageList": {"width": "332.812px", "margin-inline-start": "0px", "margin-inline-end": "0px"},
        "assistantContent": {"width": "290.812px", "max-width": "none"},
        "assistantMessage": {"grid-template-columns": "32px 290.812px", "gap": "10px"},
        "assistantMeta": {"margin-bottom": "6px"},
        "errorBox": {"max-width": "100%"},
        "richResponse": {"width": "306.406px", "max-width": "none"},
        "contentError": {"width": "248.812px", "max-width": "100%"},
    },
}


def _read_r8(url, width, height):
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
            marker = page.evaluate(FILL_R8_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R8_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", sorted(EXPECTED_R8))
def test_r8_gutter_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r8(site, width, height)
    for group, props in EXPECTED_R8[(width, height)].items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 9차 — glass 테마 시트 12개 캡을 걷어 낸 뒤의 계산 값.
FILL_R9_JS = """() => {
  const shell = document.querySelector('.app-shell');
  if (!shell) return { shell: false };
  shell.dataset.state = 'chat';
  document.documentElement.setAttribute('data-glass-mode', 'reading');
  const empty = document.getElementById('emptyState');
  if (empty) empty.style.display = 'none';
  const list = document.getElementById('messageList');
  if (list) {
    list.hidden = false;
    for (const tplId of ['userMessageTemplate', 'assistantMessageTemplate']) {
      const tpl = document.getElementById(tplId);
      if (!tpl) continue;
      const node = tpl.content.firstElementChild.cloneNode(true);
      if (tplId === 'assistantMessageTemplate') {
        const content = node.querySelector('.assistant-content');
        if (content) {
          const p = document.createElement('p');
          p.textContent = '답변';
          content.appendChild(p);
          for (const cls of ['source-card', 'reference-note']) {
            const card = document.createElement('div');
            card.className = cls;
            card.textContent = cls;
            content.appendChild(card);
          }
          const rich = document.createElement('div');
          rich.className = 'rich-response';
          rich.innerHTML = '<p class="rich-response-paragraph">본문</p>';
          content.appendChild(rich);
        }
        node.dataset.lifecycle = 'completed';
      } else {
        const bubble = node.querySelector('.message-bubble');
        if (bubble) bubble.textContent = '안녕하세요';
      }
      list.appendChild(node);
    }
    list.dispatchEvent(new Event('padiem:message-lifecycle', { bubbles: true }));
  }
  const bar = document.querySelector('.sidebar') || document.body;
  if (!document.querySelector('.project-row')) {
    const pr = document.createElement('div');
    pr.className = 'project-row';
    pr.innerHTML = '<button class="project-item">프로젝트</button>';
    bar.appendChild(pr);
    const hr = document.createElement('div');
    hr.className = 'history-row';
    hr.innerHTML = '<button class="history-item">기록</button>';
    bar.appendChild(hr);
  }
  return { ready: true };
}"""

READ_R9_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    row: read('.project-row', ['background-color', 'border-top-color', 'box-shadow', 'backdrop-filter']),
    composerWrap: read('.composer-wrap', ['background']),
    composerNote: read('.composer-note', ['color']),
    assistantContent: read('.assistant-content', ['color']),
    assistantMeta: read('.assistant-meta', ['color']),
    card: read('.source-card', ['background-color', 'color', 'border-top-color', 'box-shadow']),
    answerAction: read('.answer-action', ['color']),
  };
}"""

EXPECTED_R9 = {
    "row": {
        "background-color": "rgba(241, 245, 248, 0.12)",
        "border-top-color": "rgba(255, 255, 255, 0.2)",
        "box-shadow": "rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset",
        "backdrop-filter": "blur(18px)",
    },
    "composerWrap": {"background": "rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box"},
    "composerNote": {"color": "rgba(255, 255, 255, 0.3)"},
    "assistantContent": {"color": "rgb(17, 26, 34)"},
    "assistantMeta": {"color": "rgb(83, 96, 108)"},
    "card": {
        "background-color": "rgba(249, 250, 251, 0.94)",
        "color": "rgb(23, 33, 42)",
        "border-top-color": "rgba(73, 86, 98, 0.12)",
        "box-shadow": "rgba(26, 35, 44, 0.11) 0px 18px 48px 0px, rgba(255, 255, 255, 0.48) 0px 1px 0px 0px inset",
    },
    "answerAction": {"color": "rgb(83, 96, 108)"},
}


def _read_r9(url, width, height):
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
            marker = page.evaluate(FILL_R9_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R9_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r9_glass_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r9(site, width, height)
    for group, props in EXPECTED_R9.items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 10차 — 네 시트 쌍의 캡 14개를 함께 걷어 낸 뒤의 계산 값.
READ_R10_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    row: read('.project-row', ['box-shadow', 'backdrop-filter']),
    card: read('.source-card', ['background-color', 'color']),
    meta: read('.assistant-meta', ['color']),
    conversation: read('.conversation', ['background-color', 'border-top-color']),
  };
}"""

EXPECTED_R10 = {
    (1440, 950): {
        "row": {"box-shadow": "rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset",
                "backdrop-filter": "blur(18px)"},
        "card": {"background-color": "rgba(249, 250, 251, 0.94)", "color": "rgb(23, 33, 42)"},
        "meta": {"color": "rgb(83, 96, 108)"},
        "conversation": {"background-color": "rgba(0, 0, 0, 0)",
                         "border-top-color": "rgba(255, 255, 255, 0.7)"},
    },
    (1100, 900): {
        "row": {"box-shadow": "rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset",
                "backdrop-filter": "blur(18px)"},
        "card": {"background-color": "rgba(249, 250, 251, 0.94)", "color": "rgb(23, 33, 42)"},
        "meta": {"color": "rgb(83, 96, 108)"},
        "conversation": {"background-color": "rgba(0, 0, 0, 0)",
                         "border-top-color": "rgba(255, 255, 255, 0.7)"},
    },
    (390, 844): {
        "row": {"box-shadow": "rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset",
                "backdrop-filter": "blur(18px)"},
        "card": {"background-color": "rgba(249, 250, 251, 0.94)", "color": "rgb(23, 33, 42)"},
        "meta": {"color": "rgb(83, 96, 108)"},
        "conversation": {"background-color": "rgba(242, 245, 247, 0.9)",
                         "border-top-color": "rgba(255, 255, 255, 0.58)"},
    },
}


def _read_r10(url, width, height):
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
            marker = page.evaluate(FILL_R9_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R10_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", sorted(EXPECTED_R10))
def test_r10_pairs_keep_their_computed_values_without_importance(site, width, height):
    observed = _read_r10(site, width, height)
    for group, props in EXPECTED_R10[(width, height)].items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 11차 — 남은 시트 쌍·3중 캡 15개를 함께 걷어 낸 뒤의 계산 값.
READ_R11_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    badge: read('.demo-label', ['color']),
    list: read('.message-list', ['gap']),
    conversation: read('.conversation', ['background-color', 'box-shadow', 'backdrop-filter']),
    card: read('.source-card', ['border-top-color']),
    rich: read('.assistant-content > .rich-response', ['border-top-color', 'background-color', 'box-shadow']),
  };
}"""

EXPECTED_R11 = {
    (1440, 950): {
        "badge": {"color": "rgb(120, 131, 140)"},
        "list": {"gap": "22px"},
        "conversation": {
            "background-color": "rgba(0, 0, 0, 0)",
            "box-shadow": "rgba(28, 36, 44, 0.16) 0px 24px 70px 0px, rgba(255, 255, 255, 0.72) 0px 1px 0px 0px inset",
            "backdrop-filter": "blur(30px) saturate(1.06)",
        },
        "card": {"border-top-color": "rgba(73, 86, 98, 0.12)"},
        "rich": {"border-top-color": "rgb(23, 33, 42)", "background-color": "rgba(0, 0, 0, 0)",
                 "box-shadow": "none"},
    },
    (1100, 900): {
        "badge": {"color": "rgb(120, 131, 140)"},
        "list": {"gap": "22px"},
        "conversation": {
            "background-color": "rgba(0, 0, 0, 0)",
            "box-shadow": "rgba(28, 36, 44, 0.16) 0px 24px 70px 0px, rgba(255, 255, 255, 0.72) 0px 1px 0px 0px inset",
            "backdrop-filter": "blur(30px) saturate(1.06)",
        },
        "card": {"border-top-color": "rgba(73, 86, 98, 0.12)"},
        "rich": {"border-top-color": "rgb(23, 33, 42)", "background-color": "rgba(0, 0, 0, 0)",
                 "box-shadow": "none"},
    },
    (390, 844): {
        "badge": {"color": "rgb(120, 131, 140)"},
        "list": {"gap": "22px"},
        "conversation": {
            "background-color": "rgba(242, 245, 247, 0.9)",
            "box-shadow": "rgba(28, 36, 44, 0.16) 0px 24px 70px 0px, rgba(255, 255, 255, 0.72) 0px 1px 0px 0px inset",
            "backdrop-filter": "blur(30px) saturate(1.06)",
        },
        "card": {"border-top-color": "rgba(73, 86, 98, 0.12)"},
        "rich": {"border-top-color": "rgb(23, 33, 42)", "background-color": "rgba(0, 0, 0, 0)",
                 "box-shadow": "none"},
    },
}


def _read_r11(url, width, height):
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
            marker = page.evaluate(FILL_R9_JS)
            assert marker.get("ready") is True, marker
            page.evaluate("""() => {
              const badge = document.createElement('div');
              badge.className = 'demo-label';
              badge.textContent = '상태';
              document.querySelector('.app-shell').appendChild(badge);
            }""")
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R11_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", sorted(EXPECTED_R11))
def test_r11_pairs_keep_their_computed_values_without_importance(site, width, height):
    observed = _read_r11(site, width, height)
    for group, props in EXPECTED_R11[(width, height)].items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 12차 — 유리 행 캡 6개를 걷고 덮어쓰던 규칙의 범위를 좁힌 뒤의 계산 값.
READ_R12_JS = """() => {
  const el = document.querySelector('.project-row');
  if (!el) return null;
  const cs = getComputedStyle(el);
  return {
    'background-color': cs.getPropertyValue('background-color'),
    'border': cs.getPropertyValue('border'),
    'border-radius': cs.getPropertyValue('border-radius'),
    'box-shadow': cs.getPropertyValue('box-shadow'),
    'backdrop-filter': cs.getPropertyValue('backdrop-filter'),
  };
}"""

EXPECTED_R12 = {
    (1440, 950, 'plain'): {
        'background-color': 'rgba(241, 245, 248, 0.12)',
        'border': '1px solid rgba(255, 255, 255, 0.2)',
        'border-radius': '11px',
        'box-shadow': 'rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset',
        'backdrop-filter': 'blur(18px)',
    },
    (1440, 950, 'active'): {
        'background-color': 'rgba(248, 250, 252, 0.2)',
        'border': '1px solid rgba(255, 255, 255, 0.32)',
        'border-radius': '11px',
        'box-shadow': 'rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset',
        'backdrop-filter': 'blur(18px)',
    },
    (1100, 900, 'plain'): {
        'background-color': 'rgba(241, 245, 248, 0.12)',
        'border': '1px solid rgba(255, 255, 255, 0.2)',
        'border-radius': '11px',
        'box-shadow': 'rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset',
        'backdrop-filter': 'blur(18px)',
    },
    (1100, 900, 'active'): {
        'background-color': 'rgba(248, 250, 252, 0.2)',
        'border': '1px solid rgba(255, 255, 255, 0.32)',
        'border-radius': '11px',
        'box-shadow': 'rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset',
        'backdrop-filter': 'blur(18px)',
    },
    (390, 844, 'plain'): {
        'background-color': 'rgba(241, 245, 248, 0.12)',
        'border': '1px solid rgba(255, 255, 255, 0.2)',
        'border-radius': '11px',
        'box-shadow': 'rgba(255, 255, 255, 0.08) 0px 1px 0px 0px inset',
        'backdrop-filter': 'blur(18px)',
    },
}


def _read_r12(url, width, height, active=False):
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
            marker = page.evaluate(FILL_R9_JS)
            assert marker.get("ready") is True, marker
            if active:
                page.hover('.project-row')
            page.wait_for_timeout(900)
            return page.evaluate(READ_R12_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height,state", sorted(EXPECTED_R12))
def test_r12_glass_row_keeps_its_computed_values_without_importance(site, width, height, state):
    observed = _read_r12(site, width, height, active=state == 'active')
    for prop, want in EXPECTED_R12[(width, height, state)].items():
        got = observed[prop]
        assert got == want, (width, height, state, prop, want, got)


# #8008 13차 — 답변 아이콘 3중 캡 16개를 함께 걷어 낸 뒤의 계산 값.
READ_R13_JS = """() => {
  const el = document.querySelector('.assistant-message .answer-actions .answer-action');
  if (!el) return null;
  const cs = getComputedStyle(el);
  const row = {};
  for (const p of ['width', 'height', 'min-width', 'min-height', 'padding',
                   'border', 'border-radius', 'background-color', 'color', 'font-size']) {
    row[p] = cs.getPropertyValue(p);
  }
  return row;
}"""

EXPECTED_R13 = {
    (1440, 950): {'width': '40px', 'height': '40px', 'min-width': '40px', 'min-height': '40px',
                  'padding': '0px', 'border': '0px none rgb(83, 96, 108)', 'border-radius': '6px',
                  'background-color': 'rgba(0, 0, 0, 0)', 'color': 'rgb(83, 96, 108)', 'font-size': '13px'},
    (1100, 900): {'width': '40px', 'height': '40px', 'min-width': '40px', 'min-height': '40px',
                  'padding': '0px', 'border': '0px none rgb(83, 96, 108)', 'border-radius': '6px',
                  'background-color': 'rgba(0, 0, 0, 0)', 'color': 'rgb(83, 96, 108)', 'font-size': '13px'},
    (390, 844): {'width': '44px', 'height': '44px', 'min-width': '44px', 'min-height': '44px',
                 'padding': '0px', 'border': '0px none rgb(83, 96, 108)', 'border-radius': '6px',
                 'background-color': 'rgba(0, 0, 0, 0)', 'color': 'rgb(83, 96, 108)', 'font-size': '14px'},
}


def _read_r13(url, width, height):
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
            return page.evaluate(READ_R13_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", sorted(EXPECTED_R13))
def test_r13_answer_icon_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r13(site, width, height)
    for prop, want in EXPECTED_R13[(width, height)].items():
        got = observed[prop]
        assert got == want, (width, height, prop, want, got)


# #8008 14차 — 유리 아바타 캡 11개를 걷어 낸 뒤의 계산 값.
READ_R14A_JS = """() => {
  const el = document.querySelector('.assistant-avatar');
  if (!el) return null;
  const cs = getComputedStyle(el);
  const row = {};
  for (const p of ['width', 'height', 'border', 'border-radius', 'background-color',
                   'color', 'box-shadow', 'backdrop-filter', 'font-size', 'font-weight']) {
    row[p] = cs.getPropertyValue(p);
  }
  return row;
}"""

EXPECTED_R14A = {
    'width': '32px',
    'height': '32px',
    'border': '1px solid rgba(255, 255, 255, 0.48)',
    'border-radius': '10px',
    'background-color': 'rgba(73, 84, 94, 0.52)',
    'color': 'rgb(255, 255, 255)',
    'box-shadow': 'rgba(17, 25, 33, 0.12) 0px 10px 26px 0px, rgba(255, 255, 255, 0.16) 0px 1px 0px 0px inset',
    'backdrop-filter': 'blur(16px)',
    'font-size': '15px',
    'font-weight': '800',
}


def _read_r14a(url, width, height):
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
            return page.evaluate(READ_R14A_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r14a_avatar_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r14a(site, width, height)
    for prop, want in EXPECTED_R14A.items():
        got = observed[prop]
        assert got == want, (width, height, prop, want, got)


# #8008 15차 — 컴포저 캡 10개를 걷어 낸 뒤의 계산 값.
READ_R15_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    wrap: read('.composer-wrap', ['background', 'padding-top']),
    composer: read('.composer', ['background-image', 'border-top-color', 'box-shadow', 'color']),
    send: read('.send-button', ['display']),
    retry: read('.retry-button', ['background-color', 'border-top-color']),
    recent: read('.recent-section', ['display']),
  };
}"""

EXPECTED_R15 = {
    (1440, 950): {
        'wrap': {'background': 'rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box',
                 'padding-top': '20px'},
        'composer': {'background-image': 'linear-gradient(165deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 251, 0.9))',
                     'border-top-color': 'rgba(255, 255, 255, 0.22)',
                     'box-shadow': 'rgba(255, 255, 255, 0.07) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.22) 0px 22px 64px 0px, rgba(136, 201, 255, 0.035) 0px 0px 0px 1px',
                     'color': 'rgb(23, 32, 42)'},
        'send': {'display': 'grid'},
        'retry': {'background-color': 'rgba(255, 255, 255, 0.82)', 'border-top-color': 'rgba(126, 48, 48, 0.28)'},
        'recent': {'display': 'block'},
    },
    (1100, 900): {
        'wrap': {'background': 'rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box',
                 'padding-top': '20px'},
        'composer': {'background-image': 'linear-gradient(165deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 251, 0.9))',
                     'border-top-color': 'rgba(255, 255, 255, 0.22)',
                     'box-shadow': 'rgba(255, 255, 255, 0.07) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.22) 0px 22px 64px 0px, rgba(136, 201, 255, 0.035) 0px 0px 0px 1px',
                     'color': 'rgb(23, 32, 42)'},
        'send': {'display': 'grid'},
        'retry': {'background-color': 'rgba(255, 255, 255, 0.82)', 'border-top-color': 'rgba(126, 48, 48, 0.28)'},
        'recent': {'display': 'block'},
    },
    (390, 844): {
        'wrap': {'background': 'rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box',
                 'padding-top': '26px'},
        'composer': {'background-image': 'none',
                     'border-top-color': 'rgba(255, 255, 255, 0.22)',
                     'box-shadow': 'rgba(255, 255, 255, 0.07) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.22) 0px 22px 64px 0px, rgba(136, 201, 255, 0.035) 0px 0px 0px 1px',
                     'color': 'rgb(23, 32, 42)'},
        'send': {'display': 'grid'},
        'retry': {'background-color': 'rgba(255, 255, 255, 0.82)', 'border-top-color': 'rgba(126, 48, 48, 0.28)'},
        'recent': {'display': 'block'},
    },
}


def _read_r15(url, width, height):
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
            page.evaluate("""() => {
              const l = document.getElementById('messageList');
              if (l) {
                const eb = document.createElement('div');
                eb.className = 'error-box';
                eb.innerHTML = '<button class=retry-button>retry</button>';
                l.appendChild(eb);
              }
              const actions = document.querySelector('.composer-actions');
              if (actions) {
                const sb = document.createElement('button');
                sb.className = 'send-button';
                sb.textContent = 'send';
                actions.appendChild(sb);
              }
              const rc = document.createElement('div');
              rc.className = 'recent-section';
              document.body.appendChild(rc);
            }""")
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R15_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", sorted(EXPECTED_R15))
def test_r15_composer_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r15(site, width, height)
    for group, props in EXPECTED_R15[(width, height)].items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)


# #8008 16차 — 컴포저 포커스·좁은 폭 캡 3개를 걷어 낸 뒤의 계산 값.
READ_R16_JS = """() => {
  const composer = document.querySelector('.composer');
  const wrap = document.querySelector('.composer-wrap');
  if (!composer || !wrap) return null;
  const cs = getComputedStyle(composer);
  return {
    'border-color': cs.getPropertyValue('border-top-color'),
    'box-shadow': cs.getPropertyValue('box-shadow'),
    'wrap-background': getComputedStyle(wrap).getPropertyValue('background'),
  };
}"""

EXPECTED_R16 = {
    'border-color': 'rgba(79, 91, 101, 0.22)',
    'box-shadow': 'rgba(28, 36, 44, 0.16) 0px 20px 54px 0px, rgba(255, 255, 255, 0.8) 0px 1px 0px 0px inset, rgba(255, 255, 255, 0.34) 0px 0px 0px 1px',
    'wrap-background': 'rgba(0, 0, 0, 0) none repeat scroll 0% 0% / auto padding-box border-box',
}


def _read_r16(url, width, height):
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
            page.evaluate("() => { const t = document.querySelector('.composer textarea'); if (t) t.focus(); }")
            page.wait_for_timeout(900)
            return page.evaluate(READ_R16_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r16_composer_focus_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r16(site, width, height)
    for prop, want in EXPECTED_R16.items():
        got = observed[prop]
        assert got == want, (width, height, prop, want, got)

# #8008 17차 — 리딩 시트 캡 5개를 걷어 낸 뒤의 계산 값.
READ_R17_JS = """() => {
  const read = (sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = cs.getPropertyValue(p);
    return row;
  };
  return {
    content: read('.assistant-content', ['color']),
    conversation: read('.conversation', ['box-shadow', 'transform', 'transition-property', 'transition-duration']),
    card: read('.source-card', ['background-color']),
  };
}"""

EXPECTED_R17 = {
    'content': {'color': 'rgb(17, 26, 34)'},
    'conversation': {
        'box-shadow': 'rgba(28, 36, 44, 0.16) 0px 24px 70px 0px, rgba(255, 255, 255, 0.72) 0px 1px 0px 0px inset',
        'transform': 'none',
        'transition-property': 'all',
        'transition-duration': '1e-06s',
    },
    'card': {'background-color': 'rgba(249, 250, 251, 0.94)'},
}


def _read_r17(url, width, height):
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
            marker = page.evaluate(FILL_R9_JS)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(1200)
            return page.evaluate(READ_R17_JS)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", [(1440, 950), (1100, 900), (390, 844)])
def test_r17_reading_keeps_its_computed_values_without_importance(site, width, height):
    observed = _read_r17(site, width, height)
    for group, props in EXPECTED_R17.items():
        assert observed[group] is not None, (width, height, group)
        for prop, want in props.items():
            got = observed[group][prop]
            assert got == want, (width, height, group, prop, want, got)
