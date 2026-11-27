"""#8812 D1·D4 follow-up: the padiem-glass six-panel lane crushed the PDF→MD
tool screen to ~620px at 1440 because the shared lane reserves the first-screen
artwork column (clamp(360px, 32vw, 560px)) for every view, including the util
views that have no artwork. The repair lives in the new single-rule sheet
``util-pdfmd-glass-lane.css``: a pdfmd-scoped exception that drops the artwork
reservation so the two-column workbench keeps the same 960px cap every other
theme gives .util-view. These contract tests keep the exception scoped (pdfmd
only), free of !important / selector-strength hacks, and loaded after the
shared frame sheet. Raw reads stay in _support (#8054/#8060)."""

from __future__ import annotations

import re

from _support import pdfmd_glass_lane_source as sheets

LANE_CSS = sheets.lane_sheet()
FRAME_CSS = sheets.frame_sheet()
INDEX_HTML = sheets.index_html()

MARKER = 'data-util-tool="pdfmd"'


def _rule_with_marker(css: str) -> str:
    """Return the innermost CSS rule (selector + declarations) holding MARKER."""
    for match in re.finditer(r"\{", css):
        start = match.end()
        depth = 1
        i = start
        while depth and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        body = css[start:i - 1]
        if "{" not in body and MARKER in css[max(0, css.rfind("\n", 0, match.start() - 400)):match.start()]:
            selector_start = css.rfind("}", 0, match.start()) + 1
            return css[selector_start:i]
    raise AssertionError("no rule found for " + MARKER)


def _media_of(css: str, marker: str) -> str:
    idx = css.index(marker)
    media = ""
    for match in re.finditer(r"@media[^{]*\{", css[:idx]):
        media = match.group(0)
    return media


def test_pdfmd_width_exception_exists_and_is_scoped() -> None:
    assert MARKER in LANE_CSS, "the pdfmd-scoped lane exception is missing"
    rule = _rule_with_marker(LANE_CSS)
    assert '.util-view:has(.util-tool-screen[data-util-tool="pdfmd"])' in rule
    assert "conversation" not in rule and "calendar-view" not in rule
    # Same 960px cap the other themes give .util-view, without the artwork lane.
    assert (
        "min(960px,\n      calc(100vw - var(--workspace-rail, 252px)"
        " - var(--padiem-six-panel-left) - 48px))" in rule
    )
    media = _media_of(LANE_CSS, MARKER)
    assert "(min-width: 921px)" in media


def test_pdfmd_width_exception_uses_no_hacks() -> None:
    rule = _rule_with_marker(LANE_CSS)
    assert "!important" not in LANE_CSS
    assert "#pdfmd" not in rule  # no id-strength selector strengthening


def test_exception_loads_after_the_shared_frame_sheet() -> None:
    lane_at = INDEX_HTML.index('./util-pdfmd-glass-lane.css')
    frame_at = INDEX_HTML.index('./shared-six-panel-frame.css')
    assert frame_at < lane_at, "the exception must follow the shared frame sheet"


def test_shared_lane_still_lists_util_view_everywhere() -> None:
    # The exception must not have removed .util-view from any shared lane.
    frame_lists = [segment for segment in FRAME_CSS.split(":is(") if ".meeting-view" in segment]
    assert len(frame_lists) >= 3
    for segment in frame_lists:
        assert ".util-view" in segment, "a six-panel lane is missing .util-view"
    # The artwork reservation stays for the first-screen surfaces.
    assert "clamp(360px, 32vw, 560px)" in FRAME_CSS
    # The shared frame sheet carries no pdfmd-scoped width override of its own.
    assert MARKER not in FRAME_CSS
