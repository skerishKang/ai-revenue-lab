#!/usr/bin/env python3
"""B62 D1 migration 063 gate: one owner run may stage several PC tool calls (#5015).

063 (``apps/padiem-chat/migrations/063_oracle_mesh_dispatch_tool_call_scope.sql``)
rebuilds ``oracle_mesh_dispatch`` so a run can hold one legacy single-command
dispatch and one dispatch per trusted PC file tool call. The 047
``UNIQUE (user_id, run_id)`` table constraint is replaced by three indexes:

    idx_oracle_mesh_dispatch_run_scope      UNIQUE (user_id, run_id) WHERE tool_call_ref IS NULL
    idx_oracle_mesh_dispatch_tool_call      UNIQUE (user_id, run_id, tool_call_ref) WHERE tool_call_ref IS NOT NULL
    idx_oracle_mesh_dispatch_tool_request   UNIQUE (user_id, run_id, tool_request_ref)

The third index is what keeps an old Worker (which writes the pre-063 row shape
with no scope value) and a new Worker from staging the same call twice.

This helper is the contract of ``.github/workflows/b62-d1-migration-063-gate.yml``:

* it pins the approved 063 source by SHA-256, so the applied SQL is exactly the
  reviewed file;
* it replays the committed 047/048/049 shape, inserts a real dispatch row, and
  applies 063 on a real SQLite database, proving that the row, its digest and
  its state survive, that the reviewed indexes are the only ones left, and that
  a second trusted call is accepted while a duplicate legacy run is refused;
* it reads schema metadata only (``sqlite_master``, ``PRAGMA table_info``,
  ``PRAGMA index_list``) and aggregate row counts; it never reads row content,
  user data or secret values, and it never emits an account, database or
  binding identifier.

Dispositions:
  ``MISSING``  the 047 table is absent; 063 cannot run and is not applied.
  ``PRE_063``  the committed 047/048/049 shape; 063 is applicable.
  ``EXACT``    the reviewed 063 shape is present (idempotent no-op).
  ``DRIFT``    the table exists with another shape; never mutated.
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
MIGRATION = MIGRATIONS / "063_oracle_mesh_dispatch_tool_call_scope.sql"
SOURCES = (
    MIGRATIONS / "047_oracle_mesh_dispatch.sql",
    MIGRATIONS / "048_oracle_mesh_command.sql",
    MIGRATIONS / "049_oracle_mesh_command_result_meta.sql",
)
TABLE = "oracle_mesh_dispatch"
NEXT = "oracle_mesh_dispatch_next"
# The applied SQL must be exactly the reviewed file.
PINNED_SHA256 = "7bac0b43518e59687cbe0c25ec4927290fc3e5fb9675a0af8b05d82a81edf6c2"

# (name, declared type, notnull, pk) in the reviewed order.
EXPECTED_COLUMNS = (
    ("dispatch_id", "TEXT", 0, 1),
    ("user_id", "TEXT", 1, 0),
    ("run_id", "TEXT", 1, 0),
    ("command_id", "TEXT", 1, 0),
    ("tool_request_ref", "TEXT", 1, 0),
    ("request_id", "TEXT", 1, 0),
    ("revision_ref", "TEXT", 1, 0),
    ("evidence_ref", "TEXT", 0, 0),
    ("request_fingerprint", "TEXT", 1, 0),
    ("account_ref", "TEXT", 1, 0),
    ("workspace_ref", "TEXT", 1, 0),
    ("device_id", "TEXT", 1, 0),
    ("binding_ref", "TEXT", 0, 0),
    ("node_ref", "TEXT", 1, 0),
    ("root_ref", "TEXT", 1, 0),
    ("path_relative", "TEXT", 1, 0),
    ("file_path", "TEXT", 1, 0),
    ("nonce_sha256", "TEXT", 0, 0),
    ("state", "TEXT", 1, 0),
    ("result_sha256", "TEXT", 0, 0),
    ("result_bytes", "INTEGER", 0, 0),
    ("expires_at", "TEXT", 1, 0),
    ("created_at", "TEXT", 1, 0),
    ("kind", "TEXT", 1, 0),
    ("command_text", "TEXT", 0, 0),
    ("termination", "TEXT", 0, 0),
    ("exit_code", "INTEGER", 0, 0),
    ("tool_call_ref", "TEXT", 0, 0),
)
# 047 + 048 + 049, before the scope column exists.
PRE_063_COLUMNS = EXPECTED_COLUMNS[:-1]
PRE_063_DEFAULTS = {"kind": "'read'"}
EXPECTED_DEFAULTS = {"kind": "'read'"}

# name -> (unique, partial) for the reviewed 063 indexes.
EXPECTED_INDEXES = {
    "idx_oracle_mesh_dispatch_state_expiry": (0, 0),
    "idx_oracle_mesh_dispatch_run_scope": (1, 1),
    "idx_oracle_mesh_dispatch_tool_call": (1, 1),
    "idx_oracle_mesh_dispatch_tool_request": (1, 0),
}

QUERY = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type='table' AND name='oracle_mesh_dispatch';\n"
    "PRAGMA table_info(oracle_mesh_dispatch);\n"
    "PRAGMA index_list(oracle_mesh_dispatch);"
)

COUNTS = "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch;"


def norm(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def code(value: str) -> str:
    """The executable statements, with the explanatory comments removed."""
    return norm("\n".join(line.split("--", 1)[0] for line in value.splitlines()))


def tight(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", value).lower()


def _shape(connection: sqlite3.Connection, table: str) -> tuple:
    return tuple(
        (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _defaults(connection: sqlite3.Connection, table: str) -> dict:
    values = {}
    for row in connection.execute(f"PRAGMA table_info({table})").fetchall():
        if row[4] is not None:
            values[str(row[1])] = str(row[4]).strip().lower()
    return values


def _indexes(connection: sqlite3.Connection, table: str) -> dict:
    """Named, non-automatic indexes as name -> (unique, partial)."""
    found = {}
    for row in connection.execute(f"PRAGMA index_list({table})").fetchall():
        # seq, name, unique, origin, partial
        if str(row[3]).lower() != "c":
            continue
        found[str(row[1])] = (int(row[2]), int(row[4]))
    return found


def _pre_table(connection: sqlite3.Connection) -> None:
    for path in SOURCES:
        connection.executescript(path.read_text(encoding="utf-8"))
    connection.execute(
        "CREATE TABLE claw_run_history (id TEXT PRIMARY KEY, run_id TEXT, user_id TEXT)"
    )


def _seed(connection: sqlite3.Connection) -> tuple:
    row = (
        "dsp_" + "1" * 32, "usr_" + "a" * 32, "chat_pcq_" + "b" * 32,
        "oracle_mesh_cmd_live", "oracle_mesh_tool_" + "c" * 20,
        "oracle_mesh_req_live", "oracle_mesh_rev_live", None, "f" * 64,
        "account-1", "connector-ws-1", "device-1", None, "node-1",
        "mesh_terminal", "command", "command", "n" * 64, "done", "e" * 64,
        1515, "2099-01-01T00:00:00.000Z", "2026-10-21T05:39:16.000Z",
        "command", "Get-ChildItem -LiteralPath x", "no_exit_code", None,
    )
    columns = ", ".join(EXPECTED_COLUMNS[index][0] for index in range(len(row)))
    connection.execute(
        f"INSERT INTO {TABLE} ({columns}) VALUES ("
        + ",".join("?" for _ in row) + ")",
        row,
    )
    connection.commit()
    return row


def _read_row(connection: sqlite3.Connection, dispatch_id: str) -> tuple:
    columns = ", ".join(name for name, *_rest in EXPECTED_COLUMNS[:-1])
    return connection.execute(
        f"SELECT {columns} FROM {TABLE} WHERE dispatch_id=?", (dispatch_id,),
    ).fetchone()


def source(path: Path | None = None) -> str:
    """Return the reviewed 063 SQL, or refuse anything that is not it."""
    target = MIGRATION if path is None else Path(path)
    text = target.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if path is None:
        if not PINNED_SHA256 or digest != PINNED_SHA256:
            raise ValueError("Migration 063 is not the pinned reviewed file")
    upper = code(text)
    # 063 is a rebuild of exactly one table: no other table, no data rewrite
    # outside the copy, no delete and no update.
    for forbidden in (
        "delete from", "update ", "create trigger", "drop trigger",
        "create view", "drop view", "alter table add column",
    ):
        if forbidden in upper:
            raise ValueError("Migration 063 exceeds the reviewed rebuild: " + forbidden)
    if upper.count(f"create table {NEXT}") != 1:
        raise ValueError("Migration 063 must create the replacement table exactly once")
    if upper.count(f"insert into {NEXT}") != 1:
        raise ValueError("Migration 063 must copy the existing rows exactly once")
    if upper.count(f"drop table {TABLE}") != 1:
        raise ValueError("Migration 063 must drop the replaced table exactly once")
    if upper.count(f"alter table {NEXT} rename to {TABLE}") != 1:
        raise ValueError("Migration 063 must rename the replacement exactly once")
    if "unique (user_id, run_id)" in upper:
        raise ValueError("Migration 063 must not keep the one-row-per-run constraint")

    # Prove the SQL produces the reviewed shape on a real database, starting
    # from the committed 047/048/049 table with a live-shaped row in it.
    db = sqlite3.connect(":memory:")
    try:
        _pre_table(db)
        if _shape(db, TABLE) != PRE_063_COLUMNS:
            raise ValueError("the committed 047/048/049 shape is not the expected one")
        seeded = _seed(db)
        db.executescript(text)
        if _shape(db, TABLE) != EXPECTED_COLUMNS:
            raise ValueError("Migration 063 columns do not match the reviewed shape")
        if _defaults(db, TABLE) != EXPECTED_DEFAULTS:
            raise ValueError("Migration 063 defaults are not the reviewed defaults")
        if db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0] != 1:
            raise ValueError("Migration 063 must preserve every existing row")
        if _read_row(db, seeded[0]) != seeded:
            raise ValueError("Migration 063 changed an existing dispatch row")
        if _indexes(db, TABLE) != EXPECTED_INDEXES:
            raise ValueError("Migration 063 indexes are not the reviewed set")
        if "unique (user_id, run_id)" in tight(
            db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (TABLE,),
            ).fetchone()[0]
        ):
            raise ValueError("Migration 063 left the one-row-per-run constraint")
        # A second trusted tool call in the same run is accepted, the same call
        # twice is not, and a duplicate legacy run is still refused.
        second = (
            "dsp_" + "2" * 32, seeded[1], seeded[2], "oracle_mesh_cmd_second",
            "call_read_" + "d" * 20, "oracle_mesh_req_second",
            "oracle_mesh_rev_second", None, "f" * 64, seeded[9], seeded[10],
            seeded[11], None, seeded[13], seeded[14], seeded[15], seeded[16],
            None, "pending", None, None, seeded[21], seeded[22], "command",
            "Get-Content -LiteralPath y", None, None, "call_read_" + "d" * 20,
        )
        columns = ", ".join(name for name, *_rest in EXPECTED_COLUMNS)
        db.execute(
            f"INSERT INTO {TABLE} ({columns}) VALUES ("
            + ",".join("?" for _ in second) + ")",
            second,
        )
        try:
            db.execute(
                f"INSERT INTO {TABLE} ({columns}) VALUES ("
                + ",".join("?" for _ in second) + ")",
                second,
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 063 lets one trusted call stage twice")
        legacy = (
            "dsp_" + "3" * 32, seeded[1], seeded[2], "oracle_mesh_cmd_legacy",
            "oracle_mesh_tool_" + "e" * 20, "oracle_mesh_req_legacy",
            "oracle_mesh_rev_legacy", None, "f" * 64, seeded[9], seeded[10],
            seeded[11], None, seeded[13], seeded[14], seeded[15], seeded[16],
            None, "pending", None, None, seeded[21], seeded[22], "command",
            "whoami", None, None, None,
        )
        try:
            db.execute(
                f"INSERT INTO {TABLE} ({columns}) VALUES ("
                + ",".join("?" for _ in legacy) + ")",
                legacy,
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise ValueError("Migration 063 dropped the one-per-run legacy guard")
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
        (row.get("name"), str(row.get("type", "")).upper(),
         int(row.get("notnull", -1)), int(row.get("pk", -1)))
        for row in rows
    )


def _indexes_from(rows: list[dict[str, object]]) -> dict:
    found = {}
    for row in rows:
        if str(row.get("origin", "")).lower() != "c":
            continue
        found[str(row.get("name"))] = (int(row.get("unique", -1)), int(row.get("partial", -1)))
    return found


def _has_run_unique(ddl: str) -> bool:
    return "unique(user_id,run_id)" in ddl


def classify(payload: object) -> str:
    objects, columns, indexes = _blocks(payload, 3)
    table_rows = [row for row in objects if row.get("name") == TABLE]
    shape = _shape_from(columns)
    if not table_rows:
        return "missing" if not shape and not indexes else "drift"
    if len(table_rows) != 1 or not isinstance(table_rows[0].get("sql"), str):
        return "drift"
    ddl = tight(table_rows[0]["sql"])
    defaults = {
        str(row.get("name")): str(row["dflt_value"]).strip().lower()
        for row in columns if row.get("dflt_value") is not None
    }
    found_indexes = _indexes_from(indexes)
    if shape == EXPECTED_COLUMNS:
        if defaults != EXPECTED_DEFAULTS:
            return "drift"
        if found_indexes != EXPECTED_INDEXES:
            return "drift"
        if _has_run_unique(ddl) or "tool_call_reftext" not in ddl:
            return "drift"
        return "exact"
    if shape == PRE_063_COLUMNS:
        if defaults not in (PRE_063_DEFAULTS, {}):
            return "drift"
        if not _has_run_unique(ddl):
            return "drift"
        if any(name in found_indexes for name in EXPECTED_INDEXES
               if name != "idx_oracle_mesh_dispatch_state_expiry"):
            return "drift"
        return "pre_063"
    return "drift"


def _count(payload: object) -> int:
    (rows,) = _blocks(payload, 1)
    if len(rows) != 1:
        raise ValueError("row count evidence is malformed")
    value = rows[0].get("n")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("row count is unreadable")
    return value


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        raise ValueError("expected an operation")
    action = argv[0]
    if action == "offline":
        source()
        print("B62_D1_MIGRATION_063_SOURCE_CONTRACT=PASS")
        print("PRODUCTION_MUTATION=0")
        return
    if len(argv) < 2:
        raise ValueError("expected an operation and a file")
    path = Path(argv[1])
    if action == "query":
        source()
        path.write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
    elif action == "counts":
        path.write_text(json.dumps({"sql": COUNTS}), encoding="utf-8")
    elif action == "classify":
        verdict = classify(json.loads(path.read_text(encoding="utf-8")))
        print("B62_D1_MIGRATION_063_SCHEMA=" + verdict.upper())
    elif action == "check-counts":
        if len(argv) != 3:
            raise ValueError("expected two count payloads")
        before = _count(json.loads(path.read_text(encoding="utf-8")))
        after = _count(json.loads(Path(argv[2]).read_text(encoding="utf-8")))
        if before != after:
            raise ValueError(
                f"row count changed across the rebuild: {before} -> {after}"
            )
        print(f"B62_D1_MIGRATION_063_ROW_COUNT_PRESERVED={after}")
    elif action == "check-count-arg":
        if len(argv) != 3:
            raise ValueError("expected a count payload and the readonly count")
        after = _count(json.loads(path.read_text(encoding="utf-8")))
        expected = argv[2].strip()
        if not expected.isdigit() or int(expected) != after:
            raise ValueError(
                f"row count changed in a no-op run: {expected} -> {after}"
            )
        print(f"B62_D1_MIGRATION_063_ROW_COUNT_PRESERVED={after}")
    elif action == "apply":
        source()
        path.write_text(json.dumps({"sql": MIGRATION.read_text(encoding="utf-8")}),
                        encoding="utf-8")
    elif action == "check-apply":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result") if isinstance(payload, dict) and payload.get("success") is True else None
        if (not isinstance(rows, list) or not rows
                or any(not isinstance(item, dict) or item.get("success") is not True for item in rows)):
            raise ValueError("D1 migration 063 mutation returned unsuccessful SQL")
        print("B62_D1_MIGRATION_063_APPLY_RESPONSE=PASS")
    else:
        raise ValueError("unknown 063 gate operation")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error) as error:
        print("B62_D1_MIGRATION_063_GATE=FAIL:" + str(error), file=sys.stderr)
        raise SystemExit(1)
