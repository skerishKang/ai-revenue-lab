"""#7216 R5 A5a (claw-run) — Claw 결과물·승인·실행 모듈 계약 (15함수).

app.js의 Claw 수동 실행 구역 15개 함수가 chat-claw-run-module.js로 이동했고,
app.js는 15개 한 줄 전달 함수와 clawRunModule() 팩토리만 유지한다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-claw-run-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "setClawDocumentAction",
    "clearClawArtifact",
    "formatClawBytes",
    "renderClawArtifactMeta",
    "safeClawErrorMessage",
    "downloadClawArtifact",
    "revealClawCard",
    "setApprovalControlsBusy",
    "renderClawApprovalControls",
    "clearImmediateApprovalControls",
    "applyImmediateApprovalDecision",
    "renderClawRequestEcho",
    "clawClaimDispatchKey",
    "releaseClawDispatchKey",
    "runClawExecution",
)

EXPECTED_GETTERS = {
    "clawResultDocx", "clawArtifactMeta", "clawArtifactName", "clawArtifactSize",
    "clawResultSuccessNote", "clawResultEmpty", "clawResultHint", "clawResultCard",
    "clawResultKind", "clawResultBadge", "clawApprovalActions", "clawResultPreview",
    "clawRequestEcho", "clawRequestEchoText", "clawExecuteButton", "input",
    "clawT", "setClawStatus", "setClawAreaState", "setClawButtonsBusy",
    "clawBoundedRefusalCopy", "approvalDecisionErrorMessage", "mappedUiError",
    "safeLocalUiMessage", "failureCodeNote", "loadClawRunHistory",
    "clawRetryRemaining", "clawCurrentDispatchIsUncertain", "clawVisibleExecutePayload",
    "clawExecuteWireKey", "clearClawRecovery", "clawRetryAfterFromResponse",
    "isAmbiguousClawFailure", "beginClawRetryCooldown", "showClawAmbiguousRecoveryHint",
    "beginClawWait", "clearClawWait", "conversationState", "PRODUCT_CLAW",
    "authState", "chatTransport", "app", "clawApprovalInFlight", "clawApprovalEpoch",
    "clawInFlight",
}

EXPECTED_SETTERS = {
    "clawApprovalInFlight",
    "clawLastDispatchKey",
}

MOVED_MARKERS = (
    "window.PadiemChatClawRunModule = {",
    'fetch("/api/claw/manual-intake/execute", {',
    'fetch("/api/claw/approvals/decision", {',
    "const CLAW_DISPATCH_KEY_WINDOW_MS = 10000;",
    "let clawPdfPreviewController = null;",
    "deps.clawLastDispatchKey = deps.clawExecuteWireKey(executePayload);",
)


def test_index_loads_claw_run_module_before_app() -> None:
    assert INDEX.count("./chat-claw-run-module.js") == 1
    assert INDEX.index("./chat-claw-run-module.js") < INDEX.index("./app.js")
    # A4 모듈과 같은 위치 규칙: claw-status 모듈 뒤, app.js 앞.
    assert INDEX.index("./chat-claw-status-module.js") < INDEX.index("./chat-claw-run-module.js")


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        line = f"function {name}(...a) {{ return clawRunModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function clawRunModule() {" in APP
    assert "window.PadiemChatClawRunModule.create({" in APP


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_and_setters_match_exact_closure_surface() -> None:
    start = APP.index("window.PadiemChatClawRunModule.create({")
    block = APP[start:APP.index("});", start)]
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets == EXPECTED_GETTERS
    assert sets == EXPECTED_SETTERS


def test_all_fifteen_functions_execute_in_node_vm_with_strict_live_deps() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
(async () => {
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-claw-run-module.js"), "utf8");

const el = () => ({
  hidden: false,
  textContent: "",
  value: "",
  disabled: false,
  dataset: {},
  attrs: {},
  children: [],
  classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
  setAttribute(name, value) { this.attrs[name] = String(value); },
  getAttribute(name) { return this.attrs[name] === undefined ? null : this.attrs[name]; },
  removeAttribute(name) { delete this.attrs[name]; },
  appendChild(x) { this.children.push(x); return x; },
  append(...xs) { xs.forEach((x) => this.children.push(x)); },
  replaceChildren(...xs) { this.children = xs; },
  querySelector() { return null; },
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  listeners: {},
  focus() { this.focused = (this.focused || 0) + 1; },
});

const clawResultDocx = el();
const clawArtifactMeta = el();
const clawArtifactName = el();
const clawArtifactSize = el();
const clawResultSuccessNote = el();
const clawResultEmpty = el();
const clawResultHint = el();
const clawResultCard = el();
const clawResultKind = el();
const clawResultBadge = el();
const clawApprovalActions = el();
const clawResultPreview = el();
const clawRequestEcho = el();
const clawRequestEchoText = el();
const clawExecuteButton = el();
const input = el();

let clawApprovalInFlight = false;
let clawApprovalEpoch = 7;
let clawInFlight = false;
let clawLastDispatchKey = null;
let payloadContent = "hello";
let retryRemaining = 0;
let uncertain = false;

const fetchCalls = [];
let fetchQueue = [];
const queueJson = (status, body) => fetchQueue.push({ status, body });
const fetchImpl = (url, opts) => {
  fetchCalls.push({ url: String(url), method: (opts && opts.method) || "GET",
    headers: (opts && opts.headers) || {}, body: opts && opts.body });
  const next = fetchQueue.length ? fetchQueue.shift() : { status: 404, body: { ok: false } };
  return Promise.resolve({
    ok: next.status >= 200 && next.status < 400,
    status: next.status,
    json: () => Promise.resolve(next.body),
    blob: () => Promise.resolve({ size: 3 }),
  });
};
const drain = () => new Promise((r) => setImmediate(() => setImmediate(r)));

const pdfPreview = { created: 0, set: [], cleared: 0 };
const ctx = vm.createContext({
  window: { PadiemClawPdfPreview: { create() { pdfPreview.created += 1; return {
    set(a) { pdfPreview.set.push(a); }, clear() { pdfPreview.cleared += 1; } }; } } },
  document: { createElement: (t) => el(), body: el(), documentElement: { lang: "ko" } },
  fetch: fetchImpl,
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
  setTimeout: (fn) => { fn(); return 1; },
  Date, Math, JSON, Promise, Number, String, Object, Array, Set,
  encodeURIComponent,
});
vm.runInContext(strictSrc, ctx);
vm.runInContext(modSrc, ctx);

const notes = [];
const areaStates = [];
const mod = ctx.window.PadiemChatClawRunModule.create(ctx.r5StrictDeps({
  clawResultDocx, clawArtifactMeta, clawArtifactName, clawArtifactSize,
  clawResultSuccessNote, clawResultEmpty, clawResultHint, clawResultCard,
  clawResultKind, clawResultBadge, clawApprovalActions, clawResultPreview,
  clawRequestEcho, clawRequestEchoText, clawExecuteButton, input,
  get clawApprovalInFlight() { return clawApprovalInFlight; },
  set clawApprovalInFlight(v) { clawApprovalInFlight = v; },
  get clawApprovalEpoch() { return clawApprovalEpoch; },
  get clawInFlight() { return clawInFlight; },
  set clawLastDispatchKey(v) { clawLastDispatchKey = v; },
  clawT: (key) => key,
  setClawStatus: (message, state) => notes.push([message, state]),
  setClawAreaState: (state) => areaStates.push(state),
  setClawButtonsBusy: (busy) => { clawInFlight = busy; },
  clawBoundedRefusalCopy: (code) => (code === "tier_unavailable"
    ? { message: "bounded-message", hint: "bounded-hint" } : null),
  approvalDecisionErrorMessage: () => "decision-error",
  mappedUiError: (message) => { const e = new Error(message); e.code = "ui_error"; return e; },
  safeLocalUiMessage: (error, fallback) => (error && error.message) || fallback,
  failureCodeNote: () => null,
  loadClawRunHistory: () => { notes.push(["history-loaded", null]); },
  clawRetryRemaining: () => retryRemaining,
  clawCurrentDispatchIsUncertain: () => uncertain,
  clawVisibleExecutePayload: () => ({ content: payloadContent, channel: "sms", action: "quote" }),
  clawExecuteWireKey: (payload) => JSON.stringify(payload),
  clearClawRecovery: () => {},
  clawRetryAfterFromResponse: () => null,
  isAmbiguousClawFailure: () => false,
  beginClawRetryCooldown: () => {},
  showClawAmbiguousRecoveryHint: () => {},
  beginClawWait: () => {},
  clearClawWait: () => {},
  conversationState: { setConversationId(id, product) { notes.push(["conv", id, product]); } },
  PRODUCT_CLAW: "claw",
  authState: { authenticated: true },
  chatTransport: { createRequestId: () => "req-1" },
  app: { invalidateClawRunsRead() { notes.push(["runs-invalidated", null]); },
         clawRunStatusLabel: (status) => "status:" + status },
}, "a5a"));

const empty = ctx.window.PadiemChatClawRunModule.create(ctx.r5StrictDeps({}, "empty"));
assert.ok(empty);

// formatClawBytes: 세 구간.
assert.equal(mod.formatClawBytes(500), "500 B");
assert.equal(mod.formatClawBytes(2048), "2 KB");
assert.equal(mod.formatClawBytes(5 * 1024 * 1024), "5.0 MB");
assert.equal(mod.formatClawBytes(-1), "");

// setClawDocumentAction: 켜기/끄기와 설명자 정리.
mod.setClawDocumentAction(true, "doc_" + "a".repeat(32), "report.docx");
assert.equal(clawResultDocx.disabled, false);
assert.equal(clawResultDocx.dataset.documentId, "doc_" + "a".repeat(32));
assert.equal(clawResultDocx.dataset.filename, "report.docx");
mod.setClawDocumentAction(false);
assert.equal(clawResultDocx.disabled, true);
assert.equal("documentId" in clawResultDocx.dataset, false);
assert.equal("filename" in clawResultDocx.dataset, false);

// clearClawArtifact: 결과물 영역을 전부 지운다.
clawArtifactMeta.hidden = false;
clawResultSuccessNote.hidden = false;
clawArtifactName.textContent = "x";
mod.clearClawArtifact();
assert.equal(clawArtifactMeta.hidden, true);
assert.equal(clawResultSuccessNote.hidden, true);
assert.equal(clawArtifactName.textContent, "");
assert.equal(clawArtifactSize.textContent, "");

// renderClawArtifactMeta: 문서 이름·크기·라벨·미리보기 연결.
mod.renderClawArtifactMeta({ document_id: "doc_" + "b".repeat(32), filename: "a.pdf",
  byte_length: 2048, media_type: "application/pdf" });
assert.equal(clawArtifactMeta.hidden, false);
assert.equal(clawResultSuccessNote.hidden, false);
assert.equal(clawArtifactName.textContent, "a.pdf");
assert.equal(clawArtifactSize.textContent, "2 KB");
assert.equal(pdfPreview.created, 1);
assert.deepEqual(pdfPreview.set[pdfPreview.set.length - 1].document_id, "doc_" + "b".repeat(32));

// safeClawErrorMessage: 경계 코드는 공유 표현으로, 나머지는 상태 키로.
assert.equal(mod.safeClawErrorMessage({ error: { code: "tier_unavailable" } }, { status: 400 }),
  "bounded-message");
assert.equal(mod.safeClawErrorMessage({ error: { code: "rate_limited" } }, { status: 429 }),
  "claw-error-rate-limited");
assert.equal(mod.safeClawErrorMessage({ error: { code: "auth_required" } }, { status: 401 }),
  "claw-error-auth-needed");
assert.equal(mod.safeClawErrorMessage(null, { status: 503 }), "claw-error-generic");

// revealClawCard: 카드 종류·배지.
mod.revealClawCard("견적서", false);
assert.equal(clawResultCard.hidden, false);
assert.equal(clawResultEmpty.hidden, true);
assert.equal(clawResultHint.hidden, true);
assert.equal(clawResultKind.textContent, "견적서");
assert.equal(clawResultBadge.dataset.localeKey, "claw-result-badge");
mod.revealClawCard("견적서", true);
assert.equal(clawResultBadge.dataset.localeKey, "claw-result-badge-run");

// setApprovalControlsBusy: 단추만 잠근다.
const busyBox = el();
busyBox.children = [el(), { tagName: "P" }, el()];
busyBox.children[0].tagName = "BUTTON";
busyBox.children[2].tagName = "BUTTON";
mod.setApprovalControlsBusy(busyBox, true);
assert.equal(busyBox.children[0].disabled, true);
assert.equal(busyBox.children[1].disabled, undefined);
assert.equal(busyBox.children[2].disabled, true);
mod.setApprovalControlsBusy(busyBox, false);
assert.equal(busyBox.children[0].disabled, false);

// renderClawApprovalControls: 승인/거절 단추가 붙고 클릭이 서버로 간다.
const box = el();
mod.renderClawApprovalControls(box, "run_1", (result) => {});
assert.equal(box.hidden, false);
assert.equal(box.children.length, 4);
const approveBtn = box.children[1];
const denyBtn = box.children[2];
assert.equal(approveBtn.textContent, "claw-approval-approve");
assert.equal(denyBtn.textContent, "claw-approval-deny");
queueJson(200, { ok: true, result: { run_id: "run_1", status: "approved" } });
approveBtn.listeners.click[0]();
await drain();
assert.equal(fetchCalls[fetchCalls.length - 1].url, "/api/claw/approvals/decision");
assert.equal(fetchCalls[fetchCalls.length - 1].method, "POST");
assert.deepEqual(JSON.parse(fetchCalls[fetchCalls.length - 1].body),
  { run_id: "run_1", decision: "approve" });
assert.equal(clawApprovalInFlight, false);
assert.ok(notes.some((n) => n[0] === "runs-invalidated"));

// 거절 흐름도 같은 주소로 decision=deny.
queueJson(200, { ok: true, result: { run_id: "run_1", status: "denied" } });
denyBtn.listeners.click[0]();
await drain();
assert.deepEqual(JSON.parse(fetchCalls[fetchCalls.length - 1].body),
  { run_id: "run_1", decision: "deny" });

// 세대가 바뀐 뒤 도착한 응답은 화면에 반영되지 않는다.
const invalidatedBefore = notes.filter((n) => n[0] === "runs-invalidated").length;
const staleBox = el();
mod.renderClawApprovalControls(staleBox, "run_2", null);
queueJson(200, { ok: true, result: { run_id: "run_2", status: "approved" } });
staleBox.children[1].listeners.click[0]();
clawApprovalEpoch = 8; // 응답을 기다리는 동안 세대 변경
await drain();
// 낡은 세대의 응답은 새 세대의 busy 플래그를 풀지 않는다(무효화 경로가 정리한다).
assert.equal(clawApprovalInFlight, true);
assert.equal(notes.filter((n) => n[0] === "runs-invalidated").length, invalidatedBefore);
clawApprovalInFlight = false;

// clearImmediateApprovalControls.
mod.clearImmediateApprovalControls();
assert.equal(clawApprovalActions.hidden, true);
assert.deepEqual(clawApprovalActions.children, []);

// clawClaimDispatchKey: 공유 전송 도우미로 키를 만들고 단추에 저장한다.
const k1 = mod.clawClaimDispatchKey();
assert.equal(k1, "claw-req-1");
assert.equal(clawExecuteButton.dataset.clawDispatchKey, k1);
assert.equal(mod.clawClaimDispatchKey(), k1); // 진행 중 재요청은 같은 키
mod.releaseClawDispatchKey(k1);
assert.equal("clawDispatchKey" in clawExecuteButton.dataset, false);
mod.releaseClawDispatchKey("other"); // 키가 다르면 아무것도 지우지 않는다
assert.equal("clawDispatchKey" in clawExecuteButton.dataset, false);

// runClawExecution: 실행 중복·재시도·불확실 가드.
fetchCalls.length = 0;
fetchQueue = [];
clawInFlight = true;
await mod.runClawExecution();
assert.equal(fetchCalls.length, 0);
clawInFlight = false;
retryRemaining = 1;
await mod.runClawExecution();
assert.equal(fetchCalls.length, 0);
retryRemaining = 0;
uncertain = true;
await mod.runClawExecution();
assert.equal(fetchCalls.length, 0);
uncertain = false;
payloadContent = "";
await mod.runClawExecution();
assert.equal(fetchCalls.length, 0);
assert.equal(clawResultEmpty.hidden, false);
assert.equal(clawResultEmpty.textContent, "claw-error-empty");
assert.equal(areaStates[areaStates.length - 1], "error");
payloadContent = "hello";

// 성공(결과물 있음): 서버 응답의 조각만 화면에 반영된다.
queueJson(200, { ok: true, result: { conversation_id: "conv_9", title: "견적 완료",
  status: "completed", result_text: "완료 문구",
  artifact: { document_id: "doc_" + "c".repeat(32), filename: "r.docx",
    byte_length: 2048, media_type: "application/pdf" } } });
await mod.runClawExecution();
const exec = fetchCalls[fetchCalls.length - 1];
assert.equal(exec.url, "/api/claw/manual-intake/execute");
assert.equal(exec.method, "POST");
assert.equal(exec.headers["Idempotency-Key"], "claw-req-1");
assert.deepEqual(JSON.parse(exec.body),
  { content: "hello", channel: "sms", action: "quote" });
assert.ok(notes.some((n) => n[0] === "conv" && n[1] === "conv_9" && n[2] === "claw"));
assert.equal(clawResultKind.textContent, "견적 완료");
assert.equal(clawResultPreview.textContent, "완료 문구");
assert.equal(clawResultDocx.dataset.documentId, "doc_" + "c".repeat(32));
assert.equal(areaStates[areaStates.length - 1], "success");
assert.equal(clawInFlight, false);
assert.equal(clawLastDispatchKey,
  JSON.stringify({ content: "hello", channel: "sms", action: "quote" }));

// 승인 대기 결과: 즉시 승인 조작이 열린다.
queueJson(200, { ok: true, result: { conversation_id: "conv_10", title: "승인 필요",
  status: "waiting_approval", approval_required: true, request_id: "req_77" } });
await mod.runClawExecution();
assert.equal(clawApprovalActions.children.length, 4);
assert.equal(clawResultPreview.textContent, "claw-approval-required");
assert.equal(areaStates[areaStates.length - 1], "waiting_approval");

// 경계 거절(실행 없음): 결과 영역에 경계 문구와 힌트가 함께 간다.
queueJson(400, { ok: false, error: { code: "tier_unavailable" } });
await mod.runClawExecution();
assert.equal(clawResultEmpty.textContent, "bounded-message bounded-hint");
assert.equal(areaStates[areaStates.length - 1], "error");

// 일반 실패: 상태 줄은 서버 응답의 코드 지도에서 온다.
queueJson(429, { ok: false, error: { code: "rate_limited" } });
await mod.runClawExecution();
assert.equal(notes[notes.length - 1][0], "claw-error-rate-limited");
assert.equal(notes[notes.length - 1][1], "error");
assert.equal(areaStates[areaStates.length - 1], "error");
assert.equal(clawInFlight, false); // finally 정리

console.log("a5a claw-run module contract ok");
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
