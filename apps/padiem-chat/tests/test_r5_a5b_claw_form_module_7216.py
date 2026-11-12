"""#7216 R5 A5b (claw-form) — Claw 수동 폼·실행 배선 모듈 계약.

app.js의 수동 폼 제출/미리보기 리스너와 실행·재시도 단추 배선이
chat-claw-form-module.js로 이동했고, app.js는 선언 블록과 원래 등록 위치의
wire 호출만 유지한다. 이 시험은 리스너를 직접 호출해 요청·상태 전환을 본다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

EXPECTED_GETTERS = {
    "clawManualForm", "clawResultDocx", "clawResultCard", "clawResultEmpty",
    "clawResultHint", "clawResultPreview", "clawChannel", "clawAction",
    "clawSender", "clawExecuteButton", "clawRetryButton", "input", "clawInFlight",
    "downloadClawArtifact", "clearClawArtifact", "clawT", "setClawStatus",
    "setClawAreaState", "setClawButtonsBusy", "renderClawRequestEcho",
    "revealClawCard", "runClawExecution", "noteClawContentEdited", "app",
}

MOVED_MARKERS = (
    "window.PadiemChatClawFormModule = {",
    'deps.clawManualForm.addEventListener("submit"',
    'fetch("/api/claw/manual-intake/preview", {',
    'deps.clawExecuteButton.dataset.clawExecuteWired = "1";',
    'deps.clawRetryButton.dataset.clawRetryWired = "1";',
    'node.addEventListener("input", deps.noteClawContentEdited);',
    "const renderPreviewError = () => {",
)


def test_index_loads_form_module_once_between_run_module_and_app() -> None:
    assert INDEX.count("./chat-claw-form-module.js") == 1
    run_at = INDEX.index("./chat-claw-run-module.js")
    form_at = INDEX.index("./chat-claw-form-module.js")
    app_at = INDEX.index("./app.js")
    assert run_at < form_at < app_at


def test_app_keeps_only_the_factory_and_two_wire_calls() -> None:
    assert "function clawFormModule() {" in APP
    assert "window.PadiemChatClawFormModule.create({" in APP
    assert APP.count("clawFormModule().wireManualForm();") == 1
    assert APP.count("clawFormModule().wireExecuteControls();") == 1
    # Wire calls stay at the original registration positions: the form wires
    # before the locale-change listener, the execute controls after the initial
    # area state.
    assert APP.index("clawFormModule().wireManualForm();") < APP.index(
        "// Keep preview/execute hints in sync with locale switches"
    )
    assert APP.index('setClawAreaState("idle");') < APP.index(
        "clawFormModule().wireExecuteControls();"
    )


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    assert 'clawManualForm.addEventListener("submit"' not in APP
    assert "clawExecuteButton.dataset.clawExecuteWired" not in APP
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_match_the_exact_closure_surface() -> None:
    start = APP.index("window.PadiemChatClawFormModule.create({")
    block = APP[start:APP.index("});", start)]
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets == EXPECTED_GETTERS
    assert sets == set()


def test_listeners_drive_preview_execute_and_retry_in_node_vm() -> None:
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
const modSrc = fs.readFileSync(path.join(staticDir, "chat-claw-form-module.js"), "utf8");

const el = () => ({
  hidden: false, textContent: "", value: "", disabled: false,
  dataset: {}, attrs: {}, options: [], selectedIndex: 0,
  listeners: {},
  setAttribute(n, v) { this.attrs[n] = String(v); },
  getAttribute(n) { return this.attrs[n] === undefined ? null : this.attrs[n]; },
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
  focus() { this.focused = (this.focused || 0) + 1; },
  fire(type, event) { return (this.listeners[type] || []).map((fn) => fn(event)); },
});

const clawManualForm = el();
const clawResultDocx = el();
const clawResultCard = el();
const clawResultEmpty = el();
const clawResultHint = el();
const clawResultPreview = el();
const clawChannel = el();
const clawAction = el();
const clawSender = el();
const clawExecuteButton = el();
const clawRetryButton = el();
const input = el();
clawChannel.options = [{ textContent: "문자" }];
clawAction.options = [{ textContent: "견적" }];

let clawInFlight = false;
const notes = [];
const areaStates = [];
const downloads = [];
const echoes = [];
const cards = [];
const proposals = [];
let runCalls = 0;
let edited = 0;
const app = { clawMemoryReview: el(), renderMemoryProposalReview(list) { proposals.push(list); } };

const fetchCalls = [];
let queue = [];
const queueJson = (status, body) => queue.push({ status, body });
const fetchImpl = (url, opts) => {
  fetchCalls.push({ url: String(url), method: (opts && opts.method) || "GET", body: opts && opts.body });
  const next = queue.length ? queue.shift() : { status: 500, body: { ok: false } };
  return Promise.resolve({ ok: next.status >= 200 && next.status < 400, status: next.status,
    json: () => Promise.resolve(next.body) });
};

const ctx = vm.createContext({ window: {}, document: {}, fetch: fetchImpl, JSON, Promise, Array, String, Object, Error, console });
vm.runInContext(strictSrc, ctx);
vm.runInContext(modSrc, ctx);

const mod = ctx.window.PadiemChatClawFormModule.create(ctx.r5StrictDeps({
  clawManualForm, clawResultDocx, clawResultCard, clawResultEmpty, clawResultHint,
  clawResultPreview, clawChannel, clawAction, clawSender, clawExecuteButton,
  clawRetryButton, input,
  get clawInFlight() { return clawInFlight; },
  downloadClawArtifact: (id, name) => downloads.push([id, name]),
  clearClawArtifact: () => { notes.push(["artifact-cleared"]); },
  clawT: (key) => key,
  setClawStatus: (message, state, key) => notes.push(["status", message, state, key || null]),
  setClawAreaState: (state) => areaStates.push(state),
  setClawButtonsBusy: (busy) => { clawInFlight = busy; notes.push(["busy", busy]); },
  renderClawRequestEcho: (body) => echoes.push(body),
  revealClawCard: (title) => cards.push(title),
  runClawExecution: () => { runCalls += 1; },
  noteClawContentEdited: () => { edited += 1; },
  app,
}, "a5b"));

// create() itself must not read deps (declarations stay owned by app.js).
const empty = ctx.window.PadiemChatClawFormModule.create(ctx.r5StrictDeps({}, "empty"));
assert.equal(typeof empty.wireManualForm, "function");
assert.equal(typeof empty.wireExecuteControls, "function");

mod.wireManualForm();
assert.deepEqual(Object.keys(clawManualForm.listeners), ["submit"]);
assert.deepEqual(Object.keys(clawResultDocx.listeners), ["click"]);

// docx click downloads only when enabled with an id.
clawResultDocx.dataset.documentId = "doc_" + "a".repeat(32);
clawResultDocx.dataset.filename = "a.docx";
clawResultDocx.fire("click");
assert.deepEqual(downloads, [["doc_" + "a".repeat(32), "a.docx"]]);
clawResultDocx.disabled = true;
clawResultDocx.fire("click");
assert.equal(downloads.length, 1);

// empty body: status error, focus, no request.
const submit = clawManualForm.listeners.submit[0];
await submit({ preventDefault() {} });
assert.equal(fetchCalls.length, 0);
assert(notes.some((n) => n[0] === "status" && n[1] === "claw-error-empty" && n[2] === "error"));
assert.equal(input.focused, 1);

// in-flight submit is ignored.
clawInFlight = true;
await submit({ preventDefault() {} });
assert.equal(fetchCalls.length, 0);
clawInFlight = false;

// success path: one preview POST, echo, card, memory proposals, result text.
input.value = "  견적 부탁  ";
queueJson(200, { ok: true, preview: { title: "견적서", result_text: "PREVIEW",
  memory_proposals: [{ type: "customer_contact_candidate" }] } });
await submit({ preventDefault() {} });
assert.equal(fetchCalls.length, 1);
assert.equal(fetchCalls[0].url, "/api/claw/manual-intake/preview");
assert.equal(fetchCalls[0].method, "POST");
assert.deepEqual(JSON.parse(fetchCalls[0].body), {
  content: "견적 부탁", channel: "other", action: "quote", sender_hint: null,
});
assert.deepEqual(echoes, ["견적 부탁"]);
assert.deepEqual(cards, ["견적서"]);
assert.equal(proposals.length, 1);
assert.equal(proposals[0].length, 1);
assert.equal(clawResultPreview.textContent, "PREVIEW");
assert.equal(areaStates[areaStates.length - 1], "success");
assert.equal(clawInFlight, false);

// failure path: bounded preview error, memory review hidden, no card.
app.clawMemoryReview.hidden = false;
queueJson(500, { ok: false });
await submit({ preventDefault() {} });
assert.equal(areaStates[areaStates.length - 1], "error");
assert.equal(app.clawMemoryReview.hidden, true);
assert.equal(notes.filter((n) => n[0] === "status" && n[1] === "claw-error-preview").length, 1);

// execute + retry share the single run entry point and wire once.
mod.wireExecuteControls();
clawExecuteButton.fire("click");
clawRetryButton.fire("click");
assert.equal(runCalls, 2);
assert.equal(clawExecuteButton.dataset.clawExecuteWired, "1");
assert.equal(clawRetryButton.dataset.clawRetryWired, "1");

// composing different work notifies the content-edit latch (one listener each).
input.fire("input");
input.fire("change");
clawChannel.fire("change");
clawAction.fire("input");
clawSender.fire("change");
assert.equal(edited, 5);
assert.equal(input.listeners.input.length, 1);
assert.equal(input.listeners.change.length, 1);

// the dataset flags keep the button wiring single-fire on a repeat call.
mod.wireExecuteControls();
clawExecuteButton.fire("click");
assert.equal(runCalls, 3);
assert.equal(clawExecuteButton.listeners.click.length, 1);
console.log("A5B_VM_CONTRACT_OK");
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "A5B_VM_CONTRACT_OK" in result.stdout
