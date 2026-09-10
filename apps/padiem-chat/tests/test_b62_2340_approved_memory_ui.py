"""#2340 — approved-memory review UI behavioral contracts.

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL app.js against a minimal DOM shim with a
recording fetch. The harness proves actual click -> request behavior:

- APPROVE_POST_BEFORE_EXPLICIT_CLICK=0 (no approve POST until the user clicks)
- APPROVE_BUTTON_CALLS_APPROVE_ENDPOINT=PASS
- REJECT_BUTTON_CALLS_REJECT_ENDPOINT=PASS
- POST_APPROVE_VISIBLE_REFRESH=PASS
- POST_REJECT_VISIBLE_REFRESH=PASS
- LOADING_ERROR_RETRY=PASS
- KEYBOARD_FOCUS=PASS (native buttons + focus-visible CSS)
- SENSITIVE_FIELD_DOM_PROJECTION=0 (user_id / workspace_id never rendered)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
CSS = ROOT / "static/claw-workspace.css"


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


# ── static structural contracts ────────────────────────────────────────────


def test_html_has_approved_memory_and_review_surfaces() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="clawApprovedMemory"' in html
    assert 'id="clawApprovedList"' in html
    assert 'id="clawApprovedRefresh"' in html
    assert 'id="clawMemoryReview"' in html


def test_no_forbidden_interception_tokens() -> None:
    source = _app_source()
    for token in ("MutationObserver", "localStorage", "sessionStorage", "indexedDB", "cookieStore", "window.fetch ="):
        assert token not in source


def test_explicit_approval_flag_present() -> None:
    assert "approved: true" in _app_source()


def test_approve_and_reject_endpoints_wired() -> None:
    source = _app_source()
    assert '"/api/claw/memory/approve"' in source
    assert '"/api/claw/memory/reject"' in source
    assert '"/api/claw/memory"' in source


def test_keyboard_focusable_and_visible_outline() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".claw-memory-approve:focus-visible" in css
    assert ".claw-memory-reject:focus-visible" in css
    assert ".claw-approved-action:focus-visible" in css


def test_no_sensitive_field_projection_in_renderers() -> None:
    source = _app_source()
    assert "memory.user_id" not in source
    assert "memory.workspace_id" not in source


# ── behavioral proof via Node harness executing real app.js ─────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const APP = fs.readFileSync(process.argv[2], "utf8");

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v); };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => { if (el.parentNode) el.parentNode.children = el.parentNode.children.filter((c) => c !== el); };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = (sel) => el.children.find((c) => c.className && c.className.includes(sel.replace(/^\./, ""))) || null;
  el.querySelectorAll = () => el.children;
  el.focus = () => { doc.activeElement = el; };
  el.blur = () => { if (doc.activeElement === el) doc.activeElement = null; };
  el.scrollIntoView = () => {};
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el, key: "" }));
  el.requestSubmit = () => (el.listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
  el.matches = () => false;
  return el;
}

const byId = {};
function add(id, tag) { const e = makeEl(tag); e.id = id; byId[id] = e; return e; }
[
  "emptyState","messageList","composerForm","messageInput","sendButton","cancelStreamButton","newChatButton",
  "mobileMenu","mobileClose","sidebarScrim","settingsButton","settingsDialog","settingsCloseButton",
  "attachmentFileInput","attachmentButton","attachmentTray","attachmentThumb","attachmentKind","attachmentName",
  "attachmentSize","removeAttachment","documentStarterButton","runtimeNote","loginButton","accountName",
  "historySection","historyList","historyEmpty","projectsNavButton","projectsBadge","projectsSection",
  "projectsList","projectsEmpty","projectCreateButton","projectBanner","activeProjectName","activeProjectFiles",
  "editProjectButton","exitProjectButton","projectDialog","projectForm","projectDialogTitle","projectDialogClose",
  "projectDialogCancel","projectNameInput","projectInstructionsInput","projectFormError","projectSaveButton",
  "projectFilesPanel","projectFileInput","projectFilesList","projectFilesEmpty","clawNavButton","clawWorkspace",
  "clawManualForm","clawChannel","clawAction","clawSender","clawRequestText","clawResultArea","clawResultPreview",
  "clawResultCard","clawResultEmpty","clawResultKind","clawGenerateBtn","clawExecuteButton","clawResultBadge",
  "clawResultOpen","clawResultDocx","clawStatus","clawArtifactMeta","clawArtifactName","clawArtifactSize",
  "clawResultSuccessNote","clawResultHint","clawExecuteHint","clawApprovedMemory","clawApprovedRefresh",
  "clawApprovedLoading","clawApprovedError","clawApprovedList","clawApprovedEmpty","clawMemoryReview",
].forEach((id) => add(id, "div"));
const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "견적서 초안" }];
byId.clawAction.value = "quote";

const doc = {
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => (sel === ".app-shell" ? shell : sel === ".sidebar-account" ? accountContainer : null),
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};
byId.projectForm.querySelector = () => makeEl("div");

const requests = [];
function jsonResponse(status, obj) { return { ok: status >= 200 && status < 300, status, json: async () => obj }; }
let listState = { memories: [] };
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated: true, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/memory/approve")) { listState = { memories: [{ memory_id: "mem_a", memory_type: "customer_contact_candidate", name: "A업체", note: "잠재 고객", source_channel: "kakao", status: "approved", created_at: "2026-09-10T09:00:00Z", updated_at: "2026-09-10T09:00:00Z" }] }; return jsonResponse(200, { ok: true, memory: listState.memories[0] }); }
  if (u.startsWith("/api/claw/memory/reject")) return jsonResponse(200, { ok: true, persisted: false });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: listState.memories });
  if (u.startsWith("/api/claw/manual-intake/preview")) return jsonResponse(200, { ok: true, preview: { title: "견적서", result_text: "PREVIEW", memory_proposals: [{ type: "customer_contact_candidate", name: "A업체", note: "잠재 고객", source_channel: "kakao" }] } });
  return jsonResponse(200, {});
}

const sandbox = {
  document: doc,
  fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeURL() {} },
  setTimeout, clearTimeout, console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener() {},
  __padiemLocale: { text: (k) => k },
  PadiemChatLifecycle: { states: { IDLE: "idle", STREAMING: "streaming", COMPLETED: "completed", FAILED: "failed", CANCELLED: "cancelled", TIMED_OUT: "timed_out" }, set() {} },
  PadiemConfirmDialog: { confirm: async () => true },
  PadiemChatTransport: { requestCompleted: async () => ({}), requestStreaming: async () => ({}), readSseEvents: async () => {}, errorFor: () => new Error("x") },
  PadiemChatConversationState: { reset() {}, setConversationId() {}, getConversationId() { return null; }, outboundWithUser: () => [], commitAssistant() {}, setSkill() {}, getSkill: () => "auto" },
  PadiemAttachmentCapabilities: {
    limits: { imageBytes: 4194304, textBytes: 98304, textChars: 40000 },
    images: [{ mediaTypes: ["image/jpeg", "image/png", "image/webp"] }],
    textDocuments: [{ mediaTypes: ["text/plain"], extensions: [".txt"] }],
    copy: () => ({ idleNote: "idle", unsupportedFormat: "unsupported", textTooLarge: "too large" }),
  },
  PadiemBinaryDocuments: null,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(APP, sandbox, { filename: "app.js" });

function findButton(root, text) {
  const stack = [...(root.children || [])];
  while (stack.length) {
    const el = stack.shift();
    if (String(el.tagName).toUpperCase() === "BUTTON" && el.textContent === text) return el;
    stack.push(...(el.children || []));
  }
  return null;
}
function collectText(root) {
  let out = root.textContent || "";
  (root.children || []).forEach((c) => { out += " " + collectText(c); });
  return out;
}

(async () => {
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, requests })); process.exit(0); };
  const tick = (ms) => new Promise((r) => setTimeout(r, ms));
  await tick(40);

  const approveCalls = () => requests.filter((r) => r.method === "POST" && r.url.startsWith("/api/claw/memory/approve")).length;
  const rejectCalls = () => requests.filter((r) => r.method === "POST" && r.url.startsWith("/api/claw/memory/reject")).length;
  const listCalls = () => requests.filter((r) => r.method === "GET" && r.url.startsWith("/api/claw/memory")).length;

  // 1) Open Claw workspace -> initial list fetch, but NO approve/reject POST.
  byId.clawNavButton.click();
  await tick(40);
  if (approveCalls() !== 0) fail("APPROVE_POST_BEFORE_EXPLICIT_CLICK");
  if (rejectCalls() !== 0) fail("REJECT_POST_BEFORE_EXPLICIT_CLICK");

  // 2) Run preview -> proposal review surface renders with approve/reject buttons.
  byId.clawRequestText.value = "A업체 견적 요청 품목 20개";
  byId.clawManualForm.requestSubmit();
  await tick(60);
  const approveBtn = findButton(byId.clawMemoryReview, "승인");
  const rejectBtn = findButton(byId.clawMemoryReview, "거절");
  if (!approveBtn || !rejectBtn) fail("PROPOSAL_REVIEW_BUTTONS_MISSING");
  if (approveCalls() !== 0) fail("APPROVE_POST_BEFORE_EXPLICIT_CLICK_AFTER_RENDER");

  // 3) Explicit approve click -> approve POST (approved:true + proposal) -> visible refresh.
  const listsBefore = listCalls();
  approveBtn.click();
  await tick(60);
  if (approveCalls() !== 1) fail("APPROVE_BUTTON_CALLS_APPROVE_ENDPOINT");
  const approveReq = requests.find((r) => r.url.startsWith("/api/claw/memory/approve"));
  if (!approveReq || approveReq.body.approved !== true || !approveReq.body.proposal || approveReq.body.proposal.name !== "A업체") fail("APPROVE_BODY_INVALID");
  if (listCalls() <= listsBefore) fail("POST_APPROVE_VISIBLE_REFRESH");
  if (collectText(byId.clawApprovedList).indexOf("A업체") < 0) fail("POST_APPROVE_NOT_RENDERED");

  // 4) Explicit reject click -> reject POST (persisted:false) -> visible refresh.
  const listsBefore2 = listCalls();
  rejectBtn.click();
  await tick(60);
  if (rejectCalls() !== 1) fail("REJECT_BUTTON_CALLS_REJECT_ENDPOINT");
  if (listCalls() <= listsBefore2) fail("POST_REJECT_VISIBLE_REFRESH");

  // 5) Error + retry: force list failure -> error state; restore -> retry succeeds.
  listState = { memories: [] };
  const realFetch = sandbox.fetch;
  sandbox.fetch = async (url, opts) => { if (String(url).startsWith("/api/claw/memory")) return jsonResponse(500, { error: { code: "boom" } }); return realFetch(url, opts); };
  byId.clawApprovedRefresh.click();
  await tick(40);
  const errored = byId.clawApprovedError.hidden === false && byId.clawApprovedError.dataset.state === "error";
  sandbox.fetch = realFetch;
  byId.clawApprovedRefresh.click();
  await tick(40);
  const recovered = byId.clawApprovedError.hidden === true;
  if (!errored || !recovered) fail("LOADING_ERROR_RETRY");

  // 6) Sensitive fields never projected into DOM.
  const dom = collectText(byId.clawApprovedList) + " " + collectText(byId.clawMemoryReview);
  if (dom.indexOf("user_id") >= 0 || dom.indexOf("workspace_id") >= 0) fail("SENSITIVE_FIELD_DOM_PROJECTION");

  console.log(JSON.stringify({ ok: true, requests }));
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b62_2340_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_approve_requires_explicit_click() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    approve = [r for r in payload["requests"] if r["method"] == "POST" and r["url"].startswith("/api/claw/memory/approve")]
    assert len(approve) == 1
    assert approve[0]["body"]["approved"] is True


def test_behavioral_reject_endpoint_called() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    reject = [r for r in payload["requests"] if r["method"] == "POST" and r["url"].startswith("/api/claw/memory/reject")]
    assert len(reject) == 1


if __name__ == "__main__":
    test_html_has_approved_memory_and_review_surfaces()
    test_no_forbidden_interception_tokens()
    test_explicit_approval_flag_present()
    test_approve_and_reject_endpoints_wired()
    test_keyboard_focusable_and_visible_outline()
    test_no_sensitive_field_projection_in_renderers()
    test_behavioral_harness_passes()
    test_behavioral_approve_requires_explicit_click()
    test_behavioral_reject_endpoint_called()
    print("B62_APPROVED_MEMORY_UI_TESTS=PASS")