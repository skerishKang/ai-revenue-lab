"""B54 Claw generated-document action truthfulness (#2771).

A generated document exposes exactly one action: the bounded artifact download
through the route that already exists. The result surface must not offer a
second control labelled `문서 열기 / Open document`, because B54 ships no
in-browser document open/preview capability — the old control only repeated the
same download behind a label that promised something the product does not do.

Adjacent copy must promise only what is true: a ready document is downloadable,
not openable.

The static contracts read the shipped files. The behavioural contracts are
measured by a Node harness that executes the real `static/app.js`, against a DOM
stub built from the ids and locale keys `static/index.html` actually declares —
so a control that exists only in a test-side id list cannot make an assertion
pass, and a removed control really does become an unknown id at runtime.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
LOCALE_JS = ROOT / "static/locale.js"
APP_FACTORY = ROOT / "app/app_factory.py"

DOCUMENT_ACTION_ID = "clawResultDocx"
DOCUMENT_ACTION_KEY = "claw-result-docx"
SUCCESS_NOTE_KEY = "claw-artifact-ready"
ARTIFACT_ID = "doc_" + "a" * 32
SECOND_ARTIFACT_ID = "doc_" + "b" * 32

CARD_MARKER = '<article class="claw-result-card" id="clawResultCard" hidden>'
ACTIONS_MARKER = '<div class="claw-result-actions">'

# Copy that claims the document can be opened / previewed in the browser.
OPEN_CLAIM = re.compile(r"열기|열어|Open document|open document|Open or")
# Copy that truthfully describes the only thing the surface can do.
DOWNLOAD_CLAIM = re.compile(r"다운로드|download", re.IGNORECASE)


def _app_source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _index_source() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _locale_source() -> str:
    return LOCALE_JS.read_text(encoding="utf-8")


def _locale_table() -> dict[str, dict[str, str]]:
    """Parse the shipped KO/EN copy out of locale.js.

    The harness renders against THESE strings rather than a local duplicate, so
    shipped copy and asserted copy cannot drift apart.
    """
    source = _locale_source()
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    table = {
        "ko": {key: unescape(value) for key, value in pattern.findall(ko_part)},
        "en": {key: unescape(value) for key, value in pattern.findall(en_part)},
    }
    assert table["ko"] and table["en"]
    return table


def _card_block() -> str:
    index = _index_source()
    assert CARD_MARKER in index
    return index.split(CARD_MARKER, 1)[1].split("</article>", 1)[0]


def _actions_block() -> str:
    index = _index_source()
    assert ACTIONS_MARKER in index
    return index.split(ACTIONS_MARKER, 1)[1].split("</div>", 1)[0]


# ── static structural contracts ────────────────────────────────────────────


def test_result_surface_exposes_exactly_one_document_action() -> None:
    actions = _actions_block()
    assert actions.count("<button") == 1, actions
    assert actions.count(f'id="{DOCUMENT_ACTION_ID}"') == 1
    assert actions.count(f'data-locale-key="{DOCUMENT_ACTION_KEY}"') == 1
    # The single action is disabled until a real run produced an artifact.
    assert "disabled" in actions and 'aria-disabled="true"' in actions
    # The visible label is the download label: the one action binds exactly one
    # locale key, so no second claim can hide inside its own markup.
    button = actions.split("<button", 1)[1].split("</button>", 1)[0]
    assert re.findall(r'data-locale-key="([^"]+)"', button) == [DOCUMENT_ACTION_KEY]


def test_no_open_or_preview_control_remains_in_the_result_surface() -> None:
    card = _card_block()
    assert "clawResultOpen" not in card
    assert "claw-result-open" not in card
    # No element in the active result surface claims to open something.
    assert not re.search(r"open", card, re.IGNORECASE), card

    index = _index_source()
    assert "clawResultOpen" not in index
    assert "claw-result-open" not in index

    # The locale key is gone entirely, so no language can label this control.
    assert '"claw-result-open"' not in _locale_source()
    # And the removed control left no dead wiring behind.
    assert "clawResultOpen" not in _app_source()


def test_document_action_copy_says_download_in_both_languages() -> None:
    table = _locale_table()
    for language in ("ko", "en"):
        copy = table[language][DOCUMENT_ACTION_KEY]
        assert DOWNLOAD_CLAIM.search(copy), copy
        assert not OPEN_CLAIM.search(copy), copy


def test_artifact_ready_copy_promises_only_a_download() -> None:
    table = _locale_table()
    for language in ("ko", "en"):
        copy = table[language][SUCCESS_NOTE_KEY]
        assert DOWNLOAD_CLAIM.search(copy), copy
        assert not OPEN_CLAIM.search(copy), copy
    # The markup fallback (used when locale.js has not loaded) is the same claim.
    index = _index_source()
    fallback = index.split(f'data-locale-key="{SUCCESS_NOTE_KEY}">', 1)[1].split("</p>", 1)[0]
    assert DOWNLOAD_CLAIM.search(fallback), fallback
    assert not OPEN_CLAIM.search(fallback), fallback


def test_one_wiring_path_reuses_the_existing_bounded_route() -> None:
    app = _app_source()
    # Exactly one control is wired to the download, and the route is untouched.
    assert app.count(f'{DOCUMENT_ACTION_ID}.addEventListener("click"') == 1
    assert app.count("/api/claw/manual-intake/artifact/") == 1
    assert "/api/claw/manual-intake/artifact/${encodeURIComponent(documentId)}" in app
    # One authority for the action state, used by both the clear and render paths.
    assert app.count("function setClawDocumentAction(") == 1
    assert app.count("setClawDocumentAction(false)") == 1
    assert app.count("setClawDocumentAction(true,") == 1
    # The trusted callers are the result action, run-history re-download, and
    # Calendar's validated artifact link-back; all reuse this one route.
    callers = re.findall(r"(?<!function )\bdownloadClawArtifact\(", app)
    assert len(callers) == 3, callers
    assert 'padiem:calendar-open-link' in app
    table = _locale_table()
    for language in ("ko", "en"):
        assert not OPEN_CLAIM.search(table[language]["claw-runs-download"])


def test_no_document_open_route_was_added() -> None:
    factory = APP_FACTORY.read_text(encoding="utf-8")
    claw_paths = re.findall(r'Route\("(/api/claw[^"]*)"', factory)
    assert claw_paths
    offending = [
        path
        for path in claw_paths
        if "open" in path.lower() or "render" in path.lower() or re.search(r"(?<!pre)view", path.lower())
    ]
    assert offending == [], offending
    # The bounded artifact route is still the one registered document route.
    assert factory.count('"/api/claw/manual-intake/artifact/{document_id}"') == 1
    artifact_line = [line for line in factory.splitlines() if "/api/claw/manual-intake/artifact/{document_id}" in line][0]
    assert 'methods=["GET"]' in artifact_line


# ── behavioral proof via Node harness executing real app.js ─────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const realSetTimeout = setTimeout;
const APP = fs.readFileSync(process.argv[2], "utf8");
const COPY = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const INDEX = fs.readFileSync(process.argv[4], "utf8");
const ARTIFACT = process.argv[5];
const SECOND_ARTIFACT = process.argv[6];

// ── the DOM is built from what the SHIPPED markup declares ──
const declaredIds = [];
const declaredKeys = new Map();
{
  const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(INDEX)) !== null) {
    const attrs = m[2];
    const idMatch = /\sid="([^"]+)"/.exec(attrs);
    if (!idMatch) continue;
    if (declaredIds.indexOf(idMatch[1]) < 0) declaredIds.push(idMatch[1]);
    const keyMatch = /\sdata-locale-key="([^"]+)"/.exec(attrs);
    if (keyMatch && !declaredKeys.has(idMatch[1])) declaredKeys.set(idMatch[1], keyMatch[1]);
  }
}
const cardStart = INDEX.indexOf('id="clawResultCard"');
const cardEnd = INDEX.indexOf("</article>", cardStart);
const cardMarkup = cardStart < 0 ? "" : INDEX.slice(cardStart, cardEnd);
const cardActions = cardMarkup.match(/<button/g) || [];

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, value: "", children: [], listeners: {}, dataset: {},
    style: {}, scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    options: [], selectedIndex: 0, files: [], parentNode: null,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); if (k.indexOf("data-") === 0) el.dataset[k.slice(5).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = String(v); };
  el.getAttribute = (k) => (k in el ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); c.parentNode = el; return c; };
  el.prepend = (...cs) => cs.forEach((c) => { el.children.unshift(c); c.parentNode = el; });
  el.append = (...cs) => cs.forEach((c) => el.appendChild(c));
  el.replaceChildren = (...cs) => { el.children = []; cs.forEach((c) => el.appendChild(c)); };
  el.remove = () => { if (el.parentNode) el.parentNode.children = el.parentNode.children.filter((c) => c !== el); };
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.querySelector = (sel) => el.children.find((c) => c.className && c.className.includes(sel.replace(/^\./, ""))) || null;
  el.querySelectorAll = (sel) => (sel && sel.indexOf("claw-chip") >= 0 ? [] : el.children);
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
declaredIds.forEach((id) => add(id, "div"));

// Every element the markup binds to a locale key, so a language switch can be
// replayed exactly as locale.js applies it. The binding may sit on an element
// without an id (the action label lives on a span inside the button), so a
// key with no id gets its own node rather than being silently dropped.
const localeBound = [];
const keyElements = new Map();
{
  const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(INDEX)) !== null) {
    const keyMatch = /\sdata-locale-key="([^"]+)"/.exec(m[2]);
    if (!keyMatch) continue;
    const key = keyMatch[1];
    if (keyElements.has(key)) continue;
    const idMatch = /\sid="([^"]+)"/.exec(m[2]);
    const el = idMatch && byId[idMatch[1]] ? byId[idMatch[1]] : makeEl("span");
    el.dataset.localeKey = key;
    keyElements.set(key, el);
    localeBound.push(el);
  }
}
const actionLabel = keyElements.get("claw-result-docx");
const cardKeys = (cardMarkup.match(/data-locale-key="([^"]+)"/g) || []).map((s) => s.replace(/^data-locale-key="/, "").replace(/"$/, ""));

let lang = "ko";
function applyLocale(code) {
  lang = code;
  localeBound.forEach((el) => {
    const key = el.dataset.localeKey;
    if (key) el.textContent = COPY[code][key] || key;
  });
}

// Mirror the hidden/disabled starting state the markup declares.
byId.clawResultCard.hidden = true;
byId.clawStatus.hidden = true;
byId.clawWait.hidden = true;
byId.clawRetryHint.hidden = true;
byId.clawRetryBox.hidden = true;
byId.clawRetryButton.disabled = true;
byId.clawRunHistory.hidden = true;
byId.clawResultSuccessNote.hidden = true;

const shell = add("app-shell", "div");
shell.dataset = { state: "home" };
const accountContainer = add("sidebar-account", "div");
byId.clawChannel.options = [{ textContent: "KakaoTalk" }];
byId.clawChannel.value = "kakao";
byId.clawAction.options = [{ textContent: "quote" }];
byId.clawAction.value = "quote";

// Downloads are recorded where the browser would perform them: the anchor the
// app creates and clicks.
const anchors = [];
const doc = {
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => (sel === ".app-shell" ? shell : sel === ".sidebar-account" ? accountContainer : null),
  querySelectorAll: () => [],
  createElement: (tag) => {
    const el = makeEl(tag);
    if (tag === "a") el.click = () => anchors.push({ href: el.href, download: el.download });
    return el;
  },
  addEventListener() {},
};
byId.projectForm.querySelector = () => makeEl("div");

const requests = [];
function jsonResponse(status, obj) {
  return { ok: status >= 200 && status < 300, status, json: async () => obj };
}

let authenticated = true;
let executeCall = () => jsonResponse(200, { ok: true, result: { title: "quote", result_text: "ran", artifact: null } });

async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  requests.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : null });
  const u = String(url);
  if (u.startsWith("/api/auth/status")) return jsonResponse(200, { ready: true, authenticated, user: { name: "owner" }, history_ready: false, project_files_ready: false });
  if (u.startsWith("/api/auth/logout")) return jsonResponse(200, { ok: true });
  if (u.startsWith("/api/projects")) return jsonResponse(200, { projects: [] });
  if (u.startsWith("/api/conversations")) return jsonResponse(200, { conversations: [] });
  if (u.startsWith("/api/claw/inbox/")) return jsonResponse(200, { ok: true, kind: "tasks", items: [], limit: 20 });
  if (u.startsWith("/api/claw/memory")) return jsonResponse(200, { ok: true, memories: [] });
  if (u.startsWith("/api/claw/runs")) return jsonResponse(200, { ok: true, runs: [] });
  if (u.startsWith("/api/claw/manual-intake/artifact/")) {
    return { ok: true, status: 200, json: async () => ({}), blob: async () => ({ size: 3, type: "application/octet-stream" }) };
  }
  if (u.startsWith("/api/claw/manual-intake/execute")) return executeCall();
  return jsonResponse(200, {});
}

function localeText(key, variables) {
  const table = COPY[lang] || COPY.ko;
  const value = table[key] || COPY.ko[key] || key;
  if (!variables || typeof variables !== "object") return value;
  return Object.keys(variables).reduce((out, name) => out.split("{" + name + "}").join(String(variables[name])), value);
}

const winListeners = {};
const sandbox = {
  document: doc,
  fetch: fetchImpl,
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL() {}, revokeURL() {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  console,
  CustomEvent: class {},
  location: { href: "http://localhost/", assign() {} },
  addEventListener: (type, fn) => { (winListeners[type] = winListeners[type] || []).push(fn); },
  __padiemLocale: { text: (key, variables) => localeText(key, variables) },
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

(async () => {
  const checks = {};
  const fail = (m) => { console.log(JSON.stringify({ ok: false, error: m, checks, requests, anchors })); process.exit(0); };
  process.on("unhandledRejection", (e) => { console.log(JSON.stringify({ ok: false, error: "unhandledRejection " + String((e && e.stack) || e) })); process.exit(0); });
  process.on("uncaughtException", (e) => { console.log(JSON.stringify({ ok: false, error: "uncaughtException " + String((e && e.stack) || e) })); process.exit(0); });

  const flush = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => realSetTimeout(r, 0)); };
  const artifactGets = () => requests.filter((r) => r.url.indexOf("/api/claw/manual-intake/artifact/") === 0);
  const execPosts = () => requests.filter((r) => r.url === "/api/claw/manual-intake/execute" && r.method === "POST");
  const openClaim = (s) => /(?:열기|열어|Open document|open document|Open or)/.test(String(s));
  const downloadClaim = (s) => /(?:다운로드|download)/i.test(String(s));
  const descriptorHolders = () => Object.keys(byId).filter((id) => byId[id].dataset && byId[id].dataset.documentId);

  checks.ONE_DOCUMENT_ACTION_IN_MARKUP =
    cardActions.length === 1 &&
    cardMarkup.indexOf('id="clawResultDocx"') >= 0 &&
    !/open/i.test(cardMarkup);
  if (!checks.ONE_DOCUMENT_ACTION_IN_MARKUP) fail("ONE_DOCUMENT_ACTION_IN_MARKUP: " + cardMarkup);

  // The one action must carry a declared, resolvable download label, and no
  // locale-bound binding left in the result surface may be an "open" control.
  checks.ACTION_LABEL_IS_DECLARED_AND_DOWNLOAD_ONLY =
    !!actionLabel &&
    cardKeys.indexOf("claw-result-docx") >= 0 &&
    !cardKeys.some((k) => /open/i.test(k));
  if (!checks.ACTION_LABEL_IS_DECLARED_AND_DOWNLOAD_ONLY) fail("ACTION_LABEL_IS_DECLARED_AND_DOWNLOAD_ONLY: " + JSON.stringify(cardKeys));

  checks.BOTH_LANGUAGES_PROMISE_DOWNLOAD_ONLY = ["ko", "en"].every((code) => (
    downloadClaim(COPY[code]["claw-result-docx"]) && !openClaim(COPY[code]["claw-result-docx"]) &&
    downloadClaim(COPY[code]["claw-artifact-ready"]) && !openClaim(COPY[code]["claw-artifact-ready"])
  ));
  if (!checks.BOTH_LANGUAGES_PROMISE_DOWNLOAD_ONLY) fail("BOTH_LANGUAGES_PROMISE_DOWNLOAD_ONLY");

  applyLocale("ko");
  await flush();
  byId.clawNavButton.click();
  await flush();
  if (shell.dataset.state !== "claw") fail("CLAW_WORKSPACE_OPEN");
  byId.messageInput.value = "A업체 견적 요청 — 품목 20개";

  // ── case 1: a real run that produced a document ──
  executeCall = () => jsonResponse(200, {
    ok: true,
    result: { title: "quote", result_text: "ran", artifact: { document_id: ARTIFACT, filename: "quote.docx", byte_length: 4096 } },
  });
  byId.clawExecuteButton.click();
  await flush();

  checks.ARTIFACT_EXPOSES_SINGLE_DOWNLOAD_ACTION =
    descriptorHolders().length === 1 &&
    descriptorHolders()[0] === "clawResultDocx" &&
    byId.clawResultDocx.disabled === false &&
    byId.clawResultDocx.getAttribute("aria-disabled") === "false" &&
    byId.clawResultSuccessNote.hidden === false;
  if (!checks.ARTIFACT_EXPOSES_SINGLE_DOWNLOAD_ACTION) fail("ARTIFACT_EXPOSES_SINGLE_DOWNLOAD_ACTION: " + JSON.stringify(descriptorHolders()));

  const getsBeforeClick = artifactGets().length;
  byId.clawResultDocx.click();
  await flush();
  checks.SINGLE_CLICK_IS_ONE_BOUNDED_DOWNLOAD =
    artifactGets().length === getsBeforeClick + 1 &&
    artifactGets()[getsBeforeClick].url === "/api/claw/manual-intake/artifact/" + ARTIFACT &&
    anchors.length === 1 && anchors[0].download === "quote.docx" &&
    execPosts().length === 1;
  if (!checks.SINGLE_CLICK_IS_ONE_BOUNDED_DOWNLOAD) {
    fail("SINGLE_CLICK_IS_ONE_BOUNDED_DOWNLOAD: " + JSON.stringify({ gets: artifactGets(), anchors }));
  }

  // ── case 2: the action copy stays truthful across a language switch ──
  applyLocale("en");
  checks.LOCALE_SWITCH_KEEPS_TRUTHFUL_ACTION_COPY =
    actionLabel.textContent === COPY.en["claw-result-docx"] &&
    downloadClaim(actionLabel.textContent) &&
    !openClaim(actionLabel.textContent) &&
    byId.clawResultSuccessNote.textContent === COPY.en["claw-artifact-ready"] &&
    downloadClaim(byId.clawResultSuccessNote.textContent) &&
    !openClaim(byId.clawResultSuccessNote.textContent);
  if (!checks.LOCALE_SWITCH_KEEPS_TRUTHFUL_ACTION_COPY) {
    fail("LOCALE_SWITCH_KEEPS_TRUTHFUL_ACTION_COPY: " + JSON.stringify({ action: actionLabel.textContent, note: byId.clawResultSuccessNote.textContent }));
  }
  applyLocale("ko");
  checks.LOCALE_SWITCH_BACK_KEEPS_TRUTHFUL_ACTION_COPY =
    actionLabel.textContent === COPY.ko["claw-result-docx"] &&
    downloadClaim(actionLabel.textContent) &&
    !openClaim(actionLabel.textContent) &&
    !openClaim(byId.clawResultSuccessNote.textContent);
  if (!checks.LOCALE_SWITCH_BACK_KEEPS_TRUTHFUL_ACTION_COPY) fail("LOCALE_SWITCH_BACK_KEEPS_TRUTHFUL_ACTION_COPY");

  // ── case 3: a run without a document exposes no document action ──
  executeCall = () => jsonResponse(200, {
    ok: true,
    result: { title: "quote", result_text: "ran", artifact: null },
  });
  byId.clawExecuteButton.click();
  await flush();
  const getsAfterNoArtifact = artifactGets().length;
  checks.NO_ARTIFACT_RESULT_EXPOSES_NO_DOCUMENT_ACTION =
    byId.clawResultDocx.disabled === true &&
    byId.clawResultDocx.getAttribute("aria-disabled") === "true" &&
    descriptorHolders().length === 0 &&
    byId.clawResultSuccessNote.hidden === true;
  if (!checks.NO_ARTIFACT_RESULT_EXPOSES_NO_DOCUMENT_ACTION) {
    fail("NO_ARTIFACT_RESULT_EXPOSES_NO_DOCUMENT_ACTION: " + JSON.stringify({ holders: descriptorHolders(), noteHidden: byId.clawResultSuccessNote.hidden }));
  }
  byId.clawResultDocx.click();
  await flush();
  checks.CLEARED_ACTION_CANNOT_REPLAY_ARTIFACT =
    artifactGets().length === getsAfterNoArtifact && anchors.length === 1;
  if (!checks.CLEARED_ACTION_CANNOT_REPLAY_ARTIFACT) fail("CLEARED_ACTION_CANNOT_REPLAY_ARTIFACT");

  // ── case 4: the one action follows the CURRENT result, never a stale one ──
  executeCall = () => jsonResponse(200, {
    ok: true,
    result: { title: "order", result_text: "ran", artifact: { document_id: SECOND_ARTIFACT, filename: "order.docx", byte_length: 2048 } },
  });
  byId.clawExecuteButton.click();
  await flush();
  byId.clawResultDocx.click();
  await flush();
  const last = artifactGets()[artifactGets().length - 1];
  checks.ACTION_FOLLOWS_THE_CURRENT_RESULT =
    artifactGets().length === getsAfterNoArtifact + 1 &&
    last.url === "/api/claw/manual-intake/artifact/" + SECOND_ARTIFACT &&
    anchors.length === 2 && anchors[1].download === "order.docx";
  if (!checks.ACTION_FOLLOWS_THE_CURRENT_RESULT) {
    fail("ACTION_FOLLOWS_THE_CURRENT_RESULT: " + JSON.stringify({ gets: artifactGets(), anchors }));
  }
  checks.NO_DUPLICATE_DOWNLOAD_FOR_ONE_RESULT =
    artifactGets().length === anchors.length && execPosts().length === 3;
  if (!checks.NO_DUPLICATE_DOWNLOAD_FOR_ONE_RESULT) {
    fail("NO_DUPLICATE_DOWNLOAD_FOR_ONE_RESULT: " + JSON.stringify({ gets: artifactGets().length, anchors: anchors.length, posts: execPosts().length }));
  }

  // ── no new route, no server call, beyond what this surface already used ──
  const allowed = new Set([
    "/api/auth/status", "/api/projects", "/api/conversations", "/api/claw/runs",
    "/api/claw/memory", "/api/claw/inbox/tasks", "/api/claw/manual-intake/execute",
    "/api/claw/manual-intake/artifact/" + ARTIFACT,
    "/api/claw/manual-intake/artifact/" + SECOND_ARTIFACT,
  ]);
  const extra = Array.from(new Set(requests.map((r) => r.url.split("?")[0]))).filter((u) => !allowed.has(u));
  checks.NO_NEW_ROUTE_TOUCHED = extra.length === 0;
  if (!checks.NO_NEW_ROUTE_TOUCHED) fail("NO_NEW_ROUTE_TOUCHED: " + JSON.stringify(extra));

  console.log(JSON.stringify({ ok: true, checks, requests, anchors }));
  process.exit(0);
})().catch((e) => { console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) })); process.exit(0); });
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_b54_claw_result_action_harness.js"
    copy_path = ROOT / "tests" / "_b54_claw_result_action_copy.json"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    copy_path.write_text(json.dumps(_locale_table(), ensure_ascii=False), encoding="utf-8")
    try:
        result = subprocess.run(
            [
                node,
                str(harness_path),
                str(APP_JS),
                str(copy_path),
                str(INDEX_HTML),
                ARTIFACT_ID,
                SECOND_ARTIFACT_ID,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        harness_path.unlink(missing_ok=True)
        copy_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, f"behavioral harness failed: {payload}"


def test_behavioral_single_truthful_document_action() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    checks = payload["checks"]
    for name in (
        "ONE_DOCUMENT_ACTION_IN_MARKUP",
        "ACTION_LABEL_IS_DECLARED_AND_DOWNLOAD_ONLY",
        "BOTH_LANGUAGES_PROMISE_DOWNLOAD_ONLY",
        "ARTIFACT_EXPOSES_SINGLE_DOWNLOAD_ACTION",
        "SINGLE_CLICK_IS_ONE_BOUNDED_DOWNLOAD",
        "LOCALE_SWITCH_KEEPS_TRUTHFUL_ACTION_COPY",
        "LOCALE_SWITCH_BACK_KEEPS_TRUTHFUL_ACTION_COPY",
        "NO_ARTIFACT_RESULT_EXPOSES_NO_DOCUMENT_ACTION",
        "CLEARED_ACTION_CANNOT_REPLAY_ARTIFACT",
        "ACTION_FOLLOWS_THE_CURRENT_RESULT",
        "NO_DUPLICATE_DOWNLOAD_FOR_ONE_RESULT",
        "NO_NEW_ROUTE_TOUCHED",
    ):
        assert checks.get(name) is True, name
    # One download per user click, and every download used the bounded route.
    assert len(payload["anchors"]) == 2, payload["anchors"]
    for anchor in payload["anchors"]:
        assert anchor["href"] == "blob:x"
    # The removed control is not merely hidden: the app never looks it up, so
    # nothing in the result surface can claim to open a document.
    assert "clawResultOpen" not in _app_source()


if __name__ == "__main__":
    test_result_surface_exposes_exactly_one_document_action()
    test_no_open_or_preview_control_remains_in_the_result_surface()
    test_document_action_copy_says_download_in_both_languages()
    test_artifact_ready_copy_promises_only_a_download()
    test_one_wiring_path_reuses_the_existing_bounded_route()
    test_no_document_open_route_was_added()
    test_behavioral_harness_passes()
    test_behavioral_single_truthful_document_action()
    print("B54_CLAW_RESULT_ACTION_TRUTHFUL_TESTS=PASS")
