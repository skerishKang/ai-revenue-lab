"""Bind a real ERP import template to the canonical item-master fields.

This module exists so the ECOUNT profiles can become real without anybody
guessing a field name. It takes the **actual template file** the customer
downloaded from their ERP account, reads its header row, and produces:

* the template's own header row, verbatim and in the template's own order, so
  the written file can be pasted back into the template unchanged;
* the mapping from each canonical field to the template column that carries it;
* an explicit list of the canonical fields the template does not carry.

Three rules keep this honest:

* a written column header is **always** the text found in the template file,
  never a name this module invented;
* a canonical field that the template does not carry is reported as unmapped
  and is left empty, rather than pushed into a column that means something
  else;
* the result only becomes upload-ready when every required canonical field is
  really bound to a column of that file.

The header tokens below are **matching candidates only**. They decide which
template column a canonical field goes into; they never become an output
header. A template that uses different wording simply fails to bind, and the
binding report says which field is still unbound.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .contracts import CANONICAL_FIELDS, REQUIRED_FIELDS, ConfirmationStatus
from .erp_profile import ErpImportProfile, ImportColumn

#: Header text this module will *match* a template column by.
#:
#: These are candidate tokens, not output headers. The header that gets
#: written always comes from the template file itself.
TEMPLATE_HEADER_CANDIDATES: Mapping[str, tuple[str, ...]] = {
    "item_code": (
        "품목코드", "품목 코드", "품번", "자재코드", "자재 코드", "상품코드",
        "itemcode", "item code", "코드", "code",
    ),
    "item_name": (
        "상품명", "상품 명", "품목명", "품명", "제품명", "자재명",
        "itemname", "item name", "productname", "product name",
    ),
    "model_name": (
        "모델명", "모델", "모형", "modelname", "model", "model name",
    ),
    "manufacturer": (
        "제조사", "제조사명", "메이크", "maker", "manufacturer", "brand",
    ),
    "supplier": (
        "공급사", "공급업체", "공급처", "구매처", "구매처코드", "거래처",
        "supplier", "vendor",
    ),
    "specification": (
        "규격", "사양", "규격내용", "규격명", "specification", "spec",
    ),
    "unit": (
        "단위", "단위명", "단위코드", "unit", "uom",
    ),
    "category": (
        "분류", "상품분류", "품목분류", "품목분류코드", "분류코드", "카테고리",
        "품목그룹", "category", "itemgroup", "group",
    ),
    "purchase_price": (
        "매입가", "매입가격", "매입단가", "입고단가", "입고단가(VAT)",
        "purchaseprice", "purchase price", "inprice",
    ),
    "sales_price": (
        "판매가", "판매가격", "판매단가", "출고단가", "출고단가(VAT)",
        "salesprice", "sales price", "outprice",
    ),
}

#: How many leading rows of a template sheet are inspected for the header row.
MAX_HEADER_SEARCH_ROWS = 12

#: The binding report header, in order.
BINDING_REPORT_HEADERS: tuple[str, ...] = (
    "정규화필드",
    "템플릿열",
    "열인덱스",
    "필수여부",
    "확인상태",
    "근거",
)

_HEADER_NOISE = re.compile(r"[\s_\-/()\[\].:·,]+")

_CANDIDATE_INDEX: dict[str, str] = {}
for _name, _candidates in TEMPLATE_HEADER_CANDIDATES.items():
    for _candidate in _candidates:
        _CANDIDATE_INDEX.setdefault(_HEADER_NOISE.sub("", _candidate.lower()), _name)


class TemplateBindingError(Exception):
    """A template file the binder refuses to interpret."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class TemplateBinding:
    """What one real template file says about the canonical fields."""

    template_name: str
    template_sha256: str
    sheet_title: str
    header_row_index: int
    """The header row's index among the sheet's non-empty rows, from zero."""
    headers: tuple[str, ...]
    field_to_column: Mapping[str, int]
    unmapped_fields: tuple[str, ...]
    unbound_required_fields: tuple[str, ...]
    unused_template_columns: tuple[int, ...]
    notes: tuple[str, ...] = field(default=())
    @property
    def fully_bound(self) -> bool:
        """Whether every required canonical field found a real column."""

        return not self.unbound_required_fields

    def to_public_dict(self) -> dict[str, object]:
        return {
            "template_name": self.template_name,
            "template_sha256": self.template_sha256,
            "sheet_title": self.sheet_title,
            "header_row_index": self.header_row_index,
            "headers": list(self.headers),
            "field_to_column": dict(self.field_to_column),
            "unmapped_fields": list(self.unmapped_fields),
            "unbound_required_fields": list(self.unbound_required_fields),
            "unused_template_columns": list(self.unused_template_columns),
            "fully_bound": self.fully_bound,
            "notes": list(self.notes),
        }


def _header_key(value: object) -> str:
    text = "" if value is None else str(value)
    return _HEADER_NOISE.sub("", text.strip().lower())


def _match_fields(headers: Sequence[str]) -> dict[str, int]:
    """Match canonical fields to template columns.

    The first column wins, so a template with both "품목코드" and "코드"
    binds "품목코드" to the item code and leaves "코드" unmapped rather than
    guessing which one the ERP reads.
    """

    matches: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = _header_key(header)
        if not key:
            continue
        canonical = _CANDIDATE_INDEX.get(key)
        if canonical is None:
            continue
        if canonical in matches:
            continue
        matches[canonical] = index
    return matches


def _sheet_rows(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> tuple[tuple[str, ...], ...]:
    """The sheet's non-empty rows, in order, with the first row included.

    The shared Core reader treats the first non-empty row as the sheet's header
    and returns the rest as data rows. A vendor template usually puts a title
    and an instruction row above the real header, so the binder has to look at
    the whole sheet, not only at the rows the reader returned as data.
    """

    combined: list[tuple[str, ...]] = [tuple(str(value) for value in headers)]
    combined.extend(tuple(str(value) for value in row) for row in rows)
    return tuple(combined)


def _find_header_row(rows: Sequence[Sequence[str]]) -> int | None:
    """Find the row that is the template's header row.

    Vendor templates often put a title and an instruction row above the real
    header. The header row is the first row that matches at least one
    canonical field, preferring the row that matches the most.

    The returned index counts the sheet's non-empty rows from zero.
    """

    best_index: int | None = None
    best_score = 0
    for index, row in enumerate(rows[:MAX_HEADER_SEARCH_ROWS]):
        matched = _match_fields(row)
        if len(matched) > best_score:
            best_score = len(matched)
            best_index = index
    if best_index is None or best_score == 0:
        return None
    return best_index


def bind_template(template_path: str | Path) -> TemplateBinding:
    """Read one real template file and bind it to the canonical fields."""

    path = Path(template_path)
    if not path.is_file():
        raise TemplateBindingError("template_missing", f"The template file was not found: {path.name}")

    try:
        from padiem_ai_core.document_normalization import (
            DocumentNormalizationError,
            read_xlsx_table,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - Core is a hard dependency
        raise TemplateBindingError(
            "core_dependency_unavailable",
            "The Padiem Core document reader is unavailable.",
        ) from exc

    payload = path.read_bytes()
    try:
        table = read_xlsx_table(
            name=path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            payload=payload,
        )
    except DocumentNormalizationError as exc:
        raise TemplateBindingError("template_unreadable", exc.message) from exc

    header_index = _find_header_row(_sheet_rows(table.headers, table.rows))
    if header_index is None:
        raise TemplateBindingError(
            "template_header_not_found",
            "No header row matching a canonical item field was found in the template.",
        )

    sheet_rows = _sheet_rows(table.headers, table.rows)
    headers = tuple(str(value).strip() for value in sheet_rows[header_index])
    if not any(headers):
        raise TemplateBindingError(
            "template_header_empty",
            "The detected template header row is empty.",
        )

    matches = _match_fields(headers)
    unmapped = tuple(name for name in CANONICAL_FIELDS if name not in matches)
    unbound_required = tuple(name for name in REQUIRED_FIELDS if name not in matches)
    used = set(matches.values())
    unused = tuple(index for index in range(len(headers)) if index not in used)

    notes: list[str] = []
    if table.truncated:
        notes.append("template_rows_truncated_by_the_read_bound")
    notes.append(
        "required_column_evidence=UNVERIFIED; a vendor template marks required "
        "cells by colour and the bound reader does not report cell styling"
    )
    notes.append(
        "target_header_always_comes_from_the_template_file; this module never "
        "writes a header name it invented"
    )

    return TemplateBinding(
        template_name=path.name,
        template_sha256=hashlib.sha256(payload).hexdigest(),
        sheet_title=table.sheet_title,
        header_row_index=header_index,
        headers=headers,
        field_to_column=matches,
        unmapped_fields=unmapped,
        unbound_required_fields=unbound_required,
        unused_template_columns=unused,
        notes=tuple(notes),
    )


def binding_profile(
    binding: TemplateBinding,
    *,
    profile_id: str,
    display_name: str | None = None,
    transport: str = "FILE",
) -> ErpImportProfile:
    """Turn a real template binding into an import profile.

    The profile's columns are the template's own columns, in the template's own
    order. A canonical field that the template does not carry is left out of
    the file, and the fact is recorded in ``unmapped_fields``.
    """

    columns: list[ImportColumn] = []
    reverse = {index: name for name, index in binding.field_to_column.items()}
    for index, header in enumerate(binding.headers):
        canonical = reverse.get(index, "")
        if canonical:
            columns.append(
                ImportColumn(
                    canonical_field=canonical,
                    target_header=header,
                    required=canonical in REQUIRED_FIELDS,
                    confirmation=ConfirmationStatus.CONFIRMED_OFFICIAL,
                    evidence=(
                        f"ecount_template_file:{binding.template_name}"
                        f" sha256:{binding.template_sha256[:16]}"
                    ),
                    note="column read from the downloaded template header row",
                )
            )
        else:
            columns.append(
                ImportColumn(
                    canonical_field="",
                    target_header=header,
                    required=False,
                    confirmation=ConfirmationStatus.CONFIRMED_OFFICIAL,
                    evidence=(
                        f"ecount_template_file:{binding.template_name}"
                        f" sha256:{binding.template_sha256[:16]}"
                    ),
                    note="template column without a canonical field; written empty",
                )
            )

    notes = list(binding.notes)
    if binding.unmapped_fields:
        notes.append(
            "canonical fields this template does not carry: "
            + ", ".join(binding.unmapped_fields)
        )
    if binding.unbound_required_fields:
        notes.append(
            "required canonical fields still unbound: "
            + ", ".join(binding.unbound_required_fields)
        )

    return ErpImportProfile(
        profile_id=profile_id,
        display_name=display_name or f"{binding.template_name} 기반 임포트 프로파일",
        transport=transport,
        template_confirmed=True,
        confirmation_source=f"template_file:{binding.template_name}",
        columns=tuple(columns),
        unmapped_fields=binding.unmapped_fields,
        notes=" ".join(notes),
        upload_ready=binding.fully_bound,
    )


def binding_report_rows(binding: TemplateBinding) -> list[tuple[str, ...]]:
    """The rows that show exactly what a template binding decided."""

    rows: list[tuple[str, ...]] = []
    reverse = {index: name for name, index in binding.field_to_column.items()}
    for index, header in enumerate(binding.headers):
        canonical = reverse.get(index, "")
        rows.append(
            (
                canonical or "(매핑 없음)",
                header,
                str(index),
                "필수" if canonical in REQUIRED_FIELDS else "선택",
                (
                    ConfirmationStatus.CONFIRMED_OFFICIAL.value
                    if canonical
                    else ConfirmationStatus.NOT_FOUND.value
                ),
                (
                    f"template_file:{binding.template_name}"
                    f" sha256:{binding.template_sha256[:16]}"
                ),
            )
        )
    for name in binding.unmapped_fields:
        rows.append(
            (
                name,
                "(템플릿에 해당 열 없음)",
                "",
                "필수" if name in REQUIRED_FIELDS else "선택",
                ConfirmationStatus.NOT_FOUND.value,
                f"template_file:{binding.template_name}",
            )
        )
    return rows
