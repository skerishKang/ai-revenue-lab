"""#7543 — the PC run poll survives the run-row promotion race.

With two workers a pending-result GET can land before the signed Engine
callback promotes the chat_pcq row; one 404 must not abandon the run.
The harness executes the shipped module with a scripted fetch sequence.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"


def _run(statuses):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the PC run module contract")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const staticDir = process.argv[1];
const statuses = JSON.parse(process.argv[2]);
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-pc-run-module.js"), "utf8");
let fetches = 0;
const el = () => ({
  textContent: "",
  replaceChildren() { this.textContent = ""; },
  appendChild(child) { this.textContent += child.textContent; return child; },
  setAttribute() {},
});
const content = el();
const article = { isConnected: true, querySelector: () => content, textContent: "" };
const sandbox = {
  fetch: async (url) => {
    fetches += 1;
    const status = statuses[Math.min(fetches - 1, statuses.length - 1)];
    if (status === 404) return { ok: false, status: 404 };
    return { ok: true, status: 200, json: async () => ({
      ok: true,
      result: {
        run_id: "chat_pcq_" + "b".repeat(32),
        conversation_id: "chat_" + "c".repeat(32),
        status: "completed",
        answer: "PC result",
        answer_source: "pc_command_result",
      },
    }) };
  },
  document: { createElement: el, documentElement: { lang: "ko" } },
  window: {
    fetch: () => Promise.reject(new Error("no window fetch in this scenario")),
    setTimeout: (fn) => fn(),
    PadiemChatLifecycle: { set() {}, setTaskHint() {}, applyRuntimeLabel() {} },
    PadiemChatPcRecovery: { create: () => null },
    PadiemChatPcScopeNotice: { render() {} },
  },
  PadiemChatLifecycle: { set() {}, setTaskHint() {}, applyRuntimeLabel() {} },
  Math, Number, Array, Object, Proxy, Reflect, Set, JSON,
};
vm.createContext(sandbox);
vm.runInContext(strictSrc + "\n" + modSrc, sandbox, { filename: "chat-pc-run-module.js" });
const deps = sandbox.r5StrictDeps({
  authState: { authenticated: true, user: "usr_" + "a".repeat(32) },
  conversationState: {
    getConversationId: () => "chat_" + "c".repeat(32),
    commitAssistant: () => {},
  },
  loadRecentConversations: () => {},
  MESSAGE_LIFECYCLE: { FAILED: "failed", COMPLETED: "completed" },
  showPcRuntimeStatus: () => true,
  uiT: (k) => k,
}, "deps");
const mod = sandbox.window.PadiemChatPcRunModule.create(deps);
(async () => {
  await mod.waitForAcceptedPcRun(
    article,
    { run_id: "chat_pcq_" + "b".repeat(32), conversation_id: "chat_" + "c".repeat(32) },
    [], { aborted: false }, "chat"
  );
  assert.equal(fetches, statuses.length, "a transient 404 must keep polling");
  if (content.textContent === "PC result") console.log("PC_RUN_ANSWER_RENDERED");
  console.log("PC_RUN_404_RETRY_OK");
})().catch((err) => { console.error(err); process.exit(1); });
"""
    result = subprocess.run(
        [node, "-e", script, str(STATIC), json.dumps(statuses)],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    return result


def test_two_transient_404s_do_not_abandon_the_run():
    result = _run([404, 404, 200])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PC_RUN_404_RETRY_OK" in result.stdout
    assert "PC_RUN_ANSWER_RENDERED" in result.stdout


def test_a_persistent_404_still_ends_the_wait():
    result = _run([404, 404, 404, 404, 404, 404])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PC_RUN_404_RETRY_OK" in result.stdout
    assert "PC_RUN_ANSWER_RENDERED" not in result.stdout
