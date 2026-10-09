"""#3539/#3931 — canonical Claw routing and same-workspace composition.

Executes real routing and presentation functions from app.js against bounded
stubs. Claw submit must preserve the Claw workspace and canonical P01 lane;
normal Chat and explicit manual workflow routes must remain unchanged.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
APP_JS = APP_DIR / "static" / "app.js"
SOURCE = APP_JS.read_text(encoding="utf-8")

ROUTING_FUNCTIONS = (
    "showConversation",
    "clawGeneralRequestActive",
    "submitPrompt",
    "requestAnswer",
    "requestStreamingAnswer",
)


def _js_function(source: str, name: str) -> str:
    """Extract a function declaration, keeping any ``async`` prefix.

    Unlike the trimming helper in test_b54_claw_general_p01_routing.py this keeps
    the whole declaration (including ``async``) so the block is executable.
    """
    marker = f"function {name}("
    hit = source.index(marker)
    line_start = source.rfind("\n", 0, hit) + 1
    rest = source[hit + len(marker):]
    candidates = [
        i
        for i in (
            rest.find("\n  async function "),
            rest.find("\n  function "),
            rest.find("\n  window.PadiemChatTransport"),
            rest.find("\n})();"),
        )
        if i != -1
    ]
    end = hit + len(marker) + (min(candidates) if candidates else len(rest))
    return source[line_start:end]


def _harness() -> str:
    extracted = "\n\n".join(_js_function(SOURCE, name) for name in ROUTING_FUNCTIONS)
    return r"""
// Minimal stub environment: exercises the real routing functions, no DOM needed.
const trace = [];
const window = {}; // Browser global; optional #3930 event projection is absent here.
const shell = { dataset: {} };
const emptyState = { hidden: false };
const messageList = { hidden: true };
const setNavActive = () => {};
const clawManualForm = { hidden: false };
const input = { value: "", focus() {} };
let inFlight = false;
let activeRequestCancelReason = null;
let activeRequestArticle = null;
let activeRequestController = null;
let conversationEpoch = 0;
let selectedAttachment = null;
let activeProject = null;

const conversationState = {
  setSkill() {},
  getSkill() { return "auto"; },
  getConversationId() { return null; },
  outboundWithUser() { return []; },
  commitAssistant() {},
  setConversationId() {},
};
const uiT = (key) => key;
const updateComposer = () => {};
const renderTyping = () => {};
const selectedProductTier = () => "plus";
const attachmentPayload = () => null;
const lifecycleForError = () => "failed";
const clearAttachment = () => {};
const renderError = () => {};
const renderCancelled = () => {};
const requestCompletedAnswer = async () => false;
const addAssistantShell = () => ({ querySelector: () => ({ replaceChildren() {}, appendChild() {} }) });
const addUserMessage = () => {};
const chatTransport = {
  requestClawGeneral: async () => { trace.push("transport:clawGeneral"); return {}; },
  requestStreaming: async () => { trace.push("transport:streaming"); return {}; },
  readSseEvents: async () => {},
  errorFor: () => new Error("stub"),
};

__EXTRACTED__

// Instrument the actual presentation function, not a simulated replacement.
const __realShowConversation = showConversation;
showConversation = function (options) {
  trace.push("showConversation:state_before=" + shell.dataset.state);
  __realShowConversation(options);
  trace.push("showConversation:state_after=" + shell.dataset.state);
};

// Record exactly when the routing predicate is evaluated.
const __realClawGeneralRequestActive = clawGeneralRequestActive;
clawGeneralRequestActive = function () {
  const value = __realClawGeneralRequestActive();
  trace.push("route_decided:" + value);
  return value;
};

async function scenario(state, manualHidden) {
  trace.length = 0;
  inFlight = false;
  shell.dataset.state = state;
  clawManualForm.hidden = manualHidden;
  await submitPrompt("라우팅 회귀 시나리오");
  return { trace: trace.slice(), finalState: shell.dataset.state };
}

async function run() {
  const clawGeneral = await scenario("claw", true);
  const standalone = await scenario("chat", true);
  const clawManualVisible = await scenario("claw", false);
  console.log(JSON.stringify({ clawGeneral, standalone, clawManualVisible }));
}

run().catch((error) => { console.error(error); process.exit(1); });
""".replace("__EXTRACTED__", extracted)


def _run_harness() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "route-ordering-harness.js"
        script.write_text(_harness(), encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script)],
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(completed.stdout)


def _count(trace: list[str], entry: str) -> int:
    return trace.count(entry)


def test_claw_general_submit_keeps_claw_workspace_and_canonical_lane() -> None:
    result = _run_harness()
    claw = result["clawGeneral"]
    trace = claw["trace"]

    assert trace[0] == "route_decided:true", trace
    assert trace[1] == "showConversation:state_before=claw", trace
    assert trace[2] == "showConversation:state_after=claw", trace
    assert claw["finalState"] == "claw"
    assert _count(trace, "transport:clawGeneral") == 1, trace
    assert _count(trace, "transport:streaming") == 0, trace


def test_standalone_chat_path_keeps_stream_transport() -> None:
    result = _run_harness()
    standalone = result["standalone"]
    trace = standalone["trace"]

    assert trace[0] == "route_decided:false", trace
    assert standalone["finalState"] == "chat"
    assert _count(trace, "transport:streaming") == 1, trace
    assert _count(trace, "transport:clawGeneral") == 0, trace


def test_claw_shell_with_visible_manual_form_does_not_use_general_lane() -> None:
    result = _run_harness()
    manual = result["clawManualVisible"]
    trace = manual["trace"]

    # A Claw shell whose explicit manual form is visible is NOT the generic
    # composer; it must not be routed onto the general P01 lane.
    assert trace[0] == "route_decided:false", trace
    assert _count(trace, "transport:streaming") == 1, trace
    assert _count(trace, "transport:clawGeneral") == 0, trace


def test_request_answer_no_longer_derives_route_from_live_shell_state() -> None:
    block = _js_function(SOURCE, "requestAnswer")
    # The live-state predicate must be gone from requestAnswer: re-deriving it
    # there is exactly the Production regression (#3539).
    assert 'shell.dataset.state === "claw"' not in block
    # The snapshot arrives as a parameter and is threaded to the transport layer.
    assert "clawGeneralRequest" in block
