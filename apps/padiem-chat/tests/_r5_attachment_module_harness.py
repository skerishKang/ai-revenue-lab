"""R5 5a 첨부 구역 + Claw 실행 해제 배선 — 실제 모듈 실행 관찰 하네스 (#7186 R2).

`chat-conversation-module.js`(첨부 흡수·칩·페이로드·대화 리셋)와
`claw-session.js`(세션 소실 시 Claw 정리)를 Node vm에서 그대로 실행하고,
소스 문자열 대신 **호출 결과**를 돌려준다:

- `attachmentPayload`가 칩을 요청 본문으로 바꾸는 4분지(file_id / file / text /
  invalid 제외),
- `addAttachmentFiles`의 파일별 흡수(이미지→selectImage, 바이너리→
  binaryDocuments.read, 문서→readDocumentFile)와 칩별 거부(개수 한도·raw 단독),
- 칩 렌더(클래스·아이콘·제거 버튼 aria·locale 키)와 실제 제거 연결,
- `resetConversationView`가 `clearClawRecovery({ syncControls: true })`와
  `clearClawWait()`를 부르는지(홈 복귀의 Claw 실행 해제),
- `claw-session.js`가 인증 상태 소실 때 같은 인자로 정리를 부르는지.

deps는 `_r5_strict_deps.js` 프록시로 싸서 정의되지 않은 deps 읽기·쓰기를 즉시
실패시킨다. 값·토큰은 만들지 않는다: 파일은 합성 객체다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
CONV = STATIC / "chat-conversation-module.js"
SESSION = STATIC / "claw-session.js"
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

_NODE = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(tag) {
  const attrs = {};
  const classes = new Set();
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    id: "", textContent: "", type: "", value: "", hidden: false, disabled: false,
    open: false, isConnected: true, dataset: {}, attrs, children: [],
    parentElement: null, style: {}, scrollHeight: 0, focused: 0,
    get className() { return Array.from(classes).join(" "); },
    set className(v) {
      classes.clear();
      String(v || "").split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
    classList: {
      add(...xs) { xs.forEach((x) => classes.add(x)); },
      remove(...xs) { xs.forEach((x) => classes.delete(x)); },
      contains(x) { return classes.has(x); },
      toggle(x, on) { on ? classes.add(x) : classes.delete(x); },
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    append(...xs) { xs.forEach((x) => this.appendChild(x)); },
    appendChild(x) { x.parentElement = this; this.children.push(x); return x; },
    insertBefore(x, ref) {
      const i = this.children.indexOf(ref);
      if (i < 0) this.children.push(x); else this.children.splice(i, 0, x);
      x.parentElement = this; return x;
    },
    replaceChildren(...xs) { this.children = []; xs.forEach((x) => this.appendChild(x)); },
    remove() { if (this.parentElement) {
      const i = this.parentElement.children.indexOf(this);
      if (i >= 0) this.parentElement.children.splice(i, 1);
    } },
    focus() { this.focused += 1; },
    addEventListener(t, fn) { (node.listeners[t] = node.listeners[t] || []).push(fn); },
    dispatchEvent(ev) {
      (node.listeners[ev && ev.type] || []).forEach((fn) => fn({ type: ev && ev.type, target: node }));
      return true;
    },
    listeners: {},
    closest(sel) {
      const want = String(sel).replace(/^[.#]/, "");
      let at = this;
      while (at) {
        if (at.tagName === want.toUpperCase()
            || (typeof at.className === "string" && at.className.split(/\s+/).includes(want))) return at;
        at = at.parentElement;
      }
      return null;
    },
    querySelector(sel) { return walk(this).find((n) => matches(n, sel)) || null; },
    querySelectorAll(sel) { return walk(this).filter((n) => matches(n, sel)); },
  };
  return node;
}
function walk(root) {
  const out = [];
  for (const child of root.children || []) { out.push(child); walk(child, out); }
  return out;
}
function matches(node, sel) {
  if (sel.startsWith(".")) return node.classList.contains(sel.slice(1));
  if (sel.startsWith("#")) return node.attrs.id === sel.slice(1);
  return node.tagName === sel.toUpperCase();
}

// ── conversation module context ────────────────────────────────────────────
const results = {};
const byId = {};
function node(id, tag) { const e = makeElement(tag); e.id = id; byId[id] = e; return e; }
for (const id of ["clawRunHistoryDisclosure", "clawRunHistory", "clawApprovedDisclosure",
                  "clawApprovedMemory", "clawMemoryReview"]) node(id, "div");
byId.clawRunHistoryDisclosure.tagName = "DETAILS";
byId.clawApprovedDisclosure.tagName = "DETAILS";

const convLive = {
  selectedAttachments: [],
  attachmentKeyCounter: 0,
  inFlight: false,
  conversationEpoch: 7,
  conversationProduct: "chat",
  lastCompletedAnswerRequest: null,
  activeRequestController: null,
  activeRequestCancelReason: null,
  activeRequestArticle: null,
  activeClawRunId: null,
  activeProject: { id: "p1" },
  activeProjectFileCount: 2,
  clawArtifactShownFor: "x",
  conversationArtifactContext: null,
  binaryDocuments: null,
  ALLOWED_IMAGE_TYPES: new Set(["image/png", "image/jpeg"]),
  attachmentChipList: node("attachmentChipList", "ul"),
  attachmentTray: node("attachmentTray", "div"),
  attachmentFileInput: node("attachmentFileInput", "input"),
  messageList: node("messageList", "ol"),
  emptyState: node("emptyState", "div"),
  shell: makeElement("div"),
  input: node("messageInput", "textarea"),
  sendButton: node("sendButton", "button"),
  attachmentButton: node("attachmentButton", "button"),
  editProjectButton: node("editProjectButton", "button"),
  exitProjectButton: node("exitProjectButton", "button"),
  cancelStreamButton: node("cancelStreamButton", "button"),
  uiT: (k, vars) => (vars && vars.count !== undefined ? `${k}:${vars.count}` : k),
  extensionOf: (name) => { const i = String(name).lastIndexOf("."); return i < 0 ? "" : String(name).slice(i); },
  formatBytes: (n) => `${n}B`,
  idleNote: () => "idle",
  setNote: (note) => { convLive.notes.push(note); },
  notes: [],
  composerCalls: 0,
  selectImageCalls: 0,
  readDocumentCalls: 0,
  binaryCanReadCalls: 0,
  binaryReadCalls: 0,
  clearRecoveryArgs: [],
  clearWaitCalls: 0,
  aborts: 0,
  navCalls: 0,
  sidebarCloses: 0,
  projectRenders: 0,
  stateResets: 0,
  products: [],
  selectImage: async (file) => {
    convLive.selectImageCalls += 1;
    return { type: "image", name: file.name, mediaType: file.type, byteSize: file.size, file };
  },
  readDocumentFile: async (file) => {
    convLive.readDocumentCalls += 1;
    return { type: "document", name: file.name, mediaType: "text/plain", text: "본문", byteSize: file.size };
  },
  conversationState: {
    setProduct(p) { convLive.products.push(p); },
    reset() { convLive.stateResets += 1; },
  },
  clearClawRecovery: (options) => { convLive.clearRecoveryArgs.push(options); },
  clearClawWait: () => { convLive.clearWaitCalls += 1; },
  setNavActive: () => { convLive.navCalls += 1; },
  closeSidebar: () => { convLive.sidebarCloses += 1; },
  renderProjectState: () => { convLive.projectRenders += 1; },
};
convLive.messageList.closest = (sel) => (sel === ".conversation" ? convLive.conversationPanel : null);
convLive.conversationPanel = makeElement("section");
convLive.conversationPanel.className = "conversation";
convLive.conversationPanel.appendChild(convLive.messageList);

const convDoc = {
  documentElement: { lang: "ko" },
  createElement: (t) => makeElement(t),
  createTextNode: (v) => { const n = makeElement("#text"); n.data = String(v); n.appendData = (d) => { n.data += d; }; return n; },
  getElementById: (id) => byId[id] || null,
  body: makeElement("body"),
};
const convWindow = {};
convWindow.window = convWindow;
const convCtx = {
  document: convDoc, window: convWindow, console,
  URL: { revokeObjectURL() {} },
  setTimeout, clearTimeout, Event: class { constructor(t, init) { this.type = t; this.bubbles = Boolean(init && init.bubbles); } },
};
vm.createContext(convCtx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), convCtx, { filename: "chat-conversation-module.js" });

function convApi(overrides) {
  const base = {};
  for (const key of Object.keys(convLive)) {
    Object.defineProperty(base, key, {
      get() { return convLive[key]; },
      set(value) { convLive[key] = value; },
    });
  }
  Object.assign(base, overrides || {});
  const api = convCtx.window.PadiemChatConversationModule.create(r5StrictDeps(base, "attach.deps"));
  // app.js passes the module's own functions back through deps (one-line
  // forwarders), so the module reaches itself through the same deps surface.
  for (const name of ["renderAttachmentChips", "attachmentTrayNote", "clearAttachment", "removeAttachmentItem", "attachmentCountLimit"]) {
    Object.defineProperty(base, name, { get() { return api[name]; } });
  }
  Object.defineProperty(base, "updateComposer", {
    get() { convLive.composerCalls += 1; return api.updateComposer; },
  });
  return api;
}

(async () => {
function freshConv() {
  convLive.selectedAttachments = [];
  convLive.attachmentKeyCounter = 0;
  convLive.inFlight = false;
  convLive.notes = [];
  convLive.composerCalls = 0;
  convLive.selectImageCalls = 0;
  convLive.readDocumentCalls = 0;
  convLive.binaryCanReadCalls = 0;
  convLive.binaryReadCalls = 0;
  convLive.binaryDocuments = null;
  convLive.attachmentFileInput.value = "stale";
  convLive.attachmentChipList.replaceChildren();
  convLive.attachmentTray.hidden = false;
  return convApi();
}
const FILE_ID = "file_" + "a".repeat(32);
const pngFile = { name: "photo.png", type: "image/png", size: 123 };
const txtFile = { name: "note.txt", type: "text/plain", size: 456 };

// 1. attachmentPayload: the request-body quadrants.
{
  const api = freshConv();
  const FILE = { name: "report.pdf" };
  results.payload = {
    fileLaneChip: api.attachmentPayload([{ type: "file", name: "large.pdf", fileId: FILE_ID }]),
    fileChip: api.attachmentPayload([{ type: "document", name: "report.pdf", mediaType: "application/pdf", file: FILE }]),
    fileChipSameObject: api.attachmentPayload([{ type: "document", name: "report.pdf", mediaType: "application/pdf", file: FILE }])[0].file === FILE,
    textChip: api.attachmentPayload([{ type: "document", name: "note.txt", mediaType: "text/plain", text: "본문" }]),
    invalidExcluded: api.attachmentPayload([
      { type: "document", name: "a.txt", mediaType: "text/plain", text: "x" },
      { invalid: true, type: "document", name: "b.txt" },
    ]).length,
    empty: api.attachmentPayload([]),
    nullList: api.attachmentPayload(null),
    singleObject: api.attachmentPayload({ type: "file", fileId: FILE_ID }),
  };
}

// 2. Binary original intake: canRead -> read -> chip with key, chips re-rendered.
{
  const api = freshConv();
  convLive.binaryDocuments = {
    canRead(file) { convLive.binaryCanReadCalls += 1; return true; },
    read(file) {
      convLive.binaryReadCalls += 1;
      return { type: "document", name: file.name, mediaType: "application/pdf", file, byteSize: file.size };
    },
  };
  await api.addAttachmentFiles([{ name: "report.pdf", type: "application/pdf", size: 5000 }]);
  const chip = convLive.attachmentChipList.children[0];
  results.binaryIntake = {
    canRead: convLive.binaryCanReadCalls,
    read: convLive.binaryReadCalls,
    chips: convLive.attachmentChipList.children.length,
    chipClass: chip.className,
    icon: chip.children[0].textContent,
    name: chip.children[1].children[0].textContent,
    detail: chip.children[1].children[1].textContent,
    key: convLive.selectedAttachments[0].key,
    mediaType: convLive.selectedAttachments[0].mediaType,
    fileCarried: convLive.selectedAttachments[0].file === undefined ? null : "file",
    inputCleared: convLive.attachmentFileInput.value === "",
    note: convLive.notes[convLive.notes.length - 1],
    composer: convLive.composerCalls,
  };
}

// 3. Image routing: an image goes to selectImage, a plain document does not.
{
  const api = freshConv();
  await api.addAttachmentFiles([pngFile]);
  results.imageRouting = {
    imageToSelectImage: convLive.selectImageCalls === 1 && convLive.readDocumentCalls === 0,
    imageChipType: convLive.selectedAttachments[0].type,
    note: convLive.notes[convLive.notes.length - 1],
  };
  const api2 = freshConv();
  await api2.addAttachmentFiles([txtFile]);
  results.imageRouting.documentToReader = convLive.selectImageCalls === 0 && convLive.readDocumentCalls === 1;
  results.imageRouting.documentChipType = convLive.selectedAttachments[0].type;
}

// 4. Multi-attachment: one chip per file, per-chip refusal, invalid excluded.
{
  convCtx.window.PadiemAttachmentCapabilities = { maxPerMessage: 2 };
  const api = freshConv();
  await api.addAttachmentFiles([txtFile, { name: "b.txt", type: "text/plain", size: 7 }, { name: "c.txt", type: "text/plain", size: 8 }]);
  const chips = convLive.attachmentChipList.children.map((chip) => ({
    cls: chip.className,
    icon: chip.children[0].textContent,
    name: chip.children[1].children[0].textContent,
    detail: chip.children[1].children[1].textContent,
    removeType: chip.children[2].type,
    removeClass: chip.children[2].className,
    removeLocale: chip.children[2].getAttribute("data-locale-aria-label"),
    removeAria: chip.children[2].getAttribute("aria-label"),
    removeDisabled: chip.children[2].disabled,
  }));
  results.multiChips = {
    chips,
    payloadCount: api.attachmentPayload(convLive.selectedAttachments).length,
    trayHidden: convLive.attachmentTray.hidden,
    inputCleared: convLive.attachmentFileInput.value === "",
  };
  convCtx.window.PadiemAttachmentCapabilities = undefined;
}

// 5. A raw-byte attachment (photo) rides alone: mixing it with a document
//    refuses the new chip only.
{
  const api = freshConv();
  await api.addAttachmentFiles([txtFile]);
  await api.addAttachmentFiles([pngFile]);
  results.rawSingle = {
    validCount: convLive.selectedAttachments.filter((i) => !i.invalid).length,
    invalidError: convLive.selectedAttachments.find((i) => i.invalid).error,
    invalidName: convLive.selectedAttachments.find((i) => i.invalid).name,
    payloadCount: api.attachmentPayload(convLive.selectedAttachments).length,
  };
}

// 6. Chip removal: the button removes its own item and re-renders; in-flight
//    blocks removal and disables the buttons.
{
  const api = freshConv();
  await api.addAttachmentFiles([txtFile, { name: "b.txt", type: "text/plain", size: 7 }]);
  const first = convLive.selectedAttachments[0];
  convLive.attachmentChipList.children[0].children[2].dispatchEvent({ type: "click" });
  const removed = {
    gone: convLive.selectedAttachments.indexOf(first) < 0,
    chips: convLive.attachmentChipList.children.length,
    note: convLive.notes[convLive.notes.length - 1],
    composer: convLive.composerCalls,
  };
  convLive.inFlight = true;
  api.renderAttachmentChips();
  const busy = {
    removeDisabled: convLive.attachmentChipList.children[0].children[2].disabled,
    removeIgnored: (api.removeAttachmentItem(convLive.selectedAttachments[0]), convLive.selectedAttachments.length) === 1,
  };
  convLive.inFlight = false;
  results.chipRemoval = { removed, busy };
}

// 7. resetConversationView tears down the Claw execution state on the way home.
{
  convLive.activeRequestController = { abort() { convLive.aborts += 1; } };
  convLive.selectedAttachments = [{ type: "document", name: "a.txt" }];
  const api = freshConv();
  convLive.composerCalls = 0;
  api.resetConversationView(true);
  results.teardown = {
    resetView: {
      clearClawRecoveryArgs: convLive.clearRecoveryArgs.slice(),
      clearClawWait: convLive.clearWaitCalls,
      aborted: convLive.aborts,
      cancelReason: convLive.activeRequestCancelReason,
      controllerNull: convLive.activeRequestController === null,
      epoch: convLive.conversationEpoch,
      projectKept: convLive.activeProject !== null,
      stateHome: convLive.shell.dataset.state,
      inputCleared: convLive.input.value === "",
      listCleared: convLive.messageList.children.length === 0,
      emptyShown: convLive.emptyState.hidden === false,
      nav: convLive.navCalls,
      sidebarClosed: convLive.sidebarCloses,
      composer: convLive.composerCalls,
    },
  };
  convLive.activeProject = { id: "p1" };
  api.resetConversationView(false);
  results.teardown.resetViewProjectDropped = convLive.activeProject === null;
}

// ── claw-session.js context (separate vm context: its own window/document) ──
const sessionResults = {};
{
  const ids = {};
  const make = (id, tag) => { const e = makeElement(tag); e.id = id; ids[id] = e; return e; };
  for (const id of ["clawAutomation", "clawAutomationList", "clawWorkspace", "clawRunHistory",
                    "clawRunHistoryList", "clawRunHistoryError", "clawApprovedMemory",
                    "clawApprovedDisclosure", "clawApprovedList", "clawApprovedError",
                    "clawApprovalActions", "clawRunHistoryDisclosure"]) make(id, "div");
  ids.clawApprovedDisclosure.tagName = "DETAILS";
  ids.clawRunHistoryDisclosure.tagName = "DETAILS";
  ids.clawWorkspace.dataset.view = "automation";

  const calls = { recovery: [], wait: 0, notes: [], pdfRevokes: 0 };
  const sessionWindow = {
    listeners: {},
    addEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).concat(fn); },
  };
  sessionWindow.window = sessionWindow;
  let sessionState = { authenticated: true };
  const sessionCtx = {
    document: { getElementById: (id) => ids[id] || null },
    window: sessionWindow,
    console,
  };
  sessionCtx.window.PadiemAuthSession = { get: () => sessionState };
  sessionCtx.window.PadiemClawPdfPreview = { revokeAll() { calls.pdfRevokes += 1; } };
  vm.createContext(sessionCtx);
  vm.runInContext(fs.readFileSync(process.argv[3], "utf8"), sessionCtx, { filename: "claw-session.js" });
  sessionCtx.window.PadiemClawSession.bind({
    noteApprovalSession: (ok) => { calls.notes.push(ok); },
    clearRecovery: (options) => { calls.recovery.push(options); },
    clearWait: () => { calls.wait += 1; },
  });
  const dispatch = (authenticated) => {
    sessionState = { authenticated };
    (sessionWindow.listeners["padiem:auth-state"] || [])
      .forEach((fn) => fn({ type: "padiem:auth-state", detail: { authenticated } }));
  };

  // 1) An authenticated session tears nothing down.
  dispatch(true);
  sessionResults.authenticated = {
    recoveryCalls: calls.recovery.length,
    waitCalls: calls.wait,
    note: calls.notes[calls.notes.length - 1],
  };

  // 2) Auth loss tears down the pending execute recovery and the wait timer,
  //    and hides the session-owned Claw surfaces.
  ids.clawAutomationList.children = ["stale"];
  ids.clawApprovedList.children = ["stale"];
  ids.clawApprovalActions.children = ["stale"];
  ids.clawApprovedDisclosure.open = true;
  dispatch(false);
  sessionResults.authLoss = {
    recoveryArgs: calls.recovery.slice(),
    waitCalls: calls.wait,
    note: calls.notes[calls.notes.length - 1],
    automationHidden: ids.clawAutomation.hidden === true,
    listCleared: ids.clawAutomationList.children.length === 0,
    runHistoryHidden: ids.clawRunHistory.hidden === true,
    approvedDisclosureClosed: ids.clawApprovedDisclosure.open === false,
    approvalActionsCleared: ids.clawApprovalActions.children.length === 0,
    workspaceView: ids.clawWorkspace.dataset.view,
    pdfRevokes: calls.pdfRevokes,
  };

  // 3) Without a published session the event detail decides the same way.
  sessionCtx.window.PadiemAuthSession.get = () => null;
  calls.recovery.length = 0;
  calls.wait = 0;
  dispatch(false);
  sessionResults.authLossByDetail = {
    recoveryArgs: calls.recovery.slice(),
    waitCalls: calls.wait,
  };
}

process.stdout.write(JSON.stringify({ conv: results, session: sessionResults }));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the attachment module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(STRICT + "\n" + _NODE, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(CONV), str(SESSION)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@lru_cache(maxsize=1)
def observations() -> dict:
    """모듈을 실제 실행해 얻은 한 번의 관찰(시험 파일 간 공유)."""

    return _run_harness()
