"""#8954-9: the connected PC status bullet matches the composer colour."""
from _support.claw_static import sheet
from css_rules import parse_rules

SELECTOR = (
    'body:has(#composerPcStatus[data-pc-connect="connected"]) '
    '#pcConnectStarter [data-pc-connect-state]::first-letter'
)


def test_connected_card_bullet_reads_the_composer_success_token():
    rules = parse_rules(sheet("pc-connect-flow.css"))
    colors = [
        rule.declarations["color"]
        for rule in rules
        if SELECTOR in rule.selectors and "color" in rule.declarations
    ]
    assert colors == ["var(--success)"]
    composer_rules = parse_rules(sheet("claw-composer-connection-status.css"))
    composer = [
        rule.declarations["background"]
        for rule in composer_rules
        if '.composer-pc-status[data-state="connected"] .composer-pc-status-dot'
        in rule.selectors and "background" in rule.declarations
    ]
    assert composer == ["var(--success)"]


def test_only_connected_status_bullet_changes_not_copy_or_behaviour():
    css = sheet("pc-connect-flow.css")
    assert "body:has(#composerPcStatus[data-pc-connect=\"connected\"])" in css
    assert "data-pc-connect=\"disconnected\"" not in css
    assert "!important" not in css
    flow = sheet("pc-connect-flow.js")
    assert 'line.textContent = vocabStatus(shown, fallback);' in flow
    assert 'chip.dataset.pcConnect = "connected";' in flow
