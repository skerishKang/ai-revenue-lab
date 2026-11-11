"""#7502 — Util text tools can take their body text from the owner's own PC.

The three council-family Util tools (축사·인사말, SNS 홍보, 회의정리) get one
"내 PC에서 가져오기" action beside the body field. It reuses #6012 exactly: the
same shared picker (static/pc-file-exchange.js, opened in its import half with
an accept list), and the existing /api/pc/reference read that already extracts
.docx/.hwpx text. No second picker, no new server route, no new exchange format.

Pinned here:
- the filled field is chosen from the manifest, not from a tool name,
- the action exists in both form mode and conversational mode,
- no linked PC shows the existing connect guidance (KR/EN in locale.js),
- a picked file fills the field, an unsupported suffix is refused by name,
- an existing value is only replaced after the owner confirms,
- every request is a fake: no real user PC is contacted by the tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from css_rules import find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOOLS_JS = (STATIC / "util-tools.js").read_text(encoding="utf-8")
CHAT_MODE_JS = (STATIC / "util-chat-mode.js").read_text(encoding="utf-8")
MANIFEST_JS = (STATIC / "util-manifest.js").read_text(encoding="utf-8")
LOCALE_JS = (STATIC / "locale.js").read_text(encoding="utf-8")
TOOLS_CSS = (STATIC / "util-tools.css").read_text(encoding="utf-8")
CHAT_CSS = (STATIC / "util-chat-mode.css").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")

LOCALE_KEYS = (
    "util-pc-import",
    "util-pc-import-note",
    "util-pc-import-connect",
    "util-pc-import-unsupported",
    "util-pc-import-failed",
    "util-pc-import-replace",
)


# ── static boundary ────────────────────────────────────────────────────────


def test_app_js_stays_empty_and_the_shared_picker_is_reused() -> None:
    for token in ("util-pc-import", "PadiemPcFileExchange", "/api/pc/reference"):
        assert token not in APP_JS, token
    # One picker: #6012's shared part, opened for import.
    assert 'const PC_EXCHANGE_SCRIPT = "./pc-file-exchange.js";' in TOOLS_JS
    assert "script.src = PC_EXCHANGE_SCRIPT;" in TOOLS_JS
    assert 'mode: "import"' in TOOLS_JS
    assert "onSelect" in TOOLS_JS
    # The existing text read, not a new endpoint and not the binary lane.
    assert 'const PC_REFERENCE = "/api/pc/reference";' in TOOLS_JS
    assert "body: JSON.stringify({ file_id: picked.fileId })" in TOOLS_JS
    assert "/api/pc/browse" not in TOOLS_JS
    assert "/api/pc/fetch" not in TOOLS_JS
    assert "/api/pc/save" not in TOOLS_JS
    # The formats this lane takes, and the confirmation before replacing text.
    assert 'const PC_IMPORT_ACCEPT = Object.freeze([".txt", ".md", ".docx", ".hwpx"]);' in TOOLS_JS
    assert "window.confirm(PC_COPY.replace())" in TOOLS_JS
    # The no-PC guidance points at the existing Connectors computer card.
    assert 'document.getElementById("connectorsNavButton")' in TOOLS_JS
    assert 'document.getElementById("connectorComputerCard")' in TOOLS_JS


def test_the_filled_field_is_declared_by_the_manifest() -> None:
    assert "function pcImportField(id)" in MANIFEST_JS
    assert "pcImportField: pcImportField," in MANIFEST_JS
    assert "pcImportField(toolId)" in TOOLS_JS
    # The screen marks the field the manifest chose; no tool name is consulted.
    assert "state.importFieldKey === spec.key" in TOOLS_JS
    assert "importField.key" in TOOLS_JS


def test_new_copy_exists_in_both_shipped_languages() -> None:
    # Two locale tables (ko, en): every new key appears once in each.
    for key in LOCALE_KEYS:
        assert LOCALE_JS.count(f'"{key}":') == 2, key
    assert "util-pc-import-note" in TOOLS_JS and "util-pc-import-connect" in TOOLS_JS


def test_chat_mode_places_the_same_action() -> None:
    assert "opts.pcImport" in CHAT_MODE_JS
    assert 'el("button", "util-chat-choice util-chat-pc-import"' in CHAT_MODE_JS
    assert 'setAttribute("data-util-chat-pc-import", "")' in CHAT_MODE_JS
    assert "outcome.needPc" in CHAT_MODE_JS
    assert "values[fieldKey] = outcome.text;" in CHAT_MODE_JS
    assert "window.confirm(pcImport.confirmReplace || \"\")" in CHAT_MODE_JS
    assert "pcImport: importField ? {" in TOOLS_JS


def test_the_sheets_use_tokens_only() -> None:
    rules = parse_rules(TOOLS_CSS)
    pick = find_rules_with_selector(rules, ".util-pc-import")
    assert pick
    assert "var(--line)" in TOOLS_CSS and "var(--primary-focus)" in TOOLS_CSS
    note = find_rules_with_selector(parse_rules(CHAT_CSS), ".util-chat-pc-note")
    assert note
    for sheet in (TOOLS_CSS, CHAT_CSS):
        body = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
        assert "#" not in body.replace("#fff", "")  # no raw colours beyond the shared white
        assert "var(--line," not in body
        assert "var(--focus-ring," not in body


# ── behaviour: the real modules in a Node DOM shim, fake PC answers ────────

HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const [manifestFile, markdownFile, contractFile, chatModeFile, toolsFile] = process.argv.slice(2);

const registry = [];
const opened = [];
const requests = [];
let pairings = [];
let referenceText = "가져온 회의 본문입니다.";
let confirmAnswer = false;
let connectorOpened = 0;

function El(tag) {
  return {
    tagName: String(tag || "div").toUpperCase(),
    id: "", className: "", type: "", name: "", value: "", textContent: "",
    placeholder: "", rows: 0, required: false, disabled: false, hidden: false,
    noValidate: false, scrollTop: 0, scrollHeight: 100,
    children: [], attrs: {}, dataset: {}, listeners: {}, parentElement: null,
    get classList() {
      const self = this;
      return {
        add: (...c) => { self.className = [...new Set([...String(self.className).split(/\s+/).filter(Boolean), ...c])].join(" "); },
        remove: (...c) => { const d = new Set(c); self.className = String(self.className).split(/\s+/).filter((x) => x && !d.has(x)).join(" "); },
        toggle: (c, on) => { if (on) self.classList.add(c); else self.classList.remove(c); },
        contains: (c) => String(self.className).split(/\s+/).includes(c),
      };
    },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) {
      this.attrs[k] = String(v);
      if (k === "id") this.id = String(v);
      if (k.startsWith("data-")) {
        const camel = k.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
        this.dataset[camel] = String(v);
      }
    },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    click() { (this.listeners.click || []).slice().forEach((fn) => fn({ target: this, preventDefault() {}, stopPropagation() {} })); },
    closest(sel) { let cur = this; while (cur) { if (matches(cur, sel)) return cur; cur = cur.parentElement; } return null; },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { return findAll(this, sel); },
  };
}

function matches(el, sel) {
  if (!sel || !el || el.tagName === "#TEXT") return false;
  if (sel.startsWith(".")) return String(el.className || "").split(/\s+/).includes(sel.slice(1));
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  const attr = /^\[([a-zA-Z0-9_-]+)(?:="([^"]*)")?\]$/.exec(sel);
  if (attr) {
    if (attr[1] === "name") return Boolean(el.name) && (attr[2] === undefined || el.name === attr[2]);
    const val = el.getAttribute(attr[1]);
    return val !== null && (attr[2] === undefined || val === attr[2]);
  }
  return el.tagName === sel.toUpperCase();
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function fullText(el) { let out = ""; walk(el, (e) => { if (e.tagName === "#TEXT" || (!e.children.length && e.textContent)) out += e.textContent + " "; }); return out.trim(); }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }
function jsonResponse(body, status) {
  return Promise.resolve({
    ok: (status || 200) === 200, status: status || 200,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
  });
}

const connectorsButton = El("button");
connectorsButton.id = "connectorsNavButton";
connectorsButton.addEventListener("click", () => { connectorOpened += 1; });
const computerCard = El("div");
computerCard.id = "connectorComputerCard";

const document = {
  readyState: "complete",
  documentElement: { lang: "ko" },
  head: El("head"),
  createElement(tag) { const n = El(tag); registry.push(n); return n; },
  createTextNode(t) { const n = El("#text"); n.textContent = String(t); return n; },
  getElementById(id) {
    if (id === "connectorsNavButton") return connectorsButton;
    if (id === "connectorComputerCard") return computerCard;
    const hits = registry.filter((e) => e.id === id);
    return hits.length ? hits[hits.length - 1] : null;
  },
  querySelector() { return null; },
  addEventListener() {},
};

const windowObj = {
  fetch(url, init) {
    const body = JSON.parse((init && init.body) || "{}");
    requests.push({ url: String(url), body: body });
    if (String(url) === "/api/pc/pairings") return jsonResponse({ ok: true, links: pairings });
    if (String(url) === "/api/pc/reference") return jsonResponse({ ok: true, name: "회의록.docx", text: referenceText });
    return jsonResponse({ answer: "초안" });
  },
  addEventListener() {},
  PadiemAuthSession: { get: () => ({ authenticated: true }) },
  PadiemTierSelection: { get: () => "free" },
  PadiemAnswerCopy: { copyText: () => Promise.resolve(true) },
  confirm: (message) => { windowObj.lastConfirm = message; return confirmAnswer; },
  PadiemPcFileExchange: {
    open(settings) {
      opened.push(settings);
      return { close() {} };
    },
  },
};

const ctx = {
  document,
  window: windowObj,
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
  Event: class { constructor(type) { this.type = type; } },
};
ctx.globalThis = ctx;
vm.createContext(ctx);
[manifestFile, markdownFile, contractFile, chatModeFile, toolsFile].forEach((file) => {
  vm.runInContext(fs.readFileSync(file, "utf8"), ctx, { filename: file });
});

const manifest = windowObj.PadiemUtilManifest;
const api = windowObj.PadiemUtilTools;
const result = { ok: true, checks: {}, opened: opened, requests: requests };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }

function mountForm(toolId) {
  const host = El("div");
  host.className = "util-tool-body";
  api.mount(toolId, host);
  return host;
}

(async () => {
  const targets = { speech: "style", sns: "content", meeting: "content" };
  Object.keys(targets).forEach((toolId) => {
    const host = mountForm(toolId);
    const button = find(host, ".util-pc-import");
    check("button_" + toolId, Boolean(button));
    check("target_" + toolId, Boolean(button) && button.getAttribute("data-util-pc-import") === targets[toolId]);
    check("label_" + toolId, Boolean(button) && button.textContent === "내 PC에서 가져오기");
    check("only_one_" + toolId, findAll(host, ".util-pc-import").length === 1);
  });

  pairings = [];
  let host = mountForm("meeting");
  let button = find(host, ".util-pc-import");
  button.click();
  await tick(); await tick();
  check("no_pc_opens_nothing", opened.length === 0);
  const note = find(host, ".util-pc-note");
  check("no_pc_note_visible", Boolean(note) && note.hidden === false);
  check("no_pc_note_sentence", fullText(note).indexOf("컴퓨터를 연결하면") >= 0);
  const connect = find(note, ".util-pc-connect");
  connect.click();
  check("no_pc_connect_action", connectorOpened === 1);

  pairings = [{ state: "active", link_id: "l1" }];
  host = mountForm("meeting");
  button = find(host, ".util-pc-import");
  button.click();
  await tick(); await tick();
  check("picker_opened", opened.length === 1);
  const settings = opened[0];
  check("picker_import_mode", settings.mode === "import");
  check("picker_accept", JSON.stringify(settings.accept) === JSON.stringify([".txt", ".md", ".docx", ".hwpx"]));

  const before = requests.length;
  settings.onSelect({ name: "회의록.docx", fileId: "dispatch-1", kind: "file" });
  await tick(); await tick();
  const read = requests.slice(before).find((r) => r.url === "/api/pc/reference");
  check("read_uses_reference", Boolean(read));
  check("read_sends_file_id", Boolean(read) && read.body.file_id === "dispatch-1");
  const content = find(host, "#utilToolField-content");
  check("field_filled", Boolean(content) && content.value === referenceText);
  check("note_hidden_after_fill", find(host, ".util-pc-note").hidden === true);

  host = mountForm("sns");
  button = find(host, ".util-pc-import");
  button.click();
  await tick(); await tick();
  const beforeUnsupported = requests.length;
  opened[opened.length - 1].onSelect({ name: "보고서.pdf", fileId: "dispatch-2", kind: "file" });
  await tick(); await tick();
  check("unsupported_no_read", requests.slice(beforeUnsupported).every((r) => r.url !== "/api/pc/reference"));
  const snsContent = find(host, "#utilToolField-content");
  check("unsupported_field_untouched", Boolean(snsContent) && snsContent.value === "");
  check("unsupported_sentence", fullText(host).indexOf("텍스트로 읽을 수 있는 파일만") >= 0);

  host = mountForm("meeting");
  const contentField = find(host, "#utilToolField-content");
  contentField.value = "이미 적어 둔 내용";
  button = find(host, ".util-pc-import");
  button.click();
  await tick(); await tick();
  confirmAnswer = false;
  opened[opened.length - 1].onSelect({ name: "회의록.txt", fileId: "dispatch-3", kind: "text" });
  await tick(); await tick();
  check("replace_declined_keeps_text", contentField.value === "이미 적어 둔 내용");
  button.click();
  await tick(); await tick();
  confirmAnswer = true;
  opened[opened.length - 1].onSelect({ name: "회의록.txt", fileId: "dispatch-4", kind: "text" });
  await tick(); await tick();
  check("replace_confirmed_fills", contentField.value === referenceText);
  check("replace_asks_first", typeof windowObj.lastConfirm === "string" && windowObj.lastConfirm.indexOf("바꿀까요") >= 0);

  pairings = [{ state: "active", link_id: "l1" }];
  host = mountForm("meeting");
  const chatTab = find(host, '[data-util-mode="chat"]');
  chatTab.click();
  const chatButton = find(host, ".util-chat-pc-import");
  check("chat_button", Boolean(chatButton));
  check("chat_open_form_label", find(host, ".util-chat-open-form").textContent === "폼으로 열기");
  check("chat_send_label", find(host, ".util-chat-send").textContent === "보내기");
  chatButton.click();
  await tick(); await tick();
  check("chat_picker_opened", opened.length === 5);
  opened[opened.length - 1].onSelect({ name: "회의록.md", fileId: "dispatch-5", kind: "text" });
  await tick(); await tick();
  check("chat_fills_form_field", find(host, "#utilToolField-content").value === referenceText);
  check("chat_summary_has_text", fullText(host).indexOf("가져온 회의 본문") >= 0);

  pairings = [];
  host = mountForm("speech");
  find(host, '[data-util-mode="chat"]').click();
  const beforeNoPc = opened.length;
  find(host, ".util-chat-pc-import").click();
  await tick(); await tick();
  check("chat_no_pc_no_picker", opened.length === beforeNoPc);
  const chatNote = find(host, ".util-chat-pc-note");
  check("chat_no_pc_note", Boolean(chatNote) && chatNote.hidden === false
    && fullText(chatNote).indexOf("컴퓨터를 연결하면") >= 0);

  result.text = fullText(host);
  console.log(JSON.stringify(result));
})();
'''


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util PC import harness"
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "util_pc_import_harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "util-manifest.js"), str(STATIC / "util-tools-markdown.js"),
             str(STATIC / "util-tools-contract.js"), str(STATIC / "util-chat-mode.js"),
             str(STATIC / "util-tools.js")],
            capture_output=True, text=True, encoding="utf-8", env=dict(os.environ), check=False,
        )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_behaviour_form_and_chat_import_from_pc() -> None:
    result = _run_harness()
    assert result["ok"] is True, {k: v for k, v in result["checks"].items() if not v}
    for name in ("button_speech", "button_sns", "button_meeting", "target_speech",
                 "no_pc_note_visible", "no_pc_connect_action", "picker_import_mode",
                 "picker_accept", "read_uses_reference", "field_filled",
                 "unsupported_no_read", "unsupported_field_untouched",
                 "replace_declined_keeps_text", "replace_confirmed_fills",
                 "chat_button", "chat_open_form_label", "chat_send_label",
                 "chat_fills_form_field", "chat_no_pc_note"):
        assert result["checks"].get(name) is True, name
    # One fake picker per open, and every read is the fake reference answer.
    assert all(r["url"] != "/api/pc/fetch" for r in result["requests"])
