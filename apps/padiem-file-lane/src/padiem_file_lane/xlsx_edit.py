"""#5895 — read an owner's Excel quote form and fill it without losing its look.

The COM2 file lane is the only place these bytes are opened. The Chat Worker never
imports openpyxl: a workbook compiles a lot of parser code, and the cold-init
regression on 2026-10-28 came from exactly that kind of extra import weight.

Two operations, both on the owner's own file:

``describe``
    The form's own structure for a model to reason about: every sheet's non-empty
    cells (address + the text it shows), the merged ranges, and the used extent.
    Formulas travel as their formula text, so a helper model can see the form's own
    arithmetic and leave it alone.

``fill``
    A copy of the form with the mapped values written in. Everything else — styles,
    number formats, column widths, row heights, merges, formulas — is the owner's
    original. When an item list needs more rows than the form has, the template row
    is duplicated *with its style* so the filled form looks like the form it came
    from; sums are never rewritten.
"""
from __future__ import annotations

import re
from copy import copy
from io import BytesIO
from typing import Any

CELL_REF = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")


class FormError(Exception):
    """A refusal with a stable code; the caller maps it to its own HTTP status."""

    def __init__(self, code: str) -> None:
        self.code = code


def _workbook(payload: bytes):
    try:
        from openpyxl import load_workbook
    except Exception:  # pragma: no cover - the deployed lane always ships openpyxl
        raise FormError("xlsx_editor_unavailable") from None
    try:
        return load_workbook(BytesIO(payload), data_only=False)
    except Exception:
        raise FormError("xlsx_unreadable") from None


def describe(payload: bytes) -> dict[str, Any]:
    """Every non-empty cell of every sheet, with its address and displayed text."""

    book = _workbook(payload)
    try:
        sheets = []
        for sheet in book.worksheets:
            cells = []
            for row in sheet.iter_rows():
                for cell in row:
                    value = cell.value
                    if value is None:
                        continue
                    text = value if isinstance(value, str) else str(value)
                    if not text.strip():
                        continue
                    formula = isinstance(value, str) and value.startswith("=")
                    cells.append({
                        "cell": cell.coordinate,
                        "text": text if len(text) <= 500 else text[:500],
                        "formula": formula,
                    })
            sheets.append({
                "name": sheet.title,
                "rows": sheet.max_row,
                "columns": sheet.max_column,
                "merged": [str(item) for item in sheet.merged_cells.ranges],
                "cells": cells,
            })
        return {"sheets": sheets}
    finally:
        book.close()


def _apply_mapping(book, mapping: Any) -> None:
    if not isinstance(mapping, dict):
        raise FormError("mapping_invalid")
    for sheet_name, cells in mapping.items():
        if not isinstance(sheet_name, str) or not isinstance(cells, dict):
            raise FormError("mapping_invalid")
        if sheet_name not in book.sheetnames:
            raise FormError("mapping_sheet_unknown")
        sheet = book[sheet_name]
        for address, value in cells.items():
            if not isinstance(address, str) or CELL_REF.fullmatch(address) is None:
                raise FormError("mapping_cell_invalid")
            if isinstance(value, (dict, list)):
                raise FormError("mapping_value_invalid")
            current = sheet[address].value
            if isinstance(current, str) and current.startswith("="):
                # The owner's own sum stays the owner's own sum.
                raise FormError("mapping_formula_protected")
            sheet[address] = value


def _extend_rows(book, extensions: Any) -> None:
    """Copy a template row's style into the rows a longer item list needs.

    ``at_row`` is where the new rows start and ``template_row`` is the row they are
    copied from. Inserting inside a merged range would tear the form apart, so that
    request is refused instead of guessed at.
    """

    if extensions is None:
        return
    if not isinstance(extensions, list):
        raise FormError("extension_invalid")
    for item in extensions:
        if not isinstance(item, dict):
            raise FormError("extension_invalid")
        sheet_name = item.get("sheet")
        template_row = item.get("template_row")
        at_row = item.get("at_row")
        count = item.get("count")
        if (
            not isinstance(sheet_name, str) or sheet_name not in book.sheetnames
            or type(template_row) is not int or template_row < 1
            or type(at_row) is not int or at_row < 1
            or type(count) is not int or count < 1 or count > 200
        ):
            raise FormError("extension_invalid")
        sheet = book[sheet_name]
        for merged in sheet.merged_cells.ranges:
            if merged.min_row <= at_row <= merged.max_row:
                raise FormError("extension_inside_merged_cells")
        template = [copy(cell._style) for cell in sheet[template_row]]
        template_heights = sheet.row_dimensions[template_row].height
        sheet.insert_rows(at_row, count)
        width = max(len(template), sheet.max_column)
        for offset in range(count):
            row = sheet[at_row + offset]
            for column in range(width):
                target = row[column] if column < len(row) else None
                if target is None:
                    continue
                source = template[column] if column < len(template) else None
                if source is not None:
                    target._style = copy(source)
            sheet.row_dimensions[at_row + offset].height = template_heights


def fill(payload: bytes, *, mapping: Any, extensions: Any = None) -> bytes:
    """The owner's form with the mapped values in it, saved as new bytes.

    The caller's original file is never touched: this returns a fresh workbook and
    the lane stores it under a new id.
    """

    book = _workbook(payload)
    try:
        _extend_rows(book, extensions)
        _apply_mapping(book, mapping)
        output = BytesIO()
        book.save(output)
        return output.getvalue()
    finally:
        book.close()
