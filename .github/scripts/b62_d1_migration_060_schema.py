#!/usr/bin/env python3
"""B62 D1 migration 060 gate: guarded one-time release of the 10 MiB metadata ceiling.

060 (``apps/padiem-chat/migrations/060_byte_length_capacity_ceiling_release.sql``)
rebuilds three D1 metadata tables so the product-side 10 MiB byte ceiling is
released while the non-empty lower bound and every other column, constraint,
index and foreign key survive::

    claw_document_metadata            (008)  byte_length > 0
    claw_conversation_artifact_index  (026)  size_bytes > 0
    b66_template_source               (027)  byte_length >= 1

This helper is the contract of ``.github/workflows/b62-d1-migration-060-gate.yml``:

* it pins the approved source of 008/027/060 by SHA-256 and reuses the
  owner-approved 026 source of ``b54_claw_artifact_schema_026.py``, so there is
  one authority per released migration, the applied SQL is exactly the reviewed
  file, and 008/026/027 are never rewritten;
* it replays 008/026/027 and 060 on a real SQLite database and derives the
  only two legal live shapes: ``pre_060`` (ceiling still present) and ``exact``
  (ceiling released);
* it classifies live schema evidence as ``missing``, ``pre_060``, ``exact`` or
  ``drift`` and never mutates a database by itself;
* it compares aggregate row counts and foreign-key violation counts around the
  one permitted apply. It reads aggregate counts only, never row content,
  identifiers or secrets.

Applying 060 to Production is a separate owner-authorized workflow dispatch.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from b54_claw_artifact_schema_026 import (  # noqa: E402  (path set above)
    assert_approved_source as approved_026_source,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"
RELEASE = MIGRATIONS / "060_byte_length_capacity_ceiling_release.sql"
SOURCE_008 = MIGRATIONS / "008_claw_document_metadata.sql"
SOURCE_027 = MIGRATIONS / "027_b66_template_source.sql"

# The applied SQL must be exactly the reviewed file. 008 and 027 are pinned
# here, 026 reuses the owner-approved source of the existing 026 gate, and 060
# is pinned so that any change to the applied migration is an explicit,
# reviewable act in the same commit that changes it.
PINNED_SHA256 = {
    SOURCE_008.name: "e98873cbf81042f80049b01355ef8b3eb4f04369ce190d007d02ee6edf4858b9",
    SOURCE_027.name: "78ab452740be1144d029d2d5e88a171942f662dc4a5e3aecda62b1881e210374",
    RELEASE.name: "6bbb93d3c58f879700fd1664ecb26e1d328eecef13e1a8b4cba31c5e86349fd1",
}

# Replayed only to derive the reviewed shape of the three rebuilt tables; they
# create the foreign-key targets of those tables.
PREREQUISITE_MIGRATIONS = (
    "001_auth_history.sql",
    "009_claw_run_history.sql",
    "014_claw_run_history_conversation.sql",
    "015_claw_run_history_workspace.sql",
)

CEILING = "10485760"

TABLES = (
    {
        "table": "claw_document_metadata",
        "index": "idx_claw_document_metadata_tenant_active",
        "column": "byte_length",
        "source": SOURCE_008.name,
    },
    {
        "table": "claw_conversation_artifact_index",
        "index": "idx_claw_conversation_artifact_owner",
        "column": "size_bytes",
        "source": "026_claw_conversation_artifact_index.sql",
    },
    {
        "table": "b66_template_source",
        "index": "idx_b66_template_source_owner_workspace_status",
        "column": "byte_length",
        "source": SOURCE_027.name,
    },
)

SCHEMA_STATEMENTS = (
    "SELECT type, name, sql FROM sqlite_master WHERE name IN ("
    "'claw_document_metadata','idx_claw_document_metadata_tenant_active',"
    "'claw_conversation_artifact_index','idx_claw_conversation_artifact_owner',"
    "'b66_template_source','idx_b66_template_source_owner_workspace_status') ORDER BY name",
    "PRAGMA table_info(claw_document_metadata)",
    "PRAGMA index_list(claw_document_metadata)",
    "PRAGMA foreign_key_list(claw_document_metadata)",
    "PRAGMA table_info(claw_conversation_artifact_index)",
    "PRAGMA index_list(claw_conversation_artifact_index)",
    "PRAGMA foreign_key_list(claw_conversation_artifact_index)",
    "PRAGMA table_info(b66_template_source)",
    "PRAGMA index_list(b66_template_source)",
    "PRAGMA foreign_key_list(b66_template_source)",
)
SCHEMA_QUERY = ";\n".join(SCHEMA_STATEMENTS)

COUNTS_STATEMENTS = tuple(
    f"SELECT COUNT(*) AS n FROM {entry['table']}" for entry in TABLES
)
COUNTS_QUERY = ";\n".join(COUNTS_STATEMENTS)

FK_STATEMENTS = ("PRAGMA foreign_key_check",)
FK_QUERY = ";\n".join(FK_STATEMENTS)

# Column names of the statements above, so a replayed SQLite result and a live
# D1 result are compared as the same dictionaries.
STATEMENT_COLUMNS = {
    "SELECT type, name, sql FROM sqlite_master": ("type", "name", "sql"),
    "PRAGMA table_info": ("cid", "name", "type", "notnull", "dflt_value", "pk"),
    "PRAGMA index_list": ("seq", "name", "unique", "origin", "partial"),
    "PRAGMA foreign_key_list": (
        "id", "seq", "table", "from", "to", "on_update", "on_delete", "match",
    ),
    "SELECT COUNT(*) AS n FROM ": ("n",),
    "PRAGMA foreign_key_check": ("table", "rowid", "parent", "fkid"),
}


class GateError(RuntimeError):
    """A fail-closed refusal. The message never carries row content or secrets."""


def canonical(sql: object) -> str:
    """Normalize DDL text so only semantic differences survive."""
    if not isinstance(sql, str):
        return ""
    text = re.sub(r"(?i)\bIF\s+NOT\s+EXISTS\b", " ", sql)
    text = text.replace('"', "")
    text = re.sub(r"[()\s]", "", text)
    return text.casefold()


def _sort_key(values: tuple) -> tuple:
    return tuple("" if value is None else str(value) for value in values)


def _statements(text: str) -> list[str]:
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in code.split(";") if statement.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_source() -> str:
    """Return the reviewed 060 SQL, refusing any change to the pinned file."""
    actual = _sha256(RELEASE)
    expected = PINNED_SHA256[RELEASE.name]
    if actual != expected:
        raise GateError("060 source SHA differs from the reviewed migration")
    return RELEASE.read_text(encoding="utf-8")


def prerequisite_sources() -> dict[str, str]:
    """Return the reviewed 008/026/027 sources without rewriting any of them."""
    for name, expected in PINNED_SHA256.items():
        actual = _sha256(MIGRATIONS / name)
        if actual != expected:
            raise GateError(f"{name} source SHA differs from the reviewed migration")
    sources = {
        SOURCE_008.name: SOURCE_008.read_text(encoding="utf-8"),
        "026_claw_conversation_artifact_index.sql": approved_026_source(),
        SOURCE_027.name: SOURCE_027.read_text(encoding="utf-8"),
    }
    for name, text in sources.items():
        if CEILING not in text:
            raise GateError(f"{name} no longer carries the reviewed 10 MiB ceiling")
    if CEILING in release_source():
        raise GateError("060 must not re-introduce the 10 MiB ceiling")
    return sources


def _rebuild_scope(
    text: str, tables: tuple = TABLES, name: str = "060"
) -> dict[str, dict[str, int]]:
    """Prove a release rebuilds exactly the reviewed tables, copy before drop."""
    statements = _statements(text)
    scope: dict[str, dict[str, int]] = {}
    for entry in tables:
        table = entry["table"]
        index = entry["index"]
        positions: dict[str, int] = {}
        for label, pattern in (
            ("create", rf"CREATE\s+TABLE\s+{re.escape(table)}_next\b"),
            ("copy", rf"INSERT\s+INTO\s+{re.escape(table)}_next\b"),
            ("drop", rf"DROP\s+TABLE\s+{re.escape(table)}\b"),
            ("rename", rf"ALTER\s+TABLE\s+{re.escape(table)}_next\s+RENAME\s+TO\s+{re.escape(table)}\b"),
            ("index", rf"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+{re.escape(index)}\b"),
        ):
            found = [
                position
                for position, statement in enumerate(statements)
                if re.search(pattern, statement, re.IGNORECASE)
            ]
            if len(found) != 1:
                raise GateError(f"{name} must {label} {table} exactly once")
            positions[label] = found[0]
        if positions["copy"] > positions["drop"]:
            raise GateError(f"{name} must copy {table} before dropping it")
        scope[table] = positions

    touched = set()
    for statement in statements:
        for match in re.finditer(
            r"(?i)\b(CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\s+"
            r"(?:IF\s+NOT\s+EXISTS\s+)?\"?([A-Za-z0-9_]+)",
            statement,
        ):
            touched.add(match.group(2))
    expected = {entry["table"] for entry in tables} | {
        f"{entry['table']}_next" for entry in tables
    }
    if touched != expected:
        raise GateError(f"{name} touches a table outside the reviewed rebuild scope")
    upper = re.sub(r"\s+", " ", text).upper()
    for forbidden in (
        "DELETE FROM", "UPDATE ", "REPLACE INTO", "TRUNCATE", "ATTACH ",
        "DETACH ", "CREATE TRIGGER", "CREATE VIEW", "DROP INDEX", "DROP COLUMN",
    ):
        if forbidden in upper:
            raise GateError(f"{name} contains a forbidden statement: {forbidden.strip()}")
    return scope


def _shape_from_connection(con: sqlite3.Connection, table: str, index: str) -> dict:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    index_row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index,)
    ).fetchone()
    columns = con.execute(f"PRAGMA table_info({table})").fetchall()
    indexes = con.execute(f"PRAGMA index_list({table})").fetchall()
    foreign_keys = con.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return {
        "table_sql": canonical(row[0]) if row else "",
        "index_sql": canonical(index_row[0]) if index_row else "",
        "columns": tuple(
            (item[1], str(item[2] or "").upper(), item[3], item[5]) for item in columns
        ),
        "indexes": tuple(
            sorted(
                ((item[1], item[2], item[3], item[4]) for item in indexes),
                key=_sort_key,
            )
        ),
        "foreign_keys": tuple(
            sorted(
                ((item[2], item[3], item[4], item[6]) for item in foreign_keys),
                key=_sort_key,
            )
        ),
    }


def replay_connection(*, with_release: bool) -> sqlite3.Connection:
    """Replay the reviewed migrations on an in-memory database."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=OFF")
    for name in PREREQUISITE_MIGRATIONS:
        con.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    for name, text in prerequisite_sources().items():
        con.executescript(text)
    if with_release:
        con.executescript(release_source())
    return con


def expected_shapes(*, with_release: bool) -> dict[str, dict]:
    con = replay_connection(with_release=with_release)
    try:
        return {
            entry["table"]: _shape_from_connection(
                con, entry["table"], entry["index"]
            )
            for entry in TABLES
        }
    finally:
        con.close()


def _payload_from_connection(con: sqlite3.Connection, statements: tuple) -> dict:
    blocks = []
    for statement in statements:
        rows = con.execute(statement).fetchall()
        columns = _columns_for(statement)
        blocks.append(
            {
                "success": True,
                "results": [dict(zip(columns, row)) for row in rows],
            }
        )
    return {"success": True, "result": blocks}


def _columns_for(statement: str) -> tuple:
    for prefix, columns in STATEMENT_COLUMNS.items():
        if statement.startswith(prefix):
            return columns
    raise GateError("unmapped statement in the gate query set")


def schema_payload(con: sqlite3.Connection) -> dict:
    return _payload_from_connection(con, SCHEMA_STATEMENTS)


def counts_payload(con: sqlite3.Connection) -> dict:
    return _payload_from_connection(con, COUNTS_STATEMENTS)


def fk_payload(con: sqlite3.Connection) -> dict:
    return _payload_from_connection(con, FK_STATEMENTS)


def _blocks(payload: object, count: int) -> list[list[dict]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise GateError("D1 query response is not successful")
    results = payload.get("result")
    if not isinstance(results, list) or len(results) != count:
        raise GateError(f"expected {count} D1 statement blocks")
    blocks: list[list[dict]] = []
    for block in results:
        if not isinstance(block, dict) or block.get("success") is not True:
            raise GateError("D1 statement block is not successful")
        rows = block.get("results")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise GateError("D1 statement rows are malformed")
        blocks.append(rows)
    return blocks


def _shape_from_live(master_rows, columns, indexes, foreign_keys, table, index) -> dict:
    master = {
        row.get("name"): row
        for row in master_rows
        if row.get("name") in (table, index)
    }
    table_row = master.get(table)
    index_row = master.get(index)
    if table_row is None:
        return {
            "table_sql": "",
            "index_sql": "",
            "columns": (),
            "indexes": (),
            "foreign_keys": (),
        }
    return {
        "table_sql": canonical(table_row.get("sql")),
        "index_sql": canonical(index_row.get("sql")) if index_row else "",
        "columns": tuple(
            (
                row.get("name"),
                str(row.get("type") or "").upper(),
                row.get("notnull"),
                row.get("pk"),
            )
            for row in columns
        ),
        "indexes": tuple(
            sorted(
                (
                    (row.get("name"), row.get("unique"), row.get("origin"),
                     row.get("partial"))
                    for row in indexes
                ),
                key=_sort_key,
            )
        ),
        "foreign_keys": tuple(
            sorted(
                (
                    (row.get("table"), row.get("from"), row.get("to"),
                     row.get("on_delete"))
                    for row in foreign_keys
                ),
                key=_sort_key,
            )
        ),
    }


def classify(payload: object) -> str:
    """Return ``missing``, ``pre_060``, ``exact`` or ``drift``."""
    blocks = _blocks(payload, len(SCHEMA_STATEMENTS))
    master_rows = blocks[0]
    live: dict[str, dict] = {}
    for offset, entry in enumerate(TABLES):
        base = 1 + offset * 3
        live[entry["table"]] = _shape_from_live(
            master_rows, blocks[base], blocks[base + 1], blocks[base + 2],
            entry["table"], entry["index"],
        )

    pre = expected_shapes(with_release=False)
    post = expected_shapes(with_release=True)
    states = {}
    for entry in TABLES:
        table = entry["table"]
        shape = live[table]
        if not shape["table_sql"]:
            states[table] = "missing"
        elif shape == pre[table]:
            states[table] = "pre_060"
        elif shape == post[table]:
            states[table] = "exact"
        else:
            states[table] = "drift"

    values = set(states.values())
    if "drift" in values:
        return "drift"
    if values == {"exact"}:
        return "exact"
    if values == {"pre_060"}:
        return "pre_060"
    if "missing" in values:
        return "missing"
    # A partially released schema is never applied again by this gate.
    return "drift"


def classify_counts(payload: object) -> dict[str, int]:
    blocks = _blocks(payload, len(COUNTS_STATEMENTS))
    counts: dict[str, int] = {}
    for entry, rows in zip(TABLES, blocks):
        if len(rows) != 1:
            raise GateError(f"unexpected row count evidence for {entry['table']}")
        value = rows[0].get("n")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise GateError(f"unreadable row count for {entry['table']}")
        counts[entry["table"]] = value
    return counts


def classify_fk(payload: object) -> dict[str, int]:
    blocks = _blocks(payload, len(FK_STATEMENTS))
    violations = {entry["table"]: 0 for entry in TABLES}
    for row in blocks[0]:
        table = row.get("table")
        if not isinstance(table, str):
            # An unreadable violation row must never be counted as "no violation".
            raise GateError("foreign key evidence is malformed")
        if table in violations:
            violations[table] += 1
    return violations


def check_counts(before_payload: object, after_payload: object) -> dict[str, int]:
    """Refuse a release that loses rows and report the per-table deltas."""
    before = classify_counts(before_payload)
    after = classify_counts(after_payload)
    deltas: dict[str, int] = {}
    for entry in TABLES:
        table = entry["table"]
        if after[table] < before[table]:
            raise GateError(f"060 lost rows in {table}")
        deltas[table] = after[table] - before[table]
    return deltas


def check_fk(before_payload: object, after_payload: object) -> dict[str, int]:
    """Refuse a release that adds foreign key violations to the three tables."""
    before = classify_fk(before_payload)
    after = classify_fk(after_payload)
    for table, violations in after.items():
        if violations > before[table]:
            raise GateError(f"060 introduced foreign key violations in {table}")
    return after


def source_contract() -> dict:
    """Prove the reviewed sources still describe the reviewed release."""
    sources = prerequisite_sources()
    release = release_source()
    scope = _rebuild_scope(release)

    pre = expected_shapes(with_release=False)
    post = expected_shapes(with_release=True)
    for entry in TABLES:
        table = entry["table"]
        column = entry["column"]
        ceiling = f"{column}<={CEILING}"
        if ceiling not in pre[table]["table_sql"]:
            raise GateError(f"{table} no longer carries the reviewed ceiling")
        if ceiling in post[table]["table_sql"]:
            raise GateError(f"{table} still carries the ceiling after 060")
        if pre[table]["table_sql"].replace("and" + ceiling, "") != post[table]["table_sql"]:
            raise GateError(f"{table} changes more than the ceiling in 060")
        for key in ("columns", "indexes", "foreign_keys", "index_sql"):
            if pre[table][key] != post[table][key]:
                raise GateError(f"{table} changes {key} in 060")
        if f"{table}" not in scope:
            raise GateError(f"{table} is not part of the reviewed rebuild")

    replay = replay_connection(with_release=False)
    try:
        user = "usr_" + "a" * 32
        chat = "chat_" + "c" * 32
        run = "run_" + "e" * 24
        digest = "a" * 64
        replay.execute(
            "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at)"
            " VALUES (?,'google','subj','a@b.c','2026-01-01','2026-01-01')", (user,),
        )
        replay.execute(
            "INSERT INTO conversations (id,user_id,title,created_at,updated_at)"
            " VALUES (?,?,'t','2026-01-01','2026-01-01')", (chat, user),
        )
        replay.execute(
            "INSERT INTO claw_run_history (id,user_id,run_id,channel,action,title,status,"
            "created_at,updated_at,conversation_id,workspace_id)"
            " VALUES ('rh1',?,?,'telegram','run','t','completed','2026-01-01','2026-01-01',?,'w')",
            (user, run, chat),
        )
        replay.execute(
            "INSERT INTO claw_document_metadata (document_id,tenant_id,object_key,filename,"
            "media_type,byte_length,created_at,expires_at,deleted_at)"
            " VALUES ('d1','t','k/d1','keep.docx','application/pdf',42,'2026-01-01','2026-01-02',NULL)",
        )
        replay.execute(
            "INSERT INTO claw_conversation_artifact_index (artifact_id,user_id,conversation_id,"
            "workspace_ref,source_run_ref,filename,media_type,size_bytes,integrity_ref,"
            "location_kind,location_ref,created_at)"
            " VALUES ('a1',?,?,'w',?,'keep.xlsx','application/pdf',120,?,'r2','k/a1','2026-01-01')",
            (user, chat, run, digest),
        )
        replay.execute(
            "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,"
            "original_filename,object_key,byte_length,sha256,status,created_at,updated_at)"
            " VALUES ('t1',?,'w','application/pdf','keep.pdf','k/t1',7,?,'uploaded','2026-01-01','2026-01-01')",
            (user, digest),
        )
        replay.executescript(release_source())
        kept = replay.execute(
            "SELECT byte_length FROM claw_document_metadata WHERE document_id='d1'"
        ).fetchone()
        kept_artifact = replay.execute(
            "SELECT size_bytes FROM claw_conversation_artifact_index WHERE artifact_id='a1'"
        ).fetchone()
        kept_template = replay.execute(
            "SELECT byte_length FROM b66_template_source WHERE id='t1'"
        ).fetchone()
        if kept != (42,) or kept_artifact != (120,) or kept_template != (7,):
            raise GateError("060 does not preserve the carried rows in replay")
        for statement, values in (
            (
                "INSERT INTO claw_document_metadata (document_id,tenant_id,object_key,filename,"
                "media_type,byte_length,created_at,expires_at,deleted_at)"
                " VALUES ('d2','t','k/d2','big.pdf','application/pdf',?,'now','later',NULL)",
                (11 * 1024 * 1024,),
            ),
            (
                "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,"
                "original_filename,object_key,byte_length,sha256,status,created_at,updated_at)"
                " VALUES ('t2',?,'w','application/pdf','big.pdf','k/t2',?,?,'uploaded','now','now')",
                (user, 11 * 1024 * 1024, digest),
            ),
        ):
            replay.execute(statement, values)
        for statement, values in (
            (
                "INSERT INTO claw_document_metadata (document_id,tenant_id,object_key,filename,"
                "media_type,byte_length,created_at,expires_at,deleted_at)"
                " VALUES ('d3','t','k/d3','zero.pdf','application/pdf',?,'now','later',NULL)",
                (0,),
            ),
            (
                "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,"
                "original_filename,object_key,byte_length,sha256,status,created_at,updated_at)"
                " VALUES ('t3',?,'w','application/pdf','zero.pdf','k/t3',?,?,'uploaded','now','now')",
                (user, 0, digest),
            ),
        ):
            try:
                replay.execute(statement, values)
            except sqlite3.IntegrityError:
                continue
            raise GateError("060 must keep refusing a zero-length metadata row")
    finally:
        replay.close()

    return {
        "sources": sorted(sources),
        "tables": [entry["table"] for entry in TABLES],
    }


def offline() -> None:
    source_contract()
    pre = expected_shapes(with_release=False)
    post = expected_shapes(with_release=True)
    print("B62_D1_MIGRATION_060_SOURCE_CONTRACT=PASS")
    print("D1_060_APPROVED_SOURCE_SHA=PASS")
    print("D1_060_RELEASED_MIGRATIONS_UNCHANGED=PASS")
    print("D1_060_REBUILD_SCOPE=PASS")
    print("D1_060_ROW_PRESERVATION_REPLAY=PASS")
    print("D1_060_CEILING_RELEASED_FLOOR_KEPT=PASS")
    print(
        "D1_060_SCHEMA_STATES="
        + ",".join(
            f"{entry['table']}:{'PRE' if pre[entry['table']] != post[entry['table']] else 'SAME'}"
            for entry in TABLES
        )
    )
    print("PRODUCTION_MUTATION=0")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args:
            raise GateError("expected an action")
        action = args[0]
        if action == "offline":
            offline()
            return 0
        if action == "query":
            source_contract()
            Path(args[1]).write_text(json.dumps({"sql": SCHEMA_QUERY}), encoding="utf-8")
            return 0
        if action == "counts":
            source_contract()
            Path(args[1]).write_text(json.dumps({"sql": COUNTS_QUERY}), encoding="utf-8")
            return 0
        if action == "fk":
            source_contract()
            Path(args[1]).write_text(json.dumps({"sql": FK_QUERY}), encoding="utf-8")
            return 0
        if action == "classify":
            print(
                "B62_D1_MIGRATION_060_SCHEMA="
                + classify(json.loads(Path(args[1]).read_text(encoding="utf-8"))).upper()
            )
            return 0
        if action == "apply":
            # The applied payload is the reviewed file itself, byte for byte.
            source_contract()
            Path(args[1]).write_text(
                json.dumps({"sql": release_source()}), encoding="utf-8"
            )
            return 0
        if action == "check-apply":
            payload = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            blocks = payload.get("result") if isinstance(payload, dict) else None
            if payload.get("success") is not True or not isinstance(blocks, list) or not blocks:
                raise GateError("060 apply returned an unsuccessful response")
            for block in blocks:
                if not isinstance(block, dict) or block.get("success") is not True:
                    raise GateError("060 apply returned an unsuccessful statement")
            print("B62_D1_MIGRATION_060_APPLY_RESPONSE=PASS")
            print(f"B62_D1_MIGRATION_060_APPLY_STATEMENTS={len(blocks)}")
            return 0
        if action == "check-counts":
            deltas = check_counts(
                json.loads(Path(args[1]).read_text(encoding="utf-8")),
                json.loads(Path(args[2]).read_text(encoding="utf-8")),
            )
            print("B62_D1_MIGRATION_060_ROW_COUNTS_PRESERVED=PASS")
            print("B62_D1_MIGRATION_060_ROW_COUNT_DELTAS=" + json.dumps(deltas, sort_keys=True))
            return 0
        if action == "check-fk":
            violations = check_fk(
                json.loads(Path(args[1]).read_text(encoding="utf-8")),
                json.loads(Path(args[2]).read_text(encoding="utf-8")),
            )
            print("B62_D1_MIGRATION_060_FOREIGN_KEYS=PASS")
            print(
                "B62_D1_MIGRATION_060_FOREIGN_KEY_VIOLATIONS="
                + json.dumps(violations, sort_keys=True)
            )
            return 0
        raise GateError(f"unknown 060 gate action: {action}")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, GateError) as error:
        print(f"B62_D1_MIGRATION_060_GATE=FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
