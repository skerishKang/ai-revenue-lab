"""#8953 3b: bounded, path-free PDF page / XLSX cell selection child.

The approved PC caller supplies complete bytes through stdin, never a path.
The existing Core pypdf and OOXML guards own format security. No network,
filesystem opens, subprocesses, passwords, or OCR are permitted here.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import json
import re
import sys
from collections.abc import Mapping

from padiem_ai_core.document_normalization import (
    DocumentNormalizationError, _open_pdf_reader, _bounded_ooxml_repackage,
    validate_ooxml_archive, _cell_text,
)

MAX_SELECTION_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SELECTION_ENVELOPE_BYTES = ((MAX_SELECTION_SOURCE_BYTES + 2) // 3) * 4 + 4096
MAX_SELECTION_REPORT_BYTES = 256 * 1024
MAX_PDF_PAGES = 10
MAX_XLSX_CELLS = 2000
MAX_EXCEL_ROW = 1048576
MAX_EXCEL_COLUMN = 16384

_PDF_MEDIA = "application/pdf"
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_RANGE_RE = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6}):([A-Z]{1,3})([1-9][0-9]{0,6})\Z")


class SelectionRefusal(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _wire(obj: Mapping) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fits(obj: Mapping) -> bool:
    return len(_wire(obj)) <= MAX_SELECTION_REPORT_BYTES


def _error(code: str) -> dict:
    if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,39}", code) is None:
        code = "parse_failed"
    return {"ok": False, "error": code}


def _core_refusal(exc: DocumentNormalizationError) -> SelectionRefusal:
    code = exc.code
    return SelectionRefusal({
        "pdf_encrypted": "encrypted",
        "ooxml_encrypted": "encrypted",
        "document_dependency_unavailable": "extractor_unavailable",
    }.get(code, "invalid_document"))


def _pdf_selection(payload: bytes, *, start: int, count: int) -> dict:
    try:
        reader = _open_pdf_reader(payload, recover_broken_structure=True)
    except DocumentNormalizationError as exc:
        raise _core_refusal(exc) from None
    try:
        total = len(reader.pages)
        if start > total:
            raise SelectionRefusal("page_out_of_range")
        end = min(total, start + count - 1)
        entries: list[dict] = []
        for page_no in range(start, end + 1):
            try:
                body = (reader.pages[page_no - 1].extract_text() or "").strip()
            except Exception:
                raise SelectionRefusal("invalid_document") from None
            if not body:
                raise SelectionRefusal("ocr_required")
            candidate = entries + [{"page": page_no, "text": body}]
            more = page_no < total
            text = "\n\n".join(f"[page {p['page']}]\n{p['text']}" for p in candidate)
            item = {
                "ok": True, "unit": "pages", "size_bytes": len(payload), "total_pages": total,
                "page": start, "page_count": len(candidate),
                "pages": candidate, "text": text,
                "eof": not more, "partial": False,
                "truncated": more,
                "truncation_reason": ("response_bytes_limit" if page_no < end
                                      else "page_count_limit") if more else None,
                "has_more": more,
                "next_cursor": page_no + 1 if more else None,
                "source_complete": True,
            }
            if not _fits(item):
                if not entries:
                    raise SelectionRefusal("page_too_large")
                break
            entries = candidate
        last = entries[-1]["page"]
        more = last < total
        body = {
            "ok": True, "unit": "pages", "size_bytes": len(payload), "total_pages": total,
            "page": start, "page_count": len(entries),
            "pages": entries,
            "text": "\n\n".join(f"[page {p['page']}]\n{p['text']}" for p in entries),
            "eof": not more, "partial": False, "truncated": more,
            "truncation_reason": ("response_bytes_limit" if last < end
                                  else "page_count_limit") if more else None,
            "has_more": more,
            "next_cursor": last + 1 if more else None,
            "source_complete": True,
        }
        if not _fits(body):
            raise SelectionRefusal("response_bytes_limit")
        return body
    finally:
        if hasattr(reader, "close"):
            reader.close()


def _range_coordinates(text: str) -> tuple[int, int, int, int, str, str]:
    from openpyxl.utils.cell import column_index_from_string, get_column_letter
    match = _RANGE_RE.fullmatch(text)
    if match is None:
        raise SelectionRefusal("range_invalid")
    c1, r1, c2, r2 = match.groups()
    try:
        a, b = column_index_from_string(c1), column_index_from_string(c2)
        first, last = int(r1), int(r2)
    except (TypeError, ValueError):
        raise SelectionRefusal("range_invalid") from None
    if not (1 <= a <= b <= MAX_EXCEL_COLUMN and 1 <= first <= last <= MAX_EXCEL_ROW):
        raise SelectionRefusal("range_invalid")
    if (b - a + 1) * (last - first + 1) > MAX_XLSX_CELLS:
        raise SelectionRefusal("cell_limit_exceeded")
    return a, b, first, last, get_column_letter(a), get_column_letter(b)


def _xlsx_selection(payload: bytes, *, sheet_name: str, selection: str) -> dict:
    try:
        from openpyxl import load_workbook
        from openpyxl.utils.cell import get_column_letter
    except (ImportError, ModuleNotFoundError):
        raise SelectionRefusal("extractor_unavailable") from None
    a, b, first, last, start_col, end_col = _range_coordinates(selection)
    try:
        validate_ooxml_archive(payload)
        safe = _bounded_ooxml_repackage(payload)
    except DocumentNormalizationError as exc:
        raise _core_refusal(exc) from None
    except Exception:
        raise SelectionRefusal("invalid_document") from None
    values = formulas = None
    try:
        values = load_workbook(BytesIO(safe), read_only=True, data_only=True, keep_links=False)
        formulas = load_workbook(BytesIO(safe), read_only=True, data_only=False, keep_links=False)
        if sheet_name not in values.sheetnames or sheet_name not in formulas.sheetnames:
            raise SelectionRefusal("sheet_not_found")
        v_sheet, f_sheet = values[sheet_name], formulas[sheet_name]
        chosen: list[dict] = []
        note_lines: list[str] = []
        processed = 0
        for row_no, (vrow, frow) in enumerate(
                zip(v_sheet.iter_rows(min_row=first, max_row=last, min_col=a, max_col=b),
                    f_sheet.iter_rows(min_row=first, max_row=last, min_col=a, max_col=b)),
                start=first):
            row_entries = []
            row_lines = []
            for index, (value_cell, formula_cell) in enumerate(zip(vrow, frow)):
                name = f"{get_column_letter(a + index)}{row_no}"
                value = _cell_text(value_cell.value)
                formula = formula_cell.value
                if isinstance(formula, str) and formula.startswith("="):
                    item = {"cell": name, "value": value, "formula": formula}
                    line = f"[{sheet_name}!{name}] {formula} => {value or '(no cached value)'}"
                else:
                    item = {"cell": name, "value": value}
                    line = f"[{sheet_name}!{name}] {value}"
                row_entries.append(item)
                row_lines.append(line)
            candidate = chosen + row_entries
            text = "\n".join(note_lines + row_lines)
            has_more = row_no < last
            next_cursor = f"{start_col}{row_no + 1}:{end_col}{last}" if has_more else None
            frame = {
                "ok": True, "unit": "cells", "size_bytes": len(payload), "sheet": sheet_name, "range": selection,
                "cell_count": len(candidate), "cells": candidate, "text": text,
                "eof": not has_more, "partial": False, "truncated": has_more,
                "truncation_reason": "response_bytes_limit" if has_more else None,
                "has_more": has_more, "next_cursor": next_cursor,
                "source_complete": True,
            }
            if not _fits(frame):
                if not chosen:
                    raise SelectionRefusal("row_too_large")
                break
            chosen = candidate
            note_lines.extend(row_lines)
            processed = row_no - first + 1
        if processed == 0:
            raise SelectionRefusal("range_invalid")
        remaining = processed < last - first + 1
        next_row = first + processed
        answer = {
            "ok": True, "unit": "cells", "size_bytes": len(payload), "sheet": sheet_name, "range": selection,
            "cell_count": len(chosen), "cells": chosen,
            "text": "\n".join(note_lines), "eof": not remaining, "partial": False,
            "truncated": remaining,
            "truncation_reason": "response_bytes_limit" if remaining else None,
            "has_more": remaining,
            "next_cursor": f"{start_col}{next_row}:{end_col}{last}" if remaining else None,
            "source_complete": True,
        }
        if not _fits(answer):
            raise SelectionRefusal("response_bytes_limit")
        return answer
    except SelectionRefusal:
        raise
    except Exception:
        raise SelectionRefusal("invalid_document") from None
    finally:
        if formulas is not None:
            formulas.close()
        if values is not None:
            values.close()


def select_document(request: Mapping) -> dict:
    if not isinstance(request, dict):
        return _error("range_invalid")
    is_pdf = set(request) == {"name", "media_type", "base64", "page", "page_count"}
    is_xlsx = set(request) == {"name", "media_type", "base64", "sheet", "range"}
    if not is_pdf and not is_xlsx:
        return _error("range_invalid")
    name, media, data = request["name"], request["media_type"], request["base64"]
    if (not isinstance(name, str) or not 0 < len(name) <= 255
            or "/" in name or "\\" in name or "\x00" in name
            or not isinstance(data, str)
            or media != (_PDF_MEDIA if is_pdf else _XLSX_MEDIA)):
        return _error("range_invalid")
    if is_pdf:
        if not name.lower().endswith(".pdf"):
            return _error("range_invalid")
        page, count = request["page"], request["page_count"]
        if (type(page) is not int or type(count) is not int
                or not 1 <= page <= (1 << 40) or not 1 <= count <= MAX_PDF_PAGES):
            return _error("range_invalid")
    else:
        if not name.lower().endswith(".xlsx"):
            return _error("range_invalid")
        sheet, selection = request["sheet"], request["range"]
        if (not isinstance(sheet, str) or not 0 < len(sheet) <= 128
                or any(ord(c) < 32 for c in sheet)
                or not isinstance(selection, str) or len(selection) > 32):
            return _error("range_invalid")
    try:
        payload = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        return _error("invalid_document")
    if len(payload) == 0:
        return _error("invalid_document")
    if len(payload) > MAX_SELECTION_SOURCE_BYTES:
        return _error("source_limit_exceeded")
    try:
        return (_pdf_selection(payload, start=page, count=count) if is_pdf
                else _xlsx_selection(payload, sheet_name=sheet, selection=selection))
    except SelectionRefusal as exc:
        return _error(exc.code)
    except (MemoryError, RecursionError):
        return _error("source_limit_exceeded")
    except BaseException:
        return _error("parse_failed")


def main() -> int:
    # Read a complete bounded envelope only; never open a host path.
    raw = getattr(sys.stdin, "buffer", None)
    if raw is None:
        return 0
    try:
        body = raw.read(MAX_SELECTION_ENVELOPE_BYTES + 1)
        if len(body) > MAX_SELECTION_ENVELOPE_BYTES:
            result = _error("source_limit_exceeded")
        else:
            try:
                request = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeError):
                request = None
            result = select_document(request)
        output = _wire(result)
        if len(output) > MAX_SELECTION_REPORT_BYTES:
            output = _wire(_error("response_bytes_limit"))
        sys.stdout.buffer.write(output + b"\n")
        sys.stdout.buffer.flush()
    except BaseException:
        try:
            sys.stdout.buffer.write(_wire(_error("parse_failed")) + b"\n")
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
