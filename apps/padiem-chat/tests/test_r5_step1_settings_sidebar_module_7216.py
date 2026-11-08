"""#7216 R5 1단계 — 설정·사이드바 구역 모듈 계약 시험.

app.js 클로저에 있던 9개 함수를 새 모듈 파일로 옮겼다. 이 시험은 (1) 실제 모듈
본문을 Node vm에서 실행해 동작이 그대로인지, (2) deps getter가 첫 호출 전에 바뀐
클로저 값을 읽는지, (3) app.js가 한 줄 전달 함수만 남겼는지, (4) index.html이
모듈을 app.js보다 먼저 로드하는지를 확인한다. 문자열 존재만 보는 시험이 아니다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "chat-settings-module.js").read_text(encoding="utf-8")
SIDEBAR = (STATIC / "chat-sidebar-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

MODULES = {
    "settings": ("PadiemChatSettingsModule", "chat-settings-module.js",
                 ["selectedProductTier", "openSettings", "closeSettings",
                  "openAdvancedSettingsView", "closeAdvancedSettingsView"]),
    "sidebar": ("PadiemChatSidebarModule", "chat-sidebar-module.js",
                ["sidebarActionIcon", "setSidebarCollapsed", "closeSidebar", "openSidebar"]),
}
FORWARDERS = {
    "selectedProductTier": "settingsModule",
    "openSettings": "settingsModule",
    "closeSettings": "settingsModule",
    "openAdvancedSettingsView": "settingsModule",
    "closeAdvancedSettingsView": "settingsModule",
    "sidebarActionIcon": "sidebarModule",
    "setSidebarCollapsed": "sidebarModule",
    "closeSidebar": "sidebarModule",
    "openSidebar": "sidebarModule",
}

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, open: false, hidden: false, attrs, shown: 0, closed: 0, focused: 0,
    showModal() { this.shown += 1; this.open = true; },
    close() { this.closed += 1; this.open = false; },
    setAttribute(k, v) { attrs[k] = String(v); },
    removeAttribute(k) { delete attrs[k]; },
    focus() { this.focused += 1; },
    addEventListener() {},
    appendChild(child) { (this.children ||= []).push(child); return child; },
  };
}

function makeShell() {
  const classes = new Set();
  return {
    dataset: {},
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    classes,
  };
}

function makeContext() {
  const events = [];
  const svgNodes = [];
  const document = {
    createElementNS(ns, tag) {
      const node = { tag, ns, attrs: {}, children: [], setAttribute(k, v) { this.attrs[k] = String(v); },
        appendChild(child) { this.children.push(child); return child; } };
      svgNodes.push(node);
      return node;
    },
  };
  const window = {
    events,
    matchMedia(query) { return { media: query, matches: window.__mobile === true }; },
    dispatchEvent(event) { events.push(event.type); return true; },
  };
  return { window, document, events, svgNodes };
}

const settingsSource = fs.readFileSync(process.argv[2], "utf8");
const sidebarSource = fs.readFileSync(process.argv[3], "utf8");
const payload = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const results = {};

const ctx = makeContext();
ctx.CustomEvent = ctx.window.CustomEvent = class { constructor(type) { this.type = type; } };
vm.createContext(ctx);
vm.runInContext(settingsSource, ctx, { filename: "chat-settings-module.js" });
vm.runInContext(sidebarSource, ctx, { filename: "chat-sidebar-module.js" });

function deps(overrides) {
  const base = {
    settingsDialog: makeElement("settingsDialog"),
    settingsButton: makeElement("settingsButton"),
    profileToggle: makeElement("profileToggle"),
    advancedSettingsView: makeElement("advancedSettingsView"),
    advancedSettingsReturnState: null,
    shell: makeShell(),
    setNavActive: () => { base.navActive = (base.navActive || 0) + 1; },
    selectAdvancedMenu: (key) => { base.menu = key; },
    sidebarCollapseButton: makeElement("sidebarCollapseButton"),
    sidebarRestoreButton: makeElement("sidebarRestoreButton"),
    mobileMenu: makeElement("mobileMenu"),
    mobileClose: makeElement("mobileClose"),
    sidebarScrim: makeElement("sidebarScrim"),
    closeProfilePanel: () => { base.profileClosed = (base.profileClosed || 0) + 1; },
  };
  return Object.assign(base, overrides || {});
}

function settingsApi() {
  return ctx.window.PadiemChatSettingsModule.create(deps());
}
function sidebarApi() {
  return ctx.window.PadiemChatSidebarModule.create(deps());
}

// 1. selectedProductTier reads the shared tier state and falls back to free.
ctx.window.PadiemTierSelection = { get: () => "plus" };
results.tierPlus = settingsApi().selectedProductTier();
ctx.window.PadiemTierSelection = { get: () => "bogus" };
results.tierBogus = settingsApi().selectedProductTier();
ctx.window.PadiemTierSelection = undefined;
results.tierMissing = settingsApi().selectedProductTier();

// 2. openSettings opens the same dialog and marks both triggers expanded.
let d = deps();
let api = ctx.window.PadiemChatSettingsModule.create(d);
api.openSettings();
results.openSettings = { shown: d.settingsDialog.shown, open: d.settingsDialog.open,
  button: d.settingsButton.attrs["aria-expanded"], profile: d.profileToggle.attrs["aria-expanded"] };

// 3. closeSettings closes it and clears both aria flags.
api.closeSettings();
results.closeSettings = { closed: d.settingsDialog.closed, open: d.settingsDialog.open,
  button: d.settingsButton.attrs["aria-expanded"], profile: d.profileToggle.attrs["aria-expanded"] };

// 4. openAdvancedSettingsView remembers the previous shell state and shows the page.
d = deps();
d.shell.dataset.state = "claw";
ctx.window.PadiemTierSelection = { get: () => "free" };
api = ctx.window.PadiemChatSettingsModule.create(d);
api.openAdvancedSettingsView();
results.advancedOpen = { hidden: d.advancedSettingsView.hidden, state: d.shell.dataset.state,
  returnState: d.advancedSettingsReturnState, nav: d.navActive, menu: d.menu,
  events: ctx.events.slice(-1) };

// 5. closeAdvancedSettingsView restores the remembered state and clears it.
api.closeAdvancedSettingsView();
results.advancedClose = { hidden: d.advancedSettingsView.hidden, state: d.shell.dataset.state,
  returnState: d.advancedSettingsReturnState, nav: d.navActive, events: ctx.events.slice(-1) };

// 6. Without the advanced view the same entry opens the settings dialog.
d = deps({ advancedSettingsView: null });
api = ctx.window.PadiemChatSettingsModule.create(d);
api.openAdvancedSettingsView();
results.advancedFallback = { shown: d.settingsDialog.shown };

// 7. sidebarActionIcon keeps the accessible SVG shape.
d = deps();
api = ctx.window.PadiemChatSidebarModule.create(d);
const icon = api.sidebarActionIcon("settings");
const more = api.sidebarActionIcon("more");
results.icon = { tag: icon.tag, aria: icon.attrs["aria-hidden"], focusable: icon.attrs.focusable,
  path: Boolean(icon.children[0]), circles: icon.children.filter((c) => c.tag === "circle").length,
  moreCircles: more.children.filter((c) => c.tag === "circle").length };

// 8. setSidebarCollapsed toggles the desktop class and moves focus.
d = deps();
api = ctx.window.PadiemChatSidebarModule.create(d);
api.setSidebarCollapsed(true);
const collapsedOn = { classed: d.shell.classList.contains("sidebar-collapsed"),
  collapseAria: d.sidebarCollapseButton.attrs["aria-expanded"],
  restoreAria: d.sidebarRestoreButton.attrs["aria-expanded"],
  restoreFocus: d.sidebarRestoreButton.focused };
api.setSidebarCollapsed(false);
results.collapse = { on: collapsedOn,
  off: { classed: d.shell.classList.contains("sidebar-collapsed"),
         collapseFocus: d.sidebarCollapseButton.focused } };

// 9. The mobile overlay is unchanged and the desktop preference never applies there.
ctx.window.__mobile = true;
d = deps();
api = ctx.window.PadiemChatSidebarModule.create(d);
api.setSidebarCollapsed(true);
results.mobileCollapse = { classed: d.shell.classList.contains("sidebar-collapsed") };
ctx.window.__mobile = false;

// 10. openSidebar/closeSidebar keep the mobile overlay contract.
d = deps();
api = ctx.window.PadiemChatSidebarModule.create(d);
api.openSidebar();
const opened = { classed: d.shell.classList.contains("sidebar-open"),
  aria: d.mobileMenu.attrs["aria-expanded"], scrim: d.sidebarScrim.hidden, focus: d.mobileClose.focused };
api.closeSidebar();
results.sidebar = { opened,
  closed: { classed: d.shell.classList.contains("sidebar-open"),
            aria: d.mobileMenu.attrs["aria-expanded"], scrim: d.sidebarScrim.hidden,
            profileClosed: d.profileClosed } };

// 11. Getter contract: change the closure value BEFORE create() and before the first
//     call; the module must read the changed element, not a snapshot.
const live = { dialog: makeElement("before"), shell: makeShell() };
const getterDeps = {
  get settingsDialog() { return live.dialog; },
  get settingsButton() { return live.button ||= makeElement("settingsButton"); },
  get profileToggle() { return live.toggle ||= makeElement("profileToggle"); },
  get advancedSettingsView() { return live.view ||= makeElement("advancedSettingsView"); },
  get advancedSettingsReturnState() { return live.returnState; },
  set advancedSettingsReturnState(value) { live.returnState = value; },
  get shell() { return live.shell; },
  get setNavActive() { return () => {}; },
  get selectAdvancedMenu() { return () => {}; },
  get sidebarCollapseButton() { return live.collapse ||= makeElement("sidebarCollapseButton"); },
  get sidebarRestoreButton() { return live.restore ||= makeElement("sidebarRestoreButton"); },
  get mobileMenu() { return live.menu ||= makeElement("mobileMenu"); },
  get mobileClose() { return live.close ||= makeElement("mobileClose"); },
  get sidebarScrim() { return live.scrim ||= makeElement("sidebarScrim"); },
  get closeProfilePanel() { return () => { live.profileClosed = true; }; },
};
live.dialog = makeElement("after");
const late = ctx.window.PadiemChatSettingsModule.create(getterDeps);
const lateSidebar = ctx.window.PadiemChatSidebarModule.create(getterDeps);
late.openSettings();
lateSidebar.openSidebar();
lateSidebar.closeSidebar();
results.getter = { opened: live.dialog.shown,
  overlay: live.shell.classList.contains("sidebar-open"),
  profileClosed: Boolean(live.profileClosed) };

process.stdout.write(JSON.stringify(results));
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        payload = Path(tmp) / "payload.json"
        harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
        payload.write_text(json.dumps({"static": str(STATIC)}), encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-settings-module.js"),
             str(STATIC / "chat-sidebar-module.js"), str(payload)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def observed() -> dict:
    return _run_harness()


def test_module_files_expose_one_factory_and_keep_the_original_names() -> None:
    for _, (global_name, filename, names) in MODULES.items():
        source = (STATIC / filename).read_text(encoding="utf-8")
        assert f"window.{global_name} = {{" in source
        assert "create(deps) {" in source
        for name in names:
            assert f"function {name}(" in source, (filename, name)
        # One global factory only; no second authority and no DOM lookup at load.
        assert source.count("window.") >= 1
        assert "document.getElementById" not in source


def test_settings_and_sidebar_bodies_live_only_in_their_modules() -> None:
    # The moved bodies (not the one-line forwarders) are gone from app.js.
    for marker in ("settingsDialog.showModal()", "sidebarRestoreButton?.focus()",
                   "shell.classList.toggle(\"sidebar-collapsed\", collapsed)",
                   "advancedSettingsReturnState = deps"):
        assert marker not in APP, marker
    for marker in ("settingsDialog.showModal()", "sidebarRestoreButton?.focus()"):
        assert marker in SETTINGS or marker in SIDEBAR


def test_app_js_keeps_one_line_forwarders_for_all_nine_functions() -> None:
    for name, factory in FORWARDERS.items():
        line = f"function {name}(...a) {{ return {factory}().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function settingsModule() {" in APP
    assert "function sidebarModule() {" in APP


def test_modules_load_before_app_js() -> None:
    settings_at = INDEX.index("./chat-settings-module.js")
    sidebar_at = INDEX.index("./chat-sidebar-module.js")
    app_at = INDEX.index("./app.js")
    assert settings_at < app_at and sidebar_at < app_at
    assert INDEX.count("./chat-settings-module.js") == 1
    assert INDEX.count("./chat-sidebar-module.js") == 1


def test_module_behavior_matches_the_closed_over_originals(observed: dict) -> None:
    assert observed["tierPlus"] == "plus"
    assert observed["tierBogus"] == "free"
    assert observed["tierMissing"] == "free"
    assert observed["openSettings"] == {"shown": 1, "open": True, "button": "true", "profile": "true"}
    assert observed["closeSettings"] == {"closed": 1, "open": False, "button": "false", "profile": "false"}
    assert observed["advancedOpen"] == {
        "hidden": False, "state": "settings", "returnState": "claw",
        "nav": 1, "menu": "pc", "events": ["padiem:advanced-settings-open"],
    }
    assert observed["advancedClose"] == {
        "hidden": True, "state": "claw", "returnState": None,
        "nav": 2, "events": ["padiem:advanced-settings-close"],
    }
    assert observed["advancedFallback"] == {"shown": 1}
    assert observed["icon"] == {"tag": "svg", "aria": "true", "focusable": "false",
                                "path": True, "circles": 1, "moreCircles": 3}
    assert observed["collapse"] == {
        "on": {"classed": True, "collapseAria": "false", "restoreAria": "false", "restoreFocus": 1},
        "off": {"classed": False, "collapseFocus": 1},
    }
    assert observed["mobileCollapse"] == {"classed": False}
    assert observed["sidebar"] == {
        "opened": {"classed": True, "aria": "true", "scrim": False, "focus": 1},
        "closed": {"classed": False, "aria": "false", "scrim": True, "profileClosed": 1},
    }
    # Getter: the element replaced before the first call is the one that opens.
    assert observed["getter"]["opened"] == 1
    assert observed["getter"]["overlay"] is False
    assert observed["getter"]["profileClosed"] is True
