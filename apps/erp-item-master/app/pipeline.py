"""The item-master pipeline: read, normalize, dedupe, review, export.

One run answers the question this pilot asks: how much of a supplier catalog
can be turned into an ERP import file without a person touching it, how long
does that take, and what still needs a person.

The pipeline never invents a value. A field it cannot read stays empty and the
record carries a review reason, so the numbers in the report describe real
work rather than a best guess.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from .contracts import (
    CANONICAL_FIELDS,
    PRICE_FIELDS,
    FieldOrigin,
    FieldValue,
    ItemMasterError,
    ItemRecord,
    ReviewStatus,
)
from .duplicate_detection import (
    FUZZY_BLOCKING_NOTE,
    DuplicateFinding,
    scan_duplicates,
)
from .erp_profile import ErpImportProfile, all_profiles, profile_by_id
from .exporter import (
    DUPLICATE_HEADERS,
    MAPPING_HEADERS,
    MASTER_HEADERS,
    REVIEW_HEADERS,
    before_after_headers,
    before_after_row,
    mapping_rows,
    master_row,
    profile_rows,
    review_rows,
    write_json,
    write_rows,
    write_workbook,
)
from .extraction import AI_ASSIGNABLE_FIELDS, AI_PROVIDER_CALLS_IN_THIS_APP
from .normalization import (
    normalize_code,
    normalize_text,
    parse_price,
    rule_field,
    source_field,
)
from .review_rules import apply_review_rules
from .source_reader import SourceTable, read_source


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """What one pipeline run produced and how long each stage took."""

    source_name: str
    source_kind: str
    sheet_title: str | None
    source_headers: tuple[str, ...]
    unmapped_headers: tuple[str, ...]
    row_count: int
    auto_ok_count: int
    review_required_count: int
    duplicate_group_count: int
    duplicate_record_count: int
    duplicate_skipped_blocks: int
    duplicate_compared_pairs: int
    error_count: int
    ai_filled_field_count: int
    extraction_error_count: int
    timings_ms: Mapping[str, float]
    outputs: tuple[str, ...]
    profiles: Mapping[str, str]
    records: tuple[ItemRecord, ...] = field(default=(), repr=False)
    findings: tuple[DuplicateFinding, ...] = field(default=(), repr=False)

    def to_public_dict(self) -> dict[str, object]:
        """The report without the record bodies."""

        return {
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "sheet_title": self.sheet_title,
            "source_headers": list(self.source_headers),
            "unmapped_headers": list(self.unmapped_headers),
            "row_count": self.row_count,
            "auto_ok_count": self.auto_ok_count,
            "review_required_count": self.review_required_count,
            "duplicate_group_count": self.duplicate_group_count,
            "duplicate_record_count": self.duplicate_record_count,
            "duplicate_skipped_blocks": self.duplicate_skipped_blocks,
            "duplicate_compared_pairs": self.duplicate_compared_pairs,
            "error_count": self.error_count,
            "ai_filled_field_count": self.ai_filled_field_count,
            "extraction_error_count": self.extraction_error_count,
            "timings_ms": {key: round(value, 3) for key, value in self.timings_ms.items()},
            "outputs": list(self.outputs),
            "profiles": dict(self.profiles),
        }


def _price_field(raw: str, *, locator: str) -> FieldValue:
    amount, error = parse_price(raw)
    if error is not None:
        return FieldValue(
            value="",
            origin=FieldOrigin.MISSING,
            confidence=Decimal("0"),
            source_locator=locator,
            note=error,
        )
    if amount is None:
        return FieldValue(
            value="",
            origin=FieldOrigin.MISSING,
            confidence=Decimal("0"),
            source_locator=locator,
            note="empty_in_source",
        )
    return FieldValue(
        value=amount,
        origin=FieldOrigin.RULE,
        confidence=Decimal("1"),
        source_locator=locator,
        note="parsed_from_source",
    )


def build_record(
    source_row: int,
    cells: Mapping[str, str],
    *,
    locator: str,
    extracted: Mapping[str, FieldValue] | None = None,
) -> ItemRecord:
    """Normalize one source row into one canonical record.

    A source value always wins. An extraction only fills a field the source
    left empty, and only for a field an extraction is allowed to propose.
    """

    fields: dict[str, FieldValue] = {}

    code_raw = cells.get("item_code", "")
    code = normalize_code(code_raw)
    fields["item_code"] = (
        rule_field(code, locator=f"{locator}:item_code", note="normalized_code")
        if code
        else source_field(code_raw, locator=f"{locator}:item_code")
    )

    for field_name in (
        "item_name",
        "model_name",
        "manufacturer",
        "supplier",
        "specification",
        "unit",
        "category",
        "memo",
    ):
        fields[field_name] = source_field(
            cells.get(field_name, ""),
            locator=f"{locator}:{field_name}",
        )

    for field_name in PRICE_FIELDS:
        fields[field_name] = _price_field(
            cells.get(field_name, ""),
            locator=f"{locator}:{field_name}",
        )

    if extracted:
        for field_name, value in extracted.items():
            if field_name not in AI_ASSIGNABLE_FIELDS:
                continue
            current = fields.get(field_name)
            if current is not None and current.present:
                continue
            fields[field_name] = value

    return ItemRecord(
        source_row=source_row,
        fields=fields,
        raw={name: str(value) for name, value in cells.items()},
    )


def _records_from_table(
    table: SourceTable,
    extractions: tuple[
        Mapping[int, tuple[Mapping[str, FieldValue], Sequence[str]]],
        Mapping[str, tuple[Mapping[str, FieldValue], Sequence[str]]],
    ],
) -> tuple[list[ItemRecord], int, int]:
    by_row, by_code = extractions
    records: list[ItemRecord] = []
    ai_filled = 0
    extraction_errors = 0
    for row in table.rows:
        code = normalize_code(row.cells.get("item_code", ""))
        found = by_row.get(row.source_row)
        if found is None and code:
            found = by_code.get(code.upper())
        extracted_payload, row_errors = found if found is not None else ({}, ())
        extraction_errors += len(row_errors)
        record = build_record(
            row.source_row,
            row.cells,
            locator=row.locator,
            extracted=extracted_payload,
        )
        ai_filled += sum(
            1
            for value in record.fields.values()
            if value.origin is FieldOrigin.AI_EXTRACTION
        )
        errors = tuple(row_errors)
        if errors:
            record = ItemRecord(
                source_row=record.source_row,
                fields=record.fields,
                raw=record.raw,
                review_reasons=record.review_reasons,
                errors=errors,
            )
        records.append(record)
    return records, ai_filled, extraction_errors


def run_pipeline(
    *,
    source: str | Path,
    output_dir: str | Path,
    extraction_file: str | Path | None = None,
    profile_ids: Sequence[str] = ("generic", "ecount_api_candidate"),
    extra_profiles: Sequence[ErpImportProfile] = (),
) -> PipelineReport:
    """Run the whole pipeline once and write every output file.

    ``extra_profiles`` carries profiles that were built at run time, such as
    one bound to a real ERP template file. They are written after the
    registered profiles and never replace one of them.
    """

    from .extraction import load_extraction_file

    timings: dict[str, float] = {}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    table = read_source(source)
    timings["read"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    extractions: tuple[
        Mapping[int, tuple[Mapping[str, FieldValue], Sequence[str]]],
        Mapping[str, tuple[Mapping[str, FieldValue], Sequence[str]]],
    ] = ({}, {})
    if extraction_file is not None:
        extractions = load_extraction_file(extraction_file)
    records, ai_filled, extraction_errors = _records_from_table(table, extractions)
    timings["normalize"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    scan = scan_duplicates(records)
    records = list(scan.records)
    findings = scan.findings
    timings["detect_duplicates"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    records = apply_review_rules(records)
    timings["review"] = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    auto_ok = [record for record in records if record.review_status is ReviewStatus.AUTO_OK]
    source_name = Path(source).name

    outputs: list[str] = []

    def written(path: Path) -> None:
        """Remember one written file with a portable, readable path."""

        outputs.append(path.as_posix())

    written(
        write_rows(
            output_path / "item_master_normalized.csv",
            MASTER_HEADERS,
            [master_row(record, source_name) for record in records],
        )
    )
    written(
        write_rows(
            output_path / "item_master_before_after.csv",
            before_after_headers(),
            [before_after_row(record) for record in records],
        )
    )
    written(
        write_rows(
            output_path / "review_required.csv",
            REVIEW_HEADERS,
            review_rows(records),
        )
    )
    duplicate_rows = [
        (
            finding.group_id,
            finding.kind.value,
            str(finding.primary_row),
            str(row),
            str(finding.similarity),
            finding.detail,
        )
        for finding in findings
        for row in finding.duplicate_rows
    ]
    written(
        write_rows(
            output_path / "duplicate_report.csv",
            DUPLICATE_HEADERS,
            duplicate_rows,
        )
    )

    mapping_rows_all: list[tuple[str, ...]] = []
    profile_sheets: list[tuple[str, Sequence[str], Sequence[Sequence[object]]]] = []
    profile_status: dict[str, str] = {}

    profiles: dict[str, ErpImportProfile] = {
        profile_id: profile_by_id(profile_id) for profile_id in profile_ids
    }
    for extra in extra_profiles:
        profiles[extra.profile_id] = extra

    for profile_id, profile in profiles.items():
        file_name = _profile_file_name(profile)
        written(
            write_rows(
                output_path / file_name,
                profile.header_row,
                profile_rows(profile, auto_ok),
            )
        )
        mapping_rows_all.extend(mapping_rows(profile))
        profile_status[profile_id] = (
            f"template_confirmed={profile.template_confirmed};"
            f"upload_ready={profile.upload_ready};"
            f"columns={len(profile.columns)}"
        )
        profile_sheets.append(
            (
                _profile_sheet_title(profile),
                profile.header_row,
                profile_rows(profile, auto_ok),
            )
        )

    written(
        write_rows(
            output_path / "erp_field_mapping_status.csv",
            MAPPING_HEADERS,
            mapping_rows_all,
        )
    )

    summary = {
        "소스파일": source_name,
        "소스형식": table.origin_kind,
        "시트명": table.sheet_title or "",
        "전체행수": len(records),
        "자동확정행수": len(auto_ok),
        "사람확인필요행수": len(records) - len(auto_ok),
        "중복그룹수": len(findings),
        "중복판정대상행수": sum(len(item.duplicate_rows) for item in findings),
        "중복탐색건너뛴블록수": scan.skipped_blocks,
        "중복탐색비교건수": scan.compared_pairs,
        "오류건수": sum(len(record.errors) for record in records),
        "AI추출적용필드수": ai_filled,
        "추출검증오류건수": extraction_errors,
        "중복탐색차단방식": FUZZY_BLOCKING_NOTE,
        "이앱의모델호출횟수": AI_PROVIDER_CALLS_IN_THIS_APP,
    }
    for profile_id, status in profile_status.items():
        summary[f"프로필:{profile_id}"] = status

    sheets: list[tuple[str, Sequence[str], Sequence[Sequence[object]]]] = [
        ("품목마스터", MASTER_HEADERS, [master_row(record, source_name) for record in records]),
        ("원본비교", before_after_headers(), [before_after_row(record) for record in records]),
        *profile_sheets,
        ("검토필요", REVIEW_HEADERS, review_rows(records)),
        ("중복보고", DUPLICATE_HEADERS, duplicate_rows),
        ("필드매핑증거", MAPPING_HEADERS, mapping_rows_all),
    ]
    written(
        write_workbook(
            output_path / "item_master_workbook.xlsx",
            sheets=sheets,
            summary=summary,
        )
    )
    timings["export"] = (time.perf_counter() - started) * 1000
    timings["total"] = sum(timings.values())

    report_path = output_path / "pipeline_report.json"
    written(report_path)

    report = PipelineReport(
        source_name=source_name,
        source_kind=table.origin_kind,
        sheet_title=table.sheet_title,
        source_headers=table.headers,
        unmapped_headers=table.unmapped_headers,
        row_count=len(records),
        auto_ok_count=len(auto_ok),
        review_required_count=len(records) - len(auto_ok),
        duplicate_group_count=len(findings),
        duplicate_record_count=sum(len(item.duplicate_rows) for item in findings),
        duplicate_skipped_blocks=scan.skipped_blocks,
        duplicate_compared_pairs=scan.compared_pairs,
        error_count=sum(len(record.errors) for record in records),
        ai_filled_field_count=ai_filled,
        extraction_error_count=extraction_errors,
        timings_ms=timings,
        outputs=tuple(outputs),
        profiles=profile_status,
        records=tuple(records),
        findings=findings,
    )
    write_json(report_path, report.to_public_dict())
    return report


def _profile_file_name(profile: ErpImportProfile) -> str:
    if profile.upload_ready:
        return f"erp_import_{profile.profile_id}.csv"
    return f"erp_import_{profile.profile_id}_CANDIDATE.csv"


def _profile_sheet_title(profile: ErpImportProfile) -> str:
    title = f"이관_{profile.profile_id}"
    return title[:31]


def available_profiles() -> Mapping[str, ErpImportProfile]:
    """Every import profile this repository ships."""

    return all_profiles()
