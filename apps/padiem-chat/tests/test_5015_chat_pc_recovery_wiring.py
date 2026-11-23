"""#5015 live PC result recovery: producer/consumer wiring contracts.

The Node test exercises the pure owner-scoped recovery controller. This Python
test keeps that JS contract in the normal pytest gate and pins the small app
wiring that makes a dropped live response recover from the durable run result
without a second PC POST.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


# #8060: shipped reads live in _support; the wiring and behavior checks stay.
from _support import chat_pc_recovery_wiring_source as sheets

NODE_TEST = sheets.tests_path("test_5015_chat_pc_recovery.mjs")


def test_frontend_recovery_controller_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=sheets.chat_root(),
        capture_output=True,
        text=True, encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_pc_run_handle_and_recovery_are_wired_to_the_real_consumer():
    app_js = sheets.sheet("app.js")
    stream_js = sheets.sheet("chat-streaming-module.js")
    transport = sheets.sheet("chat-transport.js")
    index = sheets.sheet("index.html")
    assert "createChatPcRunId" in transport
    assert "payload.pc_run_id = pcRunId" in stream_js
    assert "contextSnapshot.pcRunId || deps.chatTransport.createChatPcRunId" in stream_js
    # R5 2부 B2: the recovery creation moved into chat-pc-run-module.js.
    assert "PadiemChatPcRecovery?.create" in sheets.sheet("chat-pc-run-module.js")
    assert "recoverStoredPcResult(" in app_js
    assert "window.PadiemChatPcRunModule.create(Object.setPrototypeOf({" in app_js
    assert "chat-pc-run-module.js" in index
    assert "chat-pc-result-recovery.js" in index

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

const recoverOnceCalls = [];
const waitCalls = [];
const rendered = [];

const ctx = vm.createContext({
  window: {
    fetch: () => { throw new Error("no fetch in this scenario"); },
    PadiemChatLifecycle: {},
    // R5 2부 B2: the recovery controller is created inside the module from
    // this stub, so the recovery scenarios drive the same fake.
    PadiemChatPcRecovery: {
      create: () => ({
        recoverOnce: async (args) => { recoverOnceCalls.push(args); return nextFirst; },
        waitForResult: async (args) => { waitCalls.push(args); return { kind: "completed", answer: "delayed", conversationId: "c1" }; },
      }),
    },
  },
  PadiemChatLifecycle: { set: () => {} },
  Proxy, Reflect,
});
vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-pc-run-module.js" });

let nextFirst = null;
let mod = null;
const deps = ctx.r5StrictDeps({
  get MESSAGE_LIFECYCLE() { return { STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed" }; },
  get conversationState() { return { setConversationId: () => {} }; },
  get renderStoredPcAnswer() { return (_art, res) => { rendered.push(res.answer); return true; }; },
  get renderStreamError() { return () => {}; },
  get uiT() { return (k) => k; },
}, "deps");
mod = ctx.window.PadiemChatPcRunModule.create(deps);

(async () => {
  const signal = { aborted: false };
  const article = { isConnected: true };

  // 1. Completed on first recoverOnce marks the run resolved and skips the
  // duplicate handle. R5 2부 B2: the resolved-run set is module-internal —
  // the marking is proven by the dedup (the second call recovers nothing).
  nextFirst = { kind: "completed", answer: "immediate", conversationId: "c1" };
  assert.equal(await mod.recoverStoredPcResult(article, { pcRunId: "r1", conversationId: "c1", product: "chat" }, [], null, signal), true);
  assert.equal(recoverOnceCalls.length, 1);
  assert.equal(await mod.recoverStoredPcResult(article, { pcRunId: "r1", conversationId: "c1", product: "chat" }, [], null, signal), false);
  assert.equal(recoverOnceCalls.length, 1);

  // 2. Pending on first recoverOnce chains into waitForResult and marks the
  // run resolved on completion — proven by the dedup on a third call.
  nextFirst = { kind: "pending", conversationId: "c1" };
  assert.equal(await mod.recoverStoredPcResult(article, { pcRunId: "r2", conversationId: "c1", product: "chat" }, [], null, signal), true);
  await new Promise((r) => setImmediate(r));
  assert.equal(waitCalls.length, 1);
  assert.deepEqual(rendered, ["immediate", "delayed"]);
  assert.equal(await mod.recoverStoredPcResult(article, { pcRunId: "r2", conversationId: "c1", product: "chat" }, [], null, signal), false);
})().catch((err) => { console.error(err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, sheets.static_dir()],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    # The recovery call is in the outer request catch, before the generic
    # renderError. A stream-incomplete error is handed to that catch.
    outer = stream_js.split("async function requestAnswer(", 1)[1]
    assert outer.index("deps.recoverStoredPcResult(") < outer.index("deps.renderError(")
    # #7297: the recovery condition no longer excludes the Claw screen — Chat
    # and Claw share the same owner-scoped PC recovery gate.
    assert "contextSnapshot?.pcRunId && !terminalError" in stream_js
    recovery = sheets.sheet("chat-pc-result-recovery.js")
    assert "method: \"GET\"" in recovery
    assert "resolved.add(runId)" in recovery
    assert "answer_source" in recovery
    assert "result.run_id !== runId" in recovery


def test_server_accepts_only_a_canonical_client_recovery_handle():
    source = sheets.server_source("chat_pc_drive.py")
    assert "validate_chat_pc_run_id" in source
    assert "chat_pc_run_id_invalid" in source
    assert "lane_run_id = run_id or _new_lane_run_id()" in source
    assert "chat_pc_run_id_conflict" in source

    routes = sheets.server_source("orchestration_routes.py")
    # The Engine stream now receives the canonical recovery handle only after
    # the same server PC verification; the surface still owns no PC executor.
    assert "resolve_chat_pc_stream_context" in routes
    assert '_client_lane_run_id(raw.get("pc_run_id"))' in routes
    assert "session_id=pc_run_id" in routes
    assert "execute_chat_pc_drive_lane" not in routes

    chat_routes = sheets.server_source("chat_routes.py")
    # The direct Chat stream entry remains compatible. Its handle travels into the
    # lane so the staged run keeps the browser's id, and into the pinned-scope
    # notice lookup for the same completion frame.
    assert chat_routes.count("run_id=raw.get(\"pc_run_id\")") == 2

    contract = sheets.server_source("request_contract.py")
    assert "\"pc_run_id\", \"web_search\"}" in contract
    assert "validate_chat_pc_run_id" in contract


def test_request_contract_accepts_only_the_canonical_pc_run_handle():
    from app.request_contract import BrowserRequestError, _validate_payload

    valid = "chat_pcq_" + "e" * 32
    _validate_payload({
        "messages": [{"role": "user", "content": "내 PC 파일을 읽어줘"}],
        "pc_run_id": valid,
    })
    for invalid in ("chat_pcq_not-hex", "chat_" + "e" * 32, "chat_pcq_" + "e" * 31):
        try:
            _validate_payload({
                "messages": [{"role": "user", "content": "내 PC 파일을 읽어줘"}],
                "pc_run_id": invalid,
            })
        except BrowserRequestError:
            pass
        else:
            raise AssertionError(invalid)
