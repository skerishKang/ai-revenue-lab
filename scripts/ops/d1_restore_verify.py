#!/usr/bin/env python3
"""Independent restore verification for a local Cloudflare D1 SQL export.

The check applies a ``wrangler d1 export`` SQL file into a fresh temporary
SQLite database and compares the result with the reference snapshot built from
the same export. It reads the source files only, writes inside a temporary
work directory, and never connects to Cloudflare or a production database.

Exit codes:
    0  restored database matches the reference (schema, row counts, integrity)
    1  mismatch detected
    2  an input file is missing, unreadable or internally invalid
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Sequence

WORK_PREFIX = "d1-restore-verify-"


class RestoreError(Exception):
    """Input cannot be verified. The message is a stable code."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _open_reference(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _schema_objects(connection: sqlite3.Connection) -> dict[tuple[str, str], dict[str, str]]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_autoindex_%' "
        "ORDER BY type, name"
    ).fetchall()
    return {
        (row["type"], row["name"]): {
            "table": row["tbl_name"],
            "sql": _normalize_sql(row["sql"]),
        }
        for row in rows
    }


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    return {
        name: connection.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0]
        for name in names
    }


def _restore(sql_path: Path, target: Path) -> None:
    script = sql_path.read_text(encoding="utf-8-sig")
    with closing(sqlite3.connect(target, timeout=30, isolation_level=None)) as connection:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.executescript(script)
        connection.commit()


def _compare(
    reference: sqlite3.Connection,
    restored: sqlite3.Connection,
) -> dict[str, Any]:
    reference_objects = _schema_objects(reference)
    restored_objects = _schema_objects(restored)
    missing = sorted(set(reference_objects) - set(restored_objects))
    extra = sorted(set(restored_objects) - set(reference_objects))
    changed = sorted(
        key
        for key in set(reference_objects) & set(restored_objects)
        if reference_objects[key] != restored_objects[key]
    )

    reference_rows = _row_counts(reference)
    restored_rows = _row_counts(restored)
    row_mismatches = [
        {
            "table": name,
            "reference": reference_rows.get(name),
            "restored": restored_rows.get(name),
        }
        for name in sorted(set(reference_rows) | set(restored_rows))
        if reference_rows.get(name) != restored_rows.get(name)
    ]

    integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = len(restored.execute("PRAGMA foreign_key_check").fetchall())

    return {
        "schema_parity": not (missing or extra or changed),
        "schema_missing_in_restore": [list(key) for key in missing],
        "schema_extra_in_restore": [list(key) for key in extra],
        "schema_changed": [list(key) for key in changed],
        "row_count_parity": not row_mismatches,
        "row_count_mismatches": row_mismatches,
        "row_counts": restored_rows,
        "tables": len(restored_rows),
        "total_rows": sum(restored_rows.values()),
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
    }


def verify(
    sql_path: Path,
    reference_path: Path,
    *,
    work_dir: Path | None = None,
    keep: bool = False,
) -> dict[str, Any]:
    sql_path = Path(sql_path)
    reference_path = Path(reference_path)
    if not sql_path.is_file():
        raise RestoreError("sql_file_missing")
    if not reference_path.is_file():
        raise RestoreError("reference_file_missing")
    if sql_path.resolve() == reference_path.resolve():
        raise RestoreError("source_paths_identical")

    source_hashes = {
        "sql_sha256": _sha256(sql_path),
        "reference_sha256": _sha256(reference_path),
    }

    parent = Path(work_dir) if work_dir is not None else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    target_dir = parent / (WORK_PREFIX + uuid.uuid4().hex)
    target_dir.mkdir()
    target = target_dir / "restored.sqlite3"

    try:
        with closing(_open_reference(reference_path)) as reference:
            reference_integrity = reference.execute("PRAGMA integrity_check").fetchone()[0]
            if reference_integrity != "ok":
                raise RestoreError("reference_integrity_failed")
            _restore(sql_path, target)
            with closing(_connect(target)) as restored:
                result = _compare(reference, restored)

        after_hashes = {
            "sql_sha256": _sha256(sql_path),
            "reference_sha256": _sha256(reference_path),
        }
        report = {
            "ok": (
                result["schema_parity"]
                and result["row_count_parity"]
                and result["integrity_check"] == "ok"
            ),
            "sql": str(sql_path),
            "reference": str(reference_path),
            "restored": str(target),
            "source_unchanged": source_hashes == after_hashes,
            "restored_sha256": _sha256(target),
            "restored_bytes": target.stat().st_size,
            **result,
        }
        report["ok"] = report["ok"] and report["source_unchanged"]
        return report
    finally:
        if not keep:
            for child in sorted(target_dir.glob("*"), reverse=True):
                child.unlink(missing_ok=True)
            target_dir.rmdir()


def _summary_line(report: dict[str, Any]) -> str:
    return (
        f"D1_RESTORE_{'OK' if report['ok'] else 'MISMATCH'} "
        f"tables={report['tables']} rows={report['total_rows']} "
        f"schema={'PARITY' if report['schema_parity'] else 'MISMATCH'} "
        f"row_counts={'PARITY' if report['row_count_parity'] else 'MISMATCH'} "
        f"integrity={report['integrity_check']} "
        f"fk_violations={report['foreign_key_violations']} "
        f"readonly={'PASS' if report['source_unchanged'] else 'FAIL'}"
    )


def _command_verify(args: argparse.Namespace) -> int:
    try:
        report = verify(
            Path(args.sql),
            Path(args.reference),
            work_dir=Path(args.work_dir) if args.work_dir else None,
            keep=args.keep,
        )
    except (RestoreError, OSError, sqlite3.Error) as error:
        code = str(error) if isinstance(error, RestoreError) else "restore_failed"
        print(f"D1_RESTORE_FAILED reason={code}", file=sys.stderr)
        return 2
    if args.json_out:
        destination = Path(args.json_out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(_summary_line(report))
    return 0 if report["ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sql", required=True, help="wrangler d1 export SQL file")
    parser.add_argument("--reference", required=True, help="reference SQLite snapshot")
    parser.add_argument("--work-dir", help="parent directory for the temporary restore target")
    parser.add_argument("--json-out", help="write the detailed report to this path")
    parser.add_argument("--keep", action="store_true", help="keep the restored database")
    parser.set_defaults(handler=_command_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
