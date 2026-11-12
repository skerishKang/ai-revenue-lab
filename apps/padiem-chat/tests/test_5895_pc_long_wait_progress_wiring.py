"""#5895: a PC turn that runs for minutes must read as work in progress.

The Node test proves the behaviour on the shipped bytes: the read-back stops
only when the stored answer lands or the caller moves on, and reopening the
conversation that started an unfinished PC run continues the same "working on
your PC — elapsed" display and lands the answer in that conversation. This
Python gate keeps that contract inside the normal pytest run and pins that the
client chose no give-up count, no deadline and no page size of its own.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# R5 0단계(R-01): 함수 경계는 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import combined_source

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "test_5895_pc_long_wait_progress.mjs"


def test_pc_long_wait_progress_contract_runs_under_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True, encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_read_back_has_no_client_side_give_up():
    recovery = (STATIC / "chat-pc-result-recovery.js").read_text(encoding="utf-8")

    # The attempt cap is caller-supplied only: with no bound the loop is open.
    assert "? details.maxAttempts : null;" in recovery
    assert "for (var attempt = 0; maxAttempts === null || attempt < maxAttempts; attempt += 1) {" in recovery
    assert "if (maxAttempts === null || attempt + 1 < maxAttempts) await sleep(intervalMs, signal);" in recovery
    # The pre-existing poll interval is reused, not re-chosen, and no deadline
    # or abort is introduced by this change.
    assert "? details.intervalMs : 2000;" in recovery
    assert "Date.now" not in recovery
    assert "deadline" not in recovery

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-pc-run-module.js"), "utf8");

let elapsedCalls = 0;
let waitOptions = null;
const notes = [];
const ctx = vm.createContext({
  fetch: async () => ({
    ok: true,
    json: async () => ({
      ok: true,
      runs: [{
        run_id: "chat_pcq_" + "a".repeat(32),
        status: "running",
        created_at: "2026-11-12T00:00:00Z",
        session: { conversation_id: "conv_1" },
      }],
    }),
  }),
  window: {
    PadiemChatLifecycle: {
      elapsedClockText: (ms) => { elapsedCalls += 1; return "02:00"; },
    },
    PadiemChatPcRecovery: { validRunId: () => true },
  },
  Date: { parse: (v) => Date.parse(v), now: () => Date.parse("2026-11-12T00:02:00Z") },
  Math, Number, Array, Proxy, Reflect,
});
vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-pc-run-module.js" });

let mod = null;
const resolved = new Set();
const deps = ctx.r5StrictDeps({
  get pcResultRecovery() {
    return {
      waitForResult: async (opts) => {
        waitOptions = opts;
        opts.onPending();
        return { kind: "pending", conversationId: "conv_1" };
      },
    };
  },
  get findUnfinishedPcRun() { return (...a) => mod.findUnfinishedPcRun(...a); },
  get resolvedPcRuns() { return resolved; },
  get pcWaitElapsed() { return (...a) => mod.pcWaitElapsed(...a); },
  get setNote() { return (text, state) => notes.push({ text, state }); },
  get uiT() { return (k, vars) => k + ":" + JSON.stringify(vars || {}); },
  get idleNote() { return () => "idle"; },
  get openSavedConversation() { return async () => {}; },
}, "deps");
mod = ctx.window.PadiemChatPcRunModule.create(deps);

(async () => {
  await mod.resumeUnfinishedPcRun("conv_1");
  assert.ok(waitOptions, "waitForResult must be called");
  assert.deepEqual(Object.keys(waitOptions).sort(), ["conversationId", "onPending", "runId"]);
  assert.equal("maxAttempts" in waitOptions, false);
  assert.equal("intervalMs" in waitOptions, false);
  assert.equal("signal" in waitOptions, false);
  assert.equal(typeof waitOptions.onPending, "function");
  assert.equal(elapsedCalls >= 2, true);
  assert.equal(notes.every((n) => n.state === "status" && n.text.includes("02:00")), true);
})().catch((err) => { console.error(err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_resume_reads_the_owner_history_and_reopens_the_same_conversation():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-pc-run-module.js"), "utf8");

function makeHarness(waitOutcome) {
  const fetches = [];
  const notes = [];
  const reopened = [];
  const streamErrors = [];
  const resolved = new Set();
  const runId = "chat_pcq_" + "b".repeat(32);
  const ctx = vm.createContext({
    fetch: async (url, init) => {
      fetches.push({ url, init: init || {} });
      return {
        ok: true,
        json: async () => ({
          ok: true,
          runs: [
            { run_id: "invalid_id", status: "running", session: { conversation_id: "c1" } },
            { run_id: runId, status: "completed", session: { conversation_id: "c1" } },
            { run_id: runId, status: "running", created_at: "2026-11-12T00:00:00Z", session: { conversation_id: "other" } },
            { run_id: runId, status: "pending", created_at: "2026-11-12T00:00:00Z", session: { conversation_id: "c1" } },
          ],
        }),
      };
    },
    window: {
      PadiemChatLifecycle: { elapsedClockText: () => "00:10" },
      PadiemChatPcRecovery: { validRunId: (id) => id.startsWith("chat_pcq_") },
    },
    Date: { parse: (v) => Date.parse(v), now: () => Date.parse("2026-11-12T00:00:10Z") },
    Math, Number, Array, Proxy, Reflect,
  });
  vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-pc-run-module.js" });
  let mod = null;
  const deps = ctx.r5StrictDeps({
    get pcResultRecovery() { return { waitForResult: async () => waitOutcome }; },
    get findUnfinishedPcRun() { return (...a) => mod.findUnfinishedPcRun(...a); },
    get resolvedPcRuns() { return resolved; },
    get pcWaitElapsed() { return (...a) => mod.pcWaitElapsed(...a); },
    get setNote() { return (t, s) => notes.push({ t, s }); },
    get uiT() { return (k) => k; },
    get idleNote() { return () => "idle"; },
    get openSavedConversation() { return async (id) => { reopened.push(id); }; },
    get renderStreamError() { return (...a) => streamErrors.push(a); },
  }, "deps");
  mod = ctx.window.PadiemChatPcRunModule.create(deps);
  return { mod, fetches, notes, reopened, streamErrors, resolved, runId };
}

(async () => {
  // 1. Pending verdict keeps waiting state, touches neither resolvedPcRuns nor reopen.
  const hPending = makeHarness({ kind: "pending", conversationId: "c1" });
  await hPending.mod.resumeUnfinishedPcRun("c1");
  assert.equal(hPending.fetches.length, 1);
  assert.equal(hPending.fetches[0].url, "/api/claw/runs");
  assert.equal(hPending.fetches[0].url.includes("limit="), false);
  assert.equal("method" in hPending.fetches[0].init, false);
  assert.equal(hPending.resolved.has(hPending.runId), false);
  assert.deepEqual(hPending.reopened, []);

  // 2. Completed verdict marks resolved, resets note to idle, reopens conversation once, skips second call.
  const hDone = makeHarness({ kind: "completed", conversationId: "c1" });
  await hDone.mod.resumeUnfinishedPcRun("c1");
  assert.equal(hDone.resolved.has(hDone.runId), true);
  assert.equal(hDone.notes.at(-1).t, "idle");
  assert.deepEqual(hDone.reopened, ["c1"]);
  assert.equal(hDone.streamErrors.length, 0);
  await hDone.mod.resumeUnfinishedPcRun("c1");
  assert.deepEqual(hDone.reopened, ["c1"]);

  // 3. Non-completed terminal verdict stops waiting note without reopening or stream error.
  const hRej = makeHarness({ kind: "rejected", conversationId: "c1" });
  await hRej.mod.resumeUnfinishedPcRun("c1");
  assert.equal(hRej.resolved.has(hRej.runId), true);
  assert.equal(hRej.notes.at(-1).t, "idle");
  assert.deepEqual(hRej.reopened, []);
  assert.equal(hRej.streamErrors.length, 0);
})().catch((err) => { console.error(err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    # The only call site is the restored conversation itself, after its saved
    # messages are rendered and before the motion resume. It is fire-and-forget:
    # the restore does not wait on the unfinished run.
    shipped = combined_source()
    restore = shipped[shipped.index("async function openSavedConversation("):]
    restore = restore[:restore.index("  // #4471:")]
    call = restore.index("void resumeUnfinishedPcRun(data.conversation.id);")
    assert restore.index("data.conversation.messages.forEach") < call
    assert call < restore.index("window.__padiemConversationMotion?.resume?.()")


def test_the_waiting_copy_names_work_in_progress_with_elapsed_time():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert locale.count('"pc-elapsed-note"') == 2
    assert '"pc-elapsed-note": "PC에서 작업 중 — 경과 {elapsed} · 완료되면 이 대화에 결과가 표시됩니다."' in locale
    assert '"pc-elapsed-note": "Working on your PC — elapsed {elapsed} · the answer will appear in this conversation when it completes."' in locale
    # The existing still-working note stays the fallback when no timestamp is
    # readable, and neither copy reads as a failure or an instruction.
    assert locale.count('"pc-processing-note"') == 2
    for key in ("pc-elapsed-note", "pc-processing-note"):
        for value in _values(locale, key):
            assert "실패" not in value and "오류" not in value, value
            assert "재시도" not in value and "retry" not in value.lower(), value


def _values(locale: str, key: str) -> list[str]:
    return re.findall(rf'"{key}": "([^"]*)"', locale)
