from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLISH_CSS = (ROOT / "static/padiem-bright-readability.css").read_text(encoding="utf-8")
CINEMATIC_ENTRY = (ROOT / "static/padiem-cinematic-chat.css").read_text(encoding="utf-8")


def test_theme_polish_layer_is_loaded_last_in_cinematic_stack():
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
            assert f"{prefix} {selector}" in POLISH_CSS

    assert "color: var(--text) !important;" in POLISH_CSS
    assert "color: var(--muted) !important;" in POLISH_CSS


def test_bright_composer_active_tools_override_dark_foreground_contract():
    for theme in ("light", "padiem-home"):
        prefix = f'html[data-theme="{theme}"]'
        assert f"{prefix} .composer .tool-button:not(:disabled)" in POLISH_CSS
        assert f"{prefix} .composer .tool-button:hover:not(:disabled)" in POLISH_CSS
        assert f'{prefix} .composer .tool-button[aria-pressed="true"]:not(:disabled)' in POLISH_CSS

    assert "background: var(--accent-soft) !important;" in POLISH_CSS
    assert "border-color: var(--line) !important;" in POLISH_CSS


def test_all_themes_keep_useful_microcopy_at_twelve_pixel_floor():
    for theme in ("light", "dark", "cinematic", "padiem-home"):
        assert f'html[data-theme="{theme}"] .composer-note' in POLISH_CSS

    for theme in ("dark", "cinematic"):
        prefix = f'html[data-theme="{theme}"]'
        assert f"{prefix} .sidebar .recent-section h2" in POLISH_CSS
        assert f"{prefix} .sidebar .section-heading-row h2" in POLISH_CSS

    assert "font-size: 12px !important;" in POLISH_CSS
    assert "line-height: 1.5;" in POLISH_CSS


def test_cinematic_has_bounded_atmospheric_distinction_from_neutral_dark():
    assert 'html[data-theme="cinematic"] body {' in POLISH_CSS
    assert "rgba(108,190,255,.28)" in POLISH_CSS
    assert "rgba(239,201,132,.20)" in POLISH_CSS
    assert 'html[data-theme="cinematic"] .sidebar {' in POLISH_CSS
    assert 'html[data-theme="cinematic"] .topbar {' in POLISH_CSS
    assert 'html[data-theme="cinematic"] .starter {' in POLISH_CSS
    assert 'html[data-theme="cinematic"] .composer {' in POLISH_CSS
    # DARK receives typography only; no cinematic atmosphere/surface override.
    assert 'html[data-theme="dark"] body {' not in POLISH_CSS
    assert 'html[data-theme="dark"] .composer {' not in POLISH_CSS


def test_mobile_chat_theme_picker_is_compact_until_focused():
    assert '@media (max-width: 640px)' in POLISH_CSS
    prefix = '.app-shell[data-state="chat"] .topbar .theme-picker'
    assert prefix in POLISH_CSS
    assert f'{prefix} .theme-option[aria-pressed="true"]' in POLISH_CSS
    assert f"{prefix}:focus-within" in POLISH_CSS
    assert f"{prefix}:focus-within .theme-option" in POLISH_CSS
    assert "display: none;" in POLISH_CSS
    assert "min-height: 44px;" in POLISH_CSS


def test_light_mobile_home_question_keeps_single_question_line_contract():
    selector = 'html[data-theme="light"] .app-shell[data-state="home"] .empty-state h1'
    assert '@media (max-width: 420px)' in POLISH_CSS
    assert selector in POLISH_CSS
    assert "font-size: 32px !important;" in POLISH_CSS
    assert "letter-spacing: -.05em;" in POLISH_CSS
