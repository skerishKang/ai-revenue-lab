"""#5608: the util page must render, and reopened drafts must keep their body.

Two production defects were confirmed on chat.padiem.net before this change:

1. VISIBILITY -- ``#utilView`` was nested inside ``#clawWorkspace``, and
   ``showUtil()`` set ``hidden = true`` on every ``.claw-workspace`` except
   ``#utilView``. Because the ancestor itself is the one element that owns the
   panel, the util page measured 0x0 and Speech/SNS/Meeting were unreachable.
   The panel is now a top-level main-panel view owned by its own
   ``data-state="util"``, exactly like Calendar/Connectors/Automation/Meeting.

2. SPEECH REOPEN -- the saved-list handler wrote ``"[저장된 파일: <name>]"``
   into ``#utilSpeechOutput`` instead of the stored body, so reopening a
   congratulation and clicking Save again overwrote the draft with the
   filename. The reader now uses the same detail contract as the Meeting
   reader (#5631): ``data.file.content``.

Static assertions pin both contracts; the Node harness executes the REAL
util-menu.js against a minimal DOM shim with a recording fetch and proves the
actual click -> request -> reopen behavior, including that the body arrives
back byte-for-byte.
"""

from __future__ import annotations

from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
import json
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static/index.html"
UTIL_MENU_JS = ROOT / "static/util-menu.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"
APP_JS = ROOT / "static/app.js"

DRAFT_BODY = (
    "존경하는 고객 여러분, 2026 Padiem Community Sharing Party에 참석해 주셔서 감사합니다."
    "\n\n[E2E 편집 마커 20261023]"
)


# --------------------------------------------------------------------------
# static structural contracts
# --------------------------------------------------------------------------


class _AncestorTracker(HTMLParser):
    """Records the open-tag chain that surrounds id="utilView"."""

    VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.util_view_parents: list[tuple[str, str | None]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if data.get("id") == "utilView" and self.util_view_parents is None:
            self.util_view_parents = [(t, a.get("id")) for t, a in self.stack]
        if tag not in self.VOID:
            self.stack.append((tag, data))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index]
                return


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_util_view_is_a_top_level_main_panel_view() -> None:
    tracker = _AncestorTracker()
    tracker.feed(_html())
    assert tracker.util_view_parents is not None, "#utilView is missing from index.html"
    parents = tracker.util_view_parents
    # The panel must not live inside the Claw workspace canvas anymore: that
    # ancestor is display:none outside the claw state, which is what hid the
    # whole util page in production.
    assert not any(parent_id == "clawWorkspace" for _, parent_id in parents)
    assert ("section", "clawWorkspace") not in parents
    assert parents[-1][0] == "main", "util page must be a direct child of <main>"


def test_util_view_visibility_is_owned_by_its_own_state() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".util-view { display: none;" in css
    assert '.app-shell[data-state="util"] .util-view { display: block' in css
    # The shared chat column and bottom composer must not render underneath
    # the util page, same convention as the other standalone views.
    assert '.app-shell[data-state="util"] .conversation' in css
    assert '.app-shell[data-state="util"] .composer-wrap { display: none !important; }' in css


def test_util_nav_enters_its_state_instead_of_hiding_its_own_ancestor() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert 'shell.dataset.state = "util"' in js
    # The production defect: the handler hid every .claw-workspace, including
    # the ancestor of #utilView.
    assert ".claw-workspace" not in js
    assert "if (utilView.hidden) showUtil()" not in js


def test_shell_state_sync_covers_the_util_state() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert 'state === "util") ? "false" : "page"' in js
    assert 'const utilNav = document.getElementById("utilNavButton");' in js
    assert 'utilNav.setAttribute("aria-current", state === "util" ? "page" : "false")' in js


def test_shipped_services_do_not_advertise_themselves_as_unavailable() -> None:
    html = _html()
    assert 'data-util="sns">SNS 홍보</button>' in html
    assert 'data-util="meeting">회의정리·책 제작</button>' in html
    assert '<span class="util-soon">' not in html
    util_section = html[html.index('id="utilView"') : html.index('id="calendarView"')]
    assert "준비 중" not in util_section


def test_speech_reopen_contract_reads_the_file_body() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert "[저장된 파일" not in js
    assert "저장된 축사의 본문을 읽을 수 없습니다." in js
    assert "저장된 축사를 열지 못했습니다." in js


# --------------------------------------------------------------------------
# behavioral harness: real util-menu.js, minimal DOM, recording fetch
# --------------------------------------------------------------------------


_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const utilMenuPath = process.argv[2];
const DRAFT_BODY = process.env.UTIL5608_DRAFT;

class N {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.type = "";
    this.name = "";
    this.placeholder = "";
    this.checked = false;
    this.rows = 0;
    this.required = false;
    this.id = "";
    this._listeners = {};
    const set = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => set.add(x)),
      remove: (...c) => c.forEach((x) => set.delete(x)),
      contains: (c) => set.has(c),
      toggle: (c, forced) => { if (forced) set.add(c); else set.delete(c); },
    };
  }
  set className(v) { this._cls = String(v || ""); }
  get className() { return this._cls || ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this._cls = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  removeChild(child) { const i = this.children.indexOf(child); if (i >= 0) this.children.splice(i, 1); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    for (const fn of this._listeners[type] || []) await fn.call(this, event || { preventDefault() {} });
  }
  focus() {}
  scrollIntoView() {}
  querySelector(sel) { return this.findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this.findAll(sel); }
  _descendants() {
    const out = [];
    for (const child of this.children) { out.push(child); out.push(...child._descendants()); }
    return out;
  }
  findAll(sel) {
    const parts = String(sel).split(/\s+/);
    let scope = [this, ...this.children];
    parts.forEach((part, index) => {
      const next = [];
      for (const node of scope) {
        if (index === 0 && simpleMatch(node, part)) next.push(node);
        for (const descendant of node._descendants()) {
          if (simpleMatch(descendant, part)) next.push(descendant);
        }
      }
      // Scope trees overlap (a child is a descendant of both parents), so drop
      // duplicates before the next combinator step.
      scope = Array.from(new Set(next));
    });
    return scope;
  }
}

function simpleMatch(node, sel) {
  let rest = String(sel);
  if (rest.endsWith(":checked")) {
    if (!node.checked) return false;
    rest = rest.slice(0, -":checked".length);
  }
  const nameMatch = /\[name=([^\]]+)\]/.exec(rest);
  if (nameMatch) {
    if (node.name !== nameMatch[1]) return false;
    rest = rest.replace(nameMatch[0], "");
  }
  const idMatch = /^#([\w-]+)/.exec(rest);
  if (idMatch) {
    if (node.id !== idMatch[1]) return false;
    rest = rest.slice(idMatch[0].length);
  }
  const tagMatch = /^([\w-]+)/.exec(rest);
  if (tagMatch) {
    if (tagMatch[1].toUpperCase() !== node.tagName) return false;
    rest = rest.slice(tagMatch[0].length);
  }
  const classes = rest.split(".").filter(Boolean);
  if (classes.length && !classes.every((c) => String(node._cls || "").split(/\s+/).includes(c))) {
    return false;
  }
  return true;
}

const root = new N("html");
const byId = {};
function mk(tag, id, cls) {
  const node = new N(tag);
  if (id) { node.id = id; byId[id] = node; }
  if (cls) node.className = cls;
  return node;
}

const shell = mk("div", null, "app-shell");
shell.dataset.state = "chat";
root.appendChild(shell);
const main = mk("main", "mainPanel", "main-panel");
shell.appendChild(main);

// The production DOM shape: workspace, conversation and composer are siblings.
const workspace = mk("section", "clawWorkspace", "claw-workspace");
workspace.hidden = true;
main.appendChild(workspace);
const conversation = mk("section", "conversation", "conversation");
main.appendChild(conversation);
const composer = mk("section", "composerWrap", "composer-wrap");
main.appendChild(composer);

const utilView = mk("section", "utilView", "util-view");
utilView.hidden = true;
main.appendChild(utilView);
const navBtn = mk("button", "utilNavButton", "side-item");
navBtn.setAttribute("aria-current", "false");
shell.appendChild(navBtn);

const speechTab = mk("button", null, "util-tab active");
speechTab.dataset.util = "speech";
utilView.appendChild(speechTab);
const form = mk("form", "utilSpeechForm", "util-form");
utilView.appendChild(form);
const eventInput = mk("input", null);
eventInput.name = "event";
eventInput.value = "2026 Padiem Community Sharing Party";
form.appendChild(eventInput);
const result = mk("div", "utilSpeechResult");
result.hidden = true;
utilView.appendChild(result);
const output = mk("textarea", "utilSpeechOutput");
result.appendChild(output);
const actions = mk("div", null, "util-actions");
result.appendChild(actions);
mk("button", "utilSpeechCopy");
mk("button", "utilSpeechDownload");
// #5727: save lives in the form area next to the generate button.
const formActions = mk("div", null, "util-form-actions");
form.appendChild(formActions);
const saveBtn = mk("button", "utilSpeechSave", "util-save");
formActions.appendChild(saveBtn);
mk("div", "utilSpeechPanel");
mk("div", "utilSnsPanel");
mk("div", "utilMeetingPanel");
mk("div", "utilMeetingOutput");
mk("div", "utilPdfmdPanel");

const requests = [];
const storedFiles = [];
function json(data) { return { ok: true, status: 200, json: async () => data }; }
async function fetch(url, opts) {
  opts = opts || {};
  const method = (opts.method || "GET").toUpperCase();
  const path = String(url).split("?")[0];
  const body = opts.body ? JSON.parse(opts.body) : null;
  requests.push({ method: method, url: path, body: body });
  if (method === "GET" && path === "/api/projects") {
    return json({ projects: [{ id: "p1", name: "유틸 작업" }] });
  }
  if (method === "POST" && path === "/api/projects") {
    return json({ project: { id: "p1", name: "유틸 작업" } });
  }
  if (method === "POST" && path === "/api/projects/p1/files") {
    const file = {
      id: "f" + (storedFiles.length + 1),
      name: body.name,
      media_type: body.media_type,
      content_chars: body.text.length,
      content: body.text,
    };
    storedFiles.push(file);
    // The list projection never carries the body.
    return json({ file: { id: file.id, name: file.name, media_type: file.media_type, content_chars: file.content_chars } });
  }
  if (method === "GET" && path === "/api/projects/p1/files") {
    return json({
      files: storedFiles.map((f) => ({ id: f.id, name: f.name, media_type: f.media_type, content_chars: f.content_chars })),
    });
  }
  const detail = /^\/api\/projects\/[^/]+\/files\/([^/]+)$/.exec(path);
  if (method === "GET" && detail) {
    const file = storedFiles.find((f) => f.id === decodeURIComponent(detail[1]));
    if (!file) return { ok: false, status: 404, json: async () => ({}) };
    return json({ file: { id: file.id, name: file.name, media_type: file.media_type, content_chars: file.content_chars, content: file.content } });
  }
  return { ok: false, status: 404, json: async () => ({}) };
}

const alerts = [];
const ctx = {
  document: {
    readyState: "complete",
    body: mk("body", null),
    documentElement: root,
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => root.findAll(sel)[0] || null,
    querySelectorAll: (sel) => root.findAll(sel),
    createElement: (tag) => new N(tag),
    addEventListener() {},
  },
  window: {},
  navigator: {},
  fetch: fetch,
  alert: (message) => alerts.push(String(message)),
  console: console,
  setTimeout: () => 0,
  Blob: function Blob() {},
  URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
};

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });

function fail(label, extra) {
  console.log(JSON.stringify({ ok: false, fail: label, extra: extra || null, alerts: alerts, requests: requests }));
  process.exit(1);
}

(async () => {
  // 1) Opening the util page enters its own shell state.
  await navBtn.dispatch("click");
  if (shell.dataset.state !== "util") fail("UTIL_STATE_NOT_ENTERED");
  if (navBtn.getAttribute("aria-current") !== "page") fail("UTIL_NAV_NOT_CURRENT");
  if (utilView.hidden !== false) fail("UTIL_VIEW_NOT_SHOWN");
  // The handler must not touch the sibling views any more: CSS owns that.
  if (workspace.hidden !== true) fail("WORKSPACE_STILL_MUTATED_BY_UTIL_NAV");

  // 2) Save the drafted speech.
  output.value = DRAFT_BODY;
  // #5727: the save button is form-area markup next to the generate button.
  if (!saveBtn) fail("SAVE_BUTTON_NOT_BUILT");
  if (saveBtn.parentNode.className !== "util-form-actions") fail("SAVE_NOT_IN_FORM_AREA");
  await saveBtn.dispatch("click");
  if (storedFiles.length !== 1) fail("SAVE_DID_NOT_STORE");
  if (storedFiles[0].content !== DRAFT_BODY) fail("SAVED_BODY_NOT_PRESERVED");
  if (storedFiles[0].name !== "2026 Padiem Community Sharing Party.txt") fail("SAVED_NAME_FROM_EVENT_FIELD");

  // 3) The saved list is populated from the (body-less) list projection.
  // #5731: each row carries the reopen button plus a 참고로 선택 action, so
  // the list renders two buttons for the one stored speech.
  const savedButtons = root.findAll("#utilSpeechSaved button");
  if (savedButtons.length !== 2) fail("SAVED_LIST_NOT_RENDERED", { count: savedButtons.length });
  if (savedButtons[0].textContent.indexOf("2026 Padiem Community Sharing Party.txt") < 0) {
    fail("SAVED_LIST_MISSING_FILE_NAME");
  }
  if (savedButtons[0].textContent.indexOf(DRAFT_BODY.length + "자") < 0) {
    fail("SAVED_LIST_MISSING_CHAR_COUNT");
  }
  if (savedButtons[1].textContent !== "참고로 선택") fail("SAVED_LIST_MISSING_REFERENCE_ACTION");

  // 4) Reopening restores the stored body, not a filename placeholder.
  await savedButtons[0].dispatch("click");
  if (output.value !== DRAFT_BODY) fail("REOPEN_DID_NOT_RESTORE_BODY");
  if (output.value.indexOf("[저장된 파일") === 0) fail("REOPEN_WROTE_FILENAME_PLACEHOLDER");
  if (result.hidden !== false) fail("REOPEN_DID_NOT_SHOW_RESULT");

  console.log(JSON.stringify({
    ok: true,
    state: shell.dataset.state,
    navAria: navBtn.getAttribute("aria-current"),
    workspaceHidden: workspace.hidden,
    storedCount: storedFiles.length,
    postedBodyMatches: storedFiles[0].content === DRAFT_BODY,
    detailRequests: requests.filter((r) => /^\/api\/projects\/[^/]+\/files\/[^/]+$/.test(r.url)).length,
    reopenedMatches: output.value === DRAFT_BODY,
    reopenedChars: output.value.length,
    alerts: alerts,
  }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: String((error && error.stack) || error) }));
});
"""


@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-menu behavioral harness"
    harness_path = ROOT / "tests" / "_5608_util_menu_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(UTIL_MENU_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "UTIL5608_DRAFT": DRAFT_BODY},
            timeout=60,
            cwd=str(ROOT),
        )
    finally:
        harness_path.unlink(missing_ok=True)
    stdout = result.stdout.strip()
    assert result.returncode == 0 and stdout, f"harness crashed: stdout={stdout!r} stderr={result.stderr!r}"
    payload = json.loads(stdout.splitlines()[-1])
    assert payload.get("ok"), f"harness failed: {payload!r}"
    return payload
    return payload


def test_real_util_menu_enters_its_state_without_hiding_siblings() -> None:
    payload = _run_harness()
    assert payload["state"] == "util"
    assert payload["navAria"] == "page"
    assert payload["workspaceHidden"] is True


def test_real_util_menu_saves_the_body_and_restores_it_on_reopen() -> None:
    payload = _run_harness()
    assert payload["storedCount"] == 1
    assert payload["postedBodyMatches"] is True
    assert payload["detailRequests"] == 1
    assert payload["reopenedMatches"] is True
    assert payload["reopenedChars"] == len(DRAFT_BODY)
    assert payload["alerts"] == []
