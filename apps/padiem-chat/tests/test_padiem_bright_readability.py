from _support.bright_readability_source import polish_css, index_html
from _support import claw_static


def test_theme_polish_layer_is_loaded_last_in_cinematic_stack():
    # #7811 C1: 8개 @import가 index.html <link>로 펼쳐졌다(@import는 부르는
    # 시트보다 앞에 온다). 순서와 부르는 시트 앞 위치를 그대로 확인한다.
    bright = 'href="./padiem-bright-readability.css"'
    first_use = 'href="./padiem-first-use.css"'
    entry = 'href="./padiem-cinematic-chat.css"'
    assert bright in index_html()
    assert index_html().index(bright) > index_html().index(first_use)
    assert index_html().index(bright) < index_html().index(entry)


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
            assert f"{prefix} {selector}" in polish_css()

    assert "color: var(--text);" in polish_css()
    assert "color: var(--muted);" in polish_css()


def test_bright_composer_active_tools_override_dark_foreground_contract():
    for theme in ("light", "padiem-home"):
        prefix = f'html[data-theme="{theme}"]'
        assert f"{prefix} .composer .tool-button:not(:disabled)" in polish_css()
        assert f"{prefix} .composer .tool-button:hover:not(:disabled)" in polish_css()
        assert f'{prefix} .composer .tool-button[aria-pressed="true"]:not(:disabled)' in polish_css()

    assert "background: var(--accent-soft);" in polish_css()
    assert "border-color: var(--line);" in polish_css()


def test_all_themes_keep_useful_microcopy_at_twelve_pixel_floor():
    for theme in ("light", "dark", "cinematic", "padiem-home"):
        assert f'html[data-theme="{theme}"] .composer-note' in polish_css()

    for theme in ("dark", "cinematic"):
        prefix = f'html[data-theme="{theme}"]'
        assert f"{prefix} .sidebar .recent-section h2" in polish_css()
        assert f"{prefix} .sidebar .section-heading-row h2" in polish_css()

    assert "font-size: 12px;" in polish_css()
    assert "line-height: 1.5;" in polish_css()


def test_cinematic_has_bounded_atmospheric_distinction_from_neutral_dark():
    # #7811 C4: body and pseudo-element atmosphere is owned by the theme sheet.
    themes_css = claw_static.sheet("padiem-themes.css")
    assert 'html[data-theme="cinematic"] body {' not in polish_css()
    assert 'html[data-theme="cinematic"] body::before {' not in polish_css()
    assert 'html[data-theme="cinematic"] body {' in themes_css
    assert 'html[data-theme="cinematic"] body::before {' in themes_css
    assert "rgba(108,190,255,.28)" in themes_css
    assert "rgba(239,201,132,.20)" in themes_css
    # #7811 C3: the sidebar edge, topbar and top-rim glow are painted by the
    # theme sheet's own cinematic rules, which read the film tokens; only the
    # starter card and composer box stay in the readability layer.
    assert 'html[data-theme="cinematic"] .sidebar {' not in polish_css()
    assert 'html[data-theme="cinematic"] .topbar {' not in polish_css()
    assert 'html[data-theme="cinematic"] .app-shell::before {' not in polish_css()
    assert 'html[data-theme="cinematic"] .sidebar {' in themes_css
    assert 'html[data-theme="cinematic"] .topbar {' in themes_css
    assert 'html[data-theme="cinematic"] .starter {' in polish_css()
    assert 'html[data-theme="cinematic"] .composer {' in polish_css()
    # DARK receives typography only; no cinematic atmosphere/surface override.
    assert 'html[data-theme="dark"] body {' not in polish_css()
    assert 'html[data-theme="dark"] .composer {' not in polish_css()


def test_mobile_chat_theme_picker_is_compact_until_focused():
    assert '@media (max-width: 640px)' in polish_css()
    prefix = '.app-shell[data-state="chat"] .topbar .theme-picker'
    assert prefix in polish_css()
    assert f'{prefix} .theme-option[aria-pressed="true"]' in polish_css()
    assert f"{prefix}:focus-within" in polish_css()
    assert f"{prefix}:focus-within .theme-option" in polish_css()
    assert "display: none;" in polish_css()
    assert "min-height: 44px;" in polish_css()


def test_light_mobile_home_question_keeps_single_question_line_contract():
    selector = 'html[data-theme="light"] .app-shell[data-state="home"] .empty-state h1'
    assert '@media (max-width: 420px)' in polish_css()
    assert selector in polish_css()
    assert "font-size: 32px;" in polish_css()
    assert "letter-spacing: -.05em;" in polish_css()
