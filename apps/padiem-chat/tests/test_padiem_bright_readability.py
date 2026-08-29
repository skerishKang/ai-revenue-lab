from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READABILITY_CSS = (ROOT / "static/padiem-bright-readability.css").read_text(encoding="utf-8")
CINEMATIC_ENTRY = (ROOT / "static/padiem-cinematic-chat.css").read_text(encoding="utf-8")


def test_bright_readability_layer_is_loaded_last_in_cinematic_stack():
    import_line = "@import url('./padiem-bright-readability.css');"
    assert import_line in CINEMATIC_ENTRY
    assert CINEMATIC_ENTRY.index(import_line) > CINEMATIC_ENTRY.index("@import url('./padiem-first-use.css');")


def test_bright_sidebar_foregrounds_override_dark_foundation_contract():
    selectors = [
        ".sidebar .side-item",
        ".sidebar .recent-item",
        ".sidebar .side-icon",
        ".sidebar .mini-badge",
        ".sidebar .recent-section h2",
        ".sidebar .section-heading-row h2",
    ]
    for theme in ("light", "padiem-home"):
        prefix = f'html[data-theme="{theme}"]'
        for selector in selectors:
            assert f"{prefix} {selector}" in READABILITY_CSS

    assert "color: var(--text) !important;" in READABILITY_CSS
    assert "color: var(--muted) !important;" in READABILITY_CSS
    assert "font-size: 12px !important;" in READABILITY_CSS


def test_bright_composer_help_copy_has_readability_floor():
    for theme in ("light", "padiem-home"):
        assert f'html[data-theme="{theme}"] .composer-note' in READABILITY_CSS
    assert "font-size: 12px !important;" in READABILITY_CSS
    assert "line-height: 1.5;" in READABILITY_CSS


def test_dark_and_cinematic_do_not_receive_bright_readability_overrides():
    assert 'html[data-theme="dark"]' not in READABILITY_CSS
    assert 'html[data-theme="cinematic"]' not in READABILITY_CSS
