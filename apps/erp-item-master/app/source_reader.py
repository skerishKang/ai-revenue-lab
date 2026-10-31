"""Read a supplier catalog from CSV or Excel into a bounded source table.

The reader is deliberately thin. It decides two things only: which physical
column holds which canonical field, and what each cell literally said. It does
not clean, judge or complete a value — that is the normalizer's job, so a
value keeps one owner and one place where it was changed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .contracts import CANONICAL_FIELDS, ItemMasterError, SourceRow, SourceTable
from .normalization import normalize_text

#: Accepted source headers per canonical field. A supplier catalog rarely
#: uses one vocabulary, so each field accepts the terms that actually appear
#: in Korean and English purchasing documents.
HEADER_ALIASES: Mapping[str, tuple[str, ...]] = {
    "item_code": (
        "품목코드", "품목 코드", "품번", "자재코드", "자재 코드", "상품코드",
        "itemcode", "item code", "sku", "code",
    ),
    "item_name": (
        "상품명", "상품 명", "품목명", "품명", "제품명", "자재명",
        "itemname", "item name", "productname", "product name", "description",
    ),
    "model_name": (
        "모델명", "모델", "모형", "modelname", "model", "model name",
    ),
    "manufacturer": (
        "제조사", "제조사명", "메이크", "maker", "manufacturer", "brand",
    ),
    "supplier": (
        "공급사", "공급업체", "공급처", "구매처", "거래처",
        "supplier", "vendor", "suppliername",
    ),
    "specification": (
        "규격", "사양", "규격내용", "규격명", "specification", "spec", "size",
    ),
    "unit": (
        "단위", "단위명", "단위코드", "unit", "uom",
    ),
    "category": (
        "분류", "상품분류", "품목분류", "품목분류코드", "카테고리", "품목그룹",
        "category", "itemgroup", "group",
    ),
    "purchase_price": (
        "매입가", "매입가격", "매입단가", "입고단가", "원가",
        "purchaseprice", "purchase price", "inprice", "in price",
    ),
    "sales_price": (
        "판매가", "판매가격", "판매단가", "출고단가",
        "salesprice", "sales price", "outprice", "out price",
    ),
}

#: Free-text column kept out of the canonical record and offered to an
#: extraction step instead. It is where a supplier's unstructured note lives.
MEMO_ALIASES: tuple[str, ...] = (
    "메모", "비고", "참고", "상세", "상세내용", "메모사항",
    "memo", "note", "notes", "remark", "remarks", "comment",
)

#: Header keys are compared after this normalization.
_HEADER_NOISE = re.compile(r"[\s_\-/()\[\].:]+")

MAX_SOURCE_ROWS = 50_000
MAX_SOURCE_COLUMNS = 64


def _header_key(header: object) -> str:
    text = normalize_text(header).lower()
    return _HEADER_NOISE.sub("", text)


_ALIAS_INDEX: dict[str, str] = {}
for _field_name, _aliases in HEADER_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_INDEX.setdefault(_HEADER_NOISE.sub("", _alias.lower()), _field_name)

_MEMO_INDEX: dict[str, str] = {
    _HEADER_NOISE.sub("", _alias.lower()): "memo" for _alias in MEMO_ALIASES
}


def map_headers(headers: Sequence[str]) -> tuple[dict[str, int], tuple[str, ...], int | None]:
    """Map physical headers onto canonical fields.

    Returns the column index per canonical field, the headers that matched no
    canonical field, and the memo column index when one is present. A header
    that matches two fields keeps the first match and the later one is
    reported as unmapped, so one column can never feed two fields.
    """

    column_by_field: dict[str, int] = {}
    unmapped: list[str] = []
    memo_index: int | None = None
    for index, header in enumerate(headers):
        key = _header_key(header)
        if not key:
            unmapped.append(header)
            continue
        if key in _ALIAS_INDEX:
            field_name = _ALIAS_INDEX[key]
            if field_name in column_by_field:
                unmapped.append(header)
                continue
            column_by_field[field_name] = index
            continue
        if key in _MEMO_INDEX and memo_index is None:
            memo_index = index
            continue
        unmapped.append(header)
    return column_by_field, tuple(unmapped), memo_index


def _rows_from_csv(path: Path) -> tuple[tuple[str, ...], list[tuple[int, list[str]]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header_row = next(reader)
        except StopIteration as exc:
            raise ItemMasterError("empty_source", "The source file has no header row.") from exc
        headers = tuple(str(cell) for cell in header_row)
        body: list[tuple[int, list[str]]] = []
        for source_row, row in enumerate(reader, start=2):
            if not any(str(cell).strip() for cell in row):
                continue
            if len(body) >= MAX_SOURCE_ROWS:
                break
            body.append((source_row, [str(cell) for cell in row]))
    return headers, body


def _rows_from_xlsx(path: Path) -> tuple[tuple[str, ...], list[tuple[int, list[str]]], str, bool]:
    try:
        from padiem_ai_core.document_normalization import (
            DocumentNormalizationError,
            read_xlsx_table,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - Core is a hard dependency
        raise ItemMasterError(
            "core_dependency_unavailable",
            "The Padiem Core document reader is unavailable.",
        ) from exc

    try:
        table = read_xlsx_table(
            name=path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            payload=path.read_bytes(),
        )
    except DocumentNormalizationError as exc:
        raise ItemMasterError("xlsx_unreadable", exc.message) from exc

    body: list[tuple[int, list[str]]] = []
    for offset, row in enumerate(table.rows, start=2):
        body.append((offset, list(row)))
    return table.headers, body, table.sheet_title, table.truncated


def read_source(path: str | Path) -> SourceTable:
    """Read one supplier catalog into a bounded, column-mapped source table."""

    source_path = Path(path)
    if not source_path.is_file():
        raise ItemMasterError("source_missing", f"The source file was not found: {source_path.name}")

    suffix = source_path.suffix.lower()
    sheet_title: str | None = None
    truncated = False
    if suffix == ".csv":
        headers, body = _rows_from_csv(source_path)
        origin_kind = "csv"
    elif suffix == ".xlsx":
        headers, body, sheet_title, truncated = _rows_from_xlsx(source_path)
        origin_kind = "xlsx"
    else:
        raise ItemMasterError(
            "unsupported_source_type",
            "Only .csv and .xlsx sources are supported.",
        )

    if len(headers) > MAX_SOURCE_COLUMNS:
        raise ItemMasterError(
            "too_many_columns",
            "The source table has more columns than the supported bound.",
        )

    column_by_field, unmapped, memo_index = map_headers(headers)
    if not column_by_field:
        raise ItemMasterError(
            "no_mappable_columns",
            "No source column matched a canonical item-master field.",
        )

    rows: list[SourceRow] = []
    for source_row, cells in body:
        mapped: dict[str, str] = {}
        for field_name, column_index in column_by_field.items():
            mapped[field_name] = cells[column_index] if column_index < len(cells) else ""
        if memo_index is not None:
            mapped["memo"] = cells[memo_index] if memo_index < len(cells) else ""
        rows.append(
            SourceRow(
                source_row=source_row,
                cells=mapped,
                locator=f"{source_path.name}:row{source_row}",
            )
        )

    return SourceTable(
        headers=headers,
        rows=tuple(rows),
        column_by_field=column_by_field,
        unmapped_headers=unmapped,
        origin_kind=origin_kind,
        sheet_title=sheet_title,
        truncated=truncated,
    )


def canonical_fields_present(column_by_field: Mapping[str, int]) -> tuple[str, ...]:
    """The canonical fields this source actually carries."""

    return tuple(name for name in CANONICAL_FIELDS if name in column_by_field)


def iter_source_headers(table: SourceTable) -> Iterable[str]:
    return table.headers
