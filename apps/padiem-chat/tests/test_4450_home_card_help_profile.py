"""Owner-requested home screen cleanup: four cards, help moved to Settings, one profile entry."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
FIRST_USE = (ROOT / "padiem-first-use.css").read_text(encoding="utf-8")
POLISH = (ROOT / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")
# R5 1단계: 설정 dialog의 열기/닫기 ARIA는 설정 모듈이 소유한다.
SETTINGS = (ROOT / "chat-settings-module.js").read_text(encoding="utf-8")
LOCALE = (ROOT / "locale.js").read_text(encoding="utf-8")


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
    아닌 같은 권한)."""
    sidebar = HTML.split('class="sidebar-bottom"', 1)[1].split('</aside>', 1)[0]
    assert 'id="settingsButton"' in sidebar
    settings_tag = sidebar.split('id="settingsButton"', 1)[0].split("<button", 1)[-1]
    assert " hidden" not in settings_tag, "설정 항목은 게스트에게도 보인다"
    assert '.sidebar-bottom > #settingsButton { display: none !important; }' not in POLISH
    assert 'class="sidebar-account account-controls"' in sidebar
    assert 'profileToggle.setAttribute("aria-controls", "settingsDialog")' in APP
    assert 'profileToggle.setAttribute("aria-haspopup", "dialog")' in APP
    click = APP.split('profileToggle.addEventListener("click"', 1)[1].split("});", 1)[0]
    assert 'settingsButton.click()' in click
    assert 'profilePanel.hidden = !opening' not in click
    assert 'profileToggle.setAttribute("aria-expanded", "true")' in SETTINGS
    assert 'profileToggle.setAttribute("aria-expanded", "false")' in SETTINGS
