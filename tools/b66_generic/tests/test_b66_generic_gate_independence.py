# -*- coding: utf-8 -*-
"""Each certification gate must be able to fail on its own (#3595 follow-up).

The point of this file is not "a PDF still passes". It is that the gates named
in certify.py are *different measurements*: a line-width change must move
`TABLE_LINES_BORDERS` and leave `LAYOUT_GEOMETRY` alone, a fill colour change
must do the opposite, a z-order swap must move `ASSET_LAYERING` while placement
and alpha stay put, and so on. If two gates collapse back into one comparison,
one of these cases goes red.

Every document here is built by this test with PyMuPDF, so no customer source is
involved and each variation is a single deliberate difference.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

TOOLS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("b66_certify", TOOLS / "certify.py")
certify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certify)


def _pixmap(alpha: bool):
    px = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), alpha)
    px.clear_with(200)
    return px


def build(
    path: Path,
    *,
    page=(200, 200),
    text="AAAA",
    text_at=(20, 40),
    text_size=10,
    second_line_at=None,
    line_width=1.0,
    line_color=(0, 0, 0),
    fill=(0.9, 0.9, 0.9),
    image_rects=((20, 100, 40, 120), (100, 100, 120, 120)),
    image_alphas=(False, False),
    image_order=None,
):
    doc = fitz.open()
    pg = doc.new_page(width=page[0], height=page[1])
    pg.insert_text(fitz.Point(*text_at), text, fontsize=text_size)
    if second_line_at is not None:
        pg.insert_text(fitz.Point(*second_line_at), "BBBB", fontsize=text_size)
    pg.draw_line(fitz.Point(20, 60), fitz.Point(180, 60),
                 color=line_color, width=line_width)
    pg.draw_rect(fitz.Rect(20, 70, 60, 90), color=None, fill=fill)
    order = list(range(len(image_rects))) if image_order is None else list(image_order)
    for i in order:
        pg.insert_image(fitz.Rect(image_rects[i]), pixmap=_pixmap(image_alphas[i]))
    doc.save(str(path))
    doc.close()
    return path


def gates(tmp: Path, **overrides) -> dict:
    """Gates for the default page against the same page with one thing changed."""
    base = build(tmp / "base.pdf")
    other = build(tmp / "other.pdf", **overrides)
    return certify.gates_for_page(base, other, 0)


def test_identical_pages_pass_every_gate(tmp_path):
    same = build(tmp_path / "same.pdf")
    result = certify.gates_for_page(same, same, 0)
    assert all(result.values()) is True


def test_page_geometry_is_its_own_gate(tmp_path):
    result = gates(tmp_path, page=(220, 200))
    assert result["PAGE_GEOMETRY"] is False
    assert result["TEXT_POSITION"] is True
    assert result["LAYOUT_GEOMETRY"] is True
    assert result["TABLE_LINES_BORDERS"] is True
    assert result["IMAGE_PLACEMENT"] is True


def test_text_position_is_not_spacing_or_wrap(tmp_path):
    result = gates(tmp_path, text_at=(40, 45))
    assert result["TEXT_POSITION"] is False
    # Same glyph run, same metrics, same line structure — only the origin moved.
    assert result["TEXT_SPACING_BASELINE"] is True
    assert result["WRAP_SHRINK"] is True
    assert result["FONT_SIZE"] is True


def test_font_size_is_its_own_gate(tmp_path):
    result = gates(tmp_path, text_size=13)
    assert result["FONT_SIZE"] is False
    assert result["WRAP_SHRINK"] is True  # same one line, four characters


def test_wrap_structure_is_its_own_gate(tmp_path):
    """One line of eight characters becomes two lines of four."""
    result = gates(tmp_path, text="AAAABBBB", second_line_at=(20, 60))
    assert result["WRAP_SHRINK"] is False
    assert result["FONT_SIZE"] is True
    assert result["FONT_FAMILY"] is True


def test_table_rule_width_is_not_layout_geometry(tmp_path):
    result = gates(tmp_path, line_width=2.0)
    assert result["TABLE_LINES_BORDERS"] is False
    assert result["LAYOUT_GEOMETRY"] is True


def test_fill_colour_is_not_a_table_rule(tmp_path):
    result = gates(tmp_path, fill=(0.2, 0.4, 0.6))
    assert result["LAYOUT_GEOMETRY"] is False
    assert result["TABLE_LINES_BORDERS"] is True


def test_image_placement_is_not_z_order(tmp_path):
    moved = ((60, 100, 80, 120), (100, 100, 120, 120))
    result = gates(tmp_path, image_rects=moved)
    assert result["IMAGE_PLACEMENT"] is False
    assert result["ASSET_LAYERING"] is True  # same first-painted image
    assert result["STAMP_ALPHA"] is True


def test_soft_mask_is_its_own_gate(tmp_path):
    result = gates(tmp_path, image_alphas=(False, True))
    assert result["STAMP_ALPHA"] is False
    assert result["IMAGE_PLACEMENT"] is True
    assert result["ASSET_LAYERING"] is True


def test_z_order_is_not_placement_or_alpha(tmp_path):
    result = gates(tmp_path, image_order=(1, 0))
    assert result["ASSET_LAYERING"] is False
    assert result["IMAGE_PLACEMENT"] is True
    assert result["STAMP_ALPHA"] is True


def test_logo_and_stamp_are_not_counted_as_two_gates():
    """The honest limit: no semantic asset roles, so no separate logo/stamp gates."""
    assert "LOGO_GEOMETRY" not in certify.CRITICAL_GATES
    assert "STAMP_GEOMETRY" not in certify.CRITICAL_GATES
    assert len(certify.CRITICAL_GATES) == len(set(certify.CRITICAL_GATES))
