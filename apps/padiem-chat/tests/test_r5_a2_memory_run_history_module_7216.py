"""R5 A2 — 기억(12함수)·실행 기록(4함수) 모듈 계약 (#7216).

B1 시범(#7439)에서 확정한 보강 4가지를 A2(승인된 기억 + 실행 기록 카드·읽기 캐시)에
동일하게 적용했다:
  (가) 모듈이 자기 선언(DOM 참조·단일 비행 플래그·읽기 캐시)을 create() 안에 가진다
       — create()는 deps를 읽지 않는다.
  (나) 최상위 리스너 4개(기억 새로고침 1 + 실행 기록 필터·새로고침·더보기 3)와 창 계약
       (window.PadiemChatMemoryReview)을 모듈 wire 메서드가 원래 자리에서 등록한다.
  (다) 공유 DOM 참조(clawMemoryReview, clawRunHistory, clawRunHistoryExpand)는
       chat-app-context.js가 소유하고, app.js 소유 상태·함수는 라이브 접근자로 올린다.
  (라) 한 줄 전달 함수 없이 app.provide("memory" | "runHistory", ...) 등록부로 연결한다.

이 시험은 (1) 정적 구조 단언, (2) Node vm에서 strict deps로 16개 이동 함수 + 3개 wire
메서드 전부를 직접 호출해 실제 행위·단일 비행·캐시·라이브 getter/setter를 검증한다.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CONTEXT = (STATIC / "chat-app-context.js").read_text(encoding="utf-8")
MEMORY = (STATIC / "chat-memory-module.js").read_text(encoding="utf-8")
RUN_HISTORY = (STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
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

MOVED_MARKERS = (
    'fetch("/api/claw/memory/approve", {',
    'fetch("/api/claw/memory/reject", {',
    'more.id = "clawApprovedMore";',
    'const CLAW_RUNS_READ_WINDOW_MS = 1500;',
    'const artifactKindMap = Object.freeze({',
    'window.PadiemChatMemoryReview = Object.freeze({',
    'window.__padiemClawRunHistoryIncludeGeneral = next;',
)

OWN_DECLARATIONS = (
    'const clawApprovedMemory = document.getElementById("clawApprovedMemory");',
    'const clawApprovedDisclosure = document.getElementById("clawApprovedDisclosure");',
    'const clawApprovedRefresh = document.getElementById("clawApprovedRefresh");',
    "let approvedMemoryInFlight = false;",
    "const CLAW_RUNS_READ_WINDOW_MS = 1500;",
    "let clawRunsRead = emptyClawRunsRead();",
    'const clawRunHistoryRefresh = document.getElementById("clawRunHistoryRefresh");',
    'const clawRunHistoryFilter = document.getElementById("clawRunHistoryFilter");',
)

LISTENER_LINES = (
    'clawApprovedRefresh.addEventListener("click", () => loadApprovedMemoryList());',
    'clawRunHistoryFilter.addEventListener("click", () => {',
    'clawRunHistoryRefresh.addEventListener("click", () => deps.loadClawRunHistory({ force: true }));',
    'deps.clawRunHistoryExpand.addEventListener("click", () => {',
)

WIRE_CALLS = (
    "memory.wireMemoryListeners();",
    "memory.wireMemoryReviewContract();",
    "runHistory.wireRunHistoryListeners();",
)

REGISTRY_CALLS = (
    'app.provide("memory",',
    'app.provide("runHistory",',
    "app.syncApprovedMemoryVisibility();",
    "app.invalidateClawRunsRead();",
    "app.clawRunStatusLabel(status)",
    "app.renderMemoryProposalReview(",
)

SHARED_READS = (
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


def test_index_loads_a2_modules_before_app() -> None:
    for name in ("./chat-memory-module.js", "./chat-run-history-module.js"):
        assert INDEX.count(name) == 1, name
        assert INDEX.index("./chat-app-context.js") < INDEX.index(name)
        assert INDEX.index(name) < INDEX.index("./app.js")


def test_moved_bodies_and_declarations_live_only_in_the_modules() -> None:
    for marker in MOVED_MARKERS:
        assert (marker in MEMORY) or (marker in RUN_HISTORY), marker
        assert marker not in APP, marker
    for decl in OWN_DECLARATIONS:
        assert (decl in MEMORY) or (decl in RUN_HISTORY), decl
        assert decl not in APP, decl
    for ctx_prop in ("clawMemoryReview", "clawRunHistory", "clawRunHistoryExpand"):
        assert f'context.{ctx_prop} = document.getElementById("{ctx_prop}");' in CONTEXT


def test_listeners_and_window_contract_register_from_module_wire_not_app() -> None:
    for line in LISTENER_LINES:
        assert (line in MEMORY) or (line in RUN_HISTORY), line
        assert line not in APP, line
    for call in WIRE_CALLS:
        assert call in APP, call
    assert "function wireMemoryListeners() {" in MEMORY
    assert "function wireMemoryReviewContract() {" in MEMORY
    assert "function wireRunHistoryListeners() {" in RUN_HISTORY


def test_registry_replaces_one_line_forwarders_and_modules_fit_budget() -> None:
    for name in MEMORY_NAMES + RUN_HISTORY_NAMES:
        assert f"function {name}(" not in APP, name
    for call in REGISTRY_CALLS:
        assert call in APP, call
    assert "window.PadiemChatMemoryModule = {" in MEMORY
    assert "window.PadiemChatRunHistoryModule = {" in RUN_HISTORY
    assert len(MEMORY.splitlines()) <= 500
    assert len(RUN_HISTORY.splitlines()) <= 500
    for name in MEMORY_NAMES:
        assert f"function {name}(" in MEMORY, name
    for name in RUN_HISTORY_NAMES:
        assert f"function {name}(" in RUN_HISTORY, name
    for name in SHARED_READS:
        assert f"get {name}() {{ return {name}; }}" in APP, name
    assert "set clawRunHistoryLimit(value) { clawRunHistoryLimit = value; }" in APP


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
__STRICT__

function makeElement(tag, id = "") {
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    id: String(id || ""),
    className: "", textContent: "", hidden: false, disabled: false, open: false,
    dataset: {}, children: [], listeners: {}, attrs: {},
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      this[k] = String(v);
      if (k.startsWith("data-")) {
        const camel = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        this.dataset[camel] = String(v);
      }
    },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    removeAttribute(k) { delete this.attrs[k]; delete this.dataset[k.replace(/^data-/, "")]; },
    append(...xs) { xs.forEach((x) => this.appendChild(x)); },
    appendChild(x) { x.parentNode = this; this.children.push(x); return x; },
    replaceChildren(...xs) { this.children = []; xs.forEach((x) => this.appendChild(x)); },
    remove() {
      this.removed = true;
      if (this.parentNode && Array.isArray(this.parentNode.children)) {
        this.parentNode.children = this.parentNode.children.filter((c) => c !== this);
      }
    },
    querySelector(sel) {
      if (sel === ".claw-approved-detail") {
        return this.children.find((c) => c.className === "claw-approved-detail") || null;
      }
      return null;
    },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    click() { for (const fn of (this.listeners.click || [])) fn(); },
  };
  return node;
}

const byId = {};
for (const id of [
  "shell", "emptyState",
  "clawApprovedMemory", "clawApprovedDisclosure", "clawApprovedRefresh",
  "clawApprovedLoading", "clawApprovedError", "clawApprovedList",
  "clawApprovedEmpty", "clawMemoryReview",
  "clawRunHistory", "clawRunHistoryRefresh", "clawRunHistoryFilter", "clawRunHistoryExpand",
]) {
  byId[id] = makeElement(id.endsWith("Disclosure") ? "details" : "div", id);
}

const documentShim = {
  documentElement: { lang: "ko" },
  getElementById(id) {
    if (byId[id]) return byId[id];
    if (id === "clawApprovedMore") {
      return byId.clawApprovedList.children.find((c) => c.id === "clawApprovedMore") || null;
    }
    return null;
  },
  createElement: (tag) => makeElement(tag),
};

const requests = [];
let fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, memories: [], runs: [] }) });

const live = {
  authState: { authenticated: true },
  shell: byId.shell,
  clawWorkspace: makeElement("div"),
  emptyState: byId.emptyState,
  uiT: (key) => key === "claw-runs-status-completed" ? "DONE_KO" : key.startsWith("claw-runs-status-") ? key : "UI:" + key,
  clawT: (key, vars) => {
    if (vars && vars.kind) return "KIND:" + vars.kind;
    return "CLAW:" + key;
  },
  syncClawRunHistoryVisibility() { live.calls.push("syncClawRunHistoryVisibility"); },
  mappedUiError(msg, data) {
    const err = new Error(msg);
    err.code = data && data.error && data.error.code ? data.error.code : "mapped";
    return err;
  },
  approvedMemoryErrorMessage: () => "mem-err",
  safeLocalUiMessage: (err, fallback) => (err && err.message) || fallback,
  failureCodeNote: (code) => {
    if (!code) return null;
    const s = makeElement("small");
    s.textContent = "CODE:" + code;
    return s;
  },
  openSavedConversation(cid) { live.openedSessions.push(cid); },
  downloadClawArtifact(docId, name) { live.downloads.push([docId, name]); },
  setClawRunHistoryStatus(msg) { live.historyStatuses.push(msg); },
  clawRunHistoryPdfControllers: new Set(),
  renderClawApprovalControls(container, runId, onDone) {
    const b = makeElement("button");
    b.dataset.approvalRunId = runId;
    b.addEventListener("click", () => onDone());
    container.appendChild(b);
  },
  async loadClawRunHistory(opts) { live.historyLoads.push(opts || null); },
  clawRunHistoryInFlight: false,
  clawRunHistoryLimit: 10,
  calls: [],
  openedSessions: [],
  downloads: [],
  historyStatuses: [],
  historyLoads: [],
};
live.clawWorkspace.dataset.view = "general";
live.shell.dataset.state = "claw";
live.emptyState.hidden = true;

const sandbox = {
  document: documentShim,
  fetch: (url, init) => { requests.push({ url: String(url), init: init || null }); return fetchImpl(url, init); },
  JSON, Set, Map, Object, Array, Number, String, Boolean, Date, Promise, Intl, encodeURIComponent, Error,
  console: { error() {} }, setTimeout,
};
sandbox.window = {
  ...sandbox,
  PadiemClawPdfPreview: {
    validHistoricalArtifact: (a) => Boolean(a && a.media_type === "application/pdf"),
    create({ mount, onError }) {
      const btn = makeElement("button");
      btn.className = "pdf-check";
      return {
        setHistorical() { mount.appendChild(btn); return true; },
        destroy() {},
        triggerError(m) { onError(m); },
      };
    },
  },
};
sandbox.__LIVE__ = live;
sandbox.r5StrictDeps = r5StrictDeps;
sandbox.__SHARED__ = __SHARED_JSON__;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(__CONTEXT__, "utf8"), sandbox, { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(__MEMORY__, "utf8"), sandbox, { filename: "chat-memory-module.js" });
vm.runInContext(fs.readFileSync(__RUN_HISTORY__, "utf8"), sandbox, { filename: "chat-run-history-module.js" });
vm.runInContext(`
  const target = {};
  for (const n of __SHARED__) {
    Object.defineProperty(target, n, {
      get() {
        const v = __LIVE__[n];
        return typeof v === "function" ? v.bind(__LIVE__) : v;
      },
      set(value) { __LIVE__[n] = value; },
    });
  }
  const sharedProxy = new Proxy(target, {
    get(obj, prop) {
      if (typeof prop === "symbol" || prop in obj) return Reflect.get(obj, prop);
      throw new Error("context.shared." + String(prop) + " is not defined in test deps");
    },
    set(obj, prop, value) { obj[prop] = value; return true; },
  });
  globalThis.app = window.PadiemChatAppContext.create(sharedProxy);
  globalThis.memory = app.provide("memory", window.PadiemChatMemoryModule.create(app));
  globalThis.runHistory = app.provide("runHistory", window.PadiemChatRunHistoryModule.create(app));
`, sandbox);

(async () => {
  const assert = require("assert");
  const M = sandbox.memory;
  const R = sandbox.runHistory;
  const app = sandbox.app;
  const checks = {};

  // 1) Rule (a): create() reads zero deps
  const strictEmpty = r5StrictDeps({}, "strict.empty");
  assert.ok(sandbox.window.PadiemChatMemoryModule.create(strictEmpty));
  assert.ok(sandbox.window.PadiemChatRunHistoryModule.create(strictEmpty));
  checks.create_reads_no_deps = true;

  // 2) Rule (d): duplicate module registration throws
  assert.throws(() => app.provide("memory", M), /duplicate module registration/);
  assert.throws(() => app.provide("runHistory", R), /duplicate module registration/);
  checks.duplicate_throws = true;

  // 3) Direct call: setApprovedMemoryStatus + proposalBody + renderMemoryProposalReview
  M.setApprovedMemoryStatus("실패 안내", "error", "e_code");
  assert.equal(byId.clawApprovedError.hidden, false);
  assert.equal(byId.clawApprovedError.dataset.state, "error");
  assert.equal(byId.clawApprovedError.children.length, 1);
  M.setApprovedMemoryStatus("", "");
  assert.equal(byId.clawApprovedError.hidden, true);

  assert.deepEqual(
    M.proposalBody({ type: "contact", name: "홍길동", note: "", source_channel: "" }),
    { type: "contact", name: "홍길동", note: null, source_channel: null },
  );

  M.renderMemoryProposalReview([]);
  assert.equal(byId.clawMemoryReview.hidden, true);
  M.renderMemoryProposalReview([{ type: "contact", name: "거래처", note: "비고", source_channel: "email" }]);
  assert.equal(byId.clawMemoryReview.hidden, false);
  assert.equal(byId.clawMemoryReview.children.length, 2); // h3 + 1 proposal card
  checks.proposal_review = true;

  // 4) Direct call: approveProposal & rejectProposal (+ single-flight guard)
  fetchImpl = async (url) => {
    if (String(url) === "/api/claw/memory/approve") {
      return { ok: true, status: 200, json: async () => ({ ok: true, memory: { memory_id: "m1" } }) };
    }
    if (String(url) === "/api/claw/memory/reject") {
      return { ok: true, status: 200, json: async () => ({ ok: true, persisted: false }) };
    }
    return {
      ok: true, status: 200,
      json: async () => ({
        ok: true,
        memories: [{ memory_id: "m1", memory_type: "contact", name: "거래처", status: "approved", note: "메모", created_at: "2026-11-10" }],
        next_cursor: "cur_1",
      }),
    };
  };
  let mark = requests.length;
  await M.approveProposal({ type: "contact", name: "거래처", note: "메모", source_channel: "email" });
  const approveReq = requests.slice(mark).find((r) => r.url === "/api/claw/memory/approve");
  assert.ok(approveReq && approveReq.init.method === "POST");
  assert.equal(JSON.parse(approveReq.init.body).approved, true);
  assert.equal(byId.clawApprovedList.children.length, 2); // 1 card + #clawApprovedMore

  mark = requests.length;
  await M.rejectProposal({ type: "contact", name: "거절건", note: "", source_channel: "" });
  const rejectReq = requests.slice(mark).find((r) => r.url === "/api/claw/memory/reject");
  assert.ok(rejectReq && rejectReq.init.method === "POST");
  assert.equal("approved" in JSON.parse(rejectReq.init.body), false);
  checks.approve_reject = true;

  // 5) Direct call: renderApprovedMemoryCard, renderApprovedMemoryDetail, loadApprovedMemoryDetail
  const cardEl = M.renderApprovedMemoryCard({
    memory_id: "m2", memory_type: "contact", name: "카드2", status: "approved", note: "n", created_at: "2026-11-11",
  });
  assert.equal(cardEl.dataset.memoryId, "m2");
  M.renderApprovedMemoryDetail({
    memory_id: "m2", memory_type: "contact", name: "카드2", note: "n",
    source_channel: "email", status: "approved", created_at: "c", updated_at: "u",
  });
  assert.ok(byId.clawApprovedList.querySelector(".claw-approved-detail"));

  byId.clawApprovedDisclosure.open = false;
  fetchImpl = async () => ({
    ok: true, status: 200,
    json: async () => ({ ok: true, memory: { memory_id: "m2", name: "상세", status: "approved" } }),
  });
  await M.loadApprovedMemoryDetail("m2");
  assert.equal(byId.clawApprovedDisclosure.open, true);
  checks.card_and_detail = true;

  // 6) Direct call: fetchApprovedMemoryList, loadApprovedMemoryList, loadMoreApprovedMemories
  fetchImpl = async () => ({
    ok: true, status: 200,
    json: async () => ({
      ok: true,
      memories: [{ memory_id: "m1", name: "첫번째", status: "approved" }],
      next_cursor: "cur_next",
    }),
  });
  await M.fetchApprovedMemoryList();
  assert.ok(documentShim.getElementById("clawApprovedMore"));

  fetchImpl = async () => ({
    ok: true, status: 200,
    json: async () => ({
      ok: true,
      memories: [{ memory_id: "m3", name: "추가건", status: "approved" }],
      next_cursor: "",
    }),
  });
  await M.loadMoreApprovedMemories("cur_next");
  assert.equal(documentShim.getElementById("clawApprovedMore"), null);

  // Stale 400 cursor removes button and shows notice
  const staleBtn = makeElement("button", "clawApprovedMore");
  staleBtn.dataset.cursor = "bad_cur";
  byId.clawApprovedList.appendChild(staleBtn);
  fetchImpl = async () => ({ ok: false, status: 400, json: async () => ({}) });
  await M.loadMoreApprovedMemories("bad_cur");
  assert.equal(documentShim.getElementById("clawApprovedMore"), null);
  assert.equal(byId.clawApprovedError.hidden, false);

  fetchImpl = async () => ({ ok: true, status: 200, json: async () => ({ ok: true, memories: [] }) });
  await M.loadApprovedMemoryList();
  assert.equal(byId.clawApprovedEmpty.hidden, false);
  checks.list_and_more = true;

  // 7) Direct call: syncApprovedMemoryVisibility (live getter reads) + wireMemory*
  live.authState.authenticated = false;
  app.syncApprovedMemoryVisibility();
  assert.equal(byId.clawApprovedMemory.hidden, true);
  assert.equal(byId.clawApprovedDisclosure.hidden, true);

  live.authState.authenticated = true;
  live.emptyState.hidden = true;
  live.shell.dataset.state = "claw";
  app.syncApprovedMemoryVisibility();
  assert.equal(byId.clawApprovedMemory.hidden, false);

  M.wireMemoryListeners();
  assert.equal(byId.clawApprovedRefresh.listeners.click.length, 1);
  M.wireMemoryReviewContract();
  assert.ok(sandbox.window.PadiemChatMemoryReview);
  live.calls.length = 0;
  sandbox.window.PadiemChatMemoryReview.sync();
  assert.deepEqual(live.calls, ["syncClawRunHistoryVisibility"]);
  checks.memory_visibility_and_wire = true;

  // 8) Direct call: readClawRuns & invalidateClawRunsRead
  let runsFetches = 0;
  fetchImpl = async (url) => {
    runsFetches += 1;
    return { ok: true, status: 200, json: async () => ({ ok: true, runs: [{ run_id: "r1" }] }) };
  };
  await app.readClawRuns(30, 1);
  await app.readClawRuns(10, 1);
  assert.equal(runsFetches, 1, "wider cached read satisfies narrower limit");
  app.invalidateClawRunsRead();
  await app.readClawRuns(10, 1);
  assert.equal(runsFetches, 2, "invalidate clears short-window cache");
  checks.runs_cache = true;

  // 9) Direct call: clawRunStatusLabel & renderClawRunCard
  assert.equal(app.clawRunStatusLabel("completed"), "DONE_KO");
  assert.equal(app.clawRunStatusLabel("custom_raw_state"), "custom_raw_state");

  const runCard = app.renderClawRunCard({
    run_id: "run_1",
    title: "견적 생성",
    status: "waiting_approval",
    channel: "email",
    action: "quote",
    created_at: "2026-11-11T00:00:00Z",
    result_summary: "요약",
    session: { conversation_id: "chat_" + "a".repeat(32) },
    artifact: {
      document_id: "doc_" + "b".repeat(32),
      filename: "out.pdf",
      media_type: "application/pdf",
    },
  });
  assert.equal(runCard.dataset.runState, "waiting_approval");
  assert.equal(live.clawRunHistoryPdfControllers.size, 1);
  // Click session reopen & artifact download inside rendered card
  const walk = (n, acc = []) => { (n.children || []).forEach((c) => { acc.push(c); walk(c, acc); }); return acc; };
  const allNodes = walk(runCard);
  const sessionBtn = allNodes.find((n) => (n.className || "").includes("claw-run-card-session"));
  const dlBtn = allNodes.find((n) => n.className === "claw-run-card-download");
  sessionBtn.click();
  dlBtn.click();
  assert.equal(live.openedSessions.length, 1);
  assert.equal(live.downloads.length, 1);
  checks.run_card = true;

  // 10) Rule (b) + live setter: wireRunHistoryListeners
  R.wireRunHistoryListeners();
  assert.equal(byId.clawRunHistoryFilter.listeners.click.length, 1);
  assert.equal(byId.clawRunHistoryRefresh.listeners.click.length, 1);
  assert.equal(byId.clawRunHistoryExpand.listeners.click.length, 1);

  byId.clawRunHistoryFilter.click();
  assert.equal(sandbox.window.__padiemClawRunHistoryIncludeGeneral, true);
  assert.equal(byId.clawRunHistoryFilter.dataset.runFilter, "all");

  byId.clawRunHistoryRefresh.click();
  assert.equal(live.clawRunHistoryLimit, 10);
  byId.clawRunHistory.hidden = false;
  byId.clawRunHistoryExpand.click();
  assert.equal(live.clawRunHistoryLimit, 30, "expand click writes back through live setter");
  assert.equal(byId.clawRunHistoryExpand.hidden, true);
  checks.run_history_wire = true;

  console.log(JSON.stringify({ ok: true, checks }));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});
"""


def test_vm_executes_all_16_a2_functions_and_wire_contracts() -> None:
    script = (
        _HARNESS
        .replace("__STRICT__", STRICT)
        .replace("__SHARED_JSON__", json.dumps(list(SHARED_READS)))
        .replace("__CONTEXT__", json.dumps(str(STATIC / "chat-app-context.js")))
        .replace("__MEMORY__", json.dumps(str(STATIC / "chat-memory-module.js")))
        .replace("__RUN_HISTORY__", json.dumps(str(STATIC / "chat-run-history-module.js")))
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tmp:
        tmp.write(script)
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            ["node", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    for key in (
        "create_reads_no_deps",
        "duplicate_throws",
        "proposal_review",
        "approve_reject",
        "card_and_detail",
        "list_and_more",
        "memory_visibility_and_wire",
        "runs_cache",
        "run_card",
        "run_history_wire",
    ):
        assert payload["checks"].get(key) is True, key
