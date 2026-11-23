"""Owner-requested home screen cleanup: four cards, help moved to Settings, one profile entry."""
from __future__ import annotations

# #8060: shipped reads live in _support; the markup and CSS checks stay.
from _support import home_card_help_profile_source as sheets

HTML = sheets.sheet("index.html")
FIRST_USE = sheets.sheet("padiem-first-use.css")
POLISH = sheets.sheet("padiem-chat-ui-polish.css")
APP = sheets.sheet("app.js")
DIALOG = sheets.sheet("chat-login-dialog-module.js")
# R5 1단계: 설정 dialog의 열기/닫기 ARIA는 설정 모듈이 소유한다.
SETTINGS = sheets.sheet("chat-settings-module.js")
LOCALE = sheets.locale_source()


def test_four_cards_fit_one_desktop_row_and_mobile_keeps_two_or_one():
    home = HTML.split('id="emptyState"', 1)[1].split('id="clawTaskHub"', 1)[0]
    assert home.count('class="starter"') == 4
    assert 'id="writingStarterButton" data-prompt=' in home
    assert "webSearchStarterButton" not in home
    assert "webSearchStarterButton" not in FIRST_USE
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr));' in FIRST_USE
    assert 'setPrompt("#writingStarterButton", "starterWriting", lang);' in LOCALE
    assert 'starterWriting:' in LOCALE
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in FIRST_USE
    assert 'grid-template-columns: 1fr;' in FIRST_USE
    assert 'width: 100%;' in FIRST_USE
    assert ".starter-grid .starter small { font-size: 12px;" in FIRST_USE

def test_excel_workflow_stays_intact_in_claw_but_not_home():
    assert '.app-shell:not([data-state="claw"]) #clawWebOffice { display: none !important; }' in POLISH
    for id_ in ("clawWebOffice", "clawWebOfficeDetails", "clawWebXlsxInput",
                "clawWebXlsxSave", "clawWebXlsxP01Panel", "clawWebXlsxP01Approve"):
        assert f'id="{id_}"' in HTML
    assert 'id="clawExcelStartButton"' in HTML  # Canonical entry is still accessible from Claw.
    assert 'id="settingsExcelGuide"' in HTML
    assert 'settings-help-excel-step3' in HTML
    for key in ("settings-help-title", "settings-help-excel", "settings-help-excel-description",
                "settings-help-excel-step1", "settings-help-excel-step2", "settings-help-excel-step3"):
        assert LOCALE.count(f'"{key}"') == 2  # Korean + English


def test_name_avatar_opens_one_settings_dialog_no_duplicate_settings_row():
    """#7365 대표 결정(2026-11-10): 설정은 아래 계정 메뉴의 1급 항목(게스트에게도
    보인다)이고, 계정 카드의 프로필 패널도 같은 설정 dialog를 연다(2중 항목이
    아닌 같은 권한). #7780: 이름·아바타는 프로필 메뉴를 열고, 메뉴 안 설정이
    같은 설정 dialog를 연다."""
    sidebar = HTML.split('class="sidebar-bottom"', 1)[1].split('</aside>', 1)[0]
    assert 'id="settingsButton"' in sidebar
    menu = sidebar.split('id="profileMenu"', 1)[1]
    start = menu.rindex("<button", 0, menu.index('id="settingsButton"'))
    settings_tag = menu[start:menu.index('id="settingsButton"')]
    assert " hidden" not in settings_tag, "설정 항목은 게스트에게도 보인다"
    assert '.sidebar-bottom > #settingsButton { display: none !important; }' not in POLISH
    assert 'class="sidebar-account account-controls"' in sidebar
    profile_menu = sheets.sheet("chat-profile-menu-module.js")
    assert 'profileToggle.setAttribute("aria-controls", "profileMenu")' in profile_menu
    assert 'profileToggle.setAttribute("aria-haspopup", "menu")' in profile_menu
    assert 'loginDialogModule().wireProfileToggle();' in APP
    click = (APP + DIALOG).split('deps.profileToggle.addEventListener("click"', 1)[1].split("});", 1)[0]
    assert 'PadiemChatProfileMenu?.toggle?.()' in click
    assert 'profilePanel.hidden = !opening' not in click
    assert 'profileToggle.setAttribute("aria-expanded", "true")' in SETTINGS
    assert 'profileToggle.setAttribute("aria-expanded", "false")' in SETTINGS
