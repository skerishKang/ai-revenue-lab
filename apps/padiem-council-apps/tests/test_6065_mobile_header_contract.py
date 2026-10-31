"""#6065: the mobile header must reflow instead of squeezing its own controls.

Measured in Chromium against the three static files exactly as `origin/main`
serves them (live bytes were proven byte-identical to main first):

  320px, signed out  document scrollWidth - clientWidth = 30px, and the header
                     actions row ended at x=350.1 — the login button hung off
                     the viewport.
  320px              the status badge was 34px wide and 114px tall: "로그인 필요"
                     stood on six lines. The brand name took two lines, the
                     "콘텐츠 언어" label stacked vertically (130x95.9) and the
                     login button read "로그/인" at 42x64.4, ending at x=350.1.
  390px              the same squeeze one notch down: badge 47.4x72.4 (three
                     lines) and a 116.9px header.

After this lane's change: overflow 0 and no occlusion in 24 cells (2 auth states
x 4 widths 320/390/768/1440 x 3 views); badge 85.5x30.8, label 177.6x44, login
65.9x44, brand 118.2x25.6 — one line per item at every width, and the 768/1440
header stays 65/69px. The language control's 44px height is #6075's, not this
lane's, and it stays stated exactly once.
"""
from __future__ import annotations

import re
from pathlib import Path
from _council_module import local_asset_targets

APP_ROOT = Path(__file__).resolve().parents[1]
CSS = (APP_ROOT / "static" / "council-app.css").read_text(encoding="utf-8")


def media_body(query: str) -> str:
    """그 매체 판 하나의 본문만. 안의 규칙은 한 줄 규칙이라 닫는 `}` 가 줄 시작에 온다."""
    found = re.search(rf"@media \({re.escape(query)}\)\s*\{{(.*?)\n\}}", CSS, re.S)
    assert found, f"the {query} block must exist"
    body = found.group(1)
    assert "@media" not in body, f"the {query} slice ran past its own block"
    return body


def declaration(body: str, selector: str) -> str:
    found = re.search(rf"{re.escape(selector)}\s*(?:,[^{{]*)?\{{([^}}]*)\}}", body)
    assert found, f"{selector} is not declared in that block"
    return found.group(1)


def test_the_narrow_header_wraps_rather_than_shrinking_to_min_content():
    mobile = media_body("max-width: 900px")
    assert "flex-wrap: wrap" in declaration(mobile, ".council-topbar"), (
        "one row forced the actions group 30px past a 320px viewport")
    assert "flex-wrap: wrap" in declaration(mobile, ".council-topbar-actions"), (
        "the actions group is wider than 292px on its own, so it must wrap too")
    # Every header item may only break between items, never inside a word:
    # squeezed to min-content the badge was 34px wide and 114px tall, the language
    # label stood on four lines and the login button read "로그/인".
    for selector in (".council-brand-name", ".council-badge", ".council-badge-action", ".council-country"):
        assert "white-space: nowrap" in declaration(mobile, selector), selector


def test_the_language_control_height_is_stated_once_and_not_re_added_here():
    """#6075 put the 44px floor for the whole file in one block and pinned that shape
    in test_6046_mobile_touch_floor.py. This lane must not restate the floor in a
    media query (desktop would keep the old value) and must not leave a second value
    in the base rule, so the base rule carries no height at all."""
    base = declaration(CSS, ".council-country select")
    assert "min-height" not in base, f"the height belongs to the single floor block: {base}"
    assert "min-height" not in media_body("max-width: 900px")
    assert "min-height" not in media_body("max-width: 390px")
    floor = re.search(r"\.council-archive-item button,[^{]*\{[^}]*min-height:\s*44px;[^}]*\}", CSS, re.S)
    assert floor and ".council-country select" in floor.group(0), "#6075's floor block must keep the language control"


def test_the_named_breakpoints_and_the_floor_count_survive():
    assert CSS.count("min-height: 44px") >= 6, CSS.count("min-height: 44px")
    for breakpoint in ("max-width: 900px", "max-width: 390px", "min-width: 1200px"):
        assert f"@media ({breakpoint})" in CSS, breakpoint
    assert ":focus-visible" in CSS


def test_the_header_fix_stays_css_only_and_keeps_the_token_aliases():
    assert "--council-bg: var(--page-bg, var(--bg))" in CSS
    assert "--council-accent: var(--accent)" in CSS
    # The aliases still resolve through Chat's theme sheet: the cinematic layer overrides
    # the role tokens on this page only, and never re-declares an alias differently.
    assert "@import" not in CSS, "the staged bundle may not import another sheet"
    for target in local_asset_targets(CSS):
        assert target.startswith("./assets/"), f"asset outside this app: {target}"
