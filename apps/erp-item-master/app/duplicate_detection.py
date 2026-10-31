"""Duplicate detection for normalized item-master records.

Three kinds of duplicate are separated, because they need different human
decisions:

``EXACT_CODE``
    Two records carry the same item code. One of them is the same ERP row and
    the other is a mistake. The code is the ERP key, so this is decided
    automatically.

``SAME_NAME_SPEC``
    Two records agree on name, specification and unit. They are the same item
    described twice. Flagged automatically.

``FUZZY_NAME``
    Two records have near-identical names in the same unit. They *may* be the
    same item. This is only ever a candidate, and it always reaches a person.

The two exact passes are dictionary passes, so they cost one lookup per row.
The fuzzy pass compares names, so it is blocked: a record only meets another
record when they share a block key, and a block that grows past
``MAX_BLOCK_SIZE`` is skipped instead of being compared pairwise. Both
properties are what keep the pass usable on a catalog of tens of thousands of
rows, and both are reported rather than hidden: see
``DUPLICATE_FUZZY_SKIPPED_BLOCKS``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Mapping, Sequence

from .contracts import DuplicateKind, ItemRecord
from .normalization import normalize_form_name

#: Name similarity at or above which two items become a fuzzy-duplicate
#: candidate. The value is deliberately high: a false positive costs a person
#: a look, and a false negative is found later by the ERP's own check.
FUZZY_NAME_SIMILARITY_THRESHOLD = Decimal("0.92")

#: How many leading and trailing name characters decide a block.
BLOCK_PREFIX_CHARS = 4
BLOCK_SUFFIX_CHARS = 4

#: A block larger than this is skipped by the fuzzy pass. A block this large
#: means the blocking key did not separate the records, so comparing them
#: pairwise would cost more than it is worth.
MAX_BLOCK_SIZE = 400

#: The fuzzy pass is blocked on unit, on the digits the name carries and on
#: the leading and trailing name characters.
FUZZY_BLOCKING_NOTE = (
    "FUZZY_BLOCKING=unit+digits+prefix4+suffix4;"
    f"MAX_BLOCK_SIZE={MAX_BLOCK_SIZE};"
    "a skipped block is reported, not silently ignored"
)

#: Digit runs inside a normalized name.
_DIGIT_RUN = re.compile(r"\d+")

#: A name whose lengths differ by more than this cannot reach the similarity
#: threshold, so the pair is dropped before the comparison runs.
#:
#: The bound follows from the threshold itself: the ratio is ``2M/(la+lb)`` and
#: ``M`` can never exceed the shorter name, so ``la+lb <= 2M/0.92`` allows a
#: length difference of up to about 17% of the longer name. The bound is set
#: just under that value so the filter can never reject a pair the ratio
#: would have accepted.
_LENGTH_TOLERANCE = Decimal("0.17")


@dataclass(frozen=True, slots=True)
class DuplicateFinding:
    """One duplicate group and why it was formed."""

    group_id: str
    kind: DuplicateKind
    primary_row: int
    duplicate_rows: tuple[int, ...]
    similarity: Decimal
    detail: str


def _name_key(record: ItemRecord) -> str:
    return normalize_form_name(record.text("item_name"))


def _spec_key(record: ItemRecord) -> str:
    return normalize_form_name(record.text("specification"))


def _unit_key(record: ItemRecord) -> str:
    return normalize_form_name(record.text("unit"))


def _code_key(record: ItemRecord) -> str:
    return record.text("item_code").upper()


def _similarity(left: str, right: str) -> Decimal:
    if not left or not right:
        return Decimal("0")
    ratio = SequenceMatcher(None, left, right).ratio()
    return Decimal(str(round(ratio, 4)))


def _apply(
    records: Sequence[ItemRecord],
    groups: Mapping[int, tuple[str, DuplicateKind, int, str]],
) -> list[ItemRecord]:
    updated: list[ItemRecord] = []
    for record in records:
        entry = groups.get(record.source_row)
        if entry is None:
            updated.append(record)
            continue
        group_id, kind, primary_row, detail = entry
        updated.append(
            replace(
                record,
                duplicate_group=group_id,
                duplicate_kind=kind,
                duplicate_of=f"row{primary_row}" if record.source_row != primary_row else None,
                review_reasons=record.review_reasons + (detail,),
            )
        )
    return updated


def _blocking_keys(record: ItemRecord) -> tuple[tuple[str, str], ...]:
    """The block keys one record belongs to.

    Four keys are used so that a near-duplicate is very likely to share one:
    the unit, the digit runs the name carries, the leading characters and the
    trailing characters. A name with no digits contributes no digit block, so
    two records whose only common part is a shared prefix are still separated
    by the suffix block.
    """

    unit = _unit_key(record)
    name = _name_key(record)
    if not name:
        return ()
    keys: list[tuple[str, str]] = [
        (unit, f"prefix:{name[:BLOCK_PREFIX_CHARS]}"),
        (unit, f"suffix:{name[-BLOCK_SUFFIX_CHARS:]}"),
    ]
    digits = "|".join(sorted(_DIGIT_RUN.findall(name)))
    if digits:
        keys.append((unit, f"digits:{digits}"))
    return tuple(keys)


def _lengths_can_match(left: str, right: str) -> bool:
    """Whether two names are close enough in length to reach the threshold."""

    if not left or not right:
        return False
    longest = max(len(left), len(right))
    shortest = min(len(left), len(right))
    return Decimal(longest - shortest) <= _LENGTH_TOLERANCE * Decimal(longest)


@dataclass(frozen=True, slots=True)
class DuplicateScan:
    """The outcome of one duplicate scan."""

    findings: tuple[DuplicateFinding, ...]
    records: tuple[ItemRecord, ...]
    skipped_blocks: int
    compared_pairs: int


def detect_duplicates(
    records: Sequence[ItemRecord],
) -> tuple[tuple[DuplicateFinding, ...], list[ItemRecord]]:
    """Find duplicate groups and return the findings with updated records."""

    scan = scan_duplicates(records)
    return scan.findings, list(scan.records)


def scan_duplicates(records: Sequence[ItemRecord]) -> DuplicateScan:
    """Find duplicate groups and report what the scan could not resolve."""

    findings: list[DuplicateFinding] = []
    assigned: dict[int, tuple[str, DuplicateKind, int, str]] = {}
    group_counter = 0
    skipped_blocks = 0
    compared_pairs = 0

    def next_group() -> str:
        nonlocal group_counter
        group_counter += 1
        return f"DUP-{group_counter:03d}"

    # 1. Exact item code.
    by_code: dict[str, list[ItemRecord]] = {}
    for record in records:
        code = _code_key(record)
        if code:
            by_code.setdefault(code, []).append(record)
    for code, group in sorted(by_code.items()):
        if len(group) < 2:
            continue
        group_id = next_group()
        primary = min(group, key=lambda item: item.source_row)
        duplicates = tuple(
            item.source_row for item in sorted(group, key=lambda item: item.source_row)
            if item.source_row != primary.source_row
        )
        detail = f"duplicate_item_code:{code}"
        for record in group:
            assigned[record.source_row] = (group_id, DuplicateKind.EXACT_CODE, primary.source_row, detail)
        findings.append(
            DuplicateFinding(
                group_id=group_id,
                kind=DuplicateKind.EXACT_CODE,
                primary_row=primary.source_row,
                duplicate_rows=duplicates,
                similarity=Decimal("1"),
                detail=detail,
            )
        )

    # 2. Same name, specification and unit.
    by_signature: dict[tuple[str, str, str], list[ItemRecord]] = {}
    for record in records:
        name = _name_key(record)
        if not name:
            continue
        signature = (name, _spec_key(record), _unit_key(record))
        by_signature.setdefault(signature, []).append(record)
    for signature, group in sorted(by_signature.items()):
        if len(group) < 2:
            continue
        rows = {item.source_row for item in group}
        if all(row in assigned for row in rows):
            continue
        group_id = next_group()
        primary = min(group, key=lambda item: item.source_row)
        duplicates = tuple(
            item.source_row for item in sorted(group, key=lambda item: item.source_row)
            if item.source_row != primary.source_row
        )
        detail = f"duplicate_name_spec_unit:{signature[0]}"
        for record in group:
            if record.source_row in assigned:
                continue
            assigned[record.source_row] = (
                group_id,
                DuplicateKind.SAME_NAME_SPEC,
                primary.source_row,
                detail,
            )
        findings.append(
            DuplicateFinding(
                group_id=group_id,
                kind=DuplicateKind.SAME_NAME_SPEC,
                primary_row=primary.source_row,
                duplicate_rows=duplicates,
                similarity=Decimal("1"),
                detail=detail,
            )
        )

    # 3. Fuzzy name inside the blocked blocks.
    blocks: dict[tuple[str, str], list[ItemRecord]] = {}
    for record in records:
        for key in _blocking_keys(record):
            blocks.setdefault(key, []).append(record)

    compared: set[tuple[int, int]] = set()
    for block_key, group in sorted(blocks.items()):
        if len(group) < 2:
            continue
        if len(group) > MAX_BLOCK_SIZE:
            skipped_blocks += 1
            continue
        ordered = sorted(group, key=lambda item: item.source_row)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                pair = (left.source_row, right.source_row)
                if pair in compared:
                    continue
                compared.add(pair)
                if left.source_row in assigned or right.source_row in assigned:
                    continue
                left_name = _name_key(left)
                right_name = _name_key(right)
                if not _lengths_can_match(left_name, right_name):
                    continue
                compared_pairs += 1
                score = _similarity(left_name, right_name)
                if score < FUZZY_NAME_SIMILARITY_THRESHOLD:
                    continue
                group_id = next_group()
                primary, duplicate = (
                    (left, right) if left.source_row < right.source_row else (right, left)
                )
                detail = (
                    f"fuzzy_name_similarity:{score}"
                    f"({_name_key(primary)}~{_name_key(duplicate)})"
                )
                assigned[primary.source_row] = (
                    group_id,
                    DuplicateKind.FUZZY_NAME,
                    primary.source_row,
                    detail,
                )
                assigned[duplicate.source_row] = (
                    group_id,
                    DuplicateKind.FUZZY_NAME,
                    primary.source_row,
                    detail,
                )
                findings.append(
                    DuplicateFinding(
                        group_id=group_id,
                        kind=DuplicateKind.FUZZY_NAME,
                        primary_row=primary.source_row,
                        duplicate_rows=(duplicate.source_row,),
                        similarity=score,
                        detail=detail,
                    )
                )

    updated = tuple(_apply(records, assigned))
    return DuplicateScan(
        findings=tuple(findings),
        records=updated,
        skipped_blocks=skipped_blocks,
        compared_pairs=compared_pairs,
    )
