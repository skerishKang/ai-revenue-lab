"""The existing manual workflow remains reachable after the Claw hero clears."""
# #8060: shipped reads live in _support; the CSS and markup checks stay.
from _support import manual_entry_visibility_source as sheets

CSS = sheets.sheet("claw-focus-layout.css")
JS = sheets.sheet("app.js")
NAV = sheets.sheet("chat-nav-module.js")
HTML = sheets.sheet("index.html")


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
    assert 'navModuleInstance.wireNavEntryListeners();' in JS
