"""#7780 — 사이드바 아래 메뉴를 프로필 메뉴로 모으는 계약.

바깥: 새 소식 · 의견 보내기 · 사용 안내 → 구분선 → [아바타] 이름 ▾.
프로필 메뉴(위로): 설정 · 앱 연결 · Padiem Home / 구분선 / 로그아웃 /
개인정보처리방침 · 이용약관. 게스트는 로그인 버튼 + 작은 메뉴 버튼으로
같은 메뉴를 열고, 로그아웃만 없다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-profile-menu-module.js").read_text(encoding="utf-8")
CSS = (STATIC / "sidebar-utility.css").read_text(encoding="utf-8")
TOKENS = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def _bottom() -> str:
    return HTML.split('class="sidebar-bottom"', 1)[1].split("</aside>", 1)[0]


def test_outer_three_in_owner_order_then_divider_then_account() -> None:
    bottom = _bottom()
    assert bottom.index('id="newsButton"') < bottom.index('id="feedbackButton"') < bottom.index('id="helpNavLink"')
    assert bottom.index('id="helpNavLink"') < bottom.index('class="sidebar-bottom-divider"')
    assert bottom.index('class="sidebar-bottom-divider"') < bottom.index('class="sidebar-account account-controls"')


def test_profile_menu_items_in_owner_order() -> None:
    menu = _bottom().split('id="profileMenu"', 1)[1]
    assert menu.index('id="settingsButton"') < menu.index('id="connectorsNavButton"') < menu.index('class="home-link"')
    assert menu.index('class="home-link"') < menu.index('class="profile-menu-divider"')
    assert menu.index('class="profile-menu-divider"') < menu.index('id="profileLogoutButton"')
    assert menu.index('id="profileLogoutButton"') < menu.index('data-locale-key="legal-privacy"')
    assert menu.index('data-locale-key="legal-privacy"') < menu.index('data-locale-key="legal-terms"')
    assert 'role="menu"' in HTML.split('id="profileMenu"', 1)[0].split("<div")[-1] or 'id="profileMenu" role="menu"' in HTML


def test_guest_has_login_button_and_small_menu_button_no_logout_in_menu() -> None:
    bottom = _bottom()
    assert 'id="loginButton"' in bottom
    assert 'id="profileGuestMenuButton"' in bottom
    guest = bottom.split('id="profileGuestMenuButton"', 1)[1].split(">", 1)[0]
    assert 'aria-haspopup="menu"' in guest
    assert 'aria-controls="profileMenu"' in guest
    assert 'aria-expanded="false"' in guest
    # 로그아웃은 게스트에서 모듈이 숨긴다(마크업에는 signed_in 전용으로 둔다).
    assert 'logout.hidden = !(state === "signed_in")' in MODULE


def test_profile_toggle_menu_aria_and_settings_connectors_entries_kept() -> None:
    assert 'profileToggle.setAttribute("aria-controls", "profileMenu")' in MODULE
    assert 'profileToggle.setAttribute("aria-haspopup", "menu")' in MODULE
    # B7: the settings API is reached through the registry (app.provide("settings")).
    assert 'settingsButton.addEventListener("click", () => { closeProfilePanel(); settings.openSettings(); })' in APP
    connectors = (STATIC / "chat-connectors-module.js").read_text(encoding="utf-8") if (STATIC / "chat-connectors-module.js").exists() else APP
    assert 'connectorsNavButton.addEventListener("click", openConnectorsView)' in connectors
    assert 'settingsLogoutButton' in HTML
    assert 'settingsLogoutButton' in MODULE


def test_dividers_and_chevron_use_existing_tokens_only() -> None:
    outer = CSS.split(".sidebar-bottom-divider {", 1)[1].split("}", 1)[0]
    assert "var(--input-border-strong)" in outer
    assert "#" not in outer
    menu_divider = CSS.split(".sidebar-account .profile-menu-divider {", 1)[1].split("}", 1)[0]
    assert "var(--input-border-strong)" in menu_divider
    assert "#" not in menu_divider
    # Glass 사이드바는 어두워 밝은 선 토큰으로 겹친다.
    assert 'html[data-theme="padiem-glass"] .sidebar-bottom-divider' in CSS
    chevron = CSS.split(".sidebar-account .account-profile-toggle::after {", 1)[1].split("}", 1)[0]
    assert "font-size: 16px" in chevron
    assert "color: inherit" in chevron
    assert '[aria-expanded="true"]::after' in CSS
    assert "rotate(180deg)" in CSS
    for token in ("--input-border-strong", "--line", "--panel", "--accent-soft"):
        assert token in TOKENS


def test_menu_items_share_size_weight_and_icon_size() -> None:
    block = CSS.split("/* 메뉴 항목은 글자 크기·굵기·아이콘 크기를 한 가지로 맞춘다. */", 1)[1].split(".sidebar-account .profile-menu-logout:hover", 1)[0]
    for sel in (".profile-menu .settings-button", ".profile-menu .side-item", ".profile-menu .home-link", ".profile-menu .profile-menu-logout"):
        assert sel in block
    assert block.count("font-size: 14px") == 1
    assert block.count("font-weight: 650") == 1
    assert "font-size: 16px" in block
    assert "width: 22px" in block
    # 설정·로그아웃 아이콘도 같은 아이콘 칸을 쓴다.
    assert '<span class="side-icon" aria-hidden="true">⚙</span>' in HTML
    assert '<span class="side-icon" aria-hidden="true">→</span>' in HTML


def _token_hex(name: str) -> tuple[int, int, int]:
    import re

    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", TOKENS)
    assert match, name
    value = match.group(1)
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    def lum(rgb: tuple[int, int, int]) -> float:
        def lin(v: int) -> float:
            s = v / 255
            return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
        return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])
    hi, lo = max(lum(fg), lum(bg)), min(lum(fg), lum(bg))
    return (hi + 0.05) / (lo + 0.05)


def test_light_theme_hero_second_line_and_empty_text_contrast() -> None:
    themes = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
    # #7817: the second line reads one theme token, so the light value lives in
    # the token sheet and no theme sheet overrides the rule any more.
    assert 'html[data-theme="light"] .empty-state h1 br + span' not in themes
    light = TOKENS.split('html[data-theme="light"] {', 1)[1].split("}", 1)[0]
    assert "--hero-sub-color: var(--muted);" in light
    hero = "--hero-sub-color: var(--muted);"
    assert "#" not in hero
    empty = themes.split('html[data-theme="light"] .sidebar .history-empty {', 1)[1].split("}", 1)[0]
    assert "var(--text)" in empty
    assert "!important" in empty, "cinematic-workspace의 !important 흰 규칙을 이겨야 한다"
    assert "#" not in empty
    # 실제 계산 색: cinematic-workspace의 .history-empty !important 흰 규칙이
    # 라이트에서 이기면 묻힌다. 라이트 규칙이 !important로 이기는지 확인한다.
    cinematic = (STATIC / "padiem-cinematic-workspace.css").read_text(encoding="utf-8")
    assert ".history-empty," in cinematic and "rgba(255, 255, 255, .52) !important" in cinematic
    # 홈 두 번째 줄은 페이지 표면 위에, 빈 문구는 페이지 표면 위에 놓인다.
    assert _contrast(_token_hex("--muted"), _token_hex("--page-bg")) >= 4.5
    assert _contrast(_token_hex("--text"), _token_hex("--page-bg")) >= 4.5


def test_glass_connectors_icon_inherits_menu_text_color() -> None:
    block = CSS.split('html[data-theme="padiem-glass"] .sidebar-account .profile-menu .side-icon,', 1)[1].split("}", 1)[0]
    assert "color: inherit" in block


HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function El(id) {
  return {
    id, hidden: false, attrs: {}, dataset: {}, listeners: {}, focused: false,
    children: [], offsetParent: {}, parentElement: null,
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k] || null; },
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    fire(t, ev) { (this.listeners[t] || []).forEach((fn) => fn(ev)); },
    focus() { this.focused = true; document.activeElement = this; },
    contains(x) { return x === this || this.children.includes(x); },
    querySelector() { return menuItems.find((el) => !el.hidden) || null; },
    querySelectorAll() { return menuItems.slice(); },
  };
}
const settingsBtn = El("settingsButton"), connectorsBtn = El("connectorsNavButton"),
  homeLink = El("home-link"), logoutBtn = El("profileLogoutButton"),
  settingsLogout = El("settingsLogoutButton");
let settingsLogoutClicks = 0;
settingsLogout.click = () => { settingsLogoutClicks += 1; };
const menuItems = [settingsBtn, connectorsBtn, homeLink, logoutBtn];
const menu = El("profileMenu"); menu.hidden = true;
menu.contains = () => false;
const profileToggle = El("accountProfileButton"), guestBtn = El("profileGuestMenuButton");
const account = El("sidebar-account"); account.dataset = { accountState: "signed_in" };
const docListeners = {}, winListeners = {};
const document = {
  readyState: "complete", activeElement: null,
  getElementById(id) {
    return ({ profileMenu: menu, accountProfileButton: profileToggle, profileGuestMenuButton: guestBtn,
      profileLogoutButton: logoutBtn, settingsLogoutButton: settingsLogout }[id] || null);
  },
  querySelector(sel) { return sel === ".sidebar-account" ? account : null; },
  contains(x) { return x === profileToggle || x === guestBtn || x === menu; },
  addEventListener(t, fn) { (docListeners[t] = docListeners[t] || []).push(fn); },
};
const windowObj = { addEventListener(t, fn) { (winListeners[t] = winListeners[t] || []).push(fn); } };
const sandbox = { document, window: windowObj, console,
  MutationObserver: class { observe() {} } };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "chat-profile-menu-module.js" });
const result = { ok: true, checks: {} };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function fireDoc(t, ev) { (docListeners[t] || []).forEach((fn) => fn(ev)); }
function closeEv() { return { key: "Escape", isComposing: false }; }

check("aria_controls_menu", profileToggle.attrs["aria-controls"] === "profileMenu");
check("aria_haspopup_menu", profileToggle.attrs["aria-haspopup"] === "menu");
check("signedin_logout_visible", logoutBtn.hidden === false);

// 열기: 첫 항목 포커스.
profileToggle.focus();
windowObj.PadiemChatProfileMenu.toggle();
check("open_unhides", menu.hidden === false);
check("open_expanded_true", profileToggle.attrs["aria-expanded"] === "true" && guestBtn.attrs["aria-expanded"] === "true");
check("open_focus_first", settingsBtn.focused === true);

// 화살표 이동.
menu.fire("keydown", { key: "ArrowDown", isComposing: false, preventDefault() {} });
check("arrow_down_next", connectorsBtn.focused === true);
menu.fire("keydown", { key: "ArrowUp", isComposing: false, preventDefault() {} });
check("arrow_up_prev", settingsBtn.focused === true);
menu.fire("keydown", { key: "End", isComposing: false, preventDefault() {} });
check("end_last", logoutBtn.focused === true);
menu.fire("keydown", { key: "Home", isComposing: false, preventDefault() {} });
check("home_first", settingsBtn.focused === true);

// Esc: 닫고 토글로 포커스 복귀.
fireDoc("keydown", closeEv());
check("esc_closes", menu.hidden === true);
check("esc_expanded_false", profileToggle.attrs["aria-expanded"] === "false");
check("esc_restores_focus", document.activeElement === profileToggle);

// 바깥 클릭: 닫힘.
windowObj.PadiemChatProfileMenu.toggle();
check("reopen", menu.hidden === false);
fireDoc("pointerdown", { target: {} });
check("outside_closes", menu.hidden === true);

// 항목 선택: 닫힘.
windowObj.PadiemChatProfileMenu.toggle();
const itemEv = { target: { closest: () => settingsBtn } };
menu.fire("click", itemEv);
check("item_closes", menu.hidden === true);

// 로그아웃 위임: 설정 창 안 버튼을 그대로 누른다.
logoutBtn.fire("click", {});
check("logout_delegates", settingsLogoutClicks === 1);

// 게스트: 로그아웃 숨김.
account.dataset.accountState = "guest";
windowObj.PadiemChatProfileMenuModule.create().syncLogoutVisibility();
check("guest_logout_hidden", logoutBtn.hidden === true);
console.log(JSON.stringify(result));
'''


def test_profile_menu_keyboard_and_close_behaviour() -> None:
    import os
    import tempfile

    handle = tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8", newline="\n")
    try:
        handle.write(HARNESS)
        handle.close()
        completed = subprocess.run(
            ["node", handle.name, str(STATIC / "chat-profile-menu-module.js")],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    result = json.loads(completed.stdout.strip())
    assert result["ok"] is True, result["checks"]
    assert all(result["checks"].values()), result["checks"]
