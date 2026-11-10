"""#7173 PR1 — Util app shell (third app switch) contract.

The representative decisions pinned here:
- top app switch Chat | Claw | Util (11-09),
- the util first screen is a card list whose whole card opens the tool's own
  screen inside the Util app (11-10; no separate 열기/이력/Claw buttons),
- hash routing (#util, #util/<id>) so Back and refresh restore the screen,
- files are separated: util-app.js/util-app.css own the Util behaviour; app.js
  only exposes the two existing navigation entry points (bounded additions).

Static assertions pin the markup/CSS boundary; a Node harness executes the
REAL util-app.js against a minimal DOM shim (the repo's b62_dom_sink_audit bans
innerHTML sinks, so the module builds nodes with createElement/textContent) and
proves routing, whole-card click, keyboard-native buttons and the switch calls.
"""
from __future__ import annotations

import json
import os
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
    assert 'data-locale-key="nav-util"' in switch


def test_util_shell_owns_only_a_render_root() -> None:
    section = _util_section()
    assert 'id="utilAppRoot"' in section
    for gone in ('class="util-tabs"', 'id="utilToolGrid"', "data-util-tool=", "util-tool-open"):
        assert gone not in section, gone
    # PR3: the PDF → Markdown panel is created by its own screen; nothing is
    # parked under the first screen and moved across the DOM.
    assert "utilPdfmdHost" not in section
    assert "utilPdfmdPanel" not in section
    assert "mountPdfmdPanel" in UTIL_JS
    assert "utilPdfmdHost" not in UTIL_JS
    # The panel module must be available before util-app.js boots.
    assert INDEX.index("./util-pdfmd.js") < INDEX.index("./util-app.js")


def test_util_logic_files_are_separate_and_app_js_stays_a_bridge() -> None:
    for token in ("utilAppRoot", "util-card", "data-util-route", "PadiemUtilApp"):
        assert token not in APP_JS, token
    assert "window.PadiemAppSwitch = Object.freeze({" in APP_JS
    assert "openChat: openChatWorkspace," in APP_JS
    assert "openClaw: openClawWorkspace," in APP_JS
    assert len(APP_JS.splitlines()) <= 6172


def test_route_contract_and_whole_card_button() -> None:
    assert 'const ROUTE_PREFIX = "#util";' in UTIL_JS
    assert "window.location.hash = hash" in UTIL_JS
    assert 'window.addEventListener("hashchange", onHashChange);' in UTIL_JS
    assert 'element("a", "util-tool-back")' in UTIL_JS
    assert 'setAttribute("href", listHref())' in UTIL_JS
    assert 'element("button", "util-card")' in UTIL_JS
    assert 'setAttribute("data-util-route", toolHref(tool.id))' in UTIL_JS
    assert 'setAttribute("aria-label"' in UTIL_JS
    for tool in TOOL_IDS:
        assert f'id: "{tool}"' in UTIL_JS, tool
    # The unsafe DOM sink boundary: the module never assembles HTML strings.
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML"):
        assert sink not in UTIL_JS, sink
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
    assert '.app-switch-item[aria-current="page"]' in UTIL_CSS
    assert "var(--primary-bg)" in UTIL_CSS
    assert "#utilNavGroup { display: none; }" in UTIL_CSS


# ── behaviour: the real util-app.js in a Node DOM shim ─────────────────────

HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const calls = [];
const registry = [];

function El(tag) {
  return {
    tagName: (tag || "div").toUpperCase(), id: "", className: "", type: "",
    textContent: "", children: [], attrs: {}, dataset: {}, listeners: {},
    hidden: false, focused: false,
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute(k, v) { this.attrs[k] = v; if (k === "id") this.id = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(node) { this.children.push(node); node.parentElement = this; return node; },
    replaceChildren(...nodes) { this.children.length = 0; nodes.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { return findAll(this, sel); },
  };
}
function matches(el, sel) {
  if (sel.startsWith(".")) return el.className === sel.slice(1);
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  return el.tagName === sel.toUpperCase();
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function allText(root) { let text = ""; walk(root, (e) => { if (typeof e.textContent === "string") text += e.textContent + " "; }); return text; }

const root = El("div"); root.id = "utilAppRoot"; registry.push(root);
const utilView = El("section"); utilView.id = "utilView"; utilView.hidden = true; registry.push(utilView);
const utilTitle = El("h2"); utilTitle.id = "utilTitle"; registry.push(utilTitle);
const utilKicker = El("p"); utilKicker.id = "utilKicker"; registry.push(utilKicker);
const utilTagline = El("p"); utilTagline.id = "utilTagline"; registry.push(utilTagline);
const shell = El("div"); shell.dataset = { state: "home" };
const appSwitch = El("nav"); appSwitch.id = "appSwitch"; registry.push(appSwitch);
const buttons = ["chat", "claw", "util"].map((app) => { const b = El("button"); b.dataset = { app }; return b; });
appSwitch.querySelectorAll = (sel) => (sel === "[data-app]" ? buttons : []);
const pdfInits = [];
const document = {
  readyState: "complete", documentElement: { lang: "ko" },
  createElement: (tag) => { const node = El(tag); registry.push(node); return node; },
  createTextNode: (text) => { const node = El("#text"); node.textContent = text; return node; },
  getElementById: (id) => { const hits = registry.filter((e) => e.id === id); return hits.length ? hits[hits.length - 1] : null; },
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
  PadiemAppSwitch: { openChat() { calls.push("chat"); }, openClaw() { calls.push("claw"); } },
  initPdfMdUtility: (panel) => { pdfInits.push(panel); } };
const sandbox = { document, window: windowObj, location: loc, history, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "util-app.js" });
const api = windowObj.PadiemUtilApp;
const result = { ok: true, checks: {} };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function fire(hash) { loc.hash = hash; if (listeners.hashchange) listeners.hashchange(); }

check("api", Boolean(api));
check("route_list", api && api.parseHash("#util") && api.parseHash("#util").screen === "list");
check("route_tool", api && api.parseHash("#util/sns") && api.parseHash("#util/sns").id === "sns");
check("route_invalid", api && api.parseHash("#util/nope") && api.parseHash("#util/nope").screen === "invalid");
check("route_other", api && api.parseHash("#chat") === null);

if ((process.env.INITIAL_HASH || "").startsWith("#util/")) {
  const id = process.env.INITIAL_HASH.split("/")[1];
  const screen = find(root, ".util-tool-screen");
  check("deep_link_screen", screen && screen.getAttribute("data-util-tool") === id);
  const back = find(root, ".util-tool-back");
  check("deep_link_backlink", back && back.getAttribute("href") === "#util");
  const heading = find(root, "#utilToolHeading");
  check("deep_link_no_focus_steal", !heading || heading.focused === false);
  if (id === "pdfmd") {
    const panel = find(root, "#utilPdfmdPanel");
    check("pdf_deep_link_panel", Boolean(panel) && pdfInits.length === 1 && pdfInits[0] === panel);
  }
} else {
  const rendered = api.renderList();
  const cards = findAll(rendered, ".util-card");
  check("list_six_cards", rendered.getAttribute("aria-label") === "유틸 도구" && cards.length === 6);
  check("cards_are_native_buttons", cards.every((c) => c.tagName === "BUTTON" && c.type === "button"
        && (c.getAttribute("data-util-route") || "").startsWith("#util/")));
  check("cards_need_no_secondary_actions", cards.every((c) => !/이력 열기|Claw에서/.test(c.getAttribute("aria-label") || "")));
  const tool = api.renderTool("speech");
  check("tool_frame", find(tool, ".util-tool-back") && find(tool, "#utilToolHeading")
        && find(tool, ".util-tool-back").getAttribute("href") === "#util");

  buttons[2].listeners.click();
  check("util_tab_sets_hash", loc.hash === "#util");
  fire("#util");
  check("list_rendered", Boolean(find(root, ".util-card-grid")) && utilView.hidden === false);
  root.listeners.click({
    target: { closest: (sel) => (sel === "[data-util-route]"
      ? { getAttribute: () => "#util/pdfmd" } : null) },
    preventDefault() {},
  });
  check("whole_card_click_sets_hash", loc.hash === "#util/pdfmd");
  fire("#util/pdfmd");
  const screen = find(root, ".util-tool-screen");
  const heading = find(root, "#utilToolHeading");
  check("tool_rendered_focus", screen && screen.getAttribute("data-util-tool") === "pdfmd"
        && heading && heading.focused === true);
  const pdfPanel = find(root, "#utilPdfmdPanel");
  check("pdf_panel_created_in_tool_body", Boolean(pdfPanel)
        && Boolean(find(find(root, ".util-tool-body"), "#utilPdfmdPanel"))
        && pdfInits.length === 1 && pdfInits[0] === pdfPanel);
  check("pdf_panel_not_parked", !find(root, "#utilPdfmdHost"));
  fire("#util/unknown");
  check("invalid_resolves_to_list", Boolean(find(root, ".util-card-grid"))
        && history.replaceCalls.some((u) => u.endsWith("#util")));
  fire("#util");
  check("back_to_list", Boolean(find(root, ".util-card-grid")) && utilView.hidden === false);
  buttons[0].listeners.click();
  check("chat_tab_calls_open_chat", calls.includes("chat") && utilView.hidden === true);
  buttons[1].listeners.click();
  check("claw_tab_calls_open_claw", calls.includes("claw"));
  loc.hash = "#util/quote";
  buttons[2].listeners.click();
  const quote = find(root, ".util-tool-screen");
  check("util_tab_renders_route", quote && quote.getAttribute("data-util-tool") === "quote");
  fire("#util");
  fire("");
  check("hash_back_to_chat", utilView.hidden === true
        && calls.filter((c) => c === "chat").length >= 2);
}
console.log(JSON.stringify(result));
'''


def test_pdfmd_screen_mounts_its_panel_on_the_deep_link() -> None:
    result = _run_harness("#util/pdfmd")
    assert result["deep_link_screen"] is True
    assert result["pdf_deep_link_panel"] is True
    assert result["deep_link_backlink"] is True
    assert result["deep_link_no_focus_steal"] is True


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
                 "list_six_cards", "cards_are_native_buttons", "cards_need_no_secondary_actions",
                 "tool_frame", "util_tab_sets_hash", "list_rendered",
                 "whole_card_click_sets_hash", "tool_rendered_focus",
                 "invalid_resolves_to_list", "back_to_list",
                 "chat_tab_calls_open_chat", "claw_tab_calls_open_claw",
                 "util_tab_renders_route", "hash_back_to_chat"):
        assert checks.get(name) is True, name


def test_behaviour_refresh_restores_a_tool_screen() -> None:
    checks = _run_harness("#util/meeting")
    for name in ("deep_link_screen", "deep_link_backlink", "deep_link_no_focus_steal"):
        assert checks.get(name) is True, name
