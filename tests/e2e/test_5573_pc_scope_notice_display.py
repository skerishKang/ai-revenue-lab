"""#5573 — the PC scope notice is displayed live as its own line.

The web-desktop E2E gate runs this file. It loads the REAL browser module
(``apps/padiem-chat/static/pc-scope-notice.js``) in Node against a minimal DOM
double and pins the three live render points that hand it a notice: the
completed-answer render, the stream completion, and the owner-scoped recovery.

The contract under test is display only: the notice is a separate element with
its own role above the answer, an absent notice leaves the surface byte-for-byte
as it was, and the answer text never contains the notice.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_ROOT = REPO_ROOT / "apps" / "padiem-chat"
STATIC = CHAT_ROOT / "static"
INDEX_HTML = STATIC / "index.html"
APP_JS = STATIC / "app.js"
CONVERSATION_JS = STATIC / "chat-conversation-module.js"
STREAMING_JS = STATIC / "chat-streaming-module.js"
PC_RUN_JS = STATIC / "chat-pc-run-module.js"
TRANSPORT_JS = STATIC / "chat-transport.js"
RECOVERY_JS = STATIC / "chat-pc-result-recovery.js"
NOTICE_JS = STATIC / "pc-scope-notice.js"

sys.path.insert(0, str(CHAT_ROOT))

from app.history import PC_SCOPE_NOTICE_LABELS  # noqa: E402


_NODE_CHECK = r"""
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.className = "";
    this.attrs = {};
    this.textContent = "";
  }
  get firstChild() {
    return this.children.length ? this.children[0] : null;
  }
  insertBefore(node, ref) {
    const at = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(at, 0, node);
    return node;
  }
  appendChild(node) {
    this.children.push(node);
    return node;
  }
  setAttribute(name, value) {
    this.attrs[name] = value;
  }
}

globalThis.document = { createElement: (tag) => new FakeNode(tag) };

const modulePath = process.argv[2];
const notice = process.argv[3];
assert.ok(modulePath && notice, "the checker was called without its arguments");
assert.ok(fs.existsSync(modulePath), "the notice module is missing");
require(path.resolve(modulePath));

const scope = globalThis.PadiemChatPcScopeNotice;
assert.ok(scope, "PadiemChatPcScopeNotice was not installed");
assert.strictEqual(typeof scope.render, "function");

// Live stream completion: the answer paragraph is already drawn.
const content = new FakeNode("div");
const answer = new FakeNode("p");
answer.textContent = "bounded answer text";
content.appendChild(answer);
const line = scope.render(content, notice);
assert.ok(line, "a present notice was not rendered");
assert.strictEqual(line.className, "pc-scope-notice");
assert.strictEqual(line.attrs.role, "note");
assert.strictEqual(line.textContent, notice);
assert.strictEqual(content.children.length, 2);
assert.strictEqual(content.firstChild, line, "the notice must sit above the result");
assert.strictEqual(content.children[1], answer, "the answer must stay intact");
assert.strictEqual(answer.textContent, "bounded answer text");
assert.ok(!answer.textContent.includes(notice), "the notice leaked into the answer");

// No notice: the surface keeps exactly the children it already had.
const untouched = new FakeNode("div");
const existing = new FakeNode("p");
existing.textContent = "bounded answer text";
untouched.appendChild(existing);
for (const absent of [undefined, null, "", 0, false]) {
  assert.strictEqual(scope.render(untouched, absent), null);
}
assert.strictEqual(untouched.children.length, 1);
assert.strictEqual(untouched.firstChild, existing);

// Only a non-empty string is a notice.
assert.strictEqual(scope.value({ scope_notice: notice }), notice);
assert.strictEqual(scope.value({}), null);
assert.strictEqual(scope.value({ scope_notice: 3 }), null);
assert.strictEqual(scope.value(null), null);

process.stdout.write("ok");
"""


def test_the_scope_notice_is_a_separate_line_above_the_answer(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    checker = tmp_path / "check_pc_scope_notice.cjs"
    checker.write_text(_NODE_CHECK, encoding="utf-8")
    notice = PC_SCOPE_NOTICE_LABELS["files_list"]
    completed = subprocess.run(
        [node, str(checker), str(NOTICE_JS), notice],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True, encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "ok"


def test_every_live_render_point_hands_the_notice_to_the_surface():
    """The three live answer surfaces are wired; the page loads the module first."""
    index = INDEX_HTML.read_text(encoding="utf-8")
    assert index.index("./pc-scope-notice.js") < index.index("./app.js")

    app_js = APP_JS.read_text(encoding="utf-8")
    # Completed JSON answer (/api/chat) — cleared container, notice first.
    # #7216 R5 step 5a moved the completed render into chat-conversation-module.js.
    conversation_js = CONVERSATION_JS.read_text(encoding="utf-8")
    assert "window.PadiemChatPcScopeNotice?.render?.(content, window.PadiemChatPcScopeNotice?.value?.(result));" in conversation_js
    # Stream completion (the browser's live orchestration path).
    # #7216 R5 step 5b moved applyStreamDone into chat-streaming-module.js.
    stream_js = STREAMING_JS.read_text(encoding="utf-8")
    apply_done = stream_js.split("function applyStreamDone(", 1)[1]
    apply_done = apply_done.split("async function requestStreamingAnswer(", 1)[0]
    assert "data.scope_notice" in apply_done
    # #7216 R5 A3 moved waitForAcceptedPcRun and renderStoredPcAnswer into chat-pc-run-module.js.
    assert index.index("./pc-scope-notice.js") < index.index("./chat-pc-run-module.js") < index.index("./app.js")
    assert "window.PadiemChatPcRunModule.create({" in app_js
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
const noticeSrc = fs.readFileSync(path.join(staticDir, "pc-scope-notice.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-pc-run-module.js"), "utf8");

function makeDom() {
  const mk = (tag) => ({
    tagName: tag.toUpperCase(),
    className: "",
    textContent: "",
    attrs: {},
    children: [],
    get firstChild() { return this.children[0] || null; },
    setAttribute(k, v) { this.attrs[k] = v; },
    replaceChildren() { this.children = []; },
    appendChild(c) { this.children.push(c); return c; },
    insertBefore(c, ref) {
      const idx = ref ? this.children.indexOf(ref) : -1;
      if (idx === -1) this.children.push(c);
      else this.children.splice(idx, 0, c);
      return c;
    },
  });
  return {
    documentElement: { lang: "ko" },
    createElement: mk,
    makeArticle() {
      const content = mk("div");
      return {
        isConnected: true,
        content,
        querySelector: (sel) => sel === ".assistant-content" ? content : null,
        scrollIntoView: () => {},
      };
    },
  };
}

const dom = makeDom();
let pollResult = null;
const ctx = vm.createContext({
  fetch: async () => ({ ok: true, json: async () => ({ result: pollResult }) }),
  document: dom,
  window: {
    setTimeout: (fn) => { fn(); return 1; },
    PadiemClawRunEventProjection: { label: () => "완료" },
    PadiemChatLifecycle: {
      setTaskHint() {}, releasePreparingRuntimeLabel() {}, applyRuntimeLabel() {},
    },
  },
  PadiemChatLifecycle: { set() {} },
  Promise, Proxy, Reflect, encodeURIComponent,
});
ctx.globalThis = ctx;
ctx.window.document = dom;
vm.runInContext(noticeSrc, ctx, { filename: "pc-scope-notice.js" });
vm.runInContext(strictSrc + "\n" + modSrc, ctx, { filename: "chat-pc-run-module.js" });

let mod = null;
const deps = ctx.r5StrictDeps({
  get MESSAGE_LIFECYCLE() { return { COMPLETED: "completed", FAILED: "failed", STREAMING: "streaming" }; },
  get authState() { return { authenticated: false, user: { id: "u1" } }; },
  get conversationProduct() { return "chat"; },
  get conversationState() {
    return {
      getConversationId: () => "c1", setProduct() {}, setConversationId() {}, commitAssistant() {},
    };
  },
  get loadRecentConversations() { return () => {}; },
  get resolvedPcRuns() { return new Set(); },
  get showPcRuntimeStatus() { return () => true; },
}, "deps");
mod = ctx.window.PadiemChatPcRunModule.create(deps);

// 1. Owner-scoped recovery render hands result.scopeNotice above answer paragraph.
const artRec = dom.makeArticle();
assert.equal(mod.renderStoredPcAnswer(artRec, { answer: "본문", scopeNotice: "허용 폴더: 문서", conversationId: "c1" }, [], { product: "chat" }), true);
assert.equal(artRec.content.children.length, 2);
assert.equal(artRec.content.children[0].textContent, "허용 폴더: 문서");
assert.equal(artRec.content.children[1].textContent, "본문");

// 2. Live pending-result poll hands result.scope_notice above answer paragraph.
const liveAuth = { authenticated: true, user: { id: "u1" } };
const resolvedLive = new Set();
const depsLive = ctx.r5StrictDeps({
  get MESSAGE_LIFECYCLE() { return { COMPLETED: "completed", FAILED: "failed", STREAMING: "streaming" }; },
  get authState() { return liveAuth; },
  get conversationProduct() { return "chat"; },
  get conversationState() {
    return {
      getConversationId: () => "c1", setProduct() {}, setConversationId() {}, commitAssistant() {},
    };
  },
  get loadRecentConversations() { return () => {}; },
  get resolvedPcRuns() { return resolvedLive; },
  get showPcRuntimeStatus() { return () => true; },
}, "depsLive");
const modLive = ctx.window.PadiemChatPcRunModule.create(depsLive);
pollResult = {
  run_id: "r1", conversation_id: "c1", status: "completed",
  answer: "폴링 본문", answer_source: "pc_command_result", scope_notice: "허용 폴더: 바탕화면",
};
const artLive = dom.makeArticle();
modLive.waitForAcceptedPcRun(artLive, { run_id: "r1", conversation_id: "c1" }, [], { aborted: false }, "chat").then(() => {
  assert.equal(artLive.content.children.length, 2);
  assert.equal(artLive.content.children[0].textContent, "허용 폴더: 바탕화면");
  assert.equal(artLive.content.children[1].textContent, "폴링 본문");
}).catch((err) => { console.error(err); process.exit(1); });
"""
    completed = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    transport = TRANSPORT_JS.read_text(encoding="utf-8")
    assert "donePayload.scope_notice = data.scope_notice;" in transport

    recovery = RECOVERY_JS.read_text(encoding="utf-8")
    assert "result && result.scope_notice" in recovery
    assert recovery.count("scopeNotice: scopeNotice(result)") == 2
