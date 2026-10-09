"""Deterministic, render-only page planning for B66 certified CGI quotations.

The private Sol source assets and approved layout geometry are supplied by a
separately certified renderer. This module does not copy, synthesize, or alter
those assets, select an AI model, or recalculate QuoteCore money. It deliberately
does not activate the currently certified 1-3-row renderer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

MAX_PLAN_INPUT_BYTES = 1024 * 1024
CONTRACT = "b66.cgi.dynamic-a4-layout.v1"


class PagePlanError(ValueError):
    """Safe, fixed error code; never put customer content in exceptions."""


def _finite(value: object, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PagePlanError("invalid_certified_geometry")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise PagePlanError("invalid_certified_geometry")
    return number


@dataclass(frozen=True)
class CertifiedGeometry:
    """Only read from signed/certified template metadata, never customer JSON."""

    page_width_pt: float
    page_height_pt: float
    first_rows_top_pt: float
    continuation_rows_top_pt: float
    rows_bottom_pt: float
    final_section_height_pt: float
    name_column_width_pt: float
    line_height_pt: float
    row_vertical_padding_pt: float
    minimum_row_height_pt: float

    def __post_init__(self) -> None:
        values = (
            self.page_width_pt, self.page_height_pt, self.first_rows_top_pt,
            self.continuation_rows_top_pt, self.rows_bottom_pt,
            self.final_section_height_pt, self.name_column_width_pt,
            self.line_height_pt, self.row_vertical_padding_pt,
            self.minimum_row_height_pt,
        )
        for value in values:
            _finite(value)
        if not (590 <= self.page_width_pt <= 596 and 839 <= self.page_height_pt <= 845):
            raise PagePlanError("invalid_certified_geometry")
        if not (0 < self.first_rows_top_pt < self.rows_bottom_pt < self.page_height_pt):
            raise PagePlanError("invalid_certified_geometry")
        if not (0 < self.continuation_rows_top_pt < self.rows_bottom_pt):
            raise PagePlanError("invalid_certified_geometry")
        if self.final_section_height_pt + self.minimum_row_height_pt > min(
            self.rows_bottom_pt - self.first_rows_top_pt,
            self.rows_bottom_pt - self.continuation_rows_top_pt,
        ):
            raise PagePlanError("invalid_certified_geometry")
        if self.row_vertical_padding_pt * 2 + self.line_height_pt > self.minimum_row_height_pt * 20:
            raise PagePlanError("invalid_certified_geometry")


@dataclass(frozen=True)
class PlacedRow:
    source_index: int
    printed_number: int
    top_pt: float
    height_pt: float
    wrapped_name: tuple[str, ...]
    hard_break_before: tuple[bool, ...]


@dataclass(frozen=True)
class PlannedPage:
    number: int
    total_pages: int
    rows: tuple[PlacedRow, ...]
    show_totals_and_terms: bool
    first_page: bool


def _wrap_exact(value: str, width_pt: float, measure: Callable[[str], float]) -> tuple[tuple[str, ...], tuple[bool, ...]]:
    """No ellipsis, stripping, or implicit truncation, including long unbroken words."""
    if not value or any(ord(ch) < 32 and ch != "\n" for ch in value):
        raise PagePlanError("invalid_item_text")
    if len(value.encode("utf-8")) > MAX_PLAN_INPUT_BYTES:
        raise PagePlanError("request_too_large")
    lines: list[str] = []
    hard_breaks: list[bool] = []
    for segment_index, segment in enumerate(value.split("\n")):
        line = ""
        hard_break = segment_index > 0
        for char in segment:
            proposed = line + char
            try:
                size = _finite(measure(proposed), positive=False)
            except (ValueError, OverflowError, TypeError):
                raise PagePlanError("invalid_text_measure") from None
            if size < 0:
                raise PagePlanError("invalid_text_measure")
            if size > width_pt:
                if not line:
                    raise PagePlanError("unrenderable_glyph")
                lines.append(line)
                hard_breaks.append(hard_break)
                hard_break = False
                line = char
                try:
                    char_width = _finite(measure(char), positive=False)
                except (ValueError, OverflowError, TypeError):
                    raise PagePlanError("invalid_text_measure") from None
                if char_width < 0 or char_width > width_pt:
                    raise PagePlanError("unrenderable_glyph")
            else:
                line = proposed
        lines.append(line)
        hard_breaks.append(hard_break)
    if "".join(("\n" if hard else "") + line for line, hard in zip(lines, hard_breaks)) != value:
        raise PagePlanError("invalid_item_text")
    return tuple(lines), tuple(hard_breaks)


def plan_pages(
    rows: Sequence[Mapping[str, object]],
    *,
    geometry: CertifiedGeometry,
    measure_name_pt: Callable[[str], float],
    content_bytes: int,
) -> tuple[PlannedPage, ...]:
    """Produce a row-exact plan; amounts are already computed by QuoteCore.

    Signed layout + the actual certified font measurement are required inputs.
    No 3-row or 100-row ceiling exists; byte and A4 geometry limits are explicit.
    A row must fit entirely, with wrapping, on a single physical page.
    """
    if type(content_bytes) is not int or not 0 < content_bytes <= MAX_PLAN_INPUT_BYTES:
        raise PagePlanError("request_too_large")
    if not isinstance(rows, (list, tuple)) or not rows:
        raise PagePlanError("invalid_items")
    if not isinstance(geometry, CertifiedGeometry) or not callable(measure_name_pt):
        raise PagePlanError("invalid_certified_geometry")
    heights: list[tuple[float, tuple[str, ...], tuple[bool, ...]]] = []
    for item in rows:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise PagePlanError("invalid_items")
        wrapped, hard_breaks = _wrap_exact(item["name"], geometry.name_column_width_pt, measure_name_pt)
        height = max(
            geometry.minimum_row_height_pt,
            2 * geometry.row_vertical_padding_pt + geometry.line_height_pt * len(wrapped),
        )
        if height > min(
            geometry.rows_bottom_pt - geometry.first_rows_top_pt,
            geometry.rows_bottom_pt - geometry.continuation_rows_top_pt,
        ):
            raise PagePlanError("row_exceeds_page")
        heights.append((height, wrapped, hard_breaks))

    count = len(heights)
    suffix_heights = [0.0] * (count + 1)
    for index in range(count - 1, -1, -1):
        suffix_heights[index] = suffix_heights[index + 1] + heights[index][0]
    pages: list[tuple[PlacedRow, ...]] = []
    next_index = 0
    while next_index < count:
        first = not pages
        top = geometry.first_rows_top_pt if first else geometry.continuation_rows_top_pt
        full = geometry.rows_bottom_pt - top
        with_totals = full - geometry.final_section_height_pt
        remaining_height = suffix_heights[next_index]
        final = remaining_height <= with_totals + 1e-7
        limit = with_totals if final else full
        placed: list[PlacedRow] = []
        y = top
        while next_index + len(placed) < count:
            i = next_index + len(placed)
            height, wrapped, hard_breaks = heights[i]
            if y + height > top + limit + 1e-7:
                break
            placed.append(PlacedRow(i, i + 1, y, height, wrapped, hard_breaks))
            y += height
        if not final and len(placed) == count - next_index:
            placed.pop()  # Reserve at least one real item for a final totals page.
        if not placed:
            raise PagePlanError("row_exceeds_final_page" if count - next_index == 1 else "row_exceeds_page")
        pages.append(tuple(placed))
        next_index += len(placed)

    total_pages = len(pages)
    result = tuple(PlannedPage(i + 1, total_pages, page, i == total_pages - 1, i == 0)
                   for i, page in enumerate(pages))
    if [entry.source_index for page in result for entry in page.rows] != list(range(count)):
        raise PagePlanError("internal_page_plan_invalid")
    return result
