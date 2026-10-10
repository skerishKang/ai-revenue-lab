"""#3566: Claw general P01 rate-limit projection and no one-click replay.

Network-free Node behavioral tests run the actual browser transport and the
actual retry-box function. Nothing calls B14, Engine or a model. The separate
B62 Chat retry behavior must remain unchanged.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")

NODE = r"""
const fs = require("fs");
const vm = require("vm");
const path = require("path");
const root = process.argv[1];
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");
const transport = fs.readFileSync(path.join(root, "chat-transport.js"), "utf8");

function assert(condition, label) { if (!condition) throw Error(label); }
function element(type) {
  return {
    tagName: type.toUpperCase(), children: [], textContent: "", handlers: {},
    append(...nodes) { this.children.push(...nodes); },
    addEventListener(kind, fn) { this.handlers[kind] = fn; },
    remove() {},
  };
}

// Execute the real Claw/Chat recovery-box function with a minimal DOM stub.
const start = app.indexOf("  function buildRetryBox(");
const end = app.indexOf("\n  function revealErrorState(", start);
assert(start >= 0 && end > start, "source function locator");
let repeatCalls = 0;
let historyOpens = 0;
let historyScrolls = 0;
const history = {hidden:false, scrollIntoView(){historyScrolls++},querySelector(){return {focus(){}}}};
const context = {
  document: {createElement: element, getElementById: (id)=>id==="clawRunHistory" ? history : null},
  authState: {authenticated:true},
  openClawWorkspace(){historyOpens++},
  uiT: (key) => key,
  conversationState: {setConversationId() {}},
  renderProjectState() {},
  requestAnswer: async () => {repeatCalls += 1; return false;},
  selectedAttachment: null,
  clearAttachment() {},
};
const build = vm.runInNewContext("(" + app.slice(start, end) + ")", context);
const args = ["engine failed", {remove() {}}, [], "auto", null,
              {conversationId:null,project:null}];
const claw = build(...args, true);
assert(claw.children.length === 4, "Claw hint plus read-only history action");
const view = claw.children[3];
assert(view.tagName === "BUTTON" && view.className.includes("claw-check-runs-button"), "only explicit view action");
assert(view.textContent === "claw-general-open-runs" && !view.disabled, "authenticated history option");
assert(claw.children[2].textContent === "claw-general-check-runs", "bounded hint");
assert(!claw.children.some(x => x.className === "retry-button"), "Claw has no one-click replay");
view.handlers.click();
assert(historyOpens === 1 && historyScrolls === 1 && repeatCalls === 0, "GET-only existing history opens without execute POST");
context.authState.authenticated = false;
const signedOut = build(...args, true);
assert(signedOut.children[3].disabled === true, "signed out cannot open private run history");
signedOut.children[3].handlers.click();
assert(historyOpens === 1 && repeatCalls === 0, "signed out click does not open private history");
context.authState.authenticated = true;
const chat = build(...args, false);
assert(chat.children.some(x => x.tagName === "BUTTON"), "B62 retry preserved");
chat.children.find(x => x.tagName === "BUTTON").handlers.click();
assert(repeatCalls === 1, "explicit B62 retry remains once only");
assert(repeatCalls !== 2, "no Claw replay dispatched");

async function run() {
  let posts = [];
  let response;
  const win = {};
  const sandbox = {
    window: win,
    fetch: async (url, opts) => {
      posts.push({url,method:opts.method});
      return response;
    },
  };
  vm.runInNewContext(transport, sandbox);
  const parse = (status, code, detail) => ({
    ok:false, status,
    headers:{get:()=> "application/json"},
    json: async () => ({error:{code,detail,message:"untrusted provider payload"}}),
  });
  response = parse(502, "engine_execution_failed", "engine_provider_rate_limited");
  try {
    await win.PadiemChatTransport.requestClawGeneral({model_id:"fixture/selected"}, null);
    throw Error("expected rate-limit rejection");
  } catch (e) {
    assert(e.code === "engine_execution_failed", "closed error code preserved");
    assert(e.clawFailureDetail === "engine_provider_rate_limited", "bounded classification");
  }
  // A spoofed detail on a different status or error code is never promoted.
  for (const [status,code,detail] of [
    [503,"engine_execution_failed","engine_provider_rate_limited"],
    [502,"other","engine_provider_rate_limited"],
    [502,"engine_execution_failed","rate_limited"],
    [502,"engine_execution_failed","provider raw text"],
  ]) {
    response = parse(status,code,detail);
    let rejected = false;
    try {
      await win.PadiemChatTransport.requestClawGeneral({}, null);
    } catch (e) {
      rejected = true;
      assert(e.clawFailureDetail === undefined, "fail closed for spoofed detail");
    }
    assert(rejected, "bad responses must always reject");
  }
  // #3930: a read-only GET capability probe is permitted BEFORE dispatch,
  // but each invocation still has exactly one P01 POST and zero retries.
  assert(posts.length === 10, "one capability GET and one POST per invocation");
  for (let i = 0; i < posts.length; i += 2) {
    assert(posts[i].url === "/api/claw/general/capabilities" && posts[i].method === "GET",
      "capability probe must be read-only and before dispatch");
    assert(posts[i + 1].url === "/api/claw/general" && posts[i + 1].method === "POST",
      "exactly one P01 POST, never direct B14, B62 Chat, or retry");
  }
  // The exact localized message is chosen in the actual Claw-only catch.
  assert(app.includes('clawGeneralRequest && error?.clawFailureDetail === "engine_provider_rate_limited"'),
    "P01 detail rendered only for Claw general");
  assert(app.includes('uiT("claw-general-provider-limit")'), "localized bounded message");
  console.log("CLAW_NO_ONE_CLICK_REPLAY=PASS");
  console.log("B62_CHAT_RETRY_UNCHANGED=PASS");
  console.log("CLOSED_PROVIDER_RATE_LIMIT_CLASS=PASS");
  console.log("NO_AUTO_RETRY_OR_FALLBACK=PASS");
}
run().catch(e => { console.error(e.message); process.exitCode = 1; });
"""


def test_claw_rate_limit_copy_and_retry_guard_have_locale_parity():
    for key in ("claw-general-provider-limit", "claw-general-check-runs", "claw-general-open-runs"):
        # One Korean and one English label; fallback text is not a raw provider body.
        assert LOCALE.count(f'"{key}":') == 2
    assert "model provider or an internal gateway" in LOCALE
    assert "실제 모델 제공자와 내부 제한" in LOCALE
    assert "raw_provider_payload" not in APP
    assert "async function requestStreaming(payload, signal)" in TRANSPORT


def test_claw_general_rate_limit_network_free_browser_behavior():
    if shutil.which("node") is None:
        pytest.skip("Node runtime unavailable; run CI for the behavioral browser contract")
    result = subprocess.run(
        ["node", "-e", NODE, str(STATIC)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        "CLAW_NO_ONE_CLICK_REPLAY=PASS",
        "B62_CHAT_RETRY_UNCHANGED=PASS",
        "CLOSED_PROVIDER_RATE_LIMIT_CLASS=PASS",
        "NO_AUTO_RETRY_OR_FALLBACK=PASS",
    ):
        assert marker in result.stdout
