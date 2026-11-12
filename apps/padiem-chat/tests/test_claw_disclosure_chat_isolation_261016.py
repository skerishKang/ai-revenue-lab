"""Claw-only execution and memory disclosure never follow a Chat turn."""
import json
import shutil
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
CONV_SOURCE = (STATIC / "chat-conversation-module.js").resolve()
RUN_HISTORY = (STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")
MEM = (STATIC / "chat-memory-module.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")

# #7186 R2: showConversation 본문 문자열 슬라이스 대신 모듈을 Node vm에서 실행해
# Chat 전환 시의 실제 DOM 결과를 확인한다.
_SHOW_CHAT_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, tagName: "DIV", hidden: false, open: false, dataset: {}, children: [],
    style: {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    replaceChildren(...kids) { this.children = kids; },
  };
}
const nodes = {};
for (const id of ["clawRunHistoryDisclosure", "clawRunHistory",
                  "clawApprovedDisclosure", "clawApprovedMemory"]) {
  const node = makeElement(id);
  node.hidden = false;
  node.tagName = id.endsWith("Disclosure") ? "DETAILS" : "DIV";
  node.open = true;
  node.destroyed = 0;
  node.replaceChildren = (...kids) => {
    node.destroyed += 1;
    node.children = kids;
  };
  nodes[id] = node;
}
const conversationPanel = makeElement("conversationPanel");
const live = {
  shell: { dataset: { state: "claw" } },
  emptyState: makeElement("emptyState"),
  messageList: makeElement("messageList"),
  PRODUCT_CHAT: "chat",
  PRODUCT_CLAW: "claw",
  conversationProduct: "claw",
  switchedTo: null,
  navActive: false,
};
live.emptyState.hidden = true;
live.messageList.childElementCount = 2;
live.messageList.closest = () => conversationPanel;
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}
deps.switchConversationProduct = (p) => { live.switchedTo = p; live.conversationProduct = p; };
deps.setNavActive = () => { live.navActive = true; };
const ctx = { document: { getElementById: (id) => nodes[id] || null }, console, window: {} };
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__CONV_PATH__, "utf8"), ctx,
                { filename: "chat-conversation-module.js" });
const api = ctx.window.PadiemChatConversationModule.create(deps);
api.showConversation({ preserveClaw: false });
process.stdout.write(JSON.stringify({
  state: live.shell.dataset.state,
  switchedTo: live.switchedTo,
  product: live.conversationProduct,
  hidden: Object.keys(nodes).map((id) => nodes[id].hidden),
  detailsClosed: [nodes.clawRunHistoryDisclosure.open === false,
                  nodes.clawApprovedDisclosure.open === false],
  runsDestroyed: nodes.clawRunHistory.destroyed,
  thread: conversationPanel.dataset.continuousThread || null,
  emptyHidden: live.emptyState.hidden,
  listHidden: live.messageList.hidden,
}));
"""


def _run_show_chat() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = _SHOW_CHAT_HARNESS.replace(
        "__CONV_PATH__", json.dumps(str(CONV_SOURCE))
    )
    completed = subprocess.run(
        [node, "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_show_chat_resets_stale_claw_disclosures_without_destroying_runs():
    # Chat으로 전환하는 showConversation 실행이 패널 4개를 정확히 숨기고 DETAILS를
    # 닫으며, 서버 소유 실행 기록(replaceChildren)을 지우지 않는다.
    payload = _run_show_chat()
    assert payload["state"] == "chat"
    assert payload["switchedTo"] == "chat"
    assert payload["product"] == "chat"
    assert payload["hidden"] == [True, True, True, True]
    assert payload["detailsClosed"] == [True, True]
    assert payload["runsDestroyed"] == 0
    assert payload["thread"] is None
    assert payload["emptyHidden"] is True
    assert payload["listHidden"] is False


def test_claw_disclosures_are_css_hidden_outside_claw_state():
    assert "CLAW_DISCLOSURE_CHAT_ISOLATION_20261016" in CSS
    assert '.app-shell:not([data-state="claw"])' in CSS
    assert "#clawRunHistoryDisclosure" in CSS
    assert "#clawApprovedDisclosure" in CSS
    assert "display: none !important" in CSS


def test_claw_owner_scoped_history_contract_survives():
    assert '/api/claw/runs?limit=' in RUN_HISTORY
    assert 'deps.shell.dataset.state === "claw"' in MEM
    assert 'deps.authState.authenticated === true' in MEM


def test_7459_chat_state_never_reexposes_claw_panels():
    """Chat 대화 중(empty-state 숨김)에도 패널을 display:block으로 되살리면 안 된다."""
    assert '.app-shell[data-state="chat"] .empty-state[hidden] ~' not in CSS
