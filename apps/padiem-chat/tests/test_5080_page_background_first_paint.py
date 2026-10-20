"""#5080 the page background must not change after the first paint.

The glass theme stylesheets used to be appended to <head> at runtime by
theme-init.js, which meant the document painted once without them, the page
background then changed when they arrived, and the portrait mask swept in over
560ms because its @property custom properties transitioned from their
registered initial value. The canvas was white as well, because the glass
theme never gave the <html> element a background.

These checks pin the first-paint contract so the background stays steady.
"""

from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX = STATIC_DIR / "index.html"
GLASS = STATIC_DIR / "padiem-glass.css"
GLASS_PORTRAIT = STATIC_DIR / "padiem-glass-portrait.css"
THEME_INIT = STATIC_DIR / "theme-init.js"


def _index() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_the_index_is_still_valid_utf8_korean_text():
    text = _index()
    assert "누구나 바로 사용할 수 있는 파디엠의 기본 AI 인터페이스" in text


def test_the_glass_stylesheets_are_linked_in_the_first_paint():
    text = _index()
    head = text.split("</head>", 1)[0]
    assert 'href="./padiem-glass.css"' in head
    assert 'href="./padiem-glass-portrait.css"' in head
    # the theme-init guard looks for these attributes, so the runtime copy is skipped
    assert "data-padiem-glass-theme" in head
    assert "data-padiem-glass-portrait" in head


def test_the_glass_stylesheets_are_the_last_stylesheets_in_the_head():
    head = _index().split("</head>", 1)[0]
    positions = [
        head.rindex('href="./padiem-glass.css"'),
        head.rindex('href="./padiem-glass-portrait.css"'),
    ]
    last_other = max(
        head.rindex(f'href="./{name}"')
        for name in (
            "styles.css",
            "padiem-themes.css",
            "padiem-chat-ui-polish.css",
            "padiem-dark-contrast.css",
            "interaction-polish.css",
        )
    )
    # the glass sheets must keep winning the cascade, exactly as they did when
    # they were appended to the end of <head> at runtime
    assert min(positions) > last_other


def test_the_theme_initializer_runs_after_the_glass_links():
    head = _index().split("</head>", 1)[0]
    assert head.rindex('src="./theme-init.js"') > head.rindex(
        'href="./padiem-glass-portrait.css"'
    )


def test_the_theme_initializer_keeps_its_runtime_fallback():
    source = THEME_INIT.read_text(encoding="utf-8")
    assert "link[data-padiem-glass-theme]" in source
    assert "link[data-padiem-glass-portrait]" in source


def test_the_glass_theme_gives_the_canvas_a_background():
    css = GLASS.read_text(encoding="utf-8")
    block = css.split('html[data-theme="padiem-glass"] {', 1)[1].split("}", 1)[0]
    assert "background-color: #aeb6bf" in block


def test_the_body_background_is_unchanged():
    css = GLASS.read_text(encoding="utf-8")
    body = css.split('html[data-theme="padiem-glass"] body {', 1)[1].split("}", 1)[0]
    assert "background-color: #aeb6bf" in body
    assert "background-attachment: fixed" in body


@pytest.mark.parametrize(
    "path",
    [INDEX, GLASS, GLASS_PORTRAIT, THEME_INIT],
)
def test_the_static_files_stay_lf_only(path):
    assert b"\r\n" not in path.read_bytes()
