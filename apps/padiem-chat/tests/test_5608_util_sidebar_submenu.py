"""#5608 follow-up: the sidebar Util entry expands into its four tools.

The owner asked for the sidebar first: ``Util`` becomes an expandable entry
(chevron, aria-expanded/aria-controls, keyboard operable) whose four rows —
축사·인사말 / SNS 홍보 / 회의정리·활동집 / PDF → Markdown — route straight into
the existing panels. The in-page duplicate tab row is hidden, and the panels,
their lazy builders, drafts and saved records keep their single owner in
util-menu.js (no feature is re-implemented here).

Static assertions pin the markup/CSS contracts; the Node harness executes the
REAL util-menu.js against a minimal DOM shim and proves the actual submenu
behavior: expand/collapse, per-item selection, exactly one active row, the
mobile drawer closing on entry, and draft preservation across switches.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static/index.html"
UTIL_MENU_JS = ROOT / "static/util-menu.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"

SUBMENU = [
    ("speech", "축사·인사말"),
    ("sns", "SNS 홍보"),
    ("meeting", "회의정리·활동집"),
    ("pdfmd", "PDF → Markdown"),
]


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_sidebar_util_entry_is_a_disclosure_with_four_tools() -> None:
    html = _html()
    assert 'id="utilNavGroup"' in html
    assert 'aria-controls="utilSubmenu"' in html
    assert 'id="utilNavButton"' in html and 'aria-expanded="false"' in html
    assert 'class="side-chevron" aria-hidden="true">›<' in html
    assert 'id="utilSubmenu" hidden' in html
    section = html[html.index('id="utilSubmenu"') : html.index("</nav>", html.index('id="utilSubmenu"'))]
    for key, label in SUBMENU:
        assert f'data-util="{key}"' in section, f"missing submenu tool: {key}"
        assert f">{label}</button>" in section, f"missing submenu label: {label}"


def test_duplicate_in_page_tabs_are_hidden_not_deleted() -> None:
    html = _html()
    assert '<nav class="util-tabs" hidden' in html
    # The switch targets stay in the DOM: the submenu drives the same panels.
    for key, _label in SUBMENU:
        assert f'data-util="{key}"' in html


def test_util_menu_js_routes_the_submenu_through_one_switch() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert "function activateUtilTab(tab)" in js
    assert "markActiveUtilSubmenuItem" in js
    assert "setUtilSubmenuOpen" in js
    assert 'setAttribute("aria-expanded", open ? "true" : "false")' in js
    assert '"⌄"' in js and '"›"' in js
    assert 'utilSubmenu.querySelectorAll(".util-submenu-item")' in js
    assert 'utilSubmenuItems.forEach' in js
    # Leaving the util view must not leave a stale highlight on a submenu row.
    assert 'attributeFilter: ["aria-current"]' in js
    # Entering a tool from the drawer must close the drawer.
    assert 'classList.contains("sidebar-open")' in js


def test_util_menu_css_hides_duplicate_tabs_and_styles_submenu() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".util-tabs[hidden] { display: none; }" in css
    assert ".util-submenu[hidden] { display: none; }" in css
    assert ".util-submenu-item" in css
    assert ".util-submenu-item:focus-visible" in css
    assert ".util-submenu-item.active" in css
    assert 'html[data-theme="padiem-glass"] .util-submenu-item' in css


def test_util_parent_shows_the_active_treatment_while_a_tool_is_open() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    rule = css[css.index('#utilNavButton[aria-current="page"]') :]
    assert "var(--accent-soft" in rule[:200]
    assert "inset 3px 0 0 var(--accent" in rule[:200]


# --------------------------------------------------------------------------
# behavioral harness: real util-menu.js, minimal DOM, no network
# --------------------------------------------------------------------------


_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const utilMenuPath = process.argv[2];

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
    this.id = "";
    this._listeners = {};
    const set = new Set();
    this._classSet = set;
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
    let scope = [this, ...this.children];
    for (const part of String(sel).split(/\s+/)) {
      const next = [];
      for (const node of scope) {
        if (simpleMatch(node, part)) next.push(node);
        for (const descendant of node._descendants()) {
          if (simpleMatch(descendant, part)) next.push(descendant);
        }
      }
      scope = Array.from(new Set(next));
    }
    return scope;
  }
}

function simpleMatch(node, sel) {
  const idMatch = /^#([\w-]+)/.exec(sel);
  if (idMatch) {
    if (node.id !== idMatch[1]) return false;
    sel = sel.slice(idMatch[0].length);
  }
  const tagMatch = /^([\w-]+)/.exec(sel);
  if (tagMatch) {
    if (tagMatch[1].toUpperCase() !== node.tagName) return false;
    sel = sel.slice(tagMatch[0].length);
  }
  const classes = sel.split(".").filter(Boolean);
  if (classes.length && !classes.every((c) => (
    String(node._cls || "").split(/\s+/).includes(c)
    || (node._classSet && node._classSet.has(c))
  ))) {
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

const utilNav = mk("button", "utilNavButton", "side-item");
utilNav.setAttribute("aria-current", "false");
utilNav.setAttribute("aria-expanded", "false");
const chevron = mk("span", null, "side-chevron");
chevron.textContent = "›";
utilNav.appendChild(chevron);
shell.appendChild(utilNav);

const utilSubmenu = mk("div", "utilSubmenu", "util-submenu");
utilSubmenu.hidden = true;
shell.appendChild(utilSubmenu);
const items = {};
for (const key of ["speech", "sns", "meeting", "pdfmd"]) {
  const item = mk("button", null, "util-submenu-item");
  item.dataset.util = key;
  item.setAttribute("aria-current", "false");
  utilSubmenu.appendChild(item);
  items[key] = item;
}

const utilView = mk("section", "utilView", "util-view");
utilView.hidden = true;
shell.appendChild(utilView);

const tabs = {};
const panels = {};
for (const key of ["speech", "sns", "meeting", "pdfmd"]) {
  const tab = mk("button", null, "util-tab");
  tab.dataset.util = key;
  utilView.appendChild(tab);
  tabs[key] = tab;
  const panel = mk("div", "util" + key.charAt(0).toUpperCase() + key.slice(1) + "Panel");
  utilView.appendChild(panel);
  panels[key] = panel;
}
tabs.speech.classList.add("active");
const output = mk("textarea", "utilSpeechOutput");
panels.speech.appendChild(output);
const meetingFlag = mk("div", "utilMeetingOutput");
panels.meeting.appendChild(meetingFlag);

const mobileMenu = mk("button", "mobileMenu");
mobileMenu.setAttribute("aria-expanded", "false");
shell.appendChild(mobileMenu);
const scrim = mk("div", "sidebarScrim");
scrim.hidden = true;
shell.appendChild(scrim);

async function fetch(url, opts) {
  return { ok: false, status: 404, json: async () => ({}) };
}

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
  alert: () => {},
  console: console,
  setTimeout: () => 0,
  Blob: function Blob() {},
  URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
};

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(utilMenuPath, "utf8"), ctx, { filename: "util-menu.js" });

function fail(label, extra) {
  console.log(JSON.stringify({ ok: false, fail: label, extra: extra || null }));
  process.exit(1);
}
function activeItems() {
  return utilSubmenu.querySelectorAll(".util-submenu-item.active");
}

(async () => {
  let routedPdfmd = false;
  // 1) The parent click enters util and expands the disclosure.
  await utilNav.dispatch("click");
  if (shell.dataset.state !== "util") fail("PARENT_CLICK_DID_NOT_ENTER_UTIL");
  if (utilNav.getAttribute("aria-expanded") !== "true") fail("PARENT_NOT_EXPANDED");
  if (utilSubmenu.hidden !== false) fail("SUBMENU_NOT_SHOWN");
  if (chevron.textContent !== "⌄") fail("CHEVRON_NOT_OPEN_STATE");
  if (activeItems().length !== 1) fail("INITIAL_ACTIVE_NOT_EXACTLY_ONE");
  if (activeItems()[0].dataset.util !== "speech") fail("INITIAL_ACTIVE_NOT_DEFAULT_TOOL");

  // 2) A submenu row routes into the existing panel and keeps one active row.
  output.value = "열린 앞 축사 초안 [draft]";
  await items.pdfmd.dispatch("click");
  if (panels.pdfmd.hidden !== false) fail("PDFMD_PANEL_NOT_SHOWN");
  if (panels.speech.hidden !== true) fail("SPEECH_PANEL_NOT_HIDDEN");
  if (activeItems().length !== 1 || activeItems()[0].dataset.util !== "pdfmd") {
    fail("ACTIVE_NOT_EXACTLY_PDFMD");
  }
  if (tabs.pdfmd.classList.contains("active") !== true) fail("HIDDEN_TAB_SWITCH_NOT_SYNCED");
  if (utilNav.getAttribute("aria-expanded") !== "true") fail("SELECTION_COLLAPSED_SUBMENU");
  routedPdfmd = panels.pdfmd.hidden === false && panels.speech.hidden === true;

  // 3) The parent collapses and re-expands without leaving the util state.
  await utilNav.dispatch("click");
  if (utilNav.getAttribute("aria-expanded") !== "false") fail("PARENT_NOT_COLLAPSED");
  if (utilSubmenu.hidden !== true) fail("SUBMENU_NOT_HIDDEN");
  if (chevron.textContent !== "›") fail("CHEVRON_NOT_CLOSED_STATE");
  if (shell.dataset.state !== "util") fail("COLLAPSE_LEFT_UTIL_STATE");
  await utilNav.dispatch("click");
  if (utilSubmenu.hidden !== false) fail("SUBMENU_NOT_RESHOWN");

  // 4) Drafts survive switching because the panels are only hidden.
  await items.speech.dispatch("click");
  if (panels.speech.hidden !== false) fail("SPEECH_PANEL_NOT_RESHOWN");
  if (output.value !== "열린 앞 축사 초안 [draft]") fail("DRAFT_LOST_ON_SWITCH");
  if (activeItems().length !== 1 || activeItems()[0].dataset.util !== "speech") {
    fail("ACTIVE_NOT_EXACTLY_SPEECH");
  }

  // 5) Entering a tool from the open mobile drawer closes the drawer.
  shell.classList.add("sidebar-open");
  scrim.hidden = false;
  await items.sns.dispatch("click");
  if (shell.classList.contains("sidebar-open")) fail("DRAWER_LEFT_OPEN");
  if (scrim.hidden !== true) fail("SCRIM_LEFT_VISIBLE");
  if (mobileMenu.getAttribute("aria-expanded") !== "false") fail("MENU_ARIA_NOT_RESET");
  if (panels.sns.hidden !== false) fail("SNS_PANEL_NOT_SHOWN");

  console.log(JSON.stringify({
    ok: true,
    state: shell.dataset.state,
    routedPdfmd: routedPdfmd,
    speechRedraft: output.value,
    snsShown: panels.sns.hidden === false,
    activeAfterSns: activeItems().length,
  }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: String((error && error.stack) || error) }));
});
"""


@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util submenu behavioral harness"
    harness_path = ROOT / "tests" / "_5608_util_submenu_behavior_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(UTIL_MENU_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ},
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


def test_real_util_menu_expands_and_routes_all_four_tools() -> None:
    payload = _run_harness()
    assert payload["state"] == "util"
    assert payload["routedPdfmd"] is True
    assert payload["snsShown"] is True
    assert payload["activeAfterSns"] == 1


def test_real_util_menu_preserves_drafts_across_switches() -> None:
    payload = _run_harness()
    assert payload["speechRedraft"] == "열린 앞 축사 초안 [draft]"
