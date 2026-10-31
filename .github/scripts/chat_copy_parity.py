#!/usr/bin/env python3
"""Read-only parity check: a D1 export copy against the COM2 Chat database.

The current stage runs D1 -> COM2 daily sync (#5508) while both sides serve, and
the staging check and the final cutover both need the same sentence backed by
numbers: *the two sides hold the same rows*. This tool answers exactly that,
using the shared digest primitives of the handback gate (``chat_d1_digest``) so
a rollback plan and a parity verdict can never measure rows differently.

Both inputs open with ``mode=ro`` — SQLite refuses to write. Output names
tables, counts and per-table key counts only; row content is never printed.
Tables another authority owns are excluded and listed as excluded, so the
coverage of the verdict stays visible.

A table without a primary key cannot be compared row by row; it is reported as
not comparable instead of aborting the whole check.

Exit codes: 0 equal, 1 anything differs (rows, keys, tables), 2 usage/config.

Usage:
    python .github/scripts/chat_copy_parity.py \
        --d1 d1-export.sqlite3 --com2 handback.sqlite3 [--json parity.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat_d1_digest as digest  # noqa: E402

EXIT_MATCH = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2

#: Per-table lines printed when nothing matches; the full list still lands in
#: the JSON summary, which is what an artifact should carry.
MAX_PRINTED_TABLES = 40


@dataclass(slots=True)
class TableParity:
    table: str
    d1_rows: int
    com2_rows: int
    missing_on_com2: int = 0
    missing_on_d1: int = 0
    changed: int = 0

    @property
    def matches(self) -> bool:
        return (
            self.d1_rows == self.com2_rows
            and self.missing_on_com2 == 0
            and self.missing_on_d1 == 0
            and self.changed == 0
        )


@dataclass(slots=True)
class ParityReport:
    d1_sha256: str
    com2_sha256: str
    tables: list[TableParity] = field(default_factory=list)
    d1_only_tables: list[str] = field(default_factory=list)
    com2_only_tables: list[str] = field(default_factory=list)
    excluded_tables: list[str] = field(default_factory=list)
    not_comparable_tables: list[str] = field(default_factory=list)

    @property
    def mismatch_tables(self) -> list[TableParity]:
        return [table for table in self.tables if not table.matches]

    @property
    def rows(self) -> int:
        """Rows compared, counted on the COM2 side (the live side)."""

        return sum(table.com2_rows for table in self.tables)

    @property
    def mismatch_rows(self) -> int:
        return sum(
            table.missing_on_com2 + table.missing_on_d1 + table.changed
            for table in self.tables
        )

    @property
    def mismatch_table_count(self) -> int:
        return (
            len(self.mismatch_tables)
            + len(self.d1_only_tables)
            + len(self.com2_only_tables)
        )

    @property
    def matches(self) -> bool:
        return self.mismatch_table_count == 0 and self.mismatch_rows == 0

    def summary(self) -> str:
        return (
            f"{len(self.tables)}표 {self.rows:,}행 "
            f"불일치 {self.mismatch_rows + self.mismatch_table_count}"
        )


def _table_keys(path: str | Path, table_names: list[str]) -> dict[str, dict[str, str]]:
    """``{table: {key: digest}}`` for the tables that have a primary key."""

    connection = digest.read_only(path)
    try:
        out: dict[str, dict[str, str]] = {}
        for table in table_names:
            if not digest.key_columns(connection, table):
                continue
            table_columns, found = digest.rows(connection, table)
            out[table] = {
                key: digest.row_digest(table_columns, row) for key, row in found.items()
            }
        return out
    finally:
        connection.close()


def compare(d1_path: str | Path, com2_path: str | Path) -> ParityReport:
    """Compare every table both sides own, without writing to either file."""

    report = ParityReport(
        d1_sha256=digest.file_sha256(d1_path),
        com2_sha256=digest.file_sha256(com2_path),
    )

    sides: dict[str, list[str]] = {}
    for label, path in (("d1", d1_path), ("com2", com2_path)):
        connection = digest.read_only(path)
        try:
            sides[label] = digest.comparable_tables(connection)
            report.excluded_tables.extend(
                name for name in digest.tables(connection) if name in digest.SKIP_TABLES
            )
            report.not_comparable_tables.extend(
                name for name in sides[label]
                if not digest.key_columns(connection, name)
            )
        finally:
            connection.close()

    d1_tables, com2_tables = set(sides["d1"]), set(sides["com2"])
    report.d1_only_tables = sorted(d1_tables - com2_tables)
    report.com2_only_tables = sorted(com2_tables - d1_tables)
    report.excluded_tables = sorted(set(report.excluded_tables))
    report.not_comparable_tables = sorted(set(report.not_comparable_tables))

    shared = sorted(d1_tables & com2_tables)
    d1_rows = _table_keys(d1_path, shared)
    com2_rows = _table_keys(com2_path, shared)

    for table in shared:
        left = d1_rows.get(table)
        right = com2_rows.get(table)
        if left is None or right is None:
            # Reported above as not comparable; row data cannot be measured.
            continue
        entry = TableParity(
            table=table,
            d1_rows=len(left),
            com2_rows=len(right),
            missing_on_com2=len(set(left) - set(right)),
            missing_on_d1=len(set(right) - set(left)),
            changed=sum(
                1 for key in set(left) & set(right) if left[key] != right[key]
            ),
        )
        report.tables.append(entry)

    return report


def _emit(report: ParityReport) -> None:
    if report.matches:
        print(
            f"CHAT_COPY_PARITY=MATCH tables={len(report.tables)} rows={report.rows} "
            f"mismatch_rows=0 mismatch_tables=0"
        )
        print(f"CHAT_COPY_PARITY_SUMMARY={report.summary()}")
        return

    print(
        f"CHAT_COPY_PARITY=DRIFT tables={len(report.tables)} rows={report.rows} "
        f"mismatch_rows={report.mismatch_rows} "
        f"mismatch_tables={report.mismatch_table_count}"
    )
    print(f"CHAT_COPY_PARITY_SUMMARY={report.summary()}")
    for table in report.mismatch_tables[:MAX_PRINTED_TABLES]:
        print(
            f"CHAT_COPY_TABLE_DRIFT {table.table} d1_rows={table.d1_rows} "
            f"com2_rows={table.com2_rows} missing_on_com2={table.missing_on_com2} "
            f"missing_on_d1={table.missing_on_d1} changed={table.changed}"
        )
    for table in report.d1_only_tables:
        print(f"CHAT_COPY_TABLE_DRIFT {table} only_on_d1")
    for table in report.com2_only_tables:
        print(f"CHAT_COPY_TABLE_DRIFT {table} only_on_com2")
    if len(report.mismatch_tables) > MAX_PRINTED_TABLES:
        print(f"CHAT_COPY_TABLE_DRIFT_TRUNCATED printed={MAX_PRINTED_TABLES}")
    if report.not_comparable_tables:
        print(
            "CHAT_COPY_NOT_COMPARABLE=" + ",".join(report.not_comparable_tables)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D1 <-> COM2 Chat copy parity")
    parser.add_argument("--d1", required=True, help="SQLite copy built from a D1 export")
    parser.add_argument("--com2", required=True, help="COM2 Chat SQLite database copy")
    parser.add_argument("--json", help="write the full report as JSON")
    args = parser.parse_args(argv)

    try:
        report = compare(args.d1, args.com2)
    except digest.GateError as exc:
        print(f"CHAT_COPY_PARITY_REFUSED reason={exc}")
        return EXIT_USAGE

    _emit(report)
    if args.json:
        Path(args.json).write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
    return EXIT_MATCH if report.matches else EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main())
