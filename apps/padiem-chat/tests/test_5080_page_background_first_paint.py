"""#5080 the page background must not change after the first paint.

The glass theme stylesheets used to be appended to <head> at runtime by
theme-init.js, which meant the document painted once without them, the page
background then changed when they arrived, and the portrait mask swept in over
560ms because its @property custom properties transitioned from their
registered initial value. The canvas was white as well, because the glass
theme never gave the <html> element a background.

These checks pin the first-paint contract so the background stays steady.
"""

import pytest

from _support import first_paint_home_source as sheets


def _index() -> str:
    return sheets.index_html()


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


def test_the_glass_stylesheets_keep_their_runtime_cascade_position():
    """theme-init.js appended them to <head> while the parser was still at the
    script tag, so they sat ahead of styles.css. The static links must sit in
    that same position, otherwise the glass variables start winning ties they
    did not win before and the chat gutter moves."""
    head = _index().split("</head>", 1)[0]
    glass = head.index('href="./padiem-glass.css"')
    portrait = head.index('href="./padiem-glass-portrait.css"')
    styles = head.index('href="./styles.css"')
    assert glass < styles
    assert portrait < styles
    for name in (
        "padiem-themes.css",
        "padiem-chat-ui-polish.css",
        "padiem-dark-contrast.css",
        "interaction-polish.css",
    ):
        assert glass < head.index(f'href="./{name}"')


def test_the_theme_initializer_runs_after_the_glass_links():
    head = _index().split("</head>", 1)[0]
    assert head.rindex('src="./theme-init.js"') > head.rindex(
        'href="./padiem-glass-portrait.css"'
    )


def test_the_theme_initializer_keeps_its_runtime_fallback():
    source = sheets.theme_init_js()
    assert "link[data-padiem-glass-theme]" in source
    assert "link[data-padiem-glass-portrait]" in source


def test_the_glass_theme_gives_the_canvas_a_background():
    css = sheets.glass_css()
    block = css.split('html[data-theme="padiem-glass"] {', 1)[1].split("}", 1)[0]
    assert "background-color: #aeb6bf" in block


def test_the_body_background_is_unchanged():
    css = sheets.glass_css()
    body = css.split('html[data-theme="padiem-glass"] body {', 1)[1].split("}", 1)[0]
    assert "background-color: #aeb6bf" in body
    assert "background-attachment: fixed" in body


@pytest.mark.parametrize(
    "path",
    [sheets.static_path(name) for name in (
        "index.html", "padiem-glass.css", "padiem-glass-portrait.css", "theme-init.js")],
)
def test_the_static_files_stay_lf_only(path):
    assert b"\r\n" not in path.read_bytes()
