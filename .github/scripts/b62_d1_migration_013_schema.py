#!/usr/bin/env python3
"""Schema-only gate for #5023 migration 013 (native Padiem Calendar tables).

013 creates exactly two additive tables under the canonical ``PADIEM_CHAT_DB``:

    padiem_calendar_work_log(id, workspace_id, owner_id, date, title, content,
      created_at, updated_at)
    padiem_calendar_appointment(id, workspace_id, owner_id, appointment_type,
      title, description, date, start_at, end_at, timezone, reminder_minutes,
      created_at, updated_at)

plus their reviewed indexes. The merged B62 Calendar routes read and write these
tables, so the release path must prove they exist before the Calendar can answer
a read.

This helper reads schema metadata only (``sqlite_master`` +
``PRAGMA table_info``). It never reads row contents, account data or secret
values, and it never emits an account, database or binding identifier.

Dispositions:
  ``MISSING`` the calendar tables are absent; 013 is applicable.
  ``EXACT``   the reviewed shape is present (idempotent apply).
  ``DRIFT``   a calendar table exists with another shape; never mutated.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/013_padiem_calendar.sql"

WORK_LOG_TABLE = "padiem_calendar_work_log"
APPOINTMENT_TABLE = "padiem_calendar_appointment"
WORK_LOG_INDEXES = (
    "idx_padiem_calendar_work_log_ws_date",
    "idx_padiem_calendar_work_log_ws_owner",
)
APPOINTMENT_INDEXES = (
    "idx_padiem_calendar_appointment_ws_date",
    "idx_padiem_calendar_appointment_ws_owner",
)

# (name, declared type, notnull, pk position) in the reviewed order.
EXPECTED_WORK_LOG_COLUMNS = (
    ("id", "TEXT", 0, 1),
    ("workspace_id", "TEXT", 1, 0),
    ("owner_id", "TEXT", 1, 0),
    ("date", "TEXT", 1, 0),
    ("title", "TEXT", 1, 0),
    ("content", "TEXT", 0, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)
EXPECTED_APPOINTMENT_COLUMNS = (
    ("id", "TEXT", 0, 1),
    ("workspace_id", "TEXT", 1, 0),
    ("owner_id", "TEXT", 1, 0),
    ("appointment_type", "TEXT", 1, 0),
    ("title", "TEXT", 1, 0),
    ("description", "TEXT", 0, 0),
    ("date", "TEXT", 1, 0),
    ("start_at", "TEXT", 0, 0),
    ("end_at", "TEXT", 0, 0),
    ("timezone", "TEXT", 0, 0),
    ("reminder_minutes", "INTEGER", 0, 0),
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
)
EXPECTED_APPOINTMENT_TYPES = ("date_only", "all_day", "timed")
EXPECTED_REMINDER_BOUNDS = (0, 40320)

QUERY = (
    "SELECT name, type, sql FROM sqlite_master WHERE name IN ("
    "'padiem_calendar_work_log','padiem_calendar_appointment',"
    "'idx_padiem_calendar_work_log_ws_date','idx_padiem_calendar_work_log_ws_owner',"
    "'idx_padiem_calendar_appointment_ws_date',"
    "'idx_padiem_calendar_appointment_ws_owner') ORDER BY name;\n"
    "PRAGMA table_info(padiem_calendar_work_log);\n"
    "PRAGMA table_info(padiem_calendar_appointment);"
)


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def source() -> str:
    """The reviewed 013 migration, proved additive and of the reviewed shape."""
    text = MIGRATION.read_text(encoding="utf-8")
    upper = norm(text)
    for forbidden in (
        "drop table",
        "alter table",
        "delete from",
        "create trigger",
        "insert into users",
        "update users",
        "update password_credentials",
        "pragma foreign_keys",
    ):
        if forbidden in upper:
            raise ValueError("Migration 013 is not additive: " + forbidden)
    for fragment in (
        "create table if not exists padiem_calendar_work_log",
        "create table if not exists padiem_calendar_appointment",
        "create index if not exists idx_padiem_calendar_work_log_ws_date",
        "create index if not exists idx_padiem_calendar_work_log_ws_owner",
        "create index if not exists idx_padiem_calendar_appointment_ws_date",
        "create index if not exists idx_padiem_calendar_appointment_ws_owner",
        "workspace_id text not null",
        "owner_id text not null",
    ):
        if fragment not in upper:
            raise ValueError("Migration 013 shape is not the reviewed shape: " + fragment)
    # Prove the SQL creates the exact reviewed shape on a real SQLite database.
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(text)
        work_log_shape = tuple(
            (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in db.execute(f"PRAGMA table_info({WORK_LOG_TABLE})").fetchall()
        )
        if work_log_shape != EXPECTED_WORK_LOG_COLUMNS:
            raise ValueError("Migration 013 work log columns do not match the reviewed shape")
        appointment_shape = tuple(
            (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
            for row in db.execute(f"PRAGMA table_info({APPOINTMENT_TABLE})").fetchall()
        )
        if appointment_shape != EXPECTED_APPOINTMENT_COLUMNS:
            raise ValueError(
                "Migration 013 appointment columns do not match the reviewed shape"
            )
        ddl = norm(
            db.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?", (APPOINTMENT_TABLE,)
            ).fetchone()[0]
        )
        for appointment_type in EXPECTED_APPOINTMENT_TYPES:
            if f"'{appointment_type}'" not in ddl:
                raise ValueError(
                    "Migration 013 appointment type set does not match the reviewed shape"
                )
        low, high = EXPECTED_REMINDER_BOUNDS
        if f">= {low}" not in ddl or f"<= {high}" not in ddl:
            raise ValueError(
                "Migration 013 reminder bounds do not match the reviewed shape"
            )
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


def classify(payload: object) -> str:
    objects, work_log_columns, appointment_columns = _blocks(payload, 3)
    by_name = {
        row.get("name"): row
        for row in objects
        if isinstance(row.get("name"), str)
    }
    work_log = by_name.get(WORK_LOG_TABLE)
    appointment = by_name.get(APPOINTMENT_TABLE)
    if work_log is None and appointment is None:
        return "missing"
    if work_log is None or appointment is None:
        # A half-applied migration is not a state this gate owns.
        return "drift"
    if work_log.get("type") != "table" or appointment.get("type") != "table":
        return "drift"
    for name in (*WORK_LOG_INDEXES, *APPOINTMENT_INDEXES):
        index = by_name.get(name)
        if index is None or index.get("type") != "index":
            return "drift"
        ddl = norm(index.get("sql"))
        if WORK_LOG_TABLE not in ddl and APPOINTMENT_TABLE not in ddl:
            return "drift"

    work_log_shape = tuple(
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in work_log_columns
    )
    if work_log_shape != EXPECTED_WORK_LOG_COLUMNS:
        return "drift"
    appointment_shape = tuple(
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in appointment_columns
    )
    if appointment_shape != EXPECTED_APPOINTMENT_COLUMNS:
        return "drift"

    appointment_ddl = norm(appointment.get("sql"))
    for appointment_type in EXPECTED_APPOINTMENT_TYPES:
        if f"'{appointment_type}'" not in appointment_ddl:
            return "drift"
    low, high = EXPECTED_REMINDER_BOUNDS
    if f">= {low}" not in appointment_ddl or f"<= {high}" not in appointment_ddl:
        return "drift"
    return "exact"


def main() -> None:
    if len(sys.argv) != 3:
        raise ValueError("expected <query|classify|apply|check-apply> <file>")
    action, path = sys.argv[1], Path(sys.argv[2])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "classify":
        verdict = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_MIGRATION_013_SCHEMA=" + verdict.upper())
    elif action == "apply":
        path.write_text(json.dumps({"sql": source()}), encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = (
            payload.get("result")
            if isinstance(payload, dict) and payload.get("success") is True
            else None
        )
        if not isinstance(rows, list) or not rows or any(
            not isinstance(item, dict) or item.get("success") is not True for item in rows
        ):
            raise ValueError("D1 additive 013 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_013_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 013 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_013_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
