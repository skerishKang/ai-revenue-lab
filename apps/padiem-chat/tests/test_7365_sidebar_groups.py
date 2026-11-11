"""#7365 대표 결정(2026-11-10) — Chat 사이드바 정리 계약.

- 묶음: 대화(새 채팅·Claw) → 도구·일정(유틸·캘린더·자동화·라이브러리) →
  내 자료(프로젝트·최근 대화) → 아래 계정(설정·앱 연결·사용 안내·약관·계정·Padiem Home).
- 회의록 사이드바 항목은 없어지고, 캡처 화면(녹음·전사) 트리거는 유틸 탭의
  회의정리·활동집 도구 화면 안에 같은 요소(id meetingNavButton)로 마운트된다.
  같은 동작: 클릭하면 기존 meetingView 캡처 화면이 열린다.
- 옛 위치 링크: #padiem-meeting 북마크는 유틸 탭 회의 도구 화면(#util/meeting)으로
  이어지고, #padiem-connectors는 기존과 같이 연결 화면을 연다.
- 최근 대화의 외부 AI 도구 요청 기록("외부 AI 도구 요청: pc_…")은 사람의 대화
  목록에서 분리되어 하나의 접힘 묶음(native <details>)으로 놓인다.

호출부 계약은 소스 고정, 유틸 마운트 동작은 Node DOM 셈 하네스(test_util_app_7173과
같은 패턴)로 검증한다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX_PATH = STATIC / "index.html"
APP_PATH = STATIC / "app.js"
UTIL_APP_PATH = STATIC / "util-app.js"
HISTORY_PATH = STATIC / "chat-history-module.js"
LOCALE_PATH = STATIC / "locale.js"


def _html() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def _sidebar() -> str:
    html = _html()
    return html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]


# ── 1. 새 구성 렌더 (묶음 순서) ─────────────────────────────────────────────


def test_sidebar_groups_render_in_the_owner_decided_order() -> None:
    sidebar = _sidebar()
    # 대화: 새 채팅(+검색) · Claw — 위쪽 하나의 묶음.
    chat_group = sidebar.split('class="sidebar-chat-claw-group"', 1)[1].split('id="workspaceNav"', 1)[0]
    assert 'id="newChatButton"' in chat_group
    assert 'id="sidebarSearchButton"' in chat_group
    assert 'id="clawNavButton"' in chat_group
    # 도구·일정: 유틸 · 캘린더 · 자동화 · 라이브러리 (대표 결정 순서).
    tools_nav = sidebar.split('id="workspaceNav"', 1)[1].split("</nav>", 1)[0]
    ids = ("utilNavButton", "calendarNavButton", "automationNavButton", "filesNavButton")
    positions = [tools_nav.index(f'id="{key}"') for key in ids]
    assert positions == sorted(positions), "도구·일정 순서는 유틸·캘린더·자동화·라이브러리"
    assert 'id="meetingNavButton"' not in tools_nav, "회의록 항목은 사이드바에서 제거"
    # 내 자료: 프로젝트 · 최근 대화 (순서 유지).
    assert sidebar.index('id="projectsSection"') < sidebar.index('id="historySection"')
    # 아래 계정: 설정 · 앱 연결 · 사용 안내 · 약관 · 계정 · Padiem Home.
    bottom = sidebar.split('class="sidebar-bottom"', 1)[1]
    bottom_ids = ("settingsButton", "connectorsNavButton", "helpNavLink")
    bottom_positions = [bottom.index(f'id="{key}"') for key in bottom_ids]
    assert bottom_positions == sorted(bottom_positions)
    assert 'data-locale-key="legal-privacy"' in bottom
    assert 'data-locale-key="legal-terms"' in bottom
    assert 'id="accountAvatar"' in bottom
    assert 'class="home-link"' in bottom


def test_the_util_row_uses_a_pictograph_icon_like_its_peers() -> None:
    html = _html()
    # #7365 후속(CTO 261111): the util row reads like the other tool rows —
    # a geometric pictograph, never a letter.
    util_button = html.split('id="utilNavButton"', 1)[1].split("</button>", 1)[0]
    assert ">▣<" in util_button
    assert ">U<" not in util_button


def test_settings_is_a_first_class_account_menu_entry_for_guests_too() -> None:
    html = _html()
    bottom = html.split('class="sidebar-bottom"', 1)[1].split("</div>", 1)[0]
    # The settings entry carries no hidden attribute: guests and signed-in
    # accounts both see it beside 앱 연결 · 사용 안내 · 약관.
    settings_tag = bottom.split('id="settingsButton"', 1)[0].split("<button", 1)[-1]
    assert " hidden" not in settings_tag


def test_guests_see_the_materials_group_honestly_empty() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    auth = (STATIC / "chat-auth-module.js").read_text(encoding="utf-8")
    # A signed-out (guest) account keeps the projects section visible with its
    # empty-state note instead of hiding the whole group.
    clear_block = app.split("function clearProjectsUI()", 1)[1].split("renderProjectState();", 1)[0]
    assert "projectsSection.hidden = false;" in clear_block
    assert "projectsEmpty.hidden = false;" in clear_block
    # The guest fallthrough shows the history section and its empty note
    # without fetching (no failure rows for an empty account).
    guest_block = auth.split('deps.accountName.textContent = deps.uiT("guest");', 1)[1]
    assert "deps.historySection.hidden = false;" in guest_block
    assert "deps.historyEmpty.hidden = false;" in guest_block


def test_the_tools_group_names_itself_for_screen_readers() -> None:
    html = _html()
    assert 'data-locale-aria-label="tools-menu"' in html
    assert 'aria-label="도구·일정"' in html
    locale = LOCALE_PATH.read_text(encoding="utf-8")
    assert '"tools-menu": "도구·일정"' in locale
    assert '"tools-menu": "Tools & schedule"' in locale
    # The aria applier binds the renamed landmark on language change.
    assert '["#workspaceNav", "aria-label", "tools-menu"]' in locale


# ── 2. 옮긴 항목이 새 위치에서 같은 동작 ────────────────────────────────────


def test_the_meeting_trigger_is_parked_in_the_util_view() -> None:
    html = _html()
    # Same element, same id: meeting-capture.js finds it at load and the click
    # opens the existing capture screen.
    assert html.count('id="meetingNavButton"') == 1
    assert 'id="meetingCaptureHost" hidden' in html
    assert html.index('id="meetingCaptureHost"') > html.index('id="utilAppRoot"')
    host = html.split('id="meetingCaptureHost"', 1)[1].split("</div>", 1)[0]
    assert 'class="util-meeting-capture-entry" id="meetingNavButton"' in host
    assert 'aria-controls="meetingView"' in host
    assert 'data-locale-key="nav-meeting"' in host


def test_util_module_mounts_the_meeting_entry_into_its_tool_screen() -> None:
    util = UTIL_APP_PATH.read_text(encoding="utf-8")
    # The parked-node pattern (the same one the legacy PDF panel uses).
    assert 'document.getElementById("meetingCaptureHost")' in util
    assert "parkMeetingCaptureEntry()" in util
    assert 'if (parsed.id === "meeting") mountMeetingCaptureEntry();' in util
    # Parking happens before every root re-render, so the same node re-mounts.
    assert util.count("parkMeetingCaptureEntry();") >= 2


def test_the_moved_bottom_entries_keep_their_behavior() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    # Same button element: the existing openConnectorsView listener still fires.
    assert 'if (connectorsNavButton) connectorsNavButton.addEventListener("click", openConnectorsView);' in app
    # The help link keeps its destination and needs no script.
    assert 'id="helpNavLink" href="./help.html"' in _html()


# ── 3. 옛 위치 링크(북마크·해시)가 새 위치로 이어짐 ─────────────────────────


def test_the_old_meeting_hash_continues_into_the_util_meeting_screen() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    # A stale #padiem-meeting bookmark lands on the Util tab's meeting tool
    # screen (#util/meeting) — the capture trigger is mounted there.
    assert 'window.location.hash = "#util/meeting";' in app
    # The capture screen itself still owns its fragment while it is open.
    assert '"#padiem-meeting"' in app
    assert "MEETING_ROUTE_HASH" in app


def test_the_connectors_hash_still_opens_the_connection_screen() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    assert "window.location.hash === CONNECTORS_ROUTE_HASH) openConnectorsView();" in app


def test_the_util_script_loads_before_the_moved_entry_consumers() -> None:
    html = _html()
    assert '<script src="./util-app.js" defer></script>' in html
    # meeting-capture binds the parked trigger at load; the util module mounts
    # the same node later — no ordering constraint between them, but the util
    # module must exist for its own boot.


# ── 4. 최근 대화: 외부 AI 도구 요청 기록 분리 ───────────────────────────────


def test_history_splits_connector_tool_requests_into_a_collapsed_group() -> None:
    history = HISTORY_PATH.read_text(encoding="utf-8")
    # One bounded prefix matches the server-side label of MCP PC-command rows.
    # The matcher mirrors the server label byte-for-byte via escapes: it is
    # data (never rendered), so no Hangul literal lands in the shipped source.
    assert 'const TOOL_REQUEST_PREFIX = "\\uc678\\ubd80 AI \\ub3c4\\uad6c \\uc694\\uccad:";' in history
    # A native <details> group keeps the rows searchable and accessible while
    # collapsed; the count rides the summary's ARIA label.
    assert 'document.createElement("details")' in history
    assert 'history-tool-requests-summary' in history
    assert 'deps.uiT("history-tool-request-group")' in history
    # The person's list emptiness no longer counts the tool-request rows.
    assert "deps.historyEmpty.hidden = normalConversationCount !== 0;" in history
    locale = LOCALE_PATH.read_text(encoding="utf-8")
    assert '"history-tool-request-group": "외부 AI 도구 요청"' in locale
    assert '"history-tool-request-group": "External tool requests"' in locale


def test_the_collapsed_group_has_its_own_styles() -> None:
    css = (STATIC / "history.css").read_text(encoding="utf-8")
    assert ".history-tool-requests" in css
    assert ".history-tool-requests-summary" in css


# ── 5. 동작: 유틸 회의 도구 화면에 캡처 진입점이 마운트된다 ──────────────────


HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const manifestSource = fs.readFileSync(process.argv[2], "utf8");
const source = fs.readFileSync(process.argv[3], "utf8");
const registry = [];

function El(tag) {
  return {
    tagName: (tag || "div").toUpperCase(), id: "", className: "", type: "",
    textContent: "", children: [], attrs: {}, dataset: {}, listeners: {},
    hidden: false, focused: false, parentElement: null,
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
  if (sel.startsWith(".")) return String(el.className || "").split(/\s+/).includes(sel.slice(1));
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  return el.tagName === sel.toUpperCase();
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }

const root = El("div"); root.id = "utilAppRoot"; registry.push(root);
const utilView = El("section"); utilView.id = "utilView"; utilView.hidden = true; registry.push(utilView);
const utilTitle = El("h2"); utilTitle.id = "utilTitle"; registry.push(utilTitle);
const utilKicker = El("p"); utilKicker.id = "utilKicker"; registry.push(utilKicker);
const utilTagline = El("p"); utilTagline.id = "utilTagline"; registry.push(utilTagline);
const shell = El("div"); shell.dataset = { state: "home" };
const appSwitch = El("nav"); appSwitch.id = "appSwitch"; registry.push(appSwitch);
const buttons = ["chat", "claw", "util"].map((app) => { const b = El("button"); b.dataset = { app }; return b; });
appSwitch.querySelectorAll = (sel) => (sel === "[data-app]" ? buttons : []);
const pdfHost = El("div"); pdfHost.id = "utilPdfmdHost"; registry.push(pdfHost);
const pdfPanel = El("div"); pdfPanel.id = "utilPdfmdPanel"; pdfPanel.parentElement = pdfHost; pdfHost.children.push(pdfPanel); registry.push(pdfPanel);
// #7365: the parked meeting trigger and its hidden host.
const meetingHost = El("div"); meetingHost.id = "meetingCaptureHost"; meetingHost.hidden = true; registry.push(meetingHost);
const meetingEntry = El("button"); meetingEntry.id = "meetingNavButton";
meetingEntry.className = "util-meeting-capture-entry";
meetingEntry.parentElement = meetingHost; meetingHost.children.push(meetingEntry); registry.push(meetingEntry);
const document = {
  readyState: "complete", documentElement: { lang: "ko" },
  createElement: (tag) => { const node = El(tag); registry.push(node); return node; },
  createTextNode: (text) => { const node = El("#text"); node.textContent = text; return node; },
  getElementById: (id) => { const hits = registry.filter((e) => e.id === id); return hits.length ? hits[hits.length - 1] : null; },
  querySelector: (sel) => (sel === ".app-shell" ? shell : null),
  addEventListener: () => {},
};
const loc = { hash: "", pathname: "/index.html", search: "" };
const history = { state: null, replaceState() {} };
const listeners = {};
const windowObj = { location: loc, history,
  addEventListener: (type, fn) => { listeners[type] = fn; } };
const sandbox = { document, window: windowObj, location: loc, history, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(manifestSource, sandbox, { filename: "util-manifest.js" });
vm.runInContext(source, sandbox, { filename: "util-app.js" });
const api = windowObj.PadiemUtilApp;
const result = { ok: true, checks: {} };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function fire(hash) { loc.hash = hash; if (listeners.hashchange) listeners.hashchange(); }

check("api", Boolean(api));
// The meeting tool screen carries the capture entry in its own body.
fire("#util/meeting");
const meetingScreen = find(root, ".util-tool-screen");
check("meeting_screen_rendered", Boolean(meetingScreen) && meetingScreen.getAttribute("data-util-tool") === "meeting");
const body = find(root, ".util-tool-body");
const entryInside = body && body.children.includes(meetingEntry);
check("capture_entry_mounted_in_tool_body", Boolean(entryInside));
check("capture_entry_outside_host", meetingEntry.parentElement !== meetingHost);
// Leaving the meeting tool parks the same node back into the hidden host.
fire("#util/pdfmd");
check("capture_entry_parked_back", meetingEntry.parentElement === meetingHost);
// Returning re-mounts the same node (no second copy).
fire("#util/meeting");
const meetingBodyAgain = find(root, ".util-tool-body");
check("capture_entry_remounted", meetingBodyAgain.children.includes(meetingEntry));
check("no_second_copy", registry.filter((e) => e.id === "meetingNavButton").length === 1);
console.log(JSON.stringify(result));
'''


def _run_node_script(script: str) -> dict:
    import os
    import tempfile

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".cjs", delete=False, encoding="utf-8", newline="\n",
    )
    try:
        handle.write(script)
        handle.close()
        completed = subprocess.run(
            ["node", handle.name, str(STATIC / "util-manifest.js"), str(UTIL_APP_PATH)],
            check=True,
            capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    return json.loads(completed.stdout.strip())


def test_the_meeting_entry_mounts_parks_and_remounts_in_the_util_module() -> None:
    result = _run_node_script(HARNESS)
    assert result["ok"] is True, result["checks"]
    checks = result["checks"]
    assert checks["meeting_screen_rendered"] is True
    assert checks["capture_entry_mounted_in_tool_body"] is True
    assert checks["capture_entry_outside_host"] is True
    assert checks["capture_entry_parked_back"] is True
    assert checks["capture_entry_remounted"] is True
    assert checks["no_second_copy"] is True
