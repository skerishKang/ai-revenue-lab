"""Owner-requested home screen cleanup: four cards, help moved to Settings, one profile entry."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
FIRST_USE = (ROOT / "padiem-first-use.css").read_text(encoding="utf-8")
POLISH = (ROOT / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")
LOCALE = (ROOT / "locale.js").read_text(encoding="utf-8")


def test_four_cards_fit_one_desktop_row_and_mobile_keeps_two_or_one():
    home = HTML.split('id="emptyState"', 1)[1].split('id="clawTaskHub"', 1)[0]
    # Four working starters are visible while the unavailable Web Search hook stays hidden.
    assert home.count('class="starter"') == 5
    assert 'id="writingStarterButton" data-prompt=' in home
    assert 'id="webSearchStarterButton" disabled aria-disabled="true" aria-pressed="false" hidden' in home
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr));' in FIRST_USE
    assert ':has(#webSearchStarterButton:not([hidden]):not(:disabled)) #writingStarterButton' in FIRST_USE
    assert 'setPrompt("#writingStarterButton", "starterWriting", lang);' in LOCALE
    assert 'starterWriting:' in LOCALE
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr));' in FIRST_USE
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
    sidebar = HTML.split('class="sidebar-bottom"', 1)[1].split('</aside>', 1)[0]
    assert 'id="settingsButton"' in sidebar
    assert 'aria-expanded="false" hidden' in sidebar
    assert '.sidebar-bottom > #settingsButton { display: none !important; }' in POLISH
    assert 'class="sidebar-account account-controls"' in sidebar
    assert 'profileToggle.setAttribute("aria-controls", "settingsDialog")' in APP
    assert 'profileToggle.setAttribute("aria-haspopup", "dialog")' in APP
    click = APP.split('profileToggle.addEventListener("click"', 1)[1].split("});", 1)[0]
    assert 'settingsButton.click()' in click
    assert 'profilePanel.hidden = !opening' not in click
    assert 'profileToggle.setAttribute("aria-expanded", "true")' in APP
    assert 'profileToggle.setAttribute("aria-expanded", "false")' in APP
