"""#5568 P2 UI/UX: conversion-mode explanation and grouped searchable history.

Two follow-ups after the P1 pass:

1. ``fast`` and ``verify`` had no explanation next to the selector. A one-line
   help paragraph now follows the selection and its copy comes from the shared
   locale authority (``window.__padiemLocale`` / ``data-locale-key``).
2. Work history was one flat list. Rows are now grouped into today, yesterday,
   this week and earlier, and filtered client-side by date, filename, status,
   mode or job id. The list API is unchanged; filenames join the index as jobs
   are opened, because the list response carries no filenames.

The Node harness executes the real ``util-pdfmd.js`` against a minimal DOM shim
and drives the locale stub, the mode selector and the search input.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PDFMD_JS = ROOT / "static/util-pdfmd.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"
LOCALE_JS = ROOT / "static/locale.js"

LOCALE_KEYS = (
    "pdfmd-mode-help-fast",
    "pdfmd-mode-help-verify",
    "pdfmd-history-search-label",
    "pdfmd-history-search-placeholder",
    "pdfmd-history-today",
    "pdfmd-history-yesterday",
    "pdfmd-history-this-week",
    "pdfmd-history-earlier",
    "pdfmd-history-no-match",
    "pdfmd-history-no-match-detail",
)


# --------------------------------------------------------------------------
# static structural contracts
# --------------------------------------------------------------------------


def test_mode_help_uses_locale_keys_in_both_languages() -> None:
    locale = LOCALE_JS.read_text(encoding="utf-8")
    for key in LOCALE_KEYS:
        assert locale.count(f'"{key}"') == 2, key
    js = PDFMD_JS.read_text(encoding="utf-8")
    assert 'modeSel.setAttribute("aria-describedby", "pdfmdModeHelp")' in js
    assert 'const modeHelp = el("p", "pdfmd-mode-help")' in js
    assert 'MODE_HELP[modeSel.value]' in js
    assert "modeHelp.dataset.localeKey = key" in js
    assert 'updateModeHelp();' in js
    assert 'MODE_HELP = {' in js


def test_history_search_and_grouping_are_client_side() -> None:
    js = PDFMD_JS.read_text(encoding="utf-8")
    assert 'histSearch.type = "search"' in js
    assert 'data-locale-placeholder", "pdfmd-history-search-placeholder"' in js
    assert 'data-locale-aria-label", "pdfmd-history-search-label"' in js
    assert 'histSearch.addEventListener("input"' in js
    assert "historyGroup(job.created_at)" in js
    assert '"this-week"' in js
    assert 'copy("pdfmd-history-no-match"' in js
    # Search is a filter over the existing list response; no API contract change.
    assert '"/api/document-conversions?limit=50"' in js
    assert "/api/document-conversions?q=" not in js
    assert "/api/document-conversions/search" not in js
    # Filenames arrive with the job detail and are cached for later searches.
    assert "itemNames.set(currentJobId" in js


def test_history_search_and_mode_help_reuse_design_tokens() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".pdfmd-mode-help" in css
    assert ".pdfmd-history-search" in css
    assert ".pdfmd-history-group" in css
    assert "min-height: 44px" in css
    assert ".pdfmd-history-search:focus-visible" in css
    assert "var(--panel, #ffffff)" in css


# --------------------------------------------------------------------------
# behavioral harness: real util-pdfmd.js, minimal DOM, locale stub
# --------------------------------------------------------------------------

_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const pdfmdPath = process.argv[2];

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
    this.title = "";
    this.id = "";
    this.tabIndex = -1;
    this.disabled = false;
    this._cls = "";
    this._listeners = {};
    const set = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => set.add(x)),
      remove: (...c) => c.forEach((x) => set.delete(x)),
      contains: (c) => set.has(c),
    };
  }
  set className(v) { this._cls = String(v || ""); }
  get className() { return this._cls || ""; }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "class") this._cls = String(v);
  }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null;
  }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener() {}
  async dispatch(type, event) {
    for (const fn of this._listeners[type] || []) await fn.call(this, event || { preventDefault() {} });
  }
  focus() {}
  click() { return this.dispatch("click"); }
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
      scope = Array.from(new Set(next));
    });
    return scope;
  }
}

function simpleMatch(node, sel) {
  let rest = String(sel);
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

function text(node) {
  return String(node.textContent || "") + node.children.map(text).join("");
}

const root = new N("html");
const panel = new N("div");
panel.id = "utilPdfmdPanel";
root.appendChild(panel);

// Fixed clock: Saturday 2026-10-24, so today / yesterday / this week
// (Monday 2026-10-19) / earlier are stable on every CI machine.
const FIXED_NOW = new Date(2026, 9, 24, 11, 55, 0);
class FixedDate extends Date {
  constructor(...args) { if (args.length === 0) super(FIXED_NOW.getTime()); else super(...args); }
  static now() { return FIXED_NOW.getTime(); }
}
function ago(days, minutes) {
  const d = new Date(FIXED_NOW.getTime());
  d.setDate(d.getDate() - days);
  d.setMinutes(d.getMinutes() - (minutes || 0));
  return d.toISOString();
}
const jobs = [
  { id: "dcj_today01", mode: "fast", status: "done", item_count: 2, created_at: ago(0, 5) },
  { id: "dcj_yesterd2", mode: "verify", status: "reviewed", item_count: 1, created_at: ago(1, 5) },
  { id: "dcj_thisweek4", mode: "fast", status: "working", item_count: 2, created_at: ago(2, 5) },
  { id: "dcj_earlier3", mode: "fast", status: "failed", item_count: 3, created_at: ago(30, 5) },
];
const todayItems = [
  { id: "dci_a", job_id: jobs[0].id, name: "sample-one.pdf", status: "done", page_count: 1, character_count: 275, has_markdown: true, report: null, error_code: null },
  { id: "dci_b", job_id: jobs[0].id, name: "damaged.pdf", status: "failed", page_count: 0, character_count: 0, has_markdown: false, report: null, error_code: "pdf_magic_mismatch" },
];

function json(data, status) {
  const code = status || 200;
  return {
    ok: code < 400,
    status: code,
    headers: { get: () => "application/json" },
    json: async () => data,
  };
}
async function fetch(url) {
  const target = String(url);
  if (target.indexOf("/api/document-conversions?limit=") !== -1) return json({ jobs: jobs });
  if (/\/api\/document-conversions\/dcj_today01$/.test(target)) return json({ items: todayItems });
  if (/\/api\/document-conversions\/dcj_[a-z0-9]+$/.test(target)) return json({ items: [] });
  return json({ error: { code: "not_found" } }, 404);
}

const EN = {
  "pdfmd-mode-help-fast": "EN fast help",
  "pdfmd-mode-help-verify": "EN verify help",
  "pdfmd-history-search-label": "EN search",
  "pdfmd-history-search-placeholder": "EN placeholder",
  "pdfmd-history-today": "EN today",
  "pdfmd-history-yesterday": "EN yesterday",
  "pdfmd-history-this-week": "EN this week",
  "pdfmd-history-earlier": "EN earlier",
  "pdfmd-history-no-match": "EN no match",
  "pdfmd-history-no-match-detail": "EN no match detail",
};

const ctx = {
  document: {
    body: new N("body"),
    documentElement: root,
    getElementById: (id) => (id === "utilPdfmdPanel" ? panel : null),
    querySelector: (sel) => root.findAll(sel)[0] || null,
    querySelectorAll: (sel) => root.findAll(sel),
    createElement: (tag) => new N(tag),
    addEventListener() {},
  },
  window: { __padiemLocale: { text: (key) => EN[key] || key } },
  fetch: fetch,
  console: console,
  Date: FixedDate,
  setTimeout: () => 0,
  URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
};

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(pdfmdPath, "utf8"), ctx, { filename: "util-pdfmd.js" });

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function fail(label, extra) {
  console.log(JSON.stringify({ ok: false, fail: label, extra: extra || null }));
  process.exit(1);
}
function rows() {
  return root.findAll(".pdfmd-history-item");
}
function headings() {
  return root.findAll(".pdfmd-history-group").map(text);
}
async function search(value) {
  const input = panel.querySelector("#pdfmdHistorySearch");
  input.value = value;
  await input.dispatch("input");
}

(async () => {
  ctx.window.initPdfMdUtility(panel);
  await flush();
  await flush();

  // 1) Mode help is localized from the locale authority and follows the mode.
  const help = panel.querySelector("#pdfmdModeHelp");
  if (!help) fail("MODE_HELP_MISSING");
  if (text(help) !== "EN fast help") fail("MODE_HELP_NOT_LOCALIZED", text(help));
  if (help.dataset.localeKey !== "pdfmd-mode-help-fast") fail("MODE_HELP_KEY_WRONG", help.dataset.localeKey);
  const mode = panel.querySelector("#pdfmdMode");
  mode.value = "verify";
  await mode.dispatch("change");
  if (text(help) !== "EN verify help") fail("MODE_HELP_NOT_UPDATED", text(help));
  if (help.dataset.localeKey !== "pdfmd-mode-help-verify") fail("MODE_HELP_KEY_NOT_UPDATED", help.dataset.localeKey);
  const verifyHelp = text(help);
  mode.value = "fast";
  await mode.dispatch("change");

  // 2) Search input is localized and history is grouped by date.
  const input = panel.querySelector("#pdfmdHistorySearch");
  if (!input) fail("SEARCH_MISSING");
  if (input.placeholder !== "EN placeholder") fail("SEARCH_PLACEHOLDER_NOT_LOCALIZED", input.placeholder);
  if (rows().length !== 4) fail("HISTORY_NOT_GROUPED", rows().length);
  const groups = headings();
  if (JSON.stringify(groups) !== JSON.stringify(["EN today", "EN yesterday", "EN this week", "EN earlier"])) {
    fail("GROUP_ORDER_WRONG", groups);
  }

  // 3) Before a job is opened its filenames are not in the index — the list
  //    API has none — so a filename search reports no match honestly.
  await search("sample");
  if (rows().length !== 0) fail("UNCACHED_FILENAME_MATCHED", rows().length);
  if (!text(panel.querySelector(".pdfmd-history")).includes("EN no match")) fail("NO_MATCH_STATE_MISSING");

  // 4) Opening a job caches its filenames; the same search now matches it.
  await search("");
  await rows()[0].dispatch("click");
  await flush();
  await flush();
  await search("sample");
  const matched = rows();
  if (matched.length !== 1) fail("CACHED_FILENAME_NOT_MATCHED", matched.length);
  if (matched[0].dataset.jobId !== "dcj_today01") fail("WRONG_JOB_MATCHED", matched[0].dataset.jobId);
  if (JSON.stringify(headings()) !== JSON.stringify(["EN today"])) fail("FILTERED_GROUP_WRONG", headings());

  // 5) Status, mode, date and id search work without any extra API call.
  await search("검증");
  if (rows().length !== 1 || rows()[0].dataset.jobId !== "dcj_yesterd2") fail("MODE_SEARCH_FAILED", rows().map((r) => r.dataset.jobId));
  await search("실패");
  if (rows().length !== 1 || rows()[0].dataset.jobId !== "dcj_earlier3") fail("STATUS_SEARCH_FAILED", rows().map((r) => r.dataset.jobId));
  await search("today01");
  if (rows().length !== 1 || rows()[0].dataset.jobId !== "dcj_today01") fail("ID_SEARCH_FAILED", rows().map((r) => r.dataset.jobId));
  await search("2026.10.22");
  if (rows().length !== 1 || rows()[0].dataset.jobId !== "dcj_thisweek4") fail("DATE_SEARCH_FAILED", rows().map((r) => r.dataset.jobId));

  // 6) Clearing the query restores every group.
  await search("");
  if (rows().length !== 4) fail("SEARCH_NOT_CLEARED", rows().length);
  if (JSON.stringify(headings()) !== JSON.stringify(["EN today", "EN yesterday", "EN this week", "EN earlier"])) {
    fail("GROUPS_NOT_RESTORED", headings());
  }

  console.log(JSON.stringify({
    ok: true,
    modeHelp: verifyHelp,
    groups: groups,
    matchedByFilename: matched.length,
    restored: rows().length,
  }));
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: String((error && error.stack) || error) }));
});
"""


@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-pdfmd behavioral harness"
    harness_path = ROOT / "tests" / "_5568_pdfmd_ui_p2_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(PDFMD_JS)],
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


def test_mode_help_follows_selector_through_locale() -> None:
    payload = _run_harness()
    assert payload["modeHelp"] == "EN verify help"


def test_history_groups_and_searches_without_api_change() -> None:
    payload = _run_harness()
    assert payload["groups"] == ["EN today", "EN yesterday", "EN this week", "EN earlier"]
    assert payload["matchedByFilename"] == 1
    assert payload["restored"] == 4
