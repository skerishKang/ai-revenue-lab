#!/usr/bin/env python3
"""Object rollback evidence: every object a D1 row points at exists in the mirror.

The cutover (#5115 step ③) moves rows to COM2 and objects to the COM2 file lane.
A rollback keeps R2 as it was, so nothing in R2 has to be undone: the objects
COM2 created during the window are mirrored *into* R2 before the handback, and
objects COM2 deleted or replaced leave their pre-cutover R2 copy untouched.

That reasoning has one failure mode worth a check of its own: the D1 handback
restores rows that reference object keys, and a restored row whose object never
reached R2 is a broken attachment after the rollback. This tool answers exactly
that, read-only:

* scan a D1 copy (SQLite) for columns that hold object keys,
* collect every referenced key,
* compare it with the mirror inventory (``r2_sync.py`` manifest, a plain
  ``{"keys": [...]}`` list, or ``{"objects": [{"key": ...}]}``; several lists
  are unioned, because each storage bucket is inventoried on its own),
* tolerate a UTF-8 BOM, which the Windows-side dumps carry,
* report referenced / missing counts per table and exit 1 on any gap.

Key values are never printed and never written by default: the JSON artifact
carries counts and a digest of the missing set, so two runs are comparable
without publishing customer object paths. ``--include-keys`` is an explicit
operator opt-in for a local run.

Exit codes: 0 every referenced key is mirrored, 1 a gap, 2 usage/config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

EXIT_MATCH = 0
EXIT_GAP = 1
EXIT_USAGE = 2

#: Column names that carry an object key. Matched case-insensitively on the
#: final name segment so ``full_context_key`` and ``object_key`` both qualify,
#: while ``project_file_key`` (a D1 text row id) does not look like a path.
KEY_COLUMN_NAMES = frozenset({
    "object_key",
    "r2_key",
    "storage_key",
    "context_key",
    "full_context_key",
    "attachment_key",
    "blob_key",
})


class CheckError(ValueError):
    """A fixed, public-safe refusal."""


@dataclass(slots=True)
class TableReference:
    table: str
    column: str
    keys: int
    missing: int


@dataclass(slots=True)
class ReferenceReport:
    db_sha256: str
    #: Digest of one inventory file, or of the sorted per-file digests when the
    #: check was given several buckets. Independent of the argument order.
    inventory_sha256: str
    inventory_files: int = 1
    tables: list[TableReference] = field(default_factory=list)
    unique_keys: int = 0
    missing_keys: int = 0
    missing_digest: str = ""
    #: Populated for the report but stripped from the JSON unless the operator
    #: explicitly asks for it: object paths embed customer identifiers.
    missing_key_values: list[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return self.missing_keys == 0


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise CheckError("CHAT_OBJECT_DB_MISSING")
    return sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_columns(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    """``(table, column)`` pairs whose name marks an object key."""

    found: list[tuple[str, str]] = []
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    for table in tables:
        for row in connection.execute(f'PRAGMA table_info("{table}")'):
            name = str(row[1])
            if name.lower() in KEY_COLUMN_NAMES:
                found.append((table, name))
    return found


def _read_inventory_file(path: Path) -> set[str]:
    """Read one inventory file: a key list, ``{"keys": [...]}``, or objects.

    The file is decoded as ``utf-8-sig`` so a BOM (Windows PowerShell exports and
    several storage tools add one) no longer makes an otherwise valid list
    unreadable. Each file must contribute at least one key: a bucket that
    dumped empty is a broken inventory, not a bucket without objects.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise CheckError("CHAT_OBJECT_INVENTORY_UNREADABLE") from None

    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("keys"), list):
        values = payload["keys"]
    elif isinstance(payload, dict) and isinstance(payload.get("objects"), list):
        values = [
            item.get("key") if isinstance(item, dict) else item
            for item in payload["objects"]
        ]
    else:
        raise CheckError("CHAT_OBJECT_INVENTORY_SHAPE_UNKNOWN")

    keys = {str(value).strip() for value in values if isinstance(value, str) and value.strip()}
    if not keys:
        raise CheckError("CHAT_OBJECT_INVENTORY_EMPTY")
    return keys


def load_inventories(paths: Iterable[str | Path]) -> tuple[set[str], str, int]:
    """Union the key sets of every inventory file, with a file-set digest.

    The R2 mirror holds several buckets (media, workspace, b66) and each one is
    inventoried separately, so a referenced key only has to appear in one of
    them. Keys are never modified, renamed or guessed: this is a union, and a
    key present in none of the lists is still a gap.
    """

    files = [Path(path) for path in paths]
    if not files:
        raise CheckError("CHAT_OBJECT_INVENTORY_UNREADABLE")
    keys: set[str] = set()
    digests: list[str] = []
    for path in files:
        keys |= _read_inventory_file(path)
        digests.append(_sha256(path))
    if len(digests) == 1:
        digest = digests[0]
    else:
        # Sorted, so passing the same buckets in another order is the same run.
        digest = hashlib.sha256("\n".join(sorted(digests)).encode("utf-8")).hexdigest()
    return keys, digest, len(files)


def load_inventory(path: str | Path) -> set[str]:
    """Read a single mirror inventory (callers that pass one bucket)."""

    return load_inventories([path])[0]


def check(
    db_path: str | Path, inventory_path: str | Path | Iterable[str | Path]
) -> ReferenceReport:
    """Compare referenced keys with one or more mirror inventories. Never writes."""

    paths = (
        [inventory_path]
        if isinstance(inventory_path, (str, Path))
        else list(inventory_path)
    )
    inventory, inventory_digest, inventory_files = load_inventories(paths)
    report = ReferenceReport(
        db_sha256=_sha256(db_path),
        inventory_sha256=inventory_digest,
        inventory_files=inventory_files,
    )

    connection = _open_read_only(db_path)
    try:
        columns = key_columns(connection)
        if not columns:
            raise CheckError("CHAT_OBJECT_KEY_COLUMN_NOT_FOUND")
        referenced: set[str] = set()
        missing_values: set[str] = set()
        for table, column in columns:
            values = {
                str(row[0]).strip()
                for row in connection.execute(f'SELECT "{column}" FROM "{table}"')
                if row[0] is not None and str(row[0]).strip()
            }
            missing = values - inventory
            report.tables.append(
                TableReference(
                    table=table, column=column, keys=len(values), missing=len(missing)
                )
            )
            referenced |= values
            missing_values |= missing
            report.missing_keys += len(missing)
            if missing:
                report.missing_digest = hashlib.sha256(
                    "\n".join(sorted(missing)).encode("utf-8")
                ).hexdigest()
        report.unique_keys = len(referenced)
        report.missing_key_values = sorted(missing_values)
    finally:
        connection.close()

    return report


def _emit(report: ReferenceReport) -> None:
    state = "MATCH" if report.matches else "GAP"
    print(
        f"CHAT_OBJECT_REFERENCE={state} tables={len(report.tables)} "
        f"inventories={report.inventory_files} keys={report.unique_keys} "
        f"missing={report.missing_keys}"
    )
    for table in report.tables:
        print(
            f"CHAT_OBJECT_TABLE {table.table}.{table.column} "
            f"keys={table.keys} missing={table.missing}"
        )
    if report.missing_keys:
        # Which table and column the gap came from, counts only: the operator
        # knows what to re-upload while no object path reaches the log.
        sources = " ".join(
            f"{table.table}.{table.column}={table.missing}"
            for table in report.tables
            if table.missing
        )
        print(f"CHAT_OBJECT_MISSING_SOURCES {sources}")
        # The digest lets two runs be compared without publishing object paths.
        print(f"CHAT_OBJECT_MISSING_DIGEST={report.missing_digest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D1 object-reference vs mirror inventory")
    parser.add_argument("--db", required=True, help="SQLite copy of the Chat D1 database")
    parser.add_argument(
        "--inventory",
        "--mirror-inventory",
        action="append",
        dest="inventory",
        metavar="JSON",
        required=True,
        help="mirror inventory JSON, repeatable (one per bucket; keys are unioned)",
    )
    parser.add_argument("--json", help="write the report as JSON")
    parser.add_argument(
        "--include-keys",
        action="store_true",
        help="write the missing object keys into the JSON report (local use only)",
    )
    args = parser.parse_args(argv)

    try:
        report = check(args.db, args.inventory)
    except CheckError as exc:
        print(f"CHAT_OBJECT_REFERENCE_REFUSED reason={exc}")
        return EXIT_USAGE

    _emit(report)
    if args.json:
        payload = asdict(report)
        if not args.include_keys:
            payload.pop("missing_key_values", None)
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
    return EXIT_MATCH if report.matches else EXIT_GAP


if __name__ == "__main__":
    sys.exit(main())
