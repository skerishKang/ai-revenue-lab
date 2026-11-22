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

호출부 계약은 _support가 파싱한 값으로, 유틸 마운트 동작은 Node DOM 셈 하네스
(test_util_app_7173과 같은 패턴)로 검증한다. 시험은 정적 원문을 직접 읽지 않는다.
"""
from __future__ import annotations

import json
import subprocess

from _r5_auth_module_harness import observations as auth_observations
from _support import sidebar_groups_7365 as support


# ── 1. 새 구성 렌더 (묶음 순서) ─────────────────────────────────────────────


def test_sidebar_groups_render_in_the_owner_decided_order() -> None:
    chat_ids = support.chat_group_ids()
    assert "newChatButton" in chat_ids
    assert "sidebarSearchButton" in chat_ids
    assert "clawNavButton" in chat_ids
    # 도구·일정: 유틸 · 캘린더 · 자동화 · 라이브러리 (대표 결정 순서).
    positions = support.tool_nav_positions()
    assert list(positions.values()) == sorted(positions.values()), "도구·일정 순서는 유틸·캘린더·자동화·라이브러리"
    assert "meetingNavButton" not in support.tool_nav_ids(), "회의록 항목은 사이드바에서 제거"
    # 내 자료: 프로젝트 · 최근 대화 (순서 유지).
    sections = support.sidebar_section_positions()
    assert sections["projectsSection"] < sections["historySection"]
    # 아래 계정(#7780 대표 결정): 바깥 새 소식 · 의견 보내기 · 사용 안내,
    # 프로필 메뉴 안 설정 · 앱 연결 · Padiem Home, 약관 · 계정.
    bottom = support.bottom_positions()
    outer = [bottom[key] for key in ("newsButton", "feedbackButton", "helpNavLink")]
    assert outer == sorted(outer), "바깥 순서는 새 소식·의견 보내기·사용 안내"
    assert bottom["helpNavLink"] < bottom["sidebar-account account-controls"]
    menu = support.menu_positions()
    assert menu["settingsButton"] < menu["connectorsNavButton"] < menu["home-link"], "메뉴 순서는 설정·앱 연결·Padiem Home"
    # #7953 대표 결정: 약관 줄은 메뉴 밖 계정 단추 바로 아래 상시 한 줄이다.
    assert "legal-privacy" not in support.menu_locale_keys()
    assert "sidebar-legal" in support.bottom_classes()
    assert bottom["sidebar-legal"] > bottom["profileMenu"]
    assert "accountAvatar" in support.bottom_ids()
    assert "home-link" in support.menu_classes()


def test_the_util_row_uses_a_pictograph_icon_like_its_peers() -> None:
    # #7365 후속(CTO 261111): the util row reads like the other tool rows —
    # a geometric pictograph, never a letter.
    glyphs = support.util_button_glyphs()
    assert "▣" in glyphs
    assert "U" not in glyphs


def test_settings_is_a_first_class_account_menu_entry_for_guests_too() -> None:
    # The settings entry carries no hidden attribute: guests and signed-in
    # accounts both see it in the profile menu beside 앱 연결 · Padiem Home.
    assert support.settings_button_hidden() is False


def test_guests_see_the_materials_group_honestly_empty() -> None:
    # R2(#7186): the guest projection is observed by executing
    # chat-auth-module.js with the shipped guest session — the history group and
    # its empty note stay visible (no failure rows for an empty account).
    guest = auth_observations()["states"]["guest"]
    assert guest["historyHidden"] is False
    assert guest["historyEmptyHidden"] is False
    assert guest["settingsHidden"] is True
    # Boundary kept as parsed assignments: clearProjectsUI lives in app.js,
    # which no module owns (R5 did not move it), so its markup assignment has
    # no execution harness. This is the projects half of the same #7438 decision.
    assignments = support.clear_project_assignments()
    assert "projectsSection.hidden = false;" in assignments
    assert "projectsEmpty.hidden = false;" in assignments


def test_the_tools_group_names_itself_for_screen_readers() -> None:
    binding = support.tools_menu_binding()
    assert binding["aria_label"] == "도구·일정"
    assert binding["ko"] == "도구·일정"
    assert binding["en"] == "Tools & schedule"
    # The aria applier binds the renamed landmark on language change.
    assert binding["aria_binding"] == ["#workspaceNav", "aria-label", "tools-menu"]


# ── 2. 옮긴 항목이 새 위치에서 같은 동작 ────────────────────────────────────


def test_the_meeting_trigger_is_parked_in_the_util_view() -> None:
    # Same element, same id: meeting-capture.js finds it at load and the click
    # opens the existing capture screen.
    trigger = support.meeting_trigger()
    assert trigger["id_count"] == 1
    assert trigger["host_hidden"] is True
    assert trigger["host_after_util"] is True
    assert "util-meeting-capture-entry" in trigger["entry_classes"]
    assert trigger["aria_controls"] == "meetingView"
    assert "nav-meeting" in trigger["locale_keys"]


def test_util_module_mounts_the_meeting_entry_into_its_tool_screen() -> None:
    # The parked-node pattern (the same one the legacy PDF panel uses).
    facts = support.meeting_park_facts()
    assert "meetingCaptureHost" in facts["looked_up_ids"]
    assert "meeting" in facts["dispatched_ids"]
    # Parking happens before every root re-render, so the same node re-mounts.
    assert facts["park_calls"] >= 2


def test_the_moved_bottom_entries_keep_their_behavior() -> None:
    # Same button element: the click listener moved into the connectors module
    # (#7216 A9), and app.js keeps the single wire call at the original spot.
    facts = support.moved_bottom_facts()
    assert facts["connector_listener"] is True
    assert facts["wire_calls"] == 1
    # The help link keeps its destination and needs no script.
    assert facts["help_href"] == "./help.html"


# ── 3. 옛 위치 링크(북마크·해시)가 새 위치로 이어짐 ─────────────────────────


def test_the_old_meeting_hash_continues_into_the_util_meeting_screen() -> None:
    # A stale #padiem-meeting bookmark lands on the Util tab's meeting tool
    # screen (#util/meeting) — the capture trigger is mounted there.
    facts = support.hash_facts()
    assert "#util/meeting" in facts["hash_assignments"]
    # The capture screen itself still owns its fragment while it is open.
    assert facts["padiem_meeting_literal"] is True
    assert facts["meeting_route_hash_count"] > 0


def test_the_connectors_hash_still_opens_the_connection_screen() -> None:
    assert support.hash_facts()["connectors_dispatch"] is True


def test_the_util_script_loads_before_the_moved_entry_consumers() -> None:
    assert ("./util-app.js", True) in support.util_script_facts()
    # meeting-capture binds the parked trigger at load; the util module mounts
    # the same node later — no ordering constraint between them, but the util
    # module must exist for its own boot.


# ── 4. 최근 대화: 외부 AI 도구 요청 기록 분리 ───────────────────────────────


def test_history_splits_connector_tool_requests_into_a_collapsed_group() -> None:
    # One bounded prefix matches the server-side label of MCP PC-command rows.
    # The matcher mirrors the server label byte-for-byte via escapes: it is
    # data (never rendered), so no Hangul literal lands in the shipped source.
    facts = support.history_group_facts()
    assert facts["tool_request_prefix"] == "외부 AI 도구 요청:"
    # A native <details> group keeps the rows searchable and accessible while
    # collapsed; the count rides the summary's ARIA label.
    assert facts["details_created"] >= 1
    assert facts["has_summary"] is True
    assert "history-tool-request-group" in facts["ui_t_keys"]
    # A visible tool-request group is a non-empty history list as well.
    assert facts["history_empty_condition"] == "normalConversationCount + toolRequestRows.length !== 0"
    assert facts["copy_ko"] == "외부 AI 도구 요청"
    assert facts["copy_en"] == "External tool requests"


def test_the_collapsed_group_has_its_own_styles() -> None:
    selectors = support.history_css_selectors()
    assert ".history-tool-requests" in selectors
    assert ".history-tool-requests-summary" in selectors


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
            ["node", handle.name, str(support.STATIC / "util-manifest.js"),
             str(support.STATIC / "util-app.js")],
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
