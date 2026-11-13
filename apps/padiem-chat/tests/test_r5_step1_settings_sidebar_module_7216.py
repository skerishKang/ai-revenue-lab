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

from html.parser import HTMLParser
from pathlib import Path

import pytest

from _r5_settings_sidebar_module_harness import observations

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "chat-settings-module.js").read_text(encoding="utf-8")
SIDEBAR = (STATIC / "chat-sidebar-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

MODULES = {
    "settings": ("PadiemChatSettingsModule", "chat-settings-module.js",
                 ["selectedProductTier", "openSettings", "closeSettings",
                  "openAdvancedSettingsView", "closeAdvancedSettingsView", "selectAdvancedMenu",
                  "wireAdvancedMenuListeners"]),
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
        source = (STATIC / filename).read_text(encoding="utf-8")
        assert f"window.{global_name} = {{" in source
        assert "create(deps) {" in source
        for name in names:
            assert f"function {name}(" in source, (filename, name)
        # One global factory only; no second authority and no DOM lookup at load.
        assert source.count("window.") >= 1
        assert "document.getElementById" not in source


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
    """호출부 호환(R5 B1): app.js의 한 줄 전달 함수 형태는 구조 결정이다.

    모듈 함수 동작은 harness가 직접 호출해 증명하므로, 여기서는 전달 함수의
    모양과 유일성만 고정한다.
    """
    for name, factory in FORWARDERS.items():
        line = f"function {name}(...a) {{ return {factory}().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function settingsModule() {" in APP
    assert "function sidebarModule() {" in APP


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
        "hidden": False, "state": "settings", "returnState": "claw",
        "nav": 1, "selected": [True, False], "blocks": [True, False],
        "events": ["padiem:advanced-settings-open"],
    }
    # 닫으면 hidden=true, 기억한 상태로 복귀, 닫힘 이벤트.
    assert observed["advancedClose"] == {
        "hidden": True, "state": "claw", "returnState": None,
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
