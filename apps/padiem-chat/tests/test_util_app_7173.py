"""#7173 PR1 — Util app shell (third app switch) contract.

The representative decisions pinned here:
- top app switch Chat | Claw | Util (11-09),
- the util first screen is a card list whose whole card opens the tool's own
  screen inside the Util app (11-10; no separate 열기/이력/Claw buttons),
- hash routing (#util, #util/<id>) so Back and refresh restore the screen,
- files are separated: util-app.js/util-app.css own the Util behaviour; app.js
  only exposes the two existing navigation entry points (bounded additions).

Static assertions pin the markup/CSS boundary; a Node harness executes the
REAL util-app.js against a minimal DOM shim and proves routing, whole-card
click, keyboard-native buttons and the Chat/Claw switch calls.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
UTIL_JS = (STATIC / "util-app.js").read_text(encoding="utf-8")
UTIL_CSS = (STATIC / "util-app.css").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")

TOOL_IDS = ("speech", "sns", "meeting", "pdfmd", "quote", "excel")


def _util_section() -> str:
    return INDEX[INDEX.index('id="utilView"') : INDEX.index('id="calendarView"')]


# ── static boundary ────────────────────────────────────────────────────────


def test_top_app_switch_has_the_three_apps() -> None:
    switch = INDEX[INDEX.index('id="appSwitch"') : INDEX.index("</nav>", INDEX.index('id="appSwitch"'))]
    assert 'aria-label="앱 전환"' in switch
    for app in ("chat", "claw", "util"):
        assert f'data-app="{app}"' in switch, app
    # Util is localized; Chat/Claw are product names.
    assert 'data-locale-key="nav-util"' in switch


def test_util_shell_owns_only_a_render_root() -> None:
    section = _util_section()
    assert 'id="utilAppRoot"' in section
    # The old in-page tab row, six-card mark-up grid and per-card buttons are
    # retired; the list and the screens are rendered by util-app.js.
    for gone in ('class="util-tabs"', 'id="utilToolGrid"', "data-util-tool=", "util-tool-open"):
        assert gone not in section, gone
    # The PDF panel node is parked (hidden) for its own screen; no inline run.
    assert 'id="utilPdfmdHost" hidden' in section
    assert 'id="utilPdfmdPanel" hidden' in section


def test_util_logic_files_are_separate_and_app_js_stays_a_bridge() -> None:
    for token in ("utilAppRoot", "util-card", "data-util-route", "PadiemUtilApp"):
        assert token not in APP_JS, token
    assert "window.PadiemAppSwitch = Object.freeze({" in APP_JS
    assert "openChat: openChatWorkspace," in APP_JS
    assert "openClaw: openClawWorkspace," in APP_JS
    # Bounded bridge only: the R5 cap test owns the exact number.
    assert len(APP_JS.splitlines()) <= 6172


def test_route_contract_and_whole_card_button() -> None:
    assert 'const ROUTE_PREFIX = "#util";' in UTIL_JS
    assert "window.location.hash = hash" in UTIL_JS
    assert 'window.addEventListener("hashchange", onHashChange);' in UTIL_JS
    assert '"util-tool-back" href=' in UTIL_JS
    assert 'class="util-card"' in UTIL_JS and "data-util-route=" in UTIL_JS
    assert '<button type="button" class="util-card"' in UTIL_JS
    assert 'aria-label="' in UTIL_JS
    for tool in TOOL_IDS:
        assert f'id: "{tool}"' in UTIL_JS, tool
    # No separate per-card actions survive the 11-10 decision.
    for gone in ("이력 열기", "Claw에서 작성", "Claw에서 진행", 'class="util-tool-open"'):
        assert gone not in UTIL_JS, gone


def test_card_css_uses_tokens_hover_focus_and_motion_guards() -> None:
    rules = parse_rules(UTIL_CSS)
    cards = find_rules_with_selector(rules, ".util-card")
    assert cards
    border_values = [declaration(rule, "border") for rule in cards if declaration(rule, "border")]
    assert any(value.startswith("1px solid var(--line") for value in border_values), border_values
    assert not any("input-border-strong" in value for value in border_values)
    focus = find_rules_with_selector(rules, ".util-card:focus-visible")
    assert focus and declaration(focus[0], "outline") == "3px solid var(--primary-focus)"
    hover = find_rules_with_selector(rules, ".util-card:hover")
    assert hover and "translateY" in declaration(hover[0], "transform")
    assert "@media (prefers-reduced-motion: reduce)" in UTIL_CSS
    assert ".util-card-grid" in UTIL_CSS and "minmax(260px, 1fr)" in UTIL_CSS
    assert "@media (max-width: 720px)" in UTIL_CSS
    # The top switch keeps the shared primary token for the current app.
    assert '.app-switch-item[aria-current="page"]' in UTIL_CSS
    assert "var(--primary-bg)" in UTIL_CSS
    # The retired sidebar entry is hidden, never deleted.
    assert "#utilNavGroup { display: none; }" in UTIL_CSS


# ── behaviour: the real util-app.js in a Node DOM shim ─────────────────────

HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const calls = [];
function El(id) {
  return {
    id, dataset: {}, attrs: {}, innerHTML: "", hidden: false, focused: false,
    children: [], listeners: {}, queries: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    focus() { this.focused = true; },
    querySelector(sel) { return this.queries[sel] || null; },
    querySelectorAll(sel) { return this.queries[sel] || []; },
    appendChild(node) { this.children.push(node); node.parentElement = this; return node; },
  };
}
const root = El("utilAppRoot");
const body = El("body");
const utilView = El("utilView"); utilView.hidden = true;
const utilTitle = El("utilTitle"), utilKicker = El("utilKicker"), utilTagline = El("utilTagline");
const shell = El("shell"); shell.dataset = { state: "home" };
const appSwitch = El("appSwitch");
const buttons = ["chat", "claw", "util"].map((app) => { const b = El("btn-" + app); b.dataset = { app }; return b; });
appSwitch.queries["[data-app]"] = buttons;
const heading = El("utilToolHeading");
const pdfHost = El("utilPdfmdHost");
const pdfPanel = El("utilPdfmdPanel"); pdfPanel.parentElement = pdfHost; pdfHost.children = [pdfPanel];
root.queries[".util-tool-body"] = body;
const ids = { utilAppRoot: root, utilView, utilTitle, utilKicker, utilTagline,
  appSwitch, utilPdfmdHost: pdfHost, utilPdfmdPanel: pdfPanel, utilToolHeading: heading };
const document = {
  readyState: "complete", documentElement: { lang: "ko" },
  getElementById: (id) => ids[id] || null,
  querySelector: (sel) => (sel === ".app-shell" ? shell : null),
  addEventListener: () => {},
};
const loc = { hash: process.env.INITIAL_HASH || "", pathname: "/index.html", search: "" };
const history = { state: null, replaceCalls: [],
  replaceState(state, title, url) {
    this.replaceCalls.push(url);
    const i = url.indexOf("#"); loc.hash = i >= 0 ? url.slice(i) : "";
  } };
const listeners = {};
const windowObj = { location: loc, history,
  addEventListener: (type, fn) => { listeners[type] = fn; },
  PadiemAppSwitch: { openChat() { calls.push("chat"); }, openClaw() { calls.push("claw"); } } };
const sandbox = { document, window: windowObj, location: loc, history, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "util-app.js" });
const api = windowObj.PadiemUtilApp;
const result = { ok: true, checks: {} };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
check("api", Boolean(api));
check("route_list", api && api.parseHash("#util") && api.parseHash("#util").screen === "list");
check("route_tool", api && api.parseHash("#util/sns") && api.parseHash("#util/sns").id === "sns");
check("route_invalid", api && api.parseHash("#util/nope") && api.parseHash("#util/nope").screen === "invalid");
check("route_other", api && api.parseHash("#chat") === null);
check("list_six_cards", api && (api.renderList().match(/data-util-route/g) || []).length === 6);
check("list_no_extra_actions", api && !/util-tool-open|이력 열기|Claw에서/.test(api.renderList()));
check("tool_frame", api && api.renderTool("speech").includes('href="#util"')
      && api.renderTool("speech").includes("util-tool-heading"));
if ((process.env.INITIAL_HASH || "").startsWith("#util/")) {
  const id = process.env.INITIAL_HASH.split("/")[1];
  check("deep_link_screen", root.innerHTML.includes('data-util-tool="' + id + '"'));
  check("deep_link_backlink", root.innerHTML.includes('href="#util"'));
  check("deep_link_no_focus_steal", heading.focused === false);
} else {
  buttons[2].listeners.click();   // Util tab
  check("util_tab_sets_hash", loc.hash === "#util");
  fire("#util");
  check("list_rendered", root.innerHTML.includes("util-card-grid") && utilView.hidden === false);
  root.listeners.click({
    target: { closest: (sel) => (sel === "[data-util-route]"
      ? { getAttribute: () => "#util/pdfmd" } : null) },
    preventDefault() {},
  });
  check("whole_card_click_sets_hash", loc.hash === "#util/pdfmd");
  fire("#util/pdfmd");
  check("tool_rendered_focus", root.innerHTML.includes('data-util-tool="pdfmd"') && heading.focused === true);
  fire("#util/unknown");
  check("invalid_resolves_to_list", root.innerHTML.includes("util-card-grid")
        && history.replaceCalls.some((u) => u.endsWith("#util")));
  fire("#util");
  check("back_to_list", root.innerHTML.includes("util-card-grid") && utilView.hidden === false);
  buttons[0].listeners.click();
  check("chat_tab_calls_open_chat", calls.includes("chat") && utilView.hidden === true);
  buttons[1].listeners.click();
  check("claw_tab_calls_open_claw", calls.includes("claw"));
  loc.hash = "#util/quote";
  buttons[2].listeners.click();
  check("util_tab_renders_route", root.innerHTML.includes('data-util-tool="quote"'));
  fire("#util");
  fire("");
  check("hash_back_to_chat", utilView.hidden === true
        && calls.filter((c) => c === "chat").length >= 2);
}
function fire(hash) { loc.hash = hash; if (listeners.hashchange) listeners.hashchange(); }
console.log(JSON.stringify(result));
'''


def _run_harness(initial_hash: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-app harness"
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "util_harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        env = dict(os.environ)
        env["INITIAL_HASH"] = initial_hash
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "util-app.js")],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result
    return result["checks"]


def test_behaviour_routing_click_and_switch() -> None:
    checks = _run_harness("")
    for name in ("api", "route_list", "route_tool", "route_invalid", "route_other",
                 "list_six_cards", "list_no_extra_actions", "tool_frame",
                 "util_tab_sets_hash", "list_rendered", "whole_card_click_sets_hash",
                 "tool_rendered_focus", "invalid_resolves_to_list", "back_to_list",
                 "chat_tab_calls_open_chat", "claw_tab_calls_open_claw",
                 "util_tab_renders_route", "hash_back_to_chat"):
        assert checks.get(name) is True, name


def test_behaviour_refresh_restores_a_tool_screen() -> None:
    checks = _run_harness("#util/meeting")
    for name in ("deep_link_screen", "deep_link_backlink", "deep_link_no_focus_steal"):
        assert checks.get(name) is True, name
