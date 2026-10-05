"""#3539 — the generic Claw routing decision is snapshotted BEFORE showConversation().

Production E2E proved the server route ``/api/claw/general`` was correct but the
browser never selected it: ``submitPrompt()`` called ``showConversation()`` first
(which sets ``shell.dataset.state = "chat"``) and only then did ``requestAnswer()``
read ``shell.dataset.state === "claw"`` — so the predicate was always false and the
generic Claw submit silently fell back to ``POST /api/chat/stream``.

String-presence contracts cannot catch that ordering bug, so this test EXECUTES the
real ``submitPrompt`` / ``requestAnswer`` / ``requestStreamingAnswer`` /
``clawGeneralRequestActive`` functions extracted from ``static/app.js`` against a
minimal stub environment (no DOM) and asserts the observable ordering:

    route_decided  ->  showConversation (state: claw -> chat)  ->  transport

with the transport still resolving to the Claw lane after the state flipped.
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
const shell = { dataset: {} };
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
let showConversation = function () {
  trace.push("showConversation:state_before=" + shell.dataset.state);
  shell.dataset.state = "chat";
};
const chatTransport = {
  requestClawGeneral: async () => { trace.push("transport:clawGeneral"); return {}; },
  requestStreaming: async () => { trace.push("transport:streaming"); return {}; },
  readSseEvents: async () => {},
  errorFor: () => new Error("stub"),
};

__EXTRACTED__

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


def test_claw_general_route_survives_show_conversation_state_flip() -> None:
    result = _run_harness()
    claw = result["clawGeneral"]
    trace = claw["trace"]

    # The decision is taken BEFORE showConversation() mutates the shell state.
    assert trace[0] == "route_decided:true", trace
    assert trace[1] == "showConversation:state_before=claw", trace

    # showConversation() did mutate the state...
    assert claw["finalState"] == "chat"

    # ...yet the transport still resolved to the canonical Claw lane.
    assert _count(trace, "transport:clawGeneral") == 1, trace
    assert _count(trace, "transport:streaming") == 0, trace


def test_standalone_chat_path_keeps_stream_transport() -> None:
    result = _run_harness()
    standalone = result["standalone"]
    trace = standalone["trace"]

    assert trace[0] == "route_decided:false", trace
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
