"""R5 1단계(#7226) 설정·사이드바 구역 — 실제 모듈 실행 관찰 하네스.

`chat-settings-module.js`·`chat-sidebar-module.js`를 Node vm에서 그대로 실행하고,
설정 창 열기·닫기·고급 설정 화면 전환, 사이드바 접기·펴기와 모바일 오버레이를
함수 직접 호출로 관찰한다. 2026-11-11 현재 동작(닫기 컨트롤 하나·알림 스위치·
계정 구역·사이드바 묶음)을 반영한 값은 각 관찰 이름 옆 주석에 적었다.

관찰은 소스 문자열이 아니라 **호출 결과**다:
  * `showModal()`/`close()`가 불렸는지, 없을 때 `open` 속성으로 대체되는지,
  * `hidden`·`aria-expanded`·class·포커스가 어디로 갔는지,
  * locale 키(`data-locale-aria-label`·`data-locale-title`·`data-locale-key`)를
    모듈이 덮어쓰지 않는지(= 번역 대상 라벨이 살아 있는지),
  * 고급 설정 메뉴 선택(`pc`)은 deps 스파이가 아니라 버튼 `selected` 클래스와
    블록 `hidden`으로 관찰하고, 발행 이벤트 이름도 함께,
  * deps getter가 첫 호출 전에 바뀐 값을 읽는지.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

_NODE = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  const classes = new Set();
  return {
    id, open: false, hidden: false, attrs, shown: 0, closed: 0, focused: 0,
    textContent: "",
    dataset: {},
    classList: {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    showModal() { this.shown += 1; this.open = true; },
    close() { this.closed += 1; this.open = false; },
    setAttribute(k, v) { attrs[k] = String(v); },
    removeAttribute(k) { delete attrs[k]; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    focus() { this.focused += 1; this.focusedId = this.id; },
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
      const node = { tag, ns, attrs: {}, children: [], textContent: "",
        setAttribute(k, v) { this.attrs[k] = String(v); },
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
    advancedMenuButtons: [
      Object.assign(makeElement("advancedMenuLink"), { dataset: { advancedMenu: "pc" } }),
      Object.assign(makeElement("advancedMenuLink2"), { dataset: { advancedMenu: "locales" } }),
    ],
    advancedPageBlocks: [
      Object.assign(makeElement("advancedPageBlock"), { dataset: { advancedBlock: "pc" } }),
      Object.assign(makeElement("advancedPageBlock2"), { dataset: { advancedBlock: "locales" } }),
    ],
    shell: makeShell(),
    setNavActive: () => { base.navActive = (base.navActive || 0) + 1; },
    sidebarCollapseButton: makeElement("sidebarCollapseButton"),
    sidebarRestoreButton: makeElement("sidebarRestoreButton"),
    mobileMenu: makeElement("mobileMenu"),
    mobileClose: makeElement("mobileClose"),
    sidebarScrim: makeElement("sidebarScrim"),
    closeProfilePanel: () => { base.profileClosed = (base.profileClosed || 0) + 1; },
  };
  return r5StrictDeps(Object.assign(base, overrides || {}), "step1.deps");
}
function settingsApi(d) { return ctx.window.PadiemChatSettingsModule.create(d || deps()); }
function sidebarApi(d) { return ctx.window.PadiemChatSidebarModule.create(d || deps()); }

// 1. Tier projection: the shared tier state, and free for anything unexpected.
ctx.window.PadiemTierSelection = { get: () => "plus" };
results.tierPlus = settingsApi().selectedProductTier();
ctx.window.PadiemTierSelection = { get: () => "bogus" };
results.tierBogus = settingsApi().selectedProductTier();
ctx.window.PadiemTierSelection = undefined;
results.tierMissing = settingsApi().selectedProductTier();

// 2. Settings dialog: one dialog, both triggers marked expanded. The dialog's
//    close control (settingsCloseButton, the only submit in the dialog since
//    #7485) submits the same closeSettings() the module owns.
let d = deps();
d.settingsDialog.setAttribute("open", "");
// The label the sidebar shows is a locale key span (#7438 account row): the
// module may flip aria-expanded, never the translated label or its key.
d.settingsButton.setAttribute("data-locale-key", "settings");
d.settingsButton.textContent = "설정";
let api = ctx.window.PadiemChatSettingsModule.create(d);
api.openSettings();
results.openSettings = { shown: d.settingsDialog.shown, open: d.settingsDialog.open,
  button: d.settingsButton.getAttribute("aria-expanded"),
  profile: d.profileToggle.getAttribute("aria-expanded"),
  localeKey: d.settingsButton.getAttribute("data-locale-key"),
  label: d.settingsButton.textContent };
api.closeSettings();
results.closeSettings = { closed: d.settingsDialog.closed, open: d.settingsDialog.open,
  button: d.settingsButton.getAttribute("aria-expanded"),
  profile: d.profileToggle.getAttribute("aria-expanded"),
  localeKey: d.settingsButton.getAttribute("data-locale-key"),
  label: d.settingsButton.textContent };

// 3. A dialog without showModal/close (the shipped fallback) uses the open
//    attribute instead — the same control closes it again.
d = deps();
d.settingsDialog.showModal = undefined;
d.settingsDialog.close = undefined;
api = ctx.window.PadiemChatSettingsModule.create(d);
api.openSettings();
const fallbackOpened = d.settingsDialog.getAttribute("open");
api.closeSettings();
results.settingsFallback = { opened: fallbackOpened, closed: d.settingsDialog.getAttribute("open"),
  button: d.settingsButton.getAttribute("aria-expanded") };

// 4. Advanced settings page: the library menu's pc block is selected, the
//    previous shell state is remembered, and the page shows.
d = deps();
d.shell.dataset.state = "claw";
api = ctx.window.PadiemChatSettingsModule.create(d);
api.openAdvancedSettingsView();
results.advancedOpen = { hidden: d.advancedSettingsView.hidden, state: d.shell.dataset.state,
  returnState: d.advancedSettingsReturnState, nav: d.navActive,
  selected: d.advancedMenuButtons.map((b) => b.classList.contains("selected")),
  blocks: d.advancedPageBlocks.map((b) => !b.hidden),
  events: ctx.events.slice(-1) };

// 5. Closing it restores the remembered state and clears it.
api.closeAdvancedSettingsView();
results.advancedClose = { hidden: d.advancedSettingsView.hidden, state: d.shell.dataset.state,
  returnState: d.advancedSettingsReturnState, nav: d.navActive, events: ctx.events.slice(-1) };

// 6. Without the advanced page the same entry opens the settings dialog.
d = deps({ advancedSettingsView: null });
api = ctx.window.PadiemChatSettingsModule.create(d);
api.openAdvancedSettingsView();
results.advancedFallback = { shown: d.settingsDialog.shown };

// 7. Sidebar action icons: decorative SVG only — every kind keeps aria-hidden
//    and carries no text, so the translated label stays on the button.
d = deps();
const sideApi = ctx.window.PadiemChatSidebarModule.create(d);
function iconOf(kind) {
  const node = sideApi.sidebarActionIcon(kind);
  return { tag: node.tag, aria: node.attrs["aria-hidden"], focusable: node.attrs.focusable,
    circles: node.children.filter((c) => c.tag === "circle").length,
    paths: node.children.filter((c) => c.tag === "path").length,
    text: node.children.map((c) => c.textContent || "").join(""),
    hasD: Boolean((node.children.find((c) => c.tag === "path") || {}).attrs) };
}
results.icon = { settings: iconOf("settings"), more: iconOf("more"),
  kinds: ["rename", "pin", "unpin", "trash", "unknown"].map(iconOf) };

// 8. Desktop collapse: class, both aria flags, and the focus that moves.
//    The locale keys the buttons carry are untouched by the module.
d = deps();
d.sidebarCollapseButton.setAttribute("data-locale-aria-label", "sidebar-collapse");
d.sidebarCollapseButton.setAttribute("data-locale-title", "sidebar-collapse");
d.sidebarCollapseButton.textContent = "사이드바 접기";
d.sidebarRestoreButton.setAttribute("data-locale-aria-label", "sidebar-expand");
d.sidebarRestoreButton.setAttribute("data-locale-title", "sidebar-expand");
d.sidebarRestoreButton.textContent = "사이드바 펼치기";
api = ctx.window.PadiemChatSidebarModule.create(d);
api.setSidebarCollapsed(true);
const collapsedOn = { classed: d.shell.classList.contains("sidebar-collapsed"),
  collapseAria: d.sidebarCollapseButton.getAttribute("aria-expanded"),
  restoreAria: d.sidebarRestoreButton.getAttribute("aria-expanded"),
  focusId: d.sidebarRestoreButton.focused ? d.sidebarRestoreButton.id : null,
  collapseLocale: [d.sidebarCollapseButton.getAttribute("data-locale-aria-label"),
                   d.sidebarCollapseButton.getAttribute("data-locale-title"),
                   d.sidebarCollapseButton.textContent],
  restoreLocale: [d.sidebarRestoreButton.getAttribute("data-locale-aria-label"),
                  d.sidebarRestoreButton.getAttribute("data-locale-title"),
                  d.sidebarRestoreButton.textContent] };
api.setSidebarCollapsed(false);
results.collapse = { on: collapsedOn,
  off: { classed: d.shell.classList.contains("sidebar-collapsed"),
         collapseFocus: d.sidebarCollapseButton.focused,
         restoreAria: d.sidebarRestoreButton.getAttribute("aria-expanded") } };

// 9. The desktop preference never applies on the phone overlay.
ctx.window.__mobile = true;
d = deps();
api = ctx.window.PadiemChatSidebarModule.create(d);
api.setSidebarCollapsed(true);
results.mobileCollapse = { classed: d.shell.classList.contains("sidebar-collapsed"),
  collapseAria: d.sidebarCollapseButton.getAttribute("aria-expanded") };
ctx.window.__mobile = false;

// 10. Phone overlay open/close keeps the scrim, the menu flag, focus and the
//     account panel close.
d = deps();
api = ctx.window.PadiemChatSidebarModule.create(d);
api.openSidebar();
const opened = { classed: d.shell.classList.contains("sidebar-open"),
  aria: d.mobileMenu.getAttribute("aria-expanded"), scrim: d.sidebarScrim.hidden,
  focusId: d.mobileClose.focused ? d.mobileClose.id : null };
api.closeSidebar();
results.sidebar = { opened,
  closed: { classed: d.shell.classList.contains("sidebar-open"),
            aria: d.mobileMenu.getAttribute("aria-expanded"), scrim: d.sidebarScrim.hidden,
            profileClosed: d.profileClosed } };

// 11. Getter contract: change the closure value BEFORE create() and before the
//     first call; the module must read the changed element, not a snapshot.
const live = { dialog: makeElement("before"), shell: makeShell() };
const getterDeps = {
  get settingsDialog() { return live.dialog; },
  get settingsButton() { return live.button ||= makeElement("settingsButton"); },
  get profileToggle() { return live.toggle ||= makeElement("profileToggle"); },
  get advancedSettingsView() { return live.view ||= makeElement("advancedSettingsView"); },
  get advancedSettingsReturnState() { return live.returnState; },
  set advancedSettingsReturnState(value) { live.returnState = value; },
  get advancedMenuButtons() { return live.menuButtons ||= []; },
  get advancedPageBlocks() { return live.pageBlocks ||= []; },
  get shell() { return live.shell; },
  get setNavActive() { return () => {}; },
  get sidebarCollapseButton() { return live.collapse ||= makeElement("sidebarCollapseButton"); },
  get sidebarRestoreButton() { return live.restore ||= makeElement("sidebarRestoreButton"); },
  get mobileMenu() { return live.menu ||= makeElement("mobileMenu"); },
  get mobileClose() { return live.close ||= makeElement("mobileClose"); },
  get sidebarScrim() { return live.scrim ||= makeElement("sidebarScrim"); },
  get closeProfilePanel() { return () => { live.profileClosed = true; }; },
};
live.dialog = makeElement("after");
const late = ctx.window.PadiemChatSettingsModule.create(r5StrictDeps(getterDeps, "step1.getterDeps"));
const lateSidebar = ctx.window.PadiemChatSidebarModule.create(r5StrictDeps(getterDeps, "step1.getterDeps"));
late.openSettings();
lateSidebar.openSidebar();
lateSidebar.closeSidebar();
results.getter = { opened: live.dialog.shown,
  overlay: live.shell.classList.contains("sidebar-open"),
  profileClosed: Boolean(live.profileClosed) };

process.stdout.write(JSON.stringify(results));
"""


def observations() -> dict:
    """실제 두 모듈을 실행해 관찰한 값. Node가 없으면 skip."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the settings/sidebar module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(STRICT + "\n" + _NODE, encoding="utf-8", newline="\n")
        payload = Path(tmp) / "payload.json"
        payload.write_text(json.dumps({"static": str(STATIC)}), encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-settings-module.js"),
             str(STATIC / "chat-sidebar-module.js"), str(payload)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
