"""Owner-accepted inline first-turn, not a replacement conversation surface."""
import json
import os
import shutil
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
#7216 R5 step 5a: showConversation moved into chat-conversation-module.js.
CONV_SOURCE = (STATIC / "chat-conversation-module.js").resolve()
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

# #7186 R2: showConversation·resetConversationView 본문 문자열 대신 모듈을
# Node vm에서 실행해 첫 턴 랜딩·저장 대화 재열기·새 대화 리셋의 실제 DOM 결과를
# 확인한다.
_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, tagName: "DIV", hidden: false, open: false, dataset: {}, children: [],
    childElementCount: 0, style: {}, value: "",
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    replaceChildren(...kids) { this.children = kids; this.childElementCount = kids.length; },
    appendChild(x) { this.children.push(x); this.childElementCount = this.children.length; return x; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    closest() { return null; },
    focus() {},
  };
}
const domRegistry = {};
for (const id of ["clawRunHistoryDisclosure", "clawRunHistory",
                  "clawApprovedDisclosure", "clawApprovedMemory", "clawMemoryReview"]) {
  const node = makeElement(id);
  node.hidden = false;
  node.tagName = id.endsWith("Disclosure") ? "DETAILS" : "DIV";
  node.open = true;
  domRegistry[id] = node;
}
const conversationPanel = makeElement("conversationPanel");
const mode = process.env.CONV_MODE;
const live = {
  shell: { dataset: { state: "claw" } },
  emptyState: makeElement("emptyState"),
  messageList: makeElement("messageList"),
  PRODUCT_CHAT: "chat",
  PRODUCT_CLAW: "claw",
  conversationProduct: "claw",
  switchedTo: null,
  navActive: false,
  conversationEpoch: 7,
  lastCompletedAnswerRequest: null,
  activeRequestController: null,
  activeRequestCancelReason: null,
  activeRequestArticle: null,
  activeClawRunId: null,
  activeProject: null,
  activeProjectFileCount: 0,
  inFlight: false,
  clawArtifactShownFor: "",
  selectedAttachments: [],
  setNote: () => {},
  idleNote: () => "idle",
  uiT: (key) => key,
  formatBytes: (n) => `fb-${n}`,
  extensionOf: (name) => name.slice(name.lastIndexOf(".")),
  clearClawRecovery: () => {},
  clearClawWait: () => {},
  renderProjectState: () => {},
  closeSidebar: () => {},
  conversationState: { setProduct() {}, reset() {} },
  conversationArtifactContext: { clear() {} },
  attachmentFileInput: makeElement("attachmentFileInput"),
  attachmentChipList: makeElement("attachmentChipList"),
  attachmentTray: makeElement("attachmentTray"),
  sendButton: makeElement("sendButton"),
  attachmentButton: makeElement("attachmentButton"),
  editProjectButton: makeElement("editProjectButton"),
  exitProjectButton: makeElement("exitProjectButton"),
  cancelStreamButton: makeElement("cancelStreamButton"),
  input: makeElement("messageInput"),
};
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
const ctx = {
  document: { getElementById: (id) => domRegistry[id] || null },
  console,
  window: {},
  URL,
  Map, Set, Array, JSON, Promise, Date, Error, TypeError, Number, String, Boolean, Object,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__CONV_PATH__, "utf8"), ctx,
                { filename: "chat-conversation-module.js" });
const api = ctx.window.PadiemChatConversationModule.create(deps);
Object.assign(deps, api);
const snapshot = () => ({
  thread: conversationPanel.dataset.continuousThread || null,
  emptyHidden: live.emptyState.hidden,
  listHidden: live.messageList.hidden,
  messages: live.messageList.childElementCount,
  state: live.shell.dataset.state,
});
let result;
if (mode === "landing") {
  live.shell.dataset.state = "home";
  live.emptyState.hidden = false;
  live.messageList.hidden = true;
  api.showConversation();
  result = snapshot();
} else if (mode === "restored") {
  conversationPanel.dataset.continuousThread = "true";
  live.emptyState.hidden = false;
  api.showConversation({ preserveClaw: true, restoreSaved: true });
  result = Object.assign(snapshot(), { switchedTo: live.switchedTo });
} else {
  conversationPanel.dataset.continuousThread = "true";
  live.messageList.replaceChildren(makeElement("m1"), makeElement("m2"));
  live.messageList.hidden = false;
  api.resetConversationView(true);
  result = snapshot();
}
process.stdout.write(JSON.stringify(result));
"""


def _run_mode(mode: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = _HARNESS.replace("__CONV_PATH__", json.dumps(str(CONV_SOURCE)))
    completed = subprocess.run(
        [node, "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**os.environ, "CONV_MODE": mode},
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_first_user_turn_preserves_original_hero_and_appends_messages() -> None:
    # #7186 R2: 본문 문자열 대신 모듈 실행. 첫 유저 턴은 소유 결정(2026-10-15)
    # 대로 히어로(emptyState)를 유지하고 messageList를 보여 준다.
    assert _run_mode("landing") == {"thread": "true", "emptyHidden": False,
                                    "listHidden": False, "messages": 0, "state": "chat"}
    # 스트리밍 와이어링(submitPrompt)의 showConversation 호출점은 아직 app.js에
    # 있다. 이 구역이 모듈로 이동하는 PR에서 이 문자열 계약을 옮겨야 한다.
    assert 'showConversation({ preserveClaw: clawGeneralRequest });' in APP


def test_saved_conversation_reopens_without_hero_and_new_chat_resets() -> None:
    # 저장 대화 재열기는 히어로 없이 열고 Claw 화면은 유지한다. 메시지 목록
    # 자체는 showConversation이 건드리지 않는다(채워넣기는 저장 대화 열기 와이어링).
    assert _run_mode("restored") == {"thread": None, "emptyHidden": True,
                                     "listHidden": False, "messages": 0, "state": "claw",
                                     "switchedTo": None}
    # 새 대화는 공유 스레드를 해제하고 히어로를 복원하며 메시지를 비운다.
    assert _run_mode("reset") == {"thread": None, "emptyHidden": False,
                                  "listHidden": True, "messages": 0, "state": "home"}
    # 저장 대화 재열기 호출점(openSavedConversation)도 아직 app.js에 있다.
    assert 'showConversation({ preserveClaw: isVerifiedClawThread, restoreSaved: true })' in APP
    # openClawWorkspace의 히어로 복원(app.js) — 대화 모듈 계약이 아니므로 유지.
    assert 'emptyState.hidden = false;' in APP


def test_same_panel_dom_and_inline_message_list_for_chat_and_claw() -> None:
    hero = HTML.index('id="emptyState"')
    messages = HTML.index('id="messageList"')
    assert hero < messages
    assert "CENTRAL_CONTINUOUS_CHAT_CLAW_20261015" in CSS
    assert '.conversation[data-continuous-thread="true"] .empty-state:not([hidden])' in CSS
    assert '.conversation[data-continuous-thread="true"] #messageList:not([hidden])' in CSS
    assert 'margin-top: clamp(28px, 3.2vh, 48px)' in CSS
