#!/usr/bin/env python3
"""B62 D1 migration 066 gate: PDF to Markdown conversion work ledger (#5568).

066 (``apps/padiem-chat/migrations/066_document_convert_jobs.sql``) adds TWO
additive tables, ``document_convert_jobs`` and ``document_convert_items``, that
store the job mode, per-item bounds, status and the bounded verification report
of a conversion request. No customer document content lives in D1: the original
PDF bytes and the converted Markdown stay in the signed-in owner's own R2
workspace objects, and this ledger holds only object keys and aggregates.

This helper holds the 066 source contract. Its per-migration gate
``.github/workflows/b62-d1-migration-066-gate.yml`` was retired by #5895 ②, so
the helper is kept as the reviewed record of 066 and is no longer dispatched:

* it pins the approved 066 source by SHA-256, so the applied SQL is exactly the
  reviewed file;
* it refuses anything that is not purely additive: the reviewed two tables and
  the reviewed three indexes, created with ``IF NOT EXISTS`` and nothing else —
  no delete, update, insert, drop, alter, trigger, view, pragma or
  ``WITHOUT ROWID`` statement may appear;
* it proves on a real SQLite database that the SQL produces the reviewed column
  set, types and CHECK constraints, that both tables are scoped by
  ``user_id REFERENCES users(id) ON DELETE CASCADE`` (an orphan row is refused
  and removing the owner removes their ledger rows), that the ``done`` item
  requires a Markdown object key and that the verification report cannot exceed
  its 12000-character ceiling, and that re-applying the file is a no-op;
* it reads schema metadata only (``sqlite_master``, ``PRAGMA table_info``,
  ``PRAGMA index_list``); it never reads row content, an object key, a document
  or a secret value, and it never emits an account, database or binding
  identifier.

Dispositions:
  ``MISSING``  neither table is present; 066 is applicable.
  ``EXACT``    the reviewed 066 shape is present (idempotent no-op).
  ``DRIFT``    the ledger exists with another shape, or only one of the two
               tables is present (a partially applied migration); never mutated.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
MIGRATION = MIGRATIONS / "066_document_convert_jobs.sql"
JOBS_TABLE = "document_convert_jobs"
ITEMS_TABLE = "document_convert_items"
TABLES = (JOBS_TABLE, ITEMS_TABLE)
JOBS_INDEX = "idx_document_convert_jobs_recent"
ITEMS_JOB_INDEX = "idx_document_convert_items_job"
ITEMS_RECENT_INDEX = "idx_document_convert_items_recent"
INDEXES = (JOBS_INDEX, ITEMS_JOB_INDEX, ITEMS_RECENT_INDEX)

# The applied SQL must be exactly the reviewed file.
PINNED_SHA256 = "b6b20d87de2c71ce4bb28adf85d5af916dabfcda29fb4c4ed1e0206d5b564884"

# (name, declared type, notnull, pk) in the reviewed order.
EXPECTED_COLUMNS = {
    JOBS_TABLE: (
        ("id", "TEXT", 1, 1),
        ("user_id", "TEXT", 1, 0),
        ("mode", "TEXT", 1, 0),
        ("status", "TEXT", 1, 0),
        ("item_count", "INTEGER", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
    ITEMS_TABLE: (
        ("id", "TEXT", 1, 1),
        ("job_id", "TEXT", 1, 0),
        ("user_id", "TEXT", 1, 0),
        ("name", "TEXT", 1, 0),
        ("status", "TEXT", 1, 0),
        ("page_count", "INTEGER", 1, 0),
        ("character_count", "INTEGER", 1, 0),
        ("original_key", "TEXT", 1, 0),
        ("markdown_key", "TEXT", 0, 0),
        ("report_json", "TEXT", 0, 0),
        ("error_code", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
}

# table -> name -> (unique, partial) for the reviewed 066 indexes. Every 066
# index is a non-unique, non-partial ``CREATE INDEX``; a primary-key autoindex
# is not a reviewed index and is filtered out by its ``origin``.
EXPECTED_INDEXES = {
    JOBS_TABLE: {JOBS_INDEX: (0, 0)},
    ITEMS_TABLE: {ITEMS_JOB_INDEX: (0, 0), ITEMS_RECENT_INDEX: (0, 0)},
}

# Normalized clauses every reviewed table DDL must carry. The owner scoping and
# the two load-bearing item bounds are here rather than only in the behavioural
# proof, so a shape that happens to survive a PRAGMA comparison is still pinned.
REQUIRED_DDL_CLAUSES = {
    JOBS_TABLE: (
        "user_id text not null references users(id) on delete cascade",
        "check (mode in ('fast','verify'))",
        "check (status in ('queued','working','reviewed','done','failed'))",
        "check (item_count >= 0)",
    ),
    ITEMS_TABLE: (
        "job_id text not null references document_convert_jobs(id) on delete cascade",
        "user_id text not null references users(id) on delete cascade",
        "check (length(name) between 1 and 120)",
        "check (status in ('queued','working','reviewed','done','failed'))",
        "check (page_count >= 0)",
        "check (character_count >= 0)",
        "check (status <> 'done' or markdown_key is not null)",
        "check (report_json is null or length(report_json) <= 12000)",
    ),
}

# 066 is additive only. ``delete from``/``update ``/``insert into`` are stated as
# statements so the reviewed ``ON DELETE CASCADE`` clause and the ``updated_at``
# columns are not mistaken for a data mutation.
FORBIDDEN_STATEMENTS = (
    "delete from",
    "update ",
    "insert into",
    "insert or",
    "replace into",
    "drop ",
    "alter ",
    "trigger",
    "create view",
    "pragma",
    "without rowid",
    "vacuum",
    "attach",
    "detach",
)

REPORT_CEILING = 12000

QUERY = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='table' AND name IN ('document_convert_jobs','document_convert_items');\n"
    "PRAGMA table_info(document_convert_jobs);\n"
    "PRAGMA index_list(document_convert_jobs);\n"
    "PRAGMA table_info(document_convert_items);\n"
    "PRAGMA index_list(document_convert_items);"
)


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def code(value: str) -> str:
    """The executable statements, with the explanatory comments removed."""
    return norm("\n".join(line.split("--", 1)[0] for line in value.splitlines()))


def _shape(connection: sqlite3.Connection, table: str) -> tuple:
    return tuple(
        (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _indexes(connection: sqlite3.Connection, table: str) -> dict:
    """Named, non-automatic indexes as name -> (unique, partial)."""
    found = {}
    for row in connection.execute(f"PRAGMA index_list({table})").fetchall():
        # seq, name, unique, origin, partial
        if str(row[3]).lower() != "c":
            continue
        found[str(row[1])] = (int(row[2]), int(row[4]))
    return found


def _ddl(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row and isinstance(row[0], str) else ""


def _statement(upper: str, table: str) -> str:
    """The one reviewed CREATE TABLE statement for ``table``.

    Scoped per statement so a clause satisfied by the *other* ledger table
    cannot mask the clause this table lost.
    """
    prefixes = (
        f"create table if not exists {table} ",
        f"create table if not exists {table}(",
    )
    owned = [
        part.strip()
        for part in upper.split(";")
        if part.strip().startswith(prefixes)
    ]
    if len(owned) != 1:
        raise ValueError(f"Migration 066 must state {table} exactly once")
    return owned[0]


def _seed_job(connection: sqlite3.Connection, *, ident: str, user: str, mode: str) -> None:
    connection.execute(
        f"INSERT INTO {JOBS_TABLE} "
        "(id, user_id, mode, status, item_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ident, user, mode, "queued", 0, "2026-10-23T00:00:00Z", "2026-10-23T00:00:00Z"),
    )


def _seed_item(
    connection: sqlite3.Connection, *, ident: str, job: str, user: str, status: str,
    markdown: str | None, report: str | None
) -> None:
    connection.execute(
        f"INSERT INTO {ITEMS_TABLE} "
        "(id, job_id, user_id, name, status, page_count, character_count, original_key, "
        "markdown_key, report_json, error_code, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
        (
            ident,
            job,
            user,
            "invoice.pdf",
            status,
            1,
            0,
            "workspace/original.pdf",
            markdown,
            report,
            "2026-10-23T00:00:00Z",
            "2026-10-23T00:00:00Z",
        ),
    )


def _ledger_count(connection: sqlite3.Connection) -> int:
    return (
        connection.execute(f"SELECT COUNT(*) FROM {JOBS_TABLE}").fetchone()[0]
        + connection.execute(f"SELECT COUNT(*) FROM {ITEMS_TABLE}").fetchone()[0]
    )


def source(path: Path | None = None) -> str:
    """Return the reviewed 066 SQL, or refuse anything that is not it."""
    target = MIGRATION if path is None else Path(path)
    text = target.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if path is None:
        if not PINNED_SHA256 or digest != PINNED_SHA256:
            raise ValueError("Migration 066 is not the pinned reviewed file")
    upper = code(text)

    # 066 is additive: two new ledger tables and three new indexes. It must
    # never touch an existing authority, rewrite data or drop anything.
    for forbidden in FORBIDDEN_STATEMENTS:
        if forbidden in upper:
            raise ValueError("Migration 066 exceeds the reviewed additive change: " + forbidden)
    for table in TABLES:
        if upper.count(f"create table if not exists {table}") != 1:
            raise ValueError("Migration 066 must create the reviewed table exactly once: " + table)
    if upper.count("create table") != len(TABLES):
        raise ValueError("Migration 066 creates a table outside the reviewed set")
    for index in INDEXES:
        if upper.count(f"create index if not exists {index}") != 1:
            raise ValueError("Migration 066 must create the reviewed index exactly once: " + index)
    if upper.count("create index") != len(INDEXES):
        raise ValueError("Migration 066 creates an index outside the reviewed set")

    # The reviewed clauses must be in the written SQL itself, stated on their
    # own table, not only implied by a later PRAGMA comparison.
    for table in TABLES:
        stated = _statement(upper, table)
        for clause in REQUIRED_DDL_CLAUSES[table]:
            if clause not in stated:
                raise ValueError(f"Migration 066 {table} loses a reviewed clause: " + clause)

    # Prove the SQL produces the reviewed shape on a real database.
    db = sqlite3.connect(":memory:")
    try:
        # The canonical account authority, so the reviewed foreign keys can be
        # exercised. It is a gate-local stub: nothing here reaches the live D1.
        db.executescript("CREATE TABLE users (id TEXT NOT NULL PRIMARY KEY);")
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(text)

        for table in TABLES:
            if _shape(db, table) != EXPECTED_COLUMNS[table]:
                raise ValueError(f"Migration 066 {table} columns do not match the reviewed shape")
            if _indexes(db, table) != EXPECTED_INDEXES[table]:
                raise ValueError(f"Migration 066 {table} indexes are not the reviewed set")
            live_ddl = code(_ddl(db, table))
            for clause in REQUIRED_DDL_CLAUSES[table]:
                if clause not in live_ddl:
                    raise ValueError(f"Migration 066 {table} DDL loses a reviewed clause: " + clause)

        db.executescript("INSERT INTO users (id) VALUES ('usr_gate'), ('usr_other');")

        # Every read/write path is scoped by the owning account: a ledger row
        # for an account that does not exist is refused outright.
        _seed_job(db, ident="job_a", user="usr_gate", mode="verify")
        try:
            _seed_job(db, ident="job_ghost", user="usr_ghost", mode="fast")
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 066 lets a ledger row escape its owner")

        # An id identifies one ledger row; the primary key is the only identity.
        try:
            _seed_job(db, ident="job_a", user="usr_gate", mode="fast")
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 066 accepts a duplicate ledger id")

        # Only the reviewed job modes are admitted.
        try:
            _seed_job(db, ident="job_mode", user="usr_gate", mode="turbo")
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 066 does not bound the reviewed job modes")

        # An item may be in flight without a Markdown object, and must not be
        # reported as done without one.
        _seed_item(
            db, ident="item_a", job="job_a", user="usr_gate", status="working",
            markdown=None, report=None
        )
        try:
            db.execute(f"UPDATE {ITEMS_TABLE} SET status = 'done' WHERE id = 'item_a'")
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 066 marks an item done with no Markdown object")
        db.execute(
            f"UPDATE {ITEMS_TABLE} SET status = 'done', markdown_key = 'workspace/out.md' "
            "WHERE id = 'item_a'"
        )

        # The bounded verification report is the only JSON this ledger holds and
        # it cannot exceed the reviewed ceiling.
        db.execute(
            f"UPDATE {ITEMS_TABLE} SET report_json = ? WHERE id = 'item_a'",
            ("[" + "x" * (REPORT_CEILING - 2) + "]",),
        )
        try:
            db.execute(
                f"UPDATE {ITEMS_TABLE} SET report_json = ? WHERE id = 'item_a'",
                ("[" + "x" * REPORT_CEILING + "]",),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 066 lets the verification report exceed its ceiling")

        # An item is scoped both to its job and to the owning account.
        try:
            _seed_item(
                db, ident="item_b", job="job_missing", user="usr_gate", status="queued",
                markdown=None, report=None
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 066 accepts an item without its job")

        # Re-applying the reviewed file is an idempotent no-op.
        before = _ledger_count(db)
        db.executescript(text)
        if _ledger_count(db) != before:
            raise ValueError("Migration 066 is not idempotent")

        # Deleting the owner removes their whole ledger through the reviewed
        # cascade, and leaves the other account untouched.
        _seed_job(db, ident="job_b", user="usr_other", mode="fast")
        db.execute("DELETE FROM users WHERE id = 'usr_gate'")
        if db.execute(
            f"SELECT COUNT(*) FROM {JOBS_TABLE} WHERE user_id = 'usr_gate'"
        ).fetchone()[0] or db.execute(
            f"SELECT COUNT(*) FROM {ITEMS_TABLE} WHERE user_id = 'usr_gate'"
        ).fetchone()[0]:
            raise ValueError("Migration 066 owner scoping is not the reviewed one")
        if db.execute(
            f"SELECT COUNT(*) FROM {JOBS_TABLE} WHERE user_id = 'usr_other'"
        ).fetchone()[0] != 1:
            raise ValueError("Migration 066 cascade deletes another owner's ledger")
    finally:
        db.close()

    return text


def _blocks(payload: object, count: int) -> list[list[dict[str, object]]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("D1 schema API error")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != count:
        raise ValueError("D1 schema response incomplete")
    blocks: list[list[dict[str, object]]] = []
    for record in results:
        if not isinstance(record, dict) or record.get("success") is not True:
            raise ValueError("D1 statement failed")
        rows = record.get("results")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("D1 rows malformed")
        blocks.append(rows)
    return blocks


def _shape_from(rows: list[dict[str, object]]) -> tuple:
    return tuple(
        (
            row.get("name"),
            str(row.get("type", "")).upper(),
            int(row.get("notnull", -1)),
            int(row.get("pk", -1)),
        )
        for row in rows
    )


def _indexes_from(rows: list[dict[str, object]]) -> dict:
    found = {}
    for row in rows:
        if str(row.get("origin", "")).lower() != "c":
            continue
        found[str(row.get("name"))] = (
            int(row.get("unique", -1)),
            int(row.get("partial", -1)),
        )
    return found


def classify(payload: object) -> str:
    blocks = _blocks(payload, 1 + 2 * len(TABLES))
    objects = blocks[0]
    live = {
        table: (blocks[1 + 2 * slot], blocks[2 + 2 * slot])
        for slot, table in enumerate(TABLES)
    }
    matched = [row for row in objects if row.get("name") in TABLES]

    if not matched:
        # A truly absent migration has no metadata either; anything else means
        # the ledger was created by something this gate does not own.
        empty = all(not shape and not indexes for shape, indexes in live.values())
        return "missing" if empty else "drift"

    if len(matched) != len(TABLES):
        # Only one of the two reviewed tables reached the database.
        return "drift"

    present = {str(row.get("name")): row for row in matched}
    if set(present) != set(TABLES):
        return "drift"

    for table in TABLES:
        if not isinstance(present[table].get("sql"), str):
            return "drift"
        shape_rows, index_rows = live[table]
        if _shape_from(shape_rows) != EXPECTED_COLUMNS[table]:
            return "drift"
        if _indexes_from(index_rows) != EXPECTED_INDEXES[table]:
            return "drift"

    return "exact"


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise ValueError("expected an operation")
    action = argv[0]
    if action == "offline":
        source()
        print("B62_D1_MIGRATION_066_SOURCE_CONTRACT=PASS")
        print("PRODUCTION_MUTATION=0")
        return
    if len(argv) < 2:
        raise ValueError("expected an operation and a file")
    path = Path(argv[1])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        verdict = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_MIGRATION_066_SCHEMA=" + verdict.upper())
    elif action == "apply":
        source()
        path.write_text(
            json.dumps({"sql": MIGRATION.read_text(encoding="utf-8")}), encoding="utf-8"
        )
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = (
            payload.get("result")
            if isinstance(payload, dict) and payload.get("success") is True
            else None
        )
        if (
            not isinstance(rows, list)
            or not rows
            or any(
                not isinstance(item, dict) or item.get("success") is not True
                for item in rows
            )
        ):
            raise ValueError("D1 migration 066 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_066_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 066 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_066_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
