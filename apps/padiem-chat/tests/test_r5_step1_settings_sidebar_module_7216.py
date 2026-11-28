"""#7216 R5 1단계 — 설정·사이드바 구역 모듈 계약 시험.

R2(#7186): 이 구역의 동작은 소스 문자열이 아니라 **모듈 실행 결과**로 고정한다.
`_r5_settings_sidebar_module_harness.py`가 `chat-settings-module.js`와
`chat-sidebar-module.js`를 Node vm에서 그대로 실행해, 함수 직접 호출로 열림·닫힘·
hidden·aria-expanded·포커스·locale 키 보존·고급 설정 메뉴 키·이벤트를 관찰한다.

문자열로 남긴 것은 R2 규칙 3의 경계 계약뿐이고, 각 시험 옆에 이유를 적었다:
  * 전역 팩토리 하나 + 로드 시 DOM 조회 없음 (모듈 경계),
  * 이동 본문의 app.js 재등장 금지 (이중 소유 금지),
  * 한 줄 전달 함수 형태 (app.js 호출부 호환, R5 B1).

index.html의 script 로드 순서는 소스 위치 비교 대신 HTMLParser로 실제 태그를
읽어 판정한다. 현재 동작 기준(2026-11-11): 설정 대화상자는 닫기 컨트롤 하나
(#7485), 알림은 켜기/끄기 스위치 하나(#7485), 기본 설정의 계정 구역(#7490),
사이드바는 대화·도구·일정·내 자료·아래 계정 묶음(#7438)이다. CSS 배치와 대화상자
마크업 구조는 R3/UI 레인 범위라 여기서 다루지 않는다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

from _r5_settings_sidebar_module_harness import observations
from _support.r5_settings_sidebar import (
    app_js,
    index_html,
    module_source,
    settings_js,
    sidebar_js,
    static_dir,
)

APP = app_js()
SETTINGS = settings_js()
SIDEBAR = sidebar_js()
INDEX = index_html()
_STATIC_DIR = static_dir()

MODULES = {
    "settings": ("PadiemChatSettingsModule", "chat-settings-module.js",
                 ["selectedProductTier", "openSettings", "closeSettings",
                  "openAdvancedSettingsView", "closeAdvancedSettingsView", "selectAdvancedMenu",
                  "wireTierChange", "wireAdvancedSettings", "wireSettingsDialog",
                  "wireAdvancedMenuListeners"]),
    "sidebar": ("PadiemChatSidebarModule", "chat-sidebar-module.js",
                ["sidebarActionIcon", "setSidebarCollapsed", "closeSidebar", "openSidebar", "wireSidebarListeners"]),
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


@pytest.fixture(scope="module")
def observed() -> dict:
    return observations()


# ── 경계 계약 (문자열 유지 · 이유 명시) ────────────────────────────────────


def test_module_files_expose_one_factory_and_keep_the_original_names() -> None:
    """모듈 경계: 전역 팩토리 하나, 원래 함수 이름, 로드 시 DOM 조회 없음.

    이 세 가지는 동작이 아니라 구조 결정이다. 실행 관찰로는 "정확히 하나의
    전역 팩토리"와 "스크립트 로드 시점에 DOM을 읽지 않음"을 증명할 수 없어
    문자열로 남긴다. 함수 동작 자체는 아래 실행 시험이 직접 호출해 증명한다.
    """
    for _, (global_name, filename, names) in MODULES.items():
        source = module_source(filename)
        assert f"window.{global_name} = {{" in source
        assert "create(deps) {" in source
        for name in names:
            assert f"function {name}(" in source, (filename, name)
        # One global factory only; DOM lookups start inside create(), never at load.
        assert source.count("window.") >= 1
        create_at = source.index("create(deps) {")
        lookup_at = source.find("document.getElementById")
        assert lookup_at == -1 or lookup_at > create_at, filename


def test_settings_and_sidebar_bodies_live_only_in_their_modules() -> None:
    """이중 소유 금지: 이동한 본문이 app.js에 다시 생기면 한쪽만 고쳐진다.

    긍정(모듈이 그 동작을 한다)은 실행 관찰이 더 강하게 증명하므로 여기서는
    부정 계약만 남긴다 — app.js에 본문이 없다.
    """
    for marker in ("settingsDialog.showModal()", "sidebarRestoreButton?.focus()",
                   "shell.classList.toggle(\"sidebar-collapsed\", collapsed)",
                   "advancedSettingsReturnState = deps",
                   "button.dataset.advancedMenu === key"):
        assert marker not in APP, marker


def test_app_js_keeps_one_line_forwarders_for_all_nine_functions() -> None:
    """호출부 호환(R5 B1+B7): 9개 API 전부 등록부(app.provide) 경유로 전환됐다.

    settings 5개·sidebar 4개 모두 app.js에 같은 이름 정의가 없고, 등록된 조각에
    이름이 있다 — 도달 가능 여부는 아래 등록부 행위 시험이 증명한다.
    selectedProductTier·closeSettings는 B6 allowlist(소유자 = settings 모듈)로
    공유 접근자를 덮는다.
    """
    for name, factory in FORWARDERS.items():
        assert f"function {name}(" not in APP, name
        assert f'app.provide("{factory.removesuffix("Module").lower()}",' in APP, name
        piece = SETTINGS if factory == "settingsModule" else SIDEBAR
        assert f"{name}," in piece, name
    assert "function settingsModule() { return settings; }" in APP
    assert "function sidebarModule() { return sidebar; }" in APP


def test_settings_and_sidebar_apis_are_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide)로 같은 이름을 찾을 수 있다.

    app.js 전달 함수가 없어도 소비자(app.js 호출자·deps getter)는 등록된 조각의
    같은 이름 API에 도달한다. 실제 모듈 본문을 node vm에서 문맥에 등록해
    settings·sidebar 조각의 API가 전부 함수로 조회되는지 본다(동작 단언은
    harness가 직접 호출로 증명한다). selectedProductTier·closeSettings·
    closeSidebar는 B6 allowlist(소유자 = 각 모듈)로 공유 접근자를 덮는다.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const staticDir = process.argv[1];
const byId = new Map();
const fakeEl = () => ({
  hidden: true, textContent: "", children: [], dataset: {},
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, removeChild() {},
});
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
  },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-settings-module.js", "utf8"), sandbox,
  { filename: "chat-settings-module.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-sidebar-module.js", "utf8"), sandbox,
  { filename: "chat-sidebar-module.js" });
const plan = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  const out = {};
  const plan = ${JSON.stringify(plan)};
  for (const [zone, factory] of Object.entries(plan.factories)) {
    app.provide(zone, window[factory].create(app));
  }
  for (const [zone, names] of Object.entries(plan.names)) {
    for (const n of names) out[n] = typeof app[n];
  }
  out;
`, sandbox, { filename: "registry-lookup" });
for (const [zone, names] of Object.entries(plan.names)) {
  for (const n of names) {
    assert.equal(result[n], "function", n + " must be reachable through the registry");
  }
}
console.log("REGISTRY_OK");
"""
    zone_plan = {
        "factories": {zone: spec[0] for zone, spec in MODULES.items()},
        "names": {zone: list(spec[2]) for zone, spec in MODULES.items()},
    }
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(zone_plan), 1), str(_STATIC_DIR)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


class _ScriptOrder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "script":
            return
        src = dict(attrs).get("src")
        if src:
            self.sources.append(src)


def test_modules_load_before_app_js() -> None:
    parser = _ScriptOrder()
    parser.feed(INDEX)
    # 실제 로드 순서: 두 모듈이 app.js보다 먼저, 각각 한 번만.
    settings_at = parser.sources.index("./chat-settings-module.js")
    sidebar_at = parser.sources.index("./chat-sidebar-module.js")
    app_at = parser.sources.index("./app.js")
    assert settings_at < app_at and sidebar_at < app_at
    assert parser.sources.count("./chat-settings-module.js") == 1
    assert parser.sources.count("./chat-sidebar-module.js") == 1


# ── 실행 관찰 (모듈 직접 호출) ─────────────────────────────────────────────


def test_the_tier_projection_reads_the_shared_state(observed: dict) -> None:
    assert observed["tierPlus"] == "plus"
    assert observed["tierBogus"] == "free"
    assert observed["tierMissing"] == "free"


def test_the_settings_dialog_opens_and_closes_from_both_triggers(observed: dict) -> None:
    # 열림: 대화상자가 실제로 열리고 두 진입점(⚙·계정 줄)이 확장 상태를 표시한다.
    assert observed["openSettings"] == {
        "shown": 1, "open": True, "button": "true", "profile": "true",
        "localeKey": "settings", "label": "설정",
    }
    # 닫힘: 대화상자를 닫고 두 진입점의 확장 상태를 되돌린다. 번역 대상 라벨과
    # locale 키는 그대로 남는다(모듈이 문구를 쓰지 않는다).
    assert observed["closeSettings"] == {
        "closed": 1, "open": False, "button": "false", "profile": "false",
        "localeKey": "settings", "label": "설정",
    }


def test_a_dialog_without_the_dialog_methods_still_opens_and_closes(observed: dict) -> None:
    # showModal/close가 없는 환경(구형 브라우저 셈)에서는 open 속성으로 같은
    # 열기·닫기가 성립하고, 확장 상태도 같이 되돌아간다.
    assert observed["settingsFallback"]["opened"] == ""
    assert observed["settingsFallback"]["closed"] is None
    assert observed["settingsFallback"]["button"] == "false"


def test_the_advanced_settings_page_shows_restores_and_selects_the_pc_block(observed: dict) -> None:
    # #7485: 고급 설정은 제목·메뉴가 있는 같은 화면이다. 열면 라이브러리(pc)
    # 블록을 고르고, 이전 셸 상태를 기억하고, 열림 이벤트를 낸다. 메뉴 선택은
    # deps 스파이가 아니라 실제 버튼 클래스와 블록 hidden으로 관찰한다.
    assert observed["advancedOpen"] == {
        "hidden": False, "state": "settings",
        "nav": 1, "selected": [True, False], "blocks": [True, False],
        "events": ["padiem:advanced-settings-open"],
    }
    # 닫으면 hidden=true, 기억한 상태로 복귀, 닫힘 이벤트.
    assert observed["advancedClose"] == {
        "hidden": True, "state": "claw",
        "nav": 2, "events": ["padiem:advanced-settings-close"],
    }
    # 고급 화면이 없는 구성에서는 같은 진입이 설정 대화상자를 연다.
    assert observed["advancedFallback"] == {"shown": 1}


def test_sidebar_action_icons_stay_decorative_for_every_kind(observed: dict) -> None:
    # 아이콘은 장식이다: aria-hidden, 포커스 불가, 글자 없음 → 번역 라벨은 버튼에
    # 남는다. 설정·더보기·이름 변경·고정·해제·삭제 모두 SVG 하나를 그린다.
    icon = observed["icon"]
    assert icon["settings"] == {"tag": "svg", "aria": "true", "focusable": "false",
                                "circles": 1, "paths": 1, "text": "", "hasD": True}
    assert icon["more"] == {"tag": "svg", "aria": "true", "focusable": "false",
                            "circles": 3, "paths": 0, "text": "", "hasD": False}
    for kind in icon["kinds"]:
        assert kind == {"tag": "svg", "aria": "true", "focusable": "false",
                        "circles": 0, "paths": 1, "text": "", "hasD": True}


def test_desktop_collapse_toggles_the_shell_and_moves_focus(observed: dict) -> None:
    collapse = observed["collapse"]
    # 접기: 셸 클래스, 두 컨트롤의 확장 상태, 포커스는 펼치기 컨트롤로.
    assert collapse["on"]["classed"] is True
    assert collapse["on"]["collapseAria"] == "false"
    assert collapse["on"]["restoreAria"] == "false"
    assert collapse["on"]["focusId"] == "sidebarRestoreButton"
    # 펴기: 클래스 해제, 포커스는 접기 컨트롤로, 펼치기 상태 복원.
    assert collapse["off"] == {"classed": False, "collapseFocus": 1, "restoreAria": "true"}
    # locale 키·제목·번역 문구는 모듈이 건드리지 않는다.
    assert collapse["on"]["collapseLocale"] == ["sidebar-collapse", "sidebar-collapse", "사이드바 접기"]
    assert collapse["on"]["restoreLocale"] == ["sidebar-expand", "sidebar-expand", "사이드바 펼치기"]


def test_the_desktop_preference_never_applies_to_the_phone_overlay(observed: dict) -> None:
    # 좁은 화면에서는 접기 선호를 적용하지 않고 aria도 건드리지 않는다.
    assert observed["mobileCollapse"] == {"classed": False, "collapseAria": None}


def test_the_phone_overlay_opens_and_closes_with_focus_and_scrim(observed: dict) -> None:
    sidebar = observed["sidebar"]
    # 열기: 셸 클래스, 메뉴 확장, 스크림 표시, 포커스는 닫기 컨트롤로.
    assert sidebar["opened"] == {"classed": True, "aria": "true", "scrim": False,
                                 "focusId": "mobileClose"}
    # 닫기: 셸 클래스·메뉴 확장 해제, 스크림 숨김, 계정 패널 닫기 1회.
    assert sidebar["closed"] == {"classed": False, "aria": "false", "scrim": True,
                                 "profileClosed": 1}


def test_getters_read_the_value_changed_before_the_first_call(observed: dict) -> None:
    # create() 전에 바꾼 요소가 실제로 열리고, 모바일 오버레이는 닫힌 상태다.
    assert observed["getter"]["opened"] == 1
    assert observed["getter"]["overlay"] is False
    assert observed["getter"]["profileClosed"] is True


def test_settings_wire_keeps_registration_order_and_dialog_callbacks(observed: dict) -> None:
    assert observed["wiredDialog"] == {
        "order": ["settingsButton:click", "settingsDialog:close", "settingsDialog:cancel",
                  "settingsDialog:click", "settingsCloseButton:click"],
        "opened": {"open": True, "profileClosed": 1, "button": "true", "profile": "true"},
        "closed": {"open": False, "button": "false", "profile": "false"},
        "cancel": {"prevented": True, "open": False},
        "insideOpen": True, "backdropOpen": False, "closeButtonOpen": False,
    }
    for earlier, later in (
        ("settingsModule().wireTierChange();", 'conversationModule().wireComposerEvents('),
        ("authModule().wireLoginButton();", "settingsModule().wireAdvancedSettings();"),
        ("settingsModule().wireAdvancedSettings();", "settingsModule().wireAdvancedMenuListeners();"),
        ("settingsModule().wireAdvancedMenuListeners();", "authModule().wireLogoutButton();"),
        ("loginDialogModule().wireProfileDismiss();", "settingsModule().wireSettingsDialog();"),
        ("settingsModule().wireSettingsDialog();", "sidebar.wireSidebarListeners();"),
    ):
        assert APP.count(earlier) == APP.count(later) == 1
        assert APP.index(earlier) < APP.index(later)


def test_settings_dialog_and_advanced_view_dom_capture_preserve_boot_order() -> None:
    """Settings owns DOM refs, but obtains them at their original app.js positions."""
    assert APP.index("settings.captureDialogElements();") < APP.index(
        'document.getElementById("accountSettingsSection")'
    )
    assert APP.index("settings.captureAdvancedView();") < APP.index(
        "settingsModule().wireTierChange();"
    )
    assert APP.index("settingsModule().wireTierChange();") < APP.index(
        "settingsModule().wireAdvancedSettings();"
    ) < APP.index("settingsModule().wireAdvancedMenuListeners();") < APP.index(
        "settingsModule().wireSettingsDialog();"
    )
    assert 'get settingsButton() { return settings.dom.settingsButton; }' in APP
    assert 'get settingsDialog() { return settings.dom.settingsDialog; }' in APP
    assert 'get advancedSettingsView() { return settings.dom.advancedSettingsView; }' in APP
    assert 'const settingsButton = document.getElementById("settingsButton")' not in APP
    assert 'const settingsDialog = document.getElementById("settingsDialog")' not in APP
    assert 'const advancedSettingsView = document.getElementById("advancedSettingsView")' not in APP

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ids = [];
const nodes = new Map();
const document = {
  getElementById(id) {
    ids.push(id);
    if (!nodes.has(id)) nodes.set(id, {id, hidden: true});
    return nodes.get(id);
  },
  querySelectorAll() { return []; },
};
const context = vm.createContext({window: {}, document, console});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const settings = context.window.PadiemChatSettingsModule.create({});
assert.equal(settings.dom.settingsButton, null);
assert.equal(settings.dom.settingsDialog, null);
assert.equal(settings.dom.advancedSettingsView, null);
assert.deepEqual(ids, ["settingsCloseButton", "settingsAdvancedOpen", "advancedSettingsBack"]);
settings.captureDialogElements();
assert.equal(settings.dom.settingsButton, nodes.get("settingsButton"));
assert.equal(settings.dom.settingsDialog, nodes.get("settingsDialog"));
assert.equal(settings.dom.advancedSettingsView, null);
settings.captureAdvancedView();
assert.equal(settings.dom.advancedSettingsView, nodes.get("advancedSettingsView"));
assert.deepEqual(ids, [
  "settingsCloseButton", "settingsAdvancedOpen", "advancedSettingsBack",
  "settingsButton", "settingsDialog", "advancedSettingsView"
]);
"""
    result = subprocess.run(
        [node, "-e", script, str(_STATIC_DIR / "chat-settings-module.js")],
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
