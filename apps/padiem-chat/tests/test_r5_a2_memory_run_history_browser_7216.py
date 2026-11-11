"""R5 A2 — 실제 Chromium에서 등록부(app.provide) 경로로 16개 함수 직접 호출 계약 (#7216).

chat-app-context.js + chat-memory-module.js(12함수) + chat-run-history-module.js(4함수)를
실제 Chromium 페이지에 로드하고, 등록부(window.__app[name])로 16개 이동 함수 전부를 직접
호출해 라우팅·실제 DOM 렌더링·라이브 getter 읽기·라이브 setter 쓰기(clawRunHistoryLimit)를
검증한다.
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
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

MEMORY_NAMES = (
    "setApprovedMemoryStatus",
    "renderMemoryProposalReview",
    "proposalBody",
    "approveProposal",
    "rejectProposal",
    "renderApprovedMemoryCard",
    "renderApprovedMemoryDetail",
    "fetchApprovedMemoryList",
    "loadApprovedMemoryList",
    "loadMoreApprovedMemories",
    "loadApprovedMemoryDetail",
    "syncApprovedMemoryVisibility",
)

RUN_HISTORY_NAMES = (
    "invalidateClawRunsRead",
    "readClawRuns",
    "clawRunStatusLabel",
    "renderClawRunCard",
)

SHARED_BROWSER_DEPS = (
    "authState",
    "shell",
    "clawWorkspace",
    "emptyState",
    "uiT",
    "clawT",
    "syncClawRunHistoryVisibility",
    "mappedUiError",
    "approvedMemoryErrorMessage",
    "safeLocalUiMessage",
    "failureCodeNote",
    "openSavedConversation",
    "downloadClawArtifact",
    "setClawRunHistoryStatus",
    "clawRunHistoryPdfControllers",
    "renderClawApprovalControls",
    "loadClawRunHistory",
    "clawRunHistoryInFlight",
    "clawRunHistoryLimit",
)

CALLS = {
    "setApprovedMemoryStatus": "['상태 안내', 'error', 'c1']",
    "renderMemoryProposalReview": "[[{type: 'contact', name: '제안1', note: '메모', source_channel: 'email'}]]",
    "proposalBody": "[{type: 'contact', name: '제안1', note: '', source_channel: ''}]",
    "approveProposal": "[{type: 'contact', name: '제안1', note: '', source_channel: ''}]",
    "rejectProposal": "[{type: 'contact', name: '제안1', note: '', source_channel: ''}]",
    "renderApprovedMemoryCard": "[{memory_id: 'm1', memory_type: 'contact', name: '기억1', status: 'approved', note: 'n', created_at: '2026-11-11'}]",
    "renderApprovedMemoryDetail": "[{memory_id: 'm1', memory_type: 'contact', name: '기억1', note: 'n', source_channel: 'email', status: 'approved', created_at: '2026-11-11', updated_at: '2026-11-11'}]",
    "fetchApprovedMemoryList": "[]",
    "loadApprovedMemoryList": "[]",
    "loadMoreApprovedMemories": "['cur_1']",
    "loadApprovedMemoryDetail": "['m1']",
    "syncApprovedMemoryVisibility": "[]",
    "invalidateClawRunsRead": "[]",
    "readClawRuns": "[10, 1, {force: false}]",
    "clawRunStatusLabel": "['completed']",
    "renderClawRunCard": "[{run_id: 'r1', title: '실행1', status: 'completed', channel: 'email', action: 'quote', created_at: '2026-11-11T00:00:00Z', result_summary: '완료', session: null, artifact: null}]",
}

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 A2 browser contract</title></head>
<body>
<div class="app-shell" id="shell" data-state="claw"></div>
<div id="emptyState" hidden></div>
<div id="clawMemoryReview" hidden></div>
<details id="clawApprovedDisclosure" hidden>
  <section id="clawApprovedMemory" hidden>
    <button id="clawApprovedRefresh" type="button"></button>
    <div id="clawApprovedLoading" hidden></div>
    <div id="clawApprovedError" hidden></div>
    <div id="clawApprovedList"></div>
    <div id="clawApprovedEmpty" hidden></div>
  </section>
</details>
<details id="clawRunHistoryDisclosure">
  <section id="clawRunHistory">
    <button id="clawRunHistoryFilter" type="button"></button>
    <button id="clawRunHistoryRefresh" type="button"></button>
    <button id="clawRunHistoryExpand" type="button"></button>
  </section>
</details>
<script src="/static/chat-app-context.js"></script>
<script src="/static/chat-memory-module.js"></script>
<script src="/static/chat-run-history-module.js"></script>
<script>
__STRICT__
window.__calls = [];
window.__writes = [];
window.fetch = async (url) => ({
  ok: true,
  status: 200,
  json: async () => ({
    ok: true,
    persisted: false,
    memory: { memory_id: "m1", name: "기억1", status: "approved" },
    memories: [{ memory_id: "m1", memory_type: "contact", name: "기억1", status: "approved", note: "n", created_at: "2026-11-11" }],
    next_cursor: null,
    runs: [{ run_id: "r1", title: "실행1", status: "completed" }],
  }),
});
const clawWorkspace = document.createElement("div");
clawWorkspace.dataset.view = "general";
const state = {
  authState: { authenticated: true },
  shell: document.getElementById("shell"),
  clawWorkspace,
  emptyState: document.getElementById("emptyState"),
  uiT: (k) => "UI:" + k,
  clawT: (k) => "CLAW:" + k,
  syncClawRunHistoryVisibility() {},
  mappedUiError: (m) => new Error(m),
  approvedMemoryErrorMessage: () => "err",
  safeLocalUiMessage: (e, f) => (e && e.message) || f,
  failureCodeNote: () => null,
  openSavedConversation() {},
  downloadClawArtifact() {},
  setClawRunHistoryStatus() {},
  clawRunHistoryPdfControllers: new Set(),
  renderClawApprovalControls() {},
  async loadClawRunHistory() {},
  clawRunHistoryInFlight: false,
  clawRunHistoryLimit: 10,
};
window.__state = state;
const sharedTarget = {};
for (const key of __DEPS__) {
  Object.defineProperty(sharedTarget, key, {
    get() {
      const v = window.__state[key];
      return typeof v === "function" ? v.bind(window.__state) : v;
    },
    set(value) { window.__state[key] = value; window.__writes.push(key); },
  });
}
const strictShared = new Proxy(sharedTarget, {
  get(obj, prop) {
    if (typeof prop === "symbol" || prop in obj) return Reflect.get(obj, prop);
    throw new Error("a2.browser." + String(prop) + " is not defined in test deps");
  },
  set(obj, prop, value) { obj[prop] = value; return true; },
});
window.__app = window.PadiemChatAppContext.create(strictShared);
function recorded(piece) {
  const out = {};
  for (const key of Object.keys(piece)) {
    out[key] = (...args) => { window.__calls.push({ name: key, argc: args.length }); return piece[key](...args); };
  }
  return out;
}
const realMem = window.PadiemChatMemoryModule.create(window.__app);
const realRuns = window.PadiemChatRunHistoryModule.create(window.__app);
window.__mem = window.__app.provide("memory", recorded(realMem));
window.__runs = window.__app.provide("runHistory", recorded(realRuns));
window.__mem.wireMemoryListeners();
window.__mem.wireMemoryReviewContract();
window.__runs.wireRunHistoryListeners();
window.__call = async (name, args) => {
  window.__calls = [];
  await window.__app[name](...args);
  return { last: window.__calls[0] || null, writes: window.__writes.slice() };
};
</script>
</body></html>
"""


def test_registry_calls_reach_all_16_a2_functions_in_chromium() -> None:
    assert set(CALLS) == set(MEMORY_NAMES) | set(RUN_HISTORY_NAMES)

    class DirHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC.parent), **kwargs)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), DirHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    harness_path = STATIC.parent / "tests" / "_a2_browser_harness.html"
    harness_path.write_text(
        HARNESS.replace("__STRICT__", STRICT).replace("__DEPS__", json.dumps(list(SHARED_BROWSER_DEPS))),
        encoding="utf-8",
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base + "/tests/_a2_browser_harness.html", wait_until="load")

            routing = {}
            for name, args in CALLS.items():
                result = page.evaluate(f"() => window.__call('{name}', {args})")
                routing[name] = result["last"]

            missing = [n for n in CALLS if not routing.get(n)]
            assert not missing, f"등록부 호출이 모듈 API에 닿지 않았다: {missing}"

            # Live getter check: guest session hides #clawApprovedMemory & #clawApprovedDisclosure
            page.evaluate("""() => {
              window.__state.authState.authenticated = false;
              return window.__call('syncApprovedMemoryVisibility', []);
            }""")
            assert page.evaluate("() => document.getElementById('clawApprovedMemory').hidden") is True
            assert page.evaluate("() => document.getElementById('clawApprovedDisclosure').hidden") is True

            page.evaluate("""() => {
              window.__state.authState.authenticated = true;
              return window.__call('syncApprovedMemoryVisibility', []);
            }""")
            assert page.evaluate("() => document.getElementById('clawApprovedMemory').hidden") is False

            # Live setter check via wired #clawRunHistoryExpand click
            page.evaluate("() => document.getElementById('clawRunHistoryExpand').click()")
            limit_after = page.evaluate("() => window.__state.clawRunHistoryLimit")
            writes = page.evaluate("() => window.__writes")
            assert limit_after == 30
            assert "clawRunHistoryLimit" in writes
            assert page.evaluate("() => Boolean(window.PadiemChatMemoryReview)") is True
            browser.close()
    finally:
        harness_path.unlink(missing_ok=True)
        server.shutdown()
        server.server_close()
