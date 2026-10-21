"""Write item-master output files.

Two properties are guaranteed for every file this module writes:

* a cell that could be read as a spreadsheet formula is neutralised before it
  is written, so an imported item name can never execute anything;
* a value the pipeline refused to derive stays empty. The exporter never fills
  a blank with a default, a guess or a zero.

The Excel workbook and the CSV files carry the same values for the same
records, so a reviewer can compare the two and reach the same conclusion.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .contracts import ItemRecord, ReviewStatus
from .erp_profile import ErpImportProfile
from .normalization import looks_like_formula

#: The master sheet header, in order.
MASTER_HEADERS: tuple[str, ...] = (
    "원본행",
    "품목코드",
    "상품명",
    "모델명",
    "제조사",
    "공급사",
    "규격",
    "단위",
    "상품분류",
    "매입가",
    "판매가",
    "정보출처",
    "중복그룹",
    "중복유형",
    "중복대상행",
    "검토상태",
    "검토사유",
    "오류",
)

#: The review sheet header, in order.
REVIEW_HEADERS: tuple[str, ...] = (
    "원본행",
    "품목코드",
    "상품명",
    "검토사유",
    "확인필요항목",
)

#: The duplicate report header, in order.
DUPLICATE_HEADERS: tuple[str, ...] = (
    "중복그룹",
    "유형",
    "기준행",
    "대상행",
    "유사도",
    "사유",
)

#: The field-mapping evidence header, in order.
MAPPING_HEADERS: tuple[str, ...] = (
    "프로필",
    "정규화필드",
    "대상필드",
    "필수여부",
    "확인상태",
    "근거",
    "비고",
)


def neutralize(value: str) -> str:
    """Make one cell safe to open in a spreadsheet."""

    if value and looks_like_formula(value):
        return "'" + value
    return value


def write_rows(
    path: str | Path,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> Path:
    """Write one UTF-8-with-BOM CSV file.

    The BOM keeps Korean headers readable when the file is opened in Excel on
    Windows, which is where an import file is usually opened first.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(list(headers))
        for row in rows:
            writer.writerow([neutralize("" if cell is None else str(cell)) for cell in row])
    return target


def master_row(record: ItemRecord, source_name: str) -> tuple[str, ...]:
    """The canonical master row for one record."""

    return (
        str(record.source_row),
        record.text("item_code"),
        record.text("item_name"),
        record.text("model_name"),
        record.text("manufacturer"),
        record.text("supplier"),
        record.text("specification"),
        record.text("unit"),
        record.text("category"),
        record.text("purchase_price"),
        record.text("sales_price"),
        f"{source_name}:row{record.source_row}",
        record.duplicate_group or "",
        record.duplicate_kind.value if record.duplicate_kind else "",
        record.duplicate_of or "",
        record.review_status.value,
        "; ".join(record.review_reasons),
        "; ".join(record.errors),
    )


def before_after_row(record: ItemRecord) -> tuple[str, ...]:
    """One row showing what the source said next to what it became."""

    cells: list[str] = [str(record.source_row)]
    for field_name in (
        "item_code",
        "item_name",
        "model_name",
        "manufacturer",
        "supplier",
        "specification",
        "unit",
        "category",
        "purchase_price",
        "sales_price",
    ):
        raw = record.raw.get(field_name, "")
        normalized = record.text(field_name)
        if not raw.strip():
            cells.append("")
        elif raw.strip() == normalized:
            cells.append(f"{raw} (동일)")
        else:
            cells.append(f"{raw} → {normalized}")
    return tuple(cells)


def before_after_headers() -> tuple[str, ...]:
    return (
        "원본행",
        "품목코드",
        "상품명",
        "모델명",
        "제조사",
        "공급사",
        "규격",
        "단위",
        "상품분류",
        "매입가",
        "판매가",
    )


def profile_rows(profile: ErpImportProfile, records: Sequence[ItemRecord]) -> list[tuple[str, ...]]:
    """The import rows for one profile, in profile column order."""

    rows: list[tuple[str, ...]] = []
    for record in records:
        cells: list[str] = []
        for column in profile.columns:
            if column.constant_value is not None:
                cells.append(column.constant_value)
                continue
            value = record.text(column.canonical_field)
            if column.canonical_field in ("purchase_price", "sales_price"):
                value = record.text(column.canonical_field)
            cells.append(value)
        rows.append(tuple(cells))
    return rows


def mapping_rows(profile: ErpImportProfile) -> list[tuple[str, ...]]:
    """The evidence rows that show what this profile is and is not confirmed."""

    rows: list[tuple[str, ...]] = []
    for column in profile.columns:
        rows.append(
            (
                profile.profile_id,
                column.canonical_field or "(상수)",
                column.target_header or "(확정 필요)",
                "필수" if column.required else "선택",
                column.confirmation.value,
                column.evidence,
                column.note,
            )
        )
    for field_name in profile.unmapped_fields:
        rows.append(
            (
                profile.profile_id,
                field_name,
                "(대응 필드 없음)",
                "선택",
                "NOT_FOUND",
                "no_official_or_reported_target_field",
                "이 정규화 필드는 이 프로필의 이관 파일에 실리지 않는다.",
            )
        )
    return rows


def write_workbook(
    path: str | Path,
    *,
    sheets: Sequence[tuple[str, Sequence[str], Sequence[Sequence[object]]]],
    summary: Mapping[str, object],
) -> Path:
    """Write the review workbook.

    ``sheets`` is a sequence of ``(title, headers, rows)``. Every value is
    written as text, so the workbook and the CSV files hold the same value for
    the same cell and a reviewer can compare them directly.
    """

    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError("The Excel writer dependency (openpyxl) is unavailable.") from exc

    # The write-only workbook streams the rows instead of holding every cell
    # in memory, which is what keeps a catalog of tens of thousands of rows
    # inside a normal machine's memory.
    workbook = Workbook(write_only=True)
    for title, headers, rows in sheets:
        worksheet = workbook.create_sheet(title=title[:31])
        for index, header in enumerate(headers, start=1):
            width = max(10, min(42, len(str(header)) + 6))
            worksheet.column_dimensions[get_column_letter(index)].width = width
        worksheet.freeze_panes = "A2"
        worksheet.append([neutralize(str(header)) for header in headers])
        for row in rows:
            worksheet.append([neutralize("" if cell is None else str(cell)) for cell in row])

    summary_sheet = workbook.create_sheet(title="처리요약")
    summary_sheet.column_dimensions["A"].width = 36
    summary_sheet.column_dimensions["B"].width = 64
    for key, value in summary.items():
        summary_sheet.append([str(key), "" if value is None else str(value)])

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    workbook.close()
    return target


def write_json(path: str | Path, payload: object) -> Path:
    """Write one UTF-8 JSON document."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def review_rows(records: Sequence[ItemRecord]) -> list[tuple[str, ...]]:
    """The rows that still need a person."""

    rows: list[tuple[str, ...]] = []
    for record in records:
        if record.review_status is not ReviewStatus.REVIEW_REQUIRED:
            continue
        rows.append(
            (
                str(record.source_row),
                record.text("item_code"),
                record.text("item_name"),
                "; ".join(record.review_reasons),
                _fields_to_confirm(record),
            )
        )
    return rows


def _fields_to_confirm(record: ItemRecord) -> str:
    fields: list[str] = []
    for reason in record.review_reasons:
        if reason.startswith("missing_"):
            fields.append(reason.removeprefix("missing_"))
        elif reason.startswith("unreadable_"):
            fields.append(reason.removeprefix("unreadable_"))
        elif reason.startswith("ai_filled_required_field:"):
            fields.append(reason.split(":", 1)[1])
        elif reason.startswith("low_confidence_ai_field:"):
            fields.append(reason.split(":", 1)[1].split("(", 1)[0])
        elif reason.startswith("duplicate_candidate:"):
            fields.append("중복 판정")
    return ", ".join(dict.fromkeys(fields))
