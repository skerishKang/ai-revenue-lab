"""R5 A1 — 실제 Chromium에서 app.js 자동화 전달 함수 호출 계약.

app.js에서 추출한 27개 한 줄 전달 함수(자동화 13 + 폼 14)를 실제 Chromium
페이지에 주입하고, 실제 모듈 소스와 deps를 연결해 각 전달 함수를 직접 호출한다.
전달 함수마다 라우팅 검사(모듈 API 호출 기록)를 두고, 대표 setter 쓰기와 라이브
getter 읽기(게스트/로그인 분기)를 실제 DOM에서 확인한다.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

ASYNC_NAMES = {"loadClawAutomationRules", "toggleClawAutomationRule",
               "submitClawAutomationEdit", "submitClawAutomationCreate"}
A_NAMES = (
    "resetClawAutomationState", "setClawAutomationLoading", "setClawAutomationError",
    "setClawAutomationForbidden", "renderClawAutomationRules", "loadClawAutomationRules",
    "setClawAutomationToggleStatus", "findRuleToggleButton", "focusRuleToggleAfterReload",
    "toggleClawAutomationRule", "mountAutomationView", "openClawAutomation",
    "setClawAutomationRetryVisible",
)
B_NAMES = (
    "setClawAutomationEditStatus", "syncClawAutomationEditFields", "clawAutomationEditExpression",
    "findRuleEditButton", "focusRuleEditAfterReload", "openClawAutomationEdit",
    "closeClawAutomationEdit", "submitClawAutomationEdit", "setClawAutomationCreateStatus",
    "syncClawAutomationCreateFields", "clawAutomationCreateExpression",
    "resetClawAutomationCreateForm", "closeClawAutomationCreate",
    "scrollClawAutomationCreateIntoView", "submitClawAutomationCreate",
)
SHARED_BROWSER_READS = (
    "authState", "shell", "clawWorkspace", "clawAutomation", "clawAutomationList", "uiT",
    "setNavActive", "closeSidebar", "clearClawWait", "syncClawRunHistoryVisibility",
)

CALLS = {
    "resetClawAutomationState": "[]",
    "setClawAutomationLoading": "[]",
    "setClawAutomationError": "[]",
    "setClawAutomationForbidden": "[]",
    "renderClawAutomationRules": "[[{rule_id: 'r1', name: 'n', schedule_kind: 'cron', schedule_expression: '0 9 * * 1-5', schedule_timezone: 'TZ', enabled: true, target_source: 'manual', output_type: 'docx', background_eligible: true, authority_status: 'canonical'}]]",
    "loadClawAutomationRules": "[]",
    "setClawAutomationToggleStatus": "['claw-automation-toggle-saved']",
    "findRuleToggleButton": "['r1']",
    "focusRuleToggleAfterReload": "['r1']",
    "toggleClawAutomationRule": "['r1', true, null]",
    "mountAutomationView": "[]",
    "openClawAutomation": "[]",
    "setClawAutomationRetryVisible": "[false]",
    "setClawAutomationEditStatus": "[null]",
    "syncClawAutomationEditFields": "[]",
    "clawAutomationEditExpression": "[]",
    "findRuleEditButton": "['r1']",
    "openClawAutomationEdit": "[{rule_id: 'r1', name: 'n', schedule_kind: 'cron', schedule_expression: '0 9 * * 1-5', schedule_timezone: 'TZ'}]",
    "closeClawAutomationEdit": "[]",
    "submitClawAutomationEdit": "[{preventDefault() {}}]",
    "setClawAutomationCreateStatus": "[null]",
    "syncClawAutomationCreateFields": "[]",
    "clawAutomationCreateExpression": "[]",
    "resetClawAutomationCreateForm": "[]",
    "closeClawAutomationCreate": "[]",
    "scrollClawAutomationCreateIntoView": "[]",
    "submitClawAutomationCreate": "[{preventDefault() {}}]",
}

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 automation forwarders</title></head>
<body>
<div class="app-shell" id="shell"></div>
<div id="automationView"><div id="automationViewBody"></div>
  <div id="automationViewTitle">자동화</div>
  <div id="automationViewSignedOut" hidden></div></div>
<section id="clawAutomation">
  <div id="clawAutomationList"></div>
  <div id="clawAutomationLoading" hidden></div>
  <div id="clawAutomationError" hidden></div>
  <div id="clawAutomationForbidden" hidden></div>
  <div id="clawAutomationEmpty" hidden></div>
  <button id="clawAutomationRetry" hidden></button>
  <div id="clawAutomationToggleStatus" hidden></div>
  <form id="clawAutomationEditForm" hidden>
    <input id="clawAutomationEditName"><select id="clawAutomationEditKind"><option value="daypart"></option><option value="interval"></option><option value="cron"></option></select>
    <input id="clawAutomationEditTimezone"><input id="clawAutomationEditDaypart"><div id="clawAutomationEditDaypartField"></div>
    <input id="clawAutomationEditInterval"><div id="clawAutomationEditIntervalField"></div>
    <input id="clawAutomationEditCron"><div id="clawAutomationEditCronField"></div>
    <div id="clawAutomationEditStatus"></div><button id="clawAutomationEditSubmit"></button><button id="clawAutomationEditCancel"></button>
  </form>
  <div id="clawAutomationCreate">
    <form id="clawAutomationCreateForm">
      <input id="clawAutomationCreateName"><select id="clawAutomationCreateKind"><option value="daypart"></option><option value="interval"></option><option value="cron"></option></select>
      <input id="clawAutomationCreateTimezone"><input id="clawAutomationCreateDaypart"><div id="clawAutomationCreateDaypartField"></div>
      <input id="clawAutomationCreateInterval"><div id="clawAutomationCreateIntervalField"></div>
      <input id="clawAutomationCreateCron"><div id="clawAutomationCreateCronField"></div>
      <div id="clawAutomationCreateStatus"></div><button id="clawAutomationCreateSubmit"></button>
    </form>
    <button id="clawAutomationCreateToggle"></button><button id="clawAutomationCreateOpen"></button>
  </div>
</section>
<script src="/static/chat-automation-module.js"></script>
<script src="/static/chat-app-context.js"></script>
<script src="/static/chat-automation-form-module.js"></script>
<script>
__STRICT__
window.__calls = [];
window.__writes = [];
window.fetch = async (url, init) => ({ ok: true, status: 200, json: async () => ({ ok: true, rules: [] }) });
const state = {
  authState: { authenticated: true },
  automationViewMounted: false,
  clawAutomationInFlightRules: new Set(),
  clawAutomationEditingRuleId: null,
  clawAutomationCreateInFlight: false,
  clawAutomationEditInFlight: false,
  shell: document.getElementById("shell"),
  clawWorkspace: document.createElement("div"),
  uiT: (k) => "T:" + k,
  setNavActive() {}, closeSidebar() {}, clearClawWait() {}, syncClawRunHistoryVisibility() {},
};
for (const id of ["clawAutomation", "clawAutomationList", "clawAutomationLoading", "clawAutomationError",
  "clawAutomationForbidden", "clawAutomationEmpty", "clawAutomationRetry", "clawAutomationToggleStatus",
  "clawAutomationEditForm", "clawAutomationEditName", "clawAutomationEditKind", "clawAutomationEditTimezone",
  "clawAutomationEditDaypart", "clawAutomationEditDaypartField", "clawAutomationEditInterval",
  "clawAutomationEditIntervalField", "clawAutomationEditCron", "clawAutomationEditCronField",
  "clawAutomationEditStatus", "clawAutomationEditSubmit", "clawAutomationCreate", "clawAutomationCreateForm",
  "clawAutomationCreateName", "clawAutomationCreateKind", "clawAutomationCreateTimezone",
  "clawAutomationCreateDaypart", "clawAutomationCreateDaypartField", "clawAutomationCreateInterval",
  "clawAutomationCreateIntervalField", "clawAutomationCreateCron", "clawAutomationCreateCronField",
  "clawAutomationCreateStatus", "clawAutomationCreateSubmit", "clawAutomationCreateToggle",
  "clawAutomationCreateOpen"]) {
  state[id] = document.getElementById(id);
}
window.__state = state;
window.__depsA = {};
window.__depsB = {};
function liveDeps(names, target) {
  for (const key of names) {
    Object.defineProperty(target, key, {
      get() {
        const v = window.__state[key];
        return typeof v === "function" ? v.bind(window.__state) : v;
      },
      set(value) { window.__state[key] = value; window.__writes.push(key); },
    });
  }
  return r5StrictDeps(target, "a1.browser");
}
const A_DEPS = __A_DEPS__;
const B_DEPS = __B_DEPS__;
liveDeps(A_DEPS, window.__depsA);
liveDeps(B_DEPS, window.__depsB);
// R5 B1 (rule (d)): app.js와 같이 컨텍스트에 모듈 API를 제공한다 — 전달 함수
// 주입 대신 등록부 경로로 호출을 기록한다.
window.__app = window.PadiemChatAppContext.create(window.__depsA);  // 공유 읽기는 라이브 getter, 컨텍스트가 자기 속성을 붙인다
// 제공 전에 기록 래퍼로 감싼다 — 평탄화된 컨텍스트 키(app[name])도 기록을 거친다.
function recorded(piece) {
  const out = {};
  for (const key of Object.keys(piece)) {
    out[key] = (...args) => { window.__calls.push({ name: key, argc: args.length }); return piece[key](...args); };
  }
  return out;
}
const realA = window.PadiemChatAutomationModule.create(window.__app);
const realB = window.PadiemChatAutomationFormModule.create(window.__app);
window.__realA = realA;
window.__realB = realB;
window.__app.provide("automation", recorded(realA));
window.__app.provide("automationForm", recorded(realB));
window.__call = async (name, args) => {
  window.__calls = [];
  const out = await window.__app[name](...args);
  return { last: window.__calls[0] || null, writes: window.__writes.slice() };
};
</script>
</body></html>
"""


def _build_harness() -> str:
    return (HARNESS
            .replace("__STRICT__", STRICT)
            .replace("__A_DEPS__", json.dumps(sorted(SHARED_BROWSER_READS)))
            .replace("__B_DEPS__", json.dumps(sorted(SHARED_BROWSER_READS))))


def test_forwarders_reach_the_real_modules_in_chromium() -> None:
    handler = SimpleHTTPRequestHandler
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    # SimpleHTTPRequestHandler는 생성 인자로 directory를 받는다.
    server.RequestHandlerClass = handler

    class DirHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC.parent), **kwargs)  # /static/... 경로를 그대로 쓴다

        def log_message(self, *args):
            pass

    server2 = ThreadingHTTPServer(("127.0.0.1", 0), DirHandler)
    thread = threading.Thread(target=server2.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server2.server_address[1]}"
    harness_path = STATIC.parent / "tests" / "_a1_browser_harness.html"
    harness_path.write_text(_build_harness(), encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base + "/tests/_a1_browser_harness.html", wait_until="load")
            # 27개 전달 함수를 전부 직접 호출한다. 편집 제출은 열기가 선행한다.
            page.evaluate("() => window.__call('openClawAutomationEdit', " + CALLS["openClawAutomationEdit"] + ")")
            assert set(CALLS) == set(A_NAMES) | (set(B_NAMES) - {"focusRuleEditAfterReload"}),                 "호출 목록은 등록부로 도달하는 27개 함수와 일치해야 한다"
            routing = {}
            editing_rule_id_at_open = None
            for name, args in CALLS.items():
                result = page.evaluate(f"() => window.__call('{name}', {args})")
                routing[name] = result["last"]
                if name == "openClawAutomationEdit":
                    # 대표 상태 쓰기: 이제 모듈 클로저 소유(보강 가)이므로 행위로
                    # 검증한다 — 폼이 열리고 이름이 채워진다.
                    opened = page.evaluate("""() => ({
                      hidden: document.getElementById('clawAutomationEditForm').hidden,
                      name: document.getElementById('clawAutomationEditName').value,
                    })""")
                    assert opened["hidden"] is False and opened["name"] == "n", opened
            # 라우팅: 모든 전달 함수가 실제 모듈 API를 호출했다.
            missing = [n for n in CALLS if not routing.get(n)]
            assert not missing, f"전달 함수가 모듈 API에 닿지 않았다: {missing}"
            # 라이브 getter: 게스트 상태에서 openClawAutomation은 섹션을 숨긴다.
            page.evaluate("""() => {
              window.__state.authState.authenticated = false;
              window.__calls = [];
              return window.__call('openClawAutomation', []);
            }""")
            hidden = page.evaluate("() => document.getElementById('clawAutomation').hidden")
            assert hidden is True, "게스트 상태에서 섹션이 숨겨져야 한다(라이브 deps 읽기)"
            page.evaluate("""() => {
              window.__state.authState.authenticated = true;
              return window.__call('openClawAutomation', []);
            }""")
            shown = page.evaluate("() => document.getElementById('clawAutomation').hidden")
            assert shown is False, "로그인 상태에서 섹션이 보여야 한다"
            # 마운트: 실제 DOM 이동이 일어났다.
            mounted = page.evaluate("() => document.getElementById('automationViewBody').children.length")
            assert mounted >= 1, "automationViewBody로 섹션이 이동했다"
            browser.close()
    finally:
        harness_path.unlink(missing_ok=True)
        server2.shutdown()
        server2.server_close()
