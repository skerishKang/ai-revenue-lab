"""#7811 C4: cinematic backdrops belong to their themed component rules."""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "static"

def _rule(name: str, selector: str) -> str:
    css = (STATIC / name).read_text(encoding="utf-8")
    matches = re.findall(r"(?m)^" + re.escape(selector) + r"\s*\{[^{}]*\}", css)
    assert len(matches) <= 1
    return matches[0] if matches else ""

def test_cinematic_backdrops_are_owned_by_theme_sheet():
    for selector in ('html[data-theme="cinematic"] body',
                     'html[data-theme="cinematic"] body::before'):
        assert not _rule("padiem-bright-readability.css", selector)
        block = _rule("padiem-themes.css", selector)
        assert "background:" in block
        assert "!important" in block
    body = _rule("padiem-themes.css", 'html[data-theme="cinematic"] body')
    before = _rule("padiem-themes.css", 'html[data-theme="cinematic"] body::before')
    assert "circle at 76% 22%" in body
    assert "circle at 80% 30%" in before
    assert "box-shadow: var(--film-vignette)" in before

def test_remaining_cinematic_surface_rules_are_preserved():
    for selector in ('html[data-theme="cinematic"] .sidebar',
                     'html[data-theme="cinematic"] .topbar',
                     'html[data-theme="cinematic"] .starter',
                     'html[data-theme="cinematic"] .composer',
                     'html[data-theme="cinematic"] .app-shell::before'):
        assert _rule("padiem-bright-readability.css", selector)
