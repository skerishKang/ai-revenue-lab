"""The existing manual workflow remains reachable after the Claw hero clears."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"
CSS = (ROOT / "claw-focus-layout.css").read_text(encoding="utf-8")
JS = (ROOT / "app.js").read_text(encoding="utf-8")
NAV = (ROOT / "chat-nav-module.js").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_manual_entry_hidden_only_before_first_use():
    assert ':has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden])) #clawManualEntryBar' in CSS
    assert ':has(.claw-workspace[data-view="general"] ~ .conversation) #clawManualEntryBar' not in CSS


def test_manual_navigation_still_reuses_one_existing_route_and_form():
    assert HTML.count('id="clawManualEntryButton"') == 1
    assert HTML.count('id="clawManualForm"') == 1
    # R5 A10: the entry listener and the view flag moved to chat-nav-module.js;
    # app.js keeps the wire call at the original listener position.
    assert 'clawManualEntryButton.addEventListener("click", openClawManual)' in NAV
    assert 'clawWorkspace.dataset.view = "manual"' in NAV
    assert 'navModule().wireNavEntryListeners();' in JS
