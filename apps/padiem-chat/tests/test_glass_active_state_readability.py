"""Active Glass surfaces keep a bright, legible foreground (#8060).

The contract is asserted on parsed CSS rules instead of pinned source text, so
a formatter or a reordered declaration list cannot break it while the painted
result stays the same.
"""
from css_rules import declaration, find_rules_with_selector, rules_for_sheet

SHEET = "padiem-glass-brand-polish.css"
RULES = rules_for_sheet(SHEET)


def _base_rule(selector: str):
    matches = [rule for rule in find_rules_with_selector(RULES, selector) if rule.media is None]
    assert len(matches) == 1, (selector, len(matches))
    return matches[0]


def test_active_chat_keeps_bright_glass_composer_surface() -> None:
    rule = _base_rule('html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .composer')
    background = declaration(rule, "background")
    assert background is not None and "rgba(255, 255, 255, .94)" in background
    assert background is not None and "var(--glass-composer-surface)" in background
    assert declaration(rule, "color") == "#17202a !important"


def test_active_chat_textarea_stays_transparent_with_dark_foreground() -> None:
    rule = _base_rule(
        'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .composer textarea'
    )
    assert declaration(rule, "background") == "transparent"
    assert declaration(rule, "color") == "#17202a"
    assert declaration(rule, "caret-color") == "#17202a"
    assert "#ffffff" not in " ".join(rule.declarations.values())


def test_glass_error_surface_uses_dark_foreground_on_light_tint() -> None:
    rule = _base_rule('html[data-theme="padiem-glass"] body .error-box')
    background = declaration(rule, "background")
    assert background is not None and "rgba(255, 249, 249, .96)" in background
    assert declaration(rule, "color") == "#5f2929"
    assert (
        declaration(_base_rule('html[data-theme="padiem-glass"] body .error-box strong'), "color")
        == "#7f2828"
    )
    assert (
        declaration(
            _base_rule('html[data-theme="padiem-glass"] body .error-box .retry-button'), "color"
        )
        == "#762626"
    )
