#!/usr/bin/env python3
"""Build a staging Chat database from the published D1 -> COM2 sync generation.

The 04:20 sync (#5508) already publishes one immutable generation per day:
``snapshots/generations/<id>/chat.sqlite3`` selected by
``snapshots/current_generation.json``. The staging Chat on 8801 needs the same
shape of data as production to be worth starting, so this tool turns the
current generation into a *separate* staging database instead of letting the
staging service run migrations into an empty file.

Everything else is reuse, not a second authority:

* the generation layout and pointer file come from ``scripts/ops/refresh_d1.py``;
* the row digest comes from ``chat_d1_digest`` and the verdict is printed by
  ``chat_copy_parity`` itself, so "the staging copy matches the generation" is
  measured with the same code as the cutover parity check;
* tables another authority owns are emptied (never copied), exactly as the
  parity check excludes them: the staging queue on 8830 owns dispatch, pairing
  and presence, and the Stage 2-C broker owns ``local_agent_*``. A staging copy
  must not carry production pairing codes, presence rows or command material.

The source generation opens with ``mode=ro`` and its SHA-256 is compared before
and after the run: the published generation is never modified. Output is counts
and table names only — a Chat row holds a person's text and none of it is
printed.

Exit codes: 0 staging database ready, 1 a check failed, 2 usage or input.

Usage:
    python .github/scripts/chat_staging_db_from_generation.py \\
        --pointer D:/PADIEM-Servers/snapshots/current_generation.json \\
        --generations-dir D:/PADIEM-Servers/snapshots/generations \\
        --out /mnt/d/padiem/chat-staging/chat.sqlite3 \\
        [--force] [--apply-pending] [--json report.json]

``--apply-pending`` exists because Production D1 can be behind the repository when
staging is rebuilt: on 2026-10-31 the published generation carried 001–078 while
the repo already had 079. The order is fixed and the copy must match the
generation *before* it is advanced:

    copy → parity MATCH → apply only the contiguous pending tail → both ledgers → report

An unknown ledger name still refuses, and a hole in the pending set (079 applied
while 050 is missing) refuses instead of guessing: only the tail of the expected
order is ever applied. Without the flag the historical refusal is unchanged.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chat_copy_parity as parity  # noqa: E402
import chat_d1_digest as digest  # noqa: E402

EXIT_READY = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

POINTER_NAME = "current_generation.json"
GENERATIONS_DIRNAME = "generations"
DEFAULT_LABEL = "chat"
#: ``apps/padiem-chat/migrations`` — the 001…079 set the local host applies.
DEFAULT_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "apps" / "padiem-chat" / "migrations"
)
#: Wrangler's bookkeeping table carried inside a D1 export.
D1_LEDGER_TABLE = "d1_migrations"
#: The CPython host's own ledger (``apps/padiem-chat/app/local_cpython.py``).
LOCAL_LEDGER_TABLE = "padiem_local_migration_ledger"

#: Refusals that mean "the caller pointed at the wrong thing", not "data drifted".
USAGE_REASONS = frozenset({
    "staging_pointer_missing",
    "staging_pointer_invalid",
    "staging_generation_missing",
    "staging_source_missing",
    "staging_label_missing",
    "staging_out_exists",
    "staging_out_is_source",
    "staging_out_inside_generations",
    "staging_migrations_dir_missing",
})


class StagingError(Exception):
    """A fixed, public-safe refusal. Never carries row data or SQL bodies."""


@dataclass(slots=True)
class StagingReport:
    generation: str = ""
    source: str = ""
    out: str = ""
    source_sha256: str = ""
    source_unchanged: bool = False
    migrations_expected: int = 0
    ledger_applied: int = 0
    ledger_missing: list[str] = field(default_factory=list)
    ledger_unknown: list[str] = field(default_factory=list)
    pending_requested: bool = False
    pending_applied: list[str] = field(default_factory=list)
    emptied_tables: dict[str, int] = field(default_factory=dict)
    local_ledger_rows: int = 0
    staging_tables: int = 0
    staging_rows: int = 0
    staging_bytes: int = 0
    parity_exit: int | None = None
    ready: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _safe_generation(value: object) -> str:
    """A generation id is one path component: no separators, no traversal."""

    text = str(value or "").strip()
    if (
        not text
        or text in {".", ".."}
        or "/" in text
        or "\\" in text
        or ":" in text
        or len(text) > 64
    ):
        raise StagingError("staging_pointer_invalid")
    return text


def resolve_generation(
    pointer: str | Path,
    generations_dir: str | Path,
    label: str = DEFAULT_LABEL,
) -> tuple[str, Path]:
    """Return ``(generation, source sqlite path)`` for the current generation."""

    pointer_path = Path(pointer)
    if not pointer_path.is_file():
        raise StagingError("staging_pointer_missing")
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise StagingError("staging_pointer_invalid") from None
    if not isinstance(payload, dict):
        raise StagingError("staging_pointer_invalid")

    generation = _safe_generation(payload.get("generation"))
    databases = payload.get("databases")
    if databases is not None and not isinstance(databases, dict):
        raise StagingError("staging_pointer_invalid")
    if isinstance(databases, dict) and databases and label not in databases:
        raise StagingError("staging_label_missing")

    folder = Path(generations_dir) / generation
    if not folder.is_dir():
        raise StagingError("staging_generation_missing")
    source = folder / (label + ".sqlite3")
    if not source.is_file():
        raise StagingError("staging_source_missing")
    return generation, source


def migration_names(migrations_dir: str | Path) -> list[str]:
    """The migration set, in the filename order the app applies them."""

    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise StagingError("staging_migrations_dir_missing")
    return sorted(path.name for path in directory.glob("*.sql"))


def ledger_names(connection: sqlite3.Connection) -> list[str]:
    """Names wrangler recorded as applied inside the export."""

    if D1_LEDGER_TABLE not in digest.tables(connection):
        raise StagingError("staging_ledger_table_missing")
    return sorted(
        {
            str(row[0])
            for row in connection.execute(f'SELECT name FROM "{D1_LEDGER_TABLE}"')
        }
    )


def ledger_state(
    connection: sqlite3.Connection, expected: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """``(missing, unknown, applied names)`` against the export's own ledger."""

    applied = ledger_names(connection)
    expected_set = set(expected)
    missing = [name for name in expected if name not in set(applied)]
    unknown = [name for name in applied if name not in expected_set]
    return missing, unknown, applied


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def empty_owned_tables(connection: sqlite3.Connection) -> dict[str, int]:
    """Clear tables another authority owns; return ``{table: rows removed}``."""

    existing = set(digest.tables(connection))
    removed: dict[str, int] = {}
    for table in sorted(digest.OWNED_BY_QUEUE | digest.OWNED_BY_BROKER):
        if table not in existing:
            continue
        rows = _count(connection, table)
        connection.execute(f'DELETE FROM "{table}"')
        removed[table] = rows
    return removed


def seed_local_ledger(
    connection: sqlite3.Connection, applied: list[str]
) -> int:
    """Mark exactly the export's applied migrations in the host's own ledger.

    The staging database is a *populated* copy, so the CPython host must not
    replay 001…079 over it. Only names the export itself applied are recorded,
    so a pending tail stays pending until it is really applied, while leaving
    wrangler's ``d1_migrations`` untouched for audit.
    """

    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {LOCAL_LEDGER_TABLE} ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied_at: dict[str, str] = {}
    for row in connection.execute(f'SELECT name, applied_at FROM "{D1_LEDGER_TABLE}"'):
        applied_at[str(row[0])] = str(row[1]) if row[1] else _utc_now()
    rows = [(name, applied_at.get(name, _utc_now())) for name in applied]
    connection.executemany(
        f"INSERT OR REPLACE INTO {LOCAL_LEDGER_TABLE} (name, applied_at) VALUES (?, ?)",
        rows,
    )
    return int(
        connection.execute(f"SELECT COUNT(*) FROM {LOCAL_LEDGER_TABLE}").fetchone()[0]
    )


def pending_tail(expected: list[str], missing: list[str]) -> list[str]:
    """The pending set, only when it is the contiguous tail of ``expected``.

    A hole means the copy is not simply behind: something applied later without
    an earlier migration, and replaying over that is a guess. Refuse instead.
    """

    if not missing:
        return []
    tail = expected[len(expected) - len(missing):]
    if list(missing) != list(tail):
        raise StagingError("staging_ledger_gap")
    return list(tail)


def _discard(path: Path) -> None:
    """Remove a staging database and its sidecars after a failed advance."""

    path.unlink(missing_ok=True)
    for stale in (
        path.with_name(path.name + "-journal"),
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    ):
        stale.unlink(missing_ok=True)


def apply_pending_migrations(
    destination: Path,
    migrations_dir: str | Path,
    names: list[str],
) -> list[str]:
    """Apply ``names`` in order to the copy and record each in both ledgers."""

    connection = sqlite3.connect(
        f"file:{destination.resolve().as_posix()}?mode=rwc",
        uri=True,
        isolation_level=None,
    )
    applied: list[str] = []
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        for name in names:
            try:
                sql = (Path(migrations_dir) / name).read_text(encoding="utf-8")
                connection.executescript(sql)
            except sqlite3.Error:
                raise StagingError("staging_pending_migration_failed") from None
            applied_at = _utc_now()
            connection.execute(
                f'INSERT INTO "{D1_LEDGER_TABLE}" (name, applied_at) VALUES (?, ?)',
                (name, applied_at),
            )
            connection.execute(
                f"INSERT OR REPLACE INTO {LOCAL_LEDGER_TABLE} "
                "(name, applied_at) VALUES (?, ?)",
                (name, applied_at),
            )
            applied.append(name)
        return applied
    finally:
        connection.close()


def _check_out_path(out: Path, source: Path, generations_dir: Path, force: bool) -> None:
    if out.resolve() == source.resolve():
        raise StagingError("staging_out_is_source")
    try:
        out.resolve().relative_to(generations_dir.resolve())
    except ValueError:
        pass
    else:
        raise StagingError("staging_out_inside_generations")
    if out.exists() and not force:
        raise StagingError("staging_out_exists")


def build_staging_db(
    pointer: str | Path,
    generations_dir: str | Path,
    out: str | Path,
    *,
    label: str = DEFAULT_LABEL,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    force: bool = False,
    apply_pending: bool = False,
) -> StagingReport:
    """Copy the current generation into ``out`` and verify it; never touch D1.

    ``apply_pending`` advances the copy past the generation, so parity is
    measured on the untouched copy first and the pending tail is applied only
    to a copy that already matched.
    """

    report = StagingReport()
    generation, source = resolve_generation(pointer, generations_dir, label)
    expected = migration_names(migrations_dir)
    if not expected:
        raise StagingError("staging_migrations_dir_missing")

    destination = Path(out)
    _check_out_path(destination, source, Path(generations_dir), force)

    report.generation = generation
    report.source = str(source)
    report.out = str(destination)
    report.migrations_expected = len(expected)
    report.pending_requested = apply_pending

    sha_before = digest.file_sha256(source)
    report.source_sha256 = sha_before

    handle = digest.read_only(source)
    try:
        integrity = handle.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise StagingError("staging_source_integrity_failed")

        missing, unknown, applied = ledger_state(handle, expected)
        report.ledger_missing = missing
        report.ledger_unknown = unknown
        report.ledger_applied = len(applied)
        if unknown:
            raise StagingError("staging_ledger_unknown")
        if missing and not apply_pending:
            raise StagingError("staging_ledger_incomplete")
        pending = pending_tail(expected, missing)

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # --force: a replaced file must not be reused in place, or an old
            # header would make SQLite read the previous staging content.
            destination.unlink()
        for stale in (destination.with_name(destination.name + "-journal"),
                      destination.with_name(destination.name + "-wal"),
                      destination.with_name(destination.name + "-shm")):
            stale.unlink(missing_ok=True)

        target = sqlite3.connect(
            f"file:{destination.resolve().as_posix()}?mode=rwc",
            uri=True,
            isolation_level=None,
        )
        try:
            # One file out: no WAL sidecar to forget when the staging root is copied.
            target.execute("PRAGMA journal_mode=DELETE")
            handle.backup(target)
            report.emptied_tables = empty_owned_tables(target)
            report.local_ledger_rows = seed_local_ledger(target, applied)
            target_integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
            if target_integrity != "ok":
                raise StagingError("staging_target_integrity_failed")
        finally:
            target.close()
    finally:
        handle.close()

    report.source_unchanged = digest.file_sha256(source) == sha_before
    if not report.source_unchanged:
        raise StagingError("staging_source_modified")

    # The verdict is printed by the parity tool itself: one measurement, one format.
    # It runs on the untouched copy, because after a pending migration the copy is
    # intentionally ahead of the generation and the two are no longer comparable.
    report.parity_exit = parity.main(
        ["--d1", str(source), "--com2", str(destination)]
    )
    report.ready = report.parity_exit == parity.EXIT_MATCH

    if report.ready and pending:
        try:
            report.pending_applied = apply_pending_migrations(
                destination, migrations_dir, pending
            )
        except StagingError:
            # A half-applied staging database is worse than none.
            _discard(destination)
            raise
        report.local_ledger_rows += len(report.pending_applied)
        report.source_unchanged = digest.file_sha256(source) == sha_before
        if not report.source_unchanged:
            raise StagingError("staging_source_modified")

    report.staging_tables = 0
    report.staging_rows = 0
    verify = digest.read_only(destination)
    try:
        report.staging_tables = len(digest.tables(verify))
        report.staging_rows = sum(
            _count(verify, table) for table in digest.comparable_tables(verify)
        )
    finally:
        verify.close()
    report.staging_bytes = destination.stat().st_size
    return report


def _emit(report: StagingReport) -> None:
    print(
        f"STAGING_DB_GENERATION generation={report.generation} "
        f"source_sha256={report.source_sha256[:16]}"
    )
    print(
        f"STAGING_DB_LEDGER applied={report.ledger_applied}/"
        f"{report.migrations_expected} missing={len(report.ledger_missing)} "
        f"unknown={len(report.ledger_unknown)} "
        f"local_ledger_rows={report.local_ledger_rows}"
    )
    emptied = ",".join(
        f"{table}:{rows}" for table, rows in sorted(report.emptied_tables.items())
    ) or "none"
    print(f"STAGING_DB_EMPTIED tables={len(report.emptied_tables)} rows={emptied}")
    print(
        f"STAGING_DB_SOURCE_UNCHANGED={'YES' if report.source_unchanged else 'NO'}"
    )
    pending_names = ",".join(report.pending_applied) or "none"
    print(
        f"STAGING_DB_PENDING_APPLIED count={len(report.pending_applied)} "
        f"requested={'YES' if report.pending_requested else 'NO'} "
        f"names={pending_names}"
    )
    verdict = "READY" if report.ready else "FAILED"
    print(
        f"STAGING_DB_FROM_GENERATION={verdict} tables={report.staging_tables} "
        f"rows={report.staging_rows} bytes={report.staging_bytes} out={report.out}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a staging Chat database from the published sync generation"
    )
    parser.add_argument("--pointer", required=True, help="snapshots/current_generation.json")
    parser.add_argument(
        "--generations-dir", required=True,
        help="snapshots/generations (holds <generation>/<label>.sqlite3)",
    )
    parser.add_argument("--out", required=True, help="staging chat.sqlite3 to create")
    parser.add_argument(
        "--label", default=DEFAULT_LABEL,
        help=f"pointer database label and file stem (default: {DEFAULT_LABEL})",
    )
    parser.add_argument(
        "--migrations-dir", default=str(DEFAULT_MIGRATIONS_DIR),
        help="apps/padiem-chat/migrations for the 001…079 ledger check",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="replace an existing staging database instead of refusing",
    )
    parser.add_argument(
        "--apply-pending", action="store_true",
        help="apply the repository migrations the generation is still missing",
    )
    parser.add_argument("--json", help="write the counts-only report as JSON")
    args = parser.parse_args(argv)

    try:
        report = build_staging_db(
            args.pointer,
            args.generations_dir,
            args.out,
            label=args.label,
            migrations_dir=args.migrations_dir,
            force=args.force,
            apply_pending=args.apply_pending,
        )
    except StagingError as exc:
        print(f"STAGING_DB_REFUSED reason={exc}")
        return EXIT_USAGE if str(exc) in USAGE_REASONS else EXIT_FAILED
    except (OSError, sqlite3.Error, digest.GateError):
        print("STAGING_DB_FAILED reason=staging_io_error")
        return EXIT_FAILED

    _emit(report)
    if args.json:
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
    return EXIT_READY if report.ready else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
