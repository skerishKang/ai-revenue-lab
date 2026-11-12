"""#pending-poll-stop 261102: a refused submit must not start result checks.

The Node test proves the transport marker and the gone bookkeeping inside the
recovery module. This gate keeps the small app wiring that turns both into
behavior: the requestAnswer catch skips recovery when the POST itself was
rejected, and a run the server answered 404 for is dropped from any further
checking on the client side too, so a retry over the same handle shows its
own failure instead of reading a gone run again.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "test_pending_poll_stop_261102.mjs"


def test_pending_poll_stop_contract_runs_under_node():
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


def test_app_skips_the_result_check_when_the_submit_was_refused():
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    stream = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")

    # The transport marks HTTP-level refusals of the submit call itself, and
    # only when an HTTP status was passed (a cut stream has none).
    assert "error.submissionRejected = true" in transport
    assert "Number.isInteger(status) && status >= 400" in transport

    # The catch that starts pending-result recovery refuses that error kind.
    assert stream.count("!error?.submissionRejected") == 1
    guard_at = stream.index("!error?.submissionRejected")
    guard_line = stream[stream.rindex("if (", 0, guard_at):guard_at]
    assert "contextSnapshot?.pcRunId" in guard_line
    assert "!error?.terminalRecord" in guard_line


def test_app_drops_a_gone_run_from_any_further_checking():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    recovery = (STATIC / "chat-pc-result-recovery.js").read_text(encoding="utf-8")

    # The recovery module answers a repeat read of a gone run without any GET.
    assert "var gone = new Set();" in recovery
    assert 'if (gone.has(runId)) return {kind: "rejected", status: 404, gone: true};' in recovery
    assert "if (status === 404) gone.add(runId);" in recovery

    # And chat-pc-run-module.js forgets the run on its side too, in both wait
    # paths, so a retry over the same handle goes straight to the failure copy.
    import shutil
    import subprocess
    import pytest

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

let recoverCalls = 0;
let firstResult = null;
let waitResult = null;
const streamErrors = [];
const resolved = new Set();

const ctx = vm.createContext({
  window: { PadiemChatLifecycle: {} },
  PadiemChatLifecycle: { set: () => {} },
  Proxy, Reflect,
});
vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-pc-run-module.js" });

const deps = ctx.r5StrictDeps({
  get MESSAGE_LIFECYCLE() { return { STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed" }; },
  get conversationState() { return { setConversationId: () => {} }; },
  get pcResultRecovery() {
    return {
      recoverOnce: async () => { recoverCalls += 1; return firstResult; },
      waitForResult: async () => waitResult,
    };
  },
  get renderStoredPcAnswer() { return () => true; },
  get renderStreamError() { return (...a) => streamErrors.push(a); },
  get resolvedPcRuns() { return resolved; },
  get uiT() { return (k) => k; },
}, "deps");
const mod = ctx.window.PadiemChatPcRunModule.create(deps);

(async () => {
  const art = { isConnected: true };
  const sig = { aborted: false };

  // Path 1: first.gone === true -> forgets run_1 immediately; second call makes 0 GETs.
  firstResult = { kind: "rejected", status: 404, gone: true };
  assert.equal(await mod.recoverStoredPcResult(art, { pcRunId: "run_1", conversationId: "c1", product: "chat" }, [], null, sig), false);
  assert.equal(resolved.has("run_1"), true);
  assert.equal(recoverCalls, 1);
  assert.equal(await mod.recoverStoredPcResult(art, { pcRunId: "run_1", conversationId: "c1", product: "chat" }, [], null, sig), false);
  assert.equal(recoverCalls, 1);

  // Path 2: result.gone === true after pending wait -> forgets run_2; subsequent call makes 0 GETs.
  firstResult = { kind: "pending", conversationId: "c1" };
  waitResult = { kind: "rejected", status: 404, gone: true };
  assert.equal(await mod.recoverStoredPcResult(art, { pcRunId: "run_2", conversationId: "c1", product: "chat" }, [], null, sig), true);
  await new Promise((r) => setImmediate(r));
  assert.equal(resolved.has("run_2"), true);
  assert.equal(streamErrors.length, 1);
  assert.equal(await mod.recoverStoredPcResult(art, { pcRunId: "run_2", conversationId: "c1", product: "chat" }, [], null, sig), false);
  assert.equal(recoverCalls, 2);
})().catch((err) => { console.error(err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_cut_stream_recovery_stays_allowed():
    stream = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
    # #5895 deferral above the terminal-refusal branch is untouched.
    deferral = stream.index("deps.chatTransport.isStreamLoss?.(data)")
    terminal = stream.index("// An explicit refusal is terminal even before the first token.")
    assert deferral < terminal
    assert stream.count("isStreamLoss?.(data)") == 1
