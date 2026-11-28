"""Closed 3b selectors shared by Core, Engine client, Chat and PC command.

This module parses no document and touches no filesystem; it rejects
ambiguous or widened page/sheet requests before the signed PC dispatch.
"""
from __future__ import annotations
import re

PDF_MAX_PAGE_COUNT = 10
XLSX_MAX_CELLS = 2000
_RANGE = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6}):([A-Z]{1,3})([1-9][0-9]{0,6})\Z")


def valid_pdf_selection(page: object, page_count: object) -> bool:
    return (type(page) is int and type(page_count) is int
            and 1 <= page <= (1 << 40) and 1 <= page_count <= PDF_MAX_PAGE_COUNT)


def _column_number(text: str) -> int:
    result = 0
    for char in text:
        result = result * 26 + (ord(char) - 64)
    return result


def valid_xlsx_selection(sheet: object, cell_range: object) -> bool:
    if (not isinstance(sheet, str) or not 0 < len(sheet) <= 128
            or any(ord(char) < 32 for char in sheet)
            or not isinstance(cell_range, str) or len(cell_range) > 32):
        return False
    match = _RANGE.fullmatch(cell_range)
    if match is None:
        return False
    start_col, start_row, end_col, end_row = match.groups()
    a, b = _column_number(start_col), _column_number(end_col)
    low, high = int(start_row), int(end_row)
    return (1 <= a <= b <= 16384 and 1 <= low <= high <= 1048576
            and (b - a + 1) * (high - low + 1) <= XLSX_MAX_CELLS)
