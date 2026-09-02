from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"
POLISH_CSS = STATIC / "padiem-glass-brand-polish.css"


def _css() -> str:
    return POLISH_CSS.read_text(encoding="utf-8")


def test_active_chat_keeps_bright_glass_composer_surface() -> None:
    css = _css()
    active = 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .composer {'
    assert active in css
    block = css.split(active, 1)[1].split("}", 1)[0]
    assert "rgba(255, 255, 255, .94)" in block
    assert "var(--glass-composer-surface)" in block
    assert "color: #17202a" in block


def test_active_chat_textarea_stays_transparent_with_dark_foreground() -> None:
    css = _css()
    selector = 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .composer textarea {'
    assert selector in css
    block = css.split(selector, 1)[1].split("}", 1)[0]
    assert "background: transparent !important" in block
    assert "color: #17202a !important" in block
    assert "caret-color: #17202a !important" in block
    assert "color: #ffffff" not in block


def test_glass_error_surface_uses_dark_foreground_on_light_tint() -> None:
    css = _css()
    selector = 'html[data-theme="padiem-glass"] body .error-box {'
    assert selector in css
    block = css.split(selector, 1)[1].split("}", 1)[0]
    assert "rgba(255, 249, 249, .96)" in block
    assert "color: #5f2929 !important" in block

    assert 'html[data-theme="padiem-glass"] body .error-box strong {' in css
    assert "color: #7f2828 !important" in css
    assert 'html[data-theme="padiem-glass"] body .error-box .retry-button {' in css
    assert "color: #762626 !important" in css
