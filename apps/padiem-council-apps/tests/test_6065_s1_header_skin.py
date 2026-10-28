"""#6065 S1: the production header carries the global design's header vocabulary.

Measured in Chromium against the bytes `origin/main` serves (live == main, sha256
proven in the integration contract) and against the design preview at the same
widths. The numbers below are the reason each declaration is pinned here.

  1440px  design brand mark x=69.8, name x=109.8, header 69.2px tall,
          gutter 12px 69.84px, gap 17.28px, mark 30x30 stroke svg with no fill.
          Production before S1: mark x=20 (a 28x28 filled accent tile), name 16px
          with normal tracking, gutter 12px 20px, gap 12px, header 69px.
          Production after S1: mark x=69.8, name x=109.8, 16.5px/-0.01em/1.2,
          gutter and gap equal to the design's, header 69px.
  390px   the mark's left edge (14px) equals the content column's left edge (14px),
          the same relationship the design has at 390 (mark 20 == cards 20).

Accepted and recorded instead of fixed: the design renders Pretendard because it
self-hosts it; this app cannot (no `@font-face` here, no `url(`, and S1 adds no
assets). A canvas width differential measured 118.1px for Pretendard against
127.7px for the fallback on the design page, and 127.7px == 127.7px here — the
type *scale* matches, the *face* does not until an owner ships the font.
"""
from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
CSS = (APP_ROOT / "static" / "council-app.css").read_text(encoding="utf-8")
HTML = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (APP_ROOT / "static" / "council-app.js").read_text(encoding="utf-8")


def rule(selector: str) -> str:
    found = re.search(rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.S | re.M)
    assert found, f"missing rule: {selector}"
    return found.group(1)


def test_the_header_gutters_are_the_design_fluid_scale():
    bar = rule(".council-topbar")
    assert "gap: clamp(8px, 1.2vw, 18px)" in bar, bar
    assert "padding: 12px clamp(20px, 4.85vw, 70px)" in bar, bar
    # The design keeps its own bar height; production must not grow a second row at desktop.
    assert "flex-wrap" not in bar, "wrapping belongs to the mobile block only (S0)"


def test_the_brand_mark_is_the_design_stroke_mark_not_a_filled_tile():
    mark = rule(".council-brand-mark")
    assert "width: 30px" in mark and "height: 30px" in mark, mark
    assert "background" not in mark, "the design's mark carries no plate"
    assert "border-radius" not in mark, mark
    assert "color: inherit" in mark, "the mark draws in the header's own ink"
    svg = rule(".council-brand-mark svg")
    for prop in ("fill: none", "stroke: currentColor", "stroke-width: 1.5"):
        assert prop in svg, f"{prop} missing from {svg}"
    assert '<svg viewBox="0 0 30 30"' in HTML, "the mark is inline markup, never a fetched asset"
    assert 'aria-hidden="true"' in HTML[HTML.index("council-brand-mark"):HTML.index("council-brand-name")], (
        "the mark must stay out of the accessible name")


def test_the_brand_name_takes_the_design_type_scale():
    name = rule(".council-brand-name")
    assert "font-size: 16.5px" in name, name
    assert "letter-spacing: -0.01em" in name, name
    assert "line-height: 1.2" in name, name
    assert "font-weight: 700" in name, name


def test_the_open_tool_is_marked_by_the_design_outline_ring():
    active = rule(".council-card.active")
    assert "outline: 2px solid var(--council-accent)" in active, active
    assert "outline-offset: 2px" in active, active
    assert "box-shadow" not in active, "the inset bar was the marker nobody could see"
    assert "grid-column: 1 / -1" in active, "the open tool still takes the row (#5942)"


def test_s1_added_no_asset_and_no_font_of_its_own():
    assert "@font-face" not in CSS, "fonts are an owner decision; S1 ships none"
    assert "url(" not in CSS and "@import" not in CSS
    assert sorted(p.name for p in (APP_ROOT / "static").iterdir()) == [
        "council-app.css", "council-app.js", "index.html"], "the staged bundle names are fixed"


def test_the_five_styles_stay_internal():
    """CENTRAL 2026-10-28: the 5 style axis is not exposed to production users.
    Nothing in this app may read or write the design's theme key or its axes."""
    for text, name in ((HTML, "index.html"), (JS, "council-app.js"), (CSS, "council-app.css")):
        assert "padiem-parliament-theme" not in text, name
        assert "data-style" not in text, name
        assert not re.search(r"\[data-country=", text), name
