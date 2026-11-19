"""#8023: util PDF→Markdown inner panels follow the theme tokens."""
from __future__ import annotations

from pathlib import Path

from css_rules import declaration, parse_rules, rule_selector_list_contains

STATIC = Path(__file__).resolve().parents[1] / "static"
UTIL_MENU_CSS = (STATIC / "util-menu.css").read_bytes().decode("utf-8", errors="replace")
UTIL_APP_CSS = (STATIC / "util-app.css").read_bytes().decode("utf-8", errors="replace")
GLASS_PORTRAIT_CSS = (STATIC / "padiem-glass-portrait.css").read_bytes().decode("utf-8", errors="replace")


def _rules(css: str):
    return parse_rules(css)


def _one(rules: list, selector: str, label: str):
    matched = [rule for rule in rules
               if rule.media is None and rule_selector_list_contains(rule, selector)]
    assert len(matched) == 1, f"{label}: expected one rule, got {len(matched)}"
    return matched[0]


def _value(rule, prop: str) -> str:
    value = declaration(rule, prop)
    assert value is not None, prop
    return value


def test_pdfmd_inner_panels_follow_the_theme_tokens() -> None:
    shell = _one(_rules(UTIL_MENU_CSS), ".pdfmd-shell", "PDF→MD shell")
    assert _value(shell, "background").startswith("var(--card-bg")
    cols = _one(_rules(UTIL_APP_CSS), ".pdfmd-input-col", "PDF→MD inner panel")
    assert _value(cols, "background").startswith("var(--glass-card-surface")
    for rule in _rules(GLASS_PORTRAIT_CSS):
        if declaration(rule, "--glass-card-surface") is not None:
            assert any('data-theme="padiem-glass"' in s for s in rule.selectors), (
                f"--glass-card-surface left the glass scope: {rule.selectors}"
            )
