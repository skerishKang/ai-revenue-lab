"""#5895 ② — the one general D1 migration gate for Padiem Chat.

Replaces the "one workflow per migration number" family. This module owns the
reasoning; the workflow owns the Cloudflare calls. It never opens a network
connection and never reads a user row: every question it answers is about
schema metadata, the wrangler ledger, and per-table COUNT(*).

Why the ledger needs a one-time baseline
---------------------------------------
Chat's Production schema was applied by per-migration gates that POSTed SQL
directly, so `d1_migrations` — wrangler's own bookkeeping table, written as
`INSERT INTO "d1_migrations" (name) VALUES ('<file>.sql')` — is empty while the
objects exist. `wrangler d1 migrations apply` would therefore try to re-run all
71 historical files. The gate closes that gap without executing them: each
migration's representative object is proven present in `sqlite_master`, and only
then is the name recorded in the ledger. The table itself is created with the
single statement wrangler creates it with
(`getCreateMigrationsTableQuery` in cloudflare/workers-sdk), and the gate
re-probes for it before writing anything.

Representative object
---------------------
Every migration file is replayed in order into an in-memory SQLite database,
exactly the way the per-migration helpers already replay their own file. The
first object the schema gains in that step — a new column where the file is an
`ALTER TABLE ... ADD COLUMN`, otherwise a new table — is that migration's
representative. Shadow rebuilds (`CREATE x_next` → `DROP x` → `RENAME`) gain no
net table, so they resolve to the column they added, or to no representative at
all, which the gate reports instead of guessing.

Safety
------
* only files at or below `--up-to` enter the apply window, and each copied byte
  is re-hashed against the inventory;
* a file whose executable SQL contains DROP TABLE/COLUMN/INDEX is refused unless
  `--allow-table-drop` is passed (SQL comments are stripped first, so a comment
  that names DROP TABLE is not a trigger);
* a name recorded in the ledger whose representative object is missing from the
  live schema is drift: hard stop, nothing is applied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

# .github/scripts/<this file> -> repository root is two levels up.
ROOT = Path(__file__).resolve().parents[2]

# wrangler's own bookkeeping table and its exact INSERT shape. Verified against
# cloudflare/workers-sdk packages/wrangler/src/d1/{constants,migrations/helpers}.ts.
LEDGER_TABLE = "d1_migrations"

DESTRUCTIVE_TOKENS = ("DROP TABLE", "DROP COLUMN", "DROP INDEX")
IDENTIFIER_RE = re.compile(r"\A[A-Za-z0-9_]+\Z")
DATABASE_ID_RE = re.compile(r"\A[0-9a-fA-F-]{32,36}\Z")
MIGRATION_FILE_RE = re.compile(r"\A(\d{3})_[A-Za-z0-9._-]+\.sql\Z")
READ_ONLY_RE = re.compile(r"\A(SELECT|PRAGMA)\b", re.IGNORECASE)

APPS: dict[str, dict[str, Any]] = {
    "chat": {
        "migrations": ROOT / "apps" / "padiem-chat" / "migrations",
        "worker": "padiem-chat",
        "binding": "PADIEM_CHAT_DB",
    },
}


class GateError(ValueError):
    """A fixed, public-safe refusal. Never carries SQL bodies or row data."""


def _app(name: str) -> dict[str, Any]:
    app = APPS.get(name)
    if app is None:
        raise GateError("B62_D1_GATE_APP_UNKNOWN")
    directory = Path(app["migrations"])
    if not directory.is_dir():
        raise GateError("B62_D1_GATE_MIGRATIONS_MISSING")
    return app


def strip_comments(sql: str) -> str:
    """Drop ``--`` line comments; the repo's own guards use the same rule."""

    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def is_destructive(sql: str) -> bool:
    upper = strip_comments(sql).upper()
    return any(token in upper for token in DESTRUCTIVE_TOKENS)


def _schema(db: sqlite3.Connection) -> dict[str, set[str]]:
    tables: set[str] = set()
    columns: set[str] = set()
    other: set[str] = set()
    for kind, name, table in db.execute(
        "SELECT type, name, tbl_name FROM sqlite_master "
        "WHERE type IN ('table','index','view','trigger') AND name NOT LIKE 'sqlite_%'"
    ):
        if kind == "table":
            tables.add(name)
        elif kind == "index":
            other.add(name)
        else:
            other.add(f"{kind}:{name}")
    for table in sorted(tables):
        for row in db.execute(f'PRAGMA table_info("{table}")'):
            columns.add(f"{table}.{row[1]}")
    return {"tables": tables, "columns": columns, "other": other}


def _representative(before: dict[str, set[str]], after: dict[str, set[str]]) -> dict[str, str] | None:
    """One object this migration is responsible for: a new table, else a new column.

    A shadow rebuild (`CREATE x_next` -> `DROP x` -> `RENAME`) leaves no net new
    table and no net new column, so it gets no representative. The gate reports
    that instead of inventing an indicator, and only a first-run baseline is
    allowed to record such a file without object proof.
    """

    gained_tables = sorted(after["tables"] - before["tables"])
    if gained_tables:
        return {"kind": "table", "table": gained_tables[0], "column": ""}
    gained_columns = sorted(after["columns"] - before["columns"])
    if gained_columns:
        table, column = gained_columns[0].split(".", 1)
        return {"kind": "column", "table": table, "column": column}
    return None


def build_inventory(app_name: str) -> list[dict[str, Any]]:
    """Replay every migration in order and pin one representative object each."""

    directory = Path(_app(app_name)["migrations"])
    files = sorted(p for p in directory.glob("*.sql") if MIGRATION_FILE_RE.match(p.name))
    skipped = sorted(p.name for p in directory.glob("*.sql") if p not in files)
    if skipped:
        raise GateError("B62_D1_GATE_UNNUMBERED_MIGRATION")
    if not files:
        raise GateError("B62_D1_GATE_MIGRATIONS_EMPTY")

    db = sqlite3.connect(":memory:")
    entries: list[dict[str, Any]] = []
    try:
        for path in files:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            before = _schema(db)
            try:
                db.executescript(text)
            except sqlite3.Error as exc:
                # Only the exception class: SQLite text can quote source lines.
                raise GateError(
                    f"B62_D1_GATE_SOURCE_NOT_REPLAYABLE:{path.name}:{type(exc).__name__}"
                ) from None
            after = _schema(db)
            entries.append(
                {
                    "name": path.name,
                    "number": MIGRATION_FILE_RE.match(path.name).group(1),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "representative": _representative(before, after),
                    "destructive": is_destructive(text),
                }
            )
    finally:
        db.close()
    return entries


def read_json(path: str | Path) -> Any:
    """Parse a gate response file.

    `wrangler --json` prints its banner and trailing log lines into the same
    stdout the JSON goes to, so the file is not necessarily bare JSON. The
    first complete JSON value is taken and anything around it is ignored; a file
    with no JSON at all is a named refusal, never a silent empty ledger.
    """

    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            return decoder.raw_decode(text, index)[0]
        except json.JSONDecodeError:
            continue
    raise GateError("B62_D1_GATE_RESPONSE_NOT_JSON")


def detail_tables(
    inventory: list[dict[str, Any]],
    up_to: str,
    live_tables: set[str],
    extra_names: tuple[str, ...] | list[str] = (),
) -> list[str]:
    """The tables one detail query may ask about, and why it is bounded.

    `sqlite_master` already answers a table representative. Only a column
    representative needs `PRAGMA table_info`, and D1 caps the statements in one
    query, so the column set inside the window is the scope. `extra_names` adds
    the tables a plan is about to create, so their row count is reported too.
    """

    wanted: set[str] = set()
    for item in inventory:
        representative = item["representative"]
        if representative is None or item["number"] > up_to:
            continue
        if representative["kind"] == "column":
            wanted.add(representative["table"])
        elif item["name"] in extra_names:
            wanted.add(representative["table"])
    return sorted(table for table in wanted if table in live_tables)


def refuse(plan: dict[str, Any]) -> dict[str, Any]:
    """One place that decides a plan may not proceed."""

    if plan["drift"]:
        raise GateError("B62_D1_LEDGER_OBJECT_DRIFT")
    if plan["refused_drop_guard"]:
        raise GateError("B62_D1_DROP_GUARD_REFUSED")
    return plan


def require_column_evidence(inventory: list[dict[str, Any]], up_to: str, detail: Any) -> None:
    """A column representative cannot be proven from `sqlite_master` alone.

    Without the PRAGMA response the gate would classify an already-applied
    `ALTER TABLE ... ADD COLUMN` as pending and re-run it in Production, so the
    detail payload is mandatory as soon as one column indicator is in scope.
    """

    needed = any(
        item["representative"] is not None
        and item["representative"]["kind"] == "column"
        and item["number"] <= up_to
        for item in inventory
    )
    if needed and detail is None:
        raise GateError("B62_D1_GATE_DETAIL_REQUIRED")


def binding_id(settings: Any, name: str) -> str:
    """The one live D1 binding id the served Worker actually points at.

    Never a guess from the database name, and never read out of wrangler.toml:
    the gate asks the platform which database the running Worker is bound to.
    """

    if not isinstance(settings, dict) or settings.get("success") is not True:
        raise GateError("B62_D1_GATE_WORKER_SETTINGS_UNREADABLE")
    hits = [
        item
        for item in settings.get("result", {}).get("bindings", [])
        if isinstance(item, dict) and item.get("type") == "d1" and item.get("name") == name
    ]
    if len(hits) != 1:
        raise GateError("B62_D1_GATE_BINDING_NOT_EXACTLY_ONE")
    database_id = hits[0].get("id")
    if not isinstance(database_id, str) or not DATABASE_ID_RE.fullmatch(database_id):
        raise GateError("B62_D1_GATE_BINDING_ID_INVALID")
    return database_id


def _rows(payload: Any, expect: str) -> list[list[dict[str, Any]]]:
    """Unwrap a `wrangler d1 execute --json` envelope into statement result blocks.

    Accepted shapes: the list-of-blocks wrangler prints, a single block, or the
    Cloudflare `/query` result the older gates used. A block whose rows are
    import statistics rather than query results is refused by name: the
    `--file` path runs an import and answers with a count of statements, and
    that would read as a schema with zero tables.
    """

    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        payload = payload["result"]
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        payload = [payload]
    if not isinstance(payload, list):
        raise GateError(f"B62_D1_GATE_{expect}_ENVELOPE_UNEXPECTED")
    blocks = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("results"), list):
            raise GateError(f"B62_D1_GATE_{expect}_ENVELOPE_UNEXPECTED")
        rows = [
            {str(key).lower(): value for key, value in row.items()} for row in item["results"]
        ]
        for row in rows:
            if any("queries executed" in key for key in row):
                raise GateError("B62_D1_GATE_IMPORT_STATS_NOT_ROWS")
        blocks.append(rows)
    return blocks


def _single_block(payload: Any, expect: str) -> list[dict[str, Any]]:
    """One statement per execute: the response must carry exactly one block.

    The first Production run proved that a two-statement file does not come
    back as two blocks, so every read now sends one query and unwraps one
    block here instead of guessing where a statement boundary fell.
    """

    blocks = _rows(payload, expect)
    if len(blocks) != 1:
        raise GateError(f"B62_D1_GATE_{expect}_BLOCKS_UNEXPECTED")
    return blocks[0]


def _schema_sets(schema_payload: Any) -> tuple[set[str], set[str], set[str]]:
    tables: set[str] = set()
    columns: set[str] = set()
    other: set[str] = set()
    for row in _single_block(schema_payload, "SNAPSHOT"):
        kind, name = row.get("type"), row.get("name")
        if kind == "table":
            tables.add(str(name))
        elif kind == "index":
            other.add(str(name))
        elif kind in ("view", "trigger"):
            other.add(f"{kind}:{name}")
    return tables, columns, other


def snapshot_rows(schema_payload: Any, probe_payload: Any) -> tuple[set[str], set[str], set[str], bool]:
    """(tables, columns, other, ledger_present) from the two split responses."""

    tables, columns, other = _schema_sets(schema_payload)
    return tables, columns, other, len(_single_block(probe_payload, "PROBE")) == 1


def snapshot_tables(schema_payload: Any) -> set[str]:
    return _schema_sets(schema_payload)[0]


def ledger_rows(payload: Any) -> list[dict[str, Any]]:
    blocks = _rows(payload, "LEDGER")
    if len(blocks) != 1:
        raise GateError("B62_D1_GATE_LEDGER_BLOCKS_UNEXPECTED")
    rows = blocks[0]
    for row in rows:
        if "name" not in row:
            raise GateError("B62_D1_GATE_LEDGER_ROW_SHAPE")
    return rows


def detail_rows(payload: Any, tables: list[str]) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Per-table column sets and row counts from one detail response."""

    blocks = _rows(payload, "DETAIL")
    if len(blocks) != 2 * len(tables):
        raise GateError("B62_D1_GATE_DETAIL_BLOCKS_UNEXPECTED")
    columns: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for index, table in enumerate(tables):
        info, count = blocks[2 * index], blocks[2 * index + 1]
        columns[table] = {str(row.get("name")) for row in info}
        if len(count) != 1 or "row_count" not in count[0]:
            raise GateError("B62_D1_GATE_COUNT_BLOCK_UNEXPECTED")
        value = count[0]["row_count"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise GateError("B62_D1_GATE_COUNT_NOT_INTEGER")
        counts[table] = value
    return columns, counts


def _require_identifier(name: str, code: str) -> str:
    if not IDENTIFIER_RE.match(name):
        raise GateError(code)
    return name


def resolve_up_to(inventory: list[dict[str, Any]], raw: str | None) -> str:
    """An empty `--up-to` means the newest migration in this checkout."""

    if raw is None or raw == "":
        return max(item["number"] for item in inventory)
    if not re.fullmatch(r"\d{3}", raw):
        raise GateError("B62_D1_GATE_UP_TO_MUST_BE_THREE_DIGITS")
    return raw


def plan_from(inventory: list[dict[str, Any]], up_to: str) -> list[dict[str, Any]]:
    window = [item for item in inventory if item["number"] <= up_to]
    if not window:
        raise GateError("B62_D1_GATE_UP_TO_MATCHES_NOTHING")
    return window


def classify(
    *,
    inventory: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    tables: set[str],
    columns: set[str],
    up_to: str,
    allow_table_drop: bool,
    detail_columns: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Decide recorded / to-seed / to-apply / refused for the requested window."""

    window = plan_from(inventory, up_to)
    recorded = {str(row.get("name")) for row in ledger}
    # An empty ledger means the earlier per-migration gates applied the schema
    # directly and never recorded it: this is the one-time baseline run.
    baseline = not recorded
    extra = sorted(recorded - {item["name"] for item in inventory})
    if extra:
        # A ledger name with no source file means the database is ahead of, or
        # different from, the main this gate was dispatched on.
        raise GateError("B62_D1_GATE_LEDGER_HAS_UNKNOWN_NAME")

    def evidence(item: dict[str, Any]) -> str:
        representative = item["representative"]
        if representative is None:
            return "unprovable"
        if detail_columns is not None and representative["kind"] == "column":
            return "present" if representative["column"] in detail_columns.get(
                representative["table"], set()
            ) else "absent"
        if representative["kind"] == "column":
            return "present" if f"{representative['table']}.{representative['column']}" in columns else "absent"
        return "present" if representative["table"] in tables else "absent"

    seed: list[str] = []
    apply: list[str] = []
    missing: list[str] = []
    unprovable: list[str] = []
    for item in window:
        name = item["name"]
        state = evidence(item)
        if name in recorded:
            if state == "absent":
                missing.append(name)
            continue
        if state == "present":
            seed.append(name)
        elif state == "unprovable" and baseline:
            # The first-run baseline records these because the earlier reviewed
            # gates already executed them; every later run executes instead.
            seed.append(name)
            unprovable.append(name)
        else:
            apply.append(name)
    # The DROP guard covers the statements that will actually run. Recording an
    # already-applied rebuild in the ledger executes nothing, so it is not a drop.
    by_name = {item["name"]: item for item in window}
    refused = [
        name for name in apply
        if by_name[name]["destructive"] and not allow_table_drop
    ]
    return {
        "up_to": up_to,
        "baseline_first_run": baseline,
        "window": [item["name"] for item in window],
        "recorded": sorted(recorded),
        "seed": seed,
        "seed_without_object_proof": unprovable,
        "apply": apply,
        "drift": missing,
        "refused_drop_guard": refused,
        "allow_table_drop": allow_table_drop,
    }


def schema_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Name-level schema delta only. Column and routine text never travels."""

    delta = {}
    for kind in ("tables", "columns", "other"):
        lost = sorted(set(before[kind]) - set(after[kind]))
        gained = sorted(set(after[kind]) - set(before[kind]))
        delta[kind] = {"added": gained, "removed": lost}
    return delta


# --- CLI -----------------------------------------------------------------------


def cmd_binding_id(argv: argparse.Namespace) -> int:
    print(binding_id(read_json(argv.settings), argv.binding))
    return 0


def cmd_probe(argv: argparse.Namespace) -> int:
    present = len(_single_block(read_json(argv.probe), "PROBE")) == 1
    print("yes" if present else "no")
    return 0


def cmd_inventory(argv: argparse.Namespace) -> int:
    inventory = build_inventory(argv.app)
    Path(argv.out).write_text(
        json.dumps(inventory, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    destructive = [item["name"] for item in inventory if item["destructive"]]
    without = [item["name"] for item in inventory if item["representative"] is None]
    print(f"B62_D1_INVENTORY_FILES={len(inventory)}")
    print(f"B62_D1_INVENTORY_DESTRUCTIVE={len(destructive)}")
    print(f"B62_D1_INVENTORY_NO_REPRESENTATIVE={len(without)}")
    print("B62_D1_INVENTORY_SHA_PINNED=PASS")
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_snapshot_sql(argv: argparse.Namespace) -> int:
    # Two files, one statement each. Both are safe on a database with no ledger
    # yet: the probe is what decides whether the ledger query may run at all, so
    # a read-only pass never asks wrangler to create anything. One statement per
    # execute because a two-statement file does not come back as two blocks.
    schema_sql = (
        "SELECT type, name, tbl_name FROM sqlite_master "
        "WHERE type IN ('table','index','view','trigger') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name;\n"
    )
    probe_sql = (
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name = '{LEDGER_TABLE}';\n"
    )
    Path(argv.out).write_text(schema_sql, encoding="utf-8")
    Path(argv.probe_out).write_text(probe_sql, encoding="utf-8")
    print("B62_D1_SNAPSHOT_QUERY=SCHEMA_AND_LEDGER_PROBE")
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_ledger_sql(argv: argparse.Namespace) -> int:
    sql = f'SELECT id, name, applied_at FROM "{LEDGER_TABLE}" ORDER BY id;\n'
    Path(argv.out).write_text(sql, encoding="utf-8")
    print("B62_D1_LEDGER_QUERY=NAMES_ONLY")
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_detail_sql(argv: argparse.Namespace) -> int:
    inventory = read_json(argv.inventory)
    live_tables = snapshot_tables(read_json(argv.snapshot))
    up_to = resolve_up_to(inventory, argv.up_to)
    extra = tuple(json.loads(Path(argv.plan).read_text(encoding="utf-8"))["apply"]) if argv.plan else ()
    tables = [
        _require_identifier(name, "B62_D1_GATE_TABLE_NAME_REJECTED")
        for name in detail_tables(inventory, up_to, live_tables, extra)
    ]
    if not tables:
        Path(argv.out).write_text("", encoding="utf-8")
        print("B62_D1_DETAIL_QUERY=NO_TABLES")
        print("PRODUCTION_MUTATION=0")
        return 0
    blocks = []
    for table in tables:
        blocks.append(f'PRAGMA table_info("{table}");')
        blocks.append(f"SELECT '{table}' AS table_name, COUNT(*) AS row_count FROM \"{table}\";")
    Path(argv.out).write_text("\n".join(blocks) + "\n", encoding="utf-8")
    print(f"B62_D1_DETAIL_TABLES={len(tables)}")
    print("B62_D1_DETAIL_QUERY=METADATA_AND_COUNTS_ONLY")
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_detail_merge(argv: argparse.Namespace) -> int:
    """Join one-block-per-execute detail answers into the block list detail_rows reads.

    Every detail statement runs as its own `--command` execute, so each part
    file answers with exactly one block. Ordering is by the numeric part name
    the workflow wrote, and a missing part is a refusal rather than a short
    block list.
    """

    directory = Path(argv.dir)
    parts = sorted(directory.glob("*.json"), key=lambda path: int(path.stem))
    if not parts:
        raise GateError("B62_D1_GATE_DETAIL_PARTS_MISSING")
    blocks = [{"results": _single_block(read_json(path), "DETAIL")} for path in parts]
    Path(argv.out).write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    print(f"B62_D1_DETAIL_MERGED={len(blocks)}")
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_classify(argv: argparse.Namespace) -> int:
    inventory = read_json(argv.inventory)
    up_to = resolve_up_to(inventory, argv.up_to)
    tables, columns, _, ledger_present = snapshot_rows(
        read_json(argv.snapshot), read_json(argv.probe)
    )
    if ledger_present:
        if not argv.ledger:
            # Reading the ledger is the whole point of a recorded run; a missing
            # response file must not be silently read as "nothing recorded".
            raise GateError("B62_D1_GATE_LEDGER_RESPONSE_REQUIRED")
        ledger = ledger_rows(read_json(argv.ledger))
    else:
        ledger = []
    detail_columns: dict[str, set[str]] | None = None
    counts: dict[str, int] = {}
    require_column_evidence(inventory, up_to, argv.detail)
    if argv.detail:
        wanted = detail_tables(inventory, up_to, tables)
        detail_columns, counts = detail_rows(read_json(argv.detail), wanted)
    result = classify(
        inventory=inventory,
        ledger=ledger,
        tables=tables,
        columns=columns,
        up_to=up_to,
        allow_table_drop=argv.allow_table_drop,
        detail_columns=detail_columns,
    )
    Path(argv.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"B62_D1_PLAN_WINDOW={len(result['window'])}")
    print(f"B62_D1_PLAN_RECORDED={len(result['recorded'])}")
    print(f"B62_D1_PLAN_SEED={len(result['seed'])}")
    print(f"B62_D1_PLAN_APPLY={len(result['apply'])}")
    print(f"B62_D1_PLAN_BASELINE_FIRST_RUN={'YES' if result['baseline_first_run'] else 'NO'}")
    if result["seed_without_object_proof"]:
        print("B62_D1_SEED_WITHOUT_OBJECT_PROOF=" + ",".join(result["seed_without_object_proof"]))
    for key, marker in (
        ("drift", "B62_D1_LEDGER_OBJECT_DRIFT"),
        ("refused_drop_guard", "B62_D1_DROP_GUARD_REFUSED"),
    ):
        if result[key]:
            print(f"{marker}=STOP:{','.join(result[key])}")
    if counts:
        print("B62_D1_ROW_COUNTS_BEFORE=" + ",".join(f"{t}={n}" for t, n in sorted(counts.items())))
    refuse(result)
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_seed_sql(argv: argparse.Namespace) -> int:
    plan = read_json(argv.plan)
    inventory = {item["name"]: item for item in read_json(argv.inventory)}
    statements = []
    for name in plan["seed"]:
        if name not in inventory:
            raise GateError("B62_D1_GATE_SEED_NAME_UNKNOWN")
        escaped = name.replace("'", "''")
        statements.append(
            f'INSERT INTO "{LEDGER_TABLE}" (name)\nvalues (\'{escaped}\');'
        )
    if not statements:
        Path(argv.out).write_text("", encoding="utf-8")
        print("B62_D1_SEED=NOP_NOTHING_UNRECORDED")
        print("PRODUCTION_MUTATION=0")
        return 0
    payload = "\n".join(statements) + "\n"
    upper = payload.upper()
    for forbidden in ("CREATE ", "ALTER ", "DROP ", "INSERT INTO \"users\"", "DELETE ", "UPDATE "):
        if forbidden in upper:
            raise GateError("B62_D1_GATE_SEED_IS_NOT_LEDGER_ONLY")
    Path(argv.out).write_text(payload, encoding="utf-8")
    print(f"B62_D1_SEED_RECORDS={len(statements)}")
    print("B62_D1_SEED_STATEMENTS=LEDGER_INSERT_ONLY")
    print("PRODUCTION_MUTATION=1")
    return 0


def cmd_window(argv: argparse.Namespace) -> int:
    plan = read_json(argv.plan)
    inventory = read_json(argv.inventory)
    by_name = {item["name"]: item for item in inventory}
    directory = Path(argv.dir)
    directory.mkdir(parents=True, exist_ok=True)
    pending = [name for name in plan["apply"] if name in plan["window"]]
    refused = [name for name in pending if by_name[name]["destructive"] and not argv.allow_table_drop]
    if refused:
        print("B62_D1_DROP_GUARD_REFUSED=" + ",".join(refused))
        raise GateError("B62_D1_DROP_GUARD_REFUSED")
    copied = []
    for name in pending:
        source = Path(_app(argv.app)["migrations"]) / name
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != by_name[name]["sha256"]:
            # The checkout moved, or the inventory was built from another tree.
            raise GateError(f"B62_D1_GATE_SOURCE_SHA_DRIFT:{name}")
        target = directory / name
        target.write_bytes(raw)
        if hashlib.sha256(target.read_bytes()).hexdigest() != by_name[name]["sha256"]:
            raise GateError(f"B62_D1_GATE_WINDOW_COPY_UNVERIFIED:{name}")
        copied.append(name)
    print(f"B62_D1_WINDOW_FILES={len(copied)}")
    print("B62_D1_WINDOW_SHA_VERIFIED=PASS")
    print("PRODUCTION_MUTATION=0")
    return 0


def cmd_report(argv: argparse.Namespace) -> int:
    before_tables, before_columns, before_other, before_ledger_present = snapshot_rows(
        read_json(argv.before), read_json(argv.before_probe)
    )
    after_tables, after_columns, after_other, after_ledger_present = snapshot_rows(
        read_json(argv.after), read_json(argv.after_probe)
    )
    delta = schema_diff(
        {"tables": before_tables, "columns": before_columns, "other": before_other},
        {"tables": after_tables, "columns": after_columns, "other": after_other},
    )
    for kind in ("tables", "columns", "other"):
        print(f"B62_D1_SCHEMA_{kind.upper()}_ADDED=" + ",".join(delta[kind]["added"]))
        print(f"B62_D1_SCHEMA_{kind.upper()}_REMOVED=" + ",".join(delta[kind]["removed"]))
    print(
        "B62_D1_LEDGER_PRESENT="
        f"{str(before_ledger_present).lower()}->{str(after_ledger_present).lower()}"
    )
    if argv.detail_before and argv.detail_after:
        inventory = read_json(argv.inventory) if argv.inventory else []
        up_to = resolve_up_to(inventory, argv.up_to) if inventory else "999"
        extra = (
            tuple(json.loads(Path(argv.plan).read_text(encoding="utf-8"))["apply"])
            if argv.plan
            else ()
        )
        before_counts = (
            detail_rows(
                read_json(argv.detail_before),
                detail_tables(inventory, up_to, before_tables, extra),
            )[1]
            if inventory
            else {}
        )
        after_counts = (
            detail_rows(
                read_json(argv.detail_after),
                detail_tables(inventory, up_to, after_tables, extra),
            )[1]
            if inventory
            else {}
        )
        for table in sorted(set(before_counts) | set(after_counts)):
            print(
                f"B62_D1_ROW_COUNT {table}="
                f"{before_counts.get(table, 'ABSENT_BEFORE')}->{after_counts.get(table, 'ABSENT_AFTER')}"
            )
    print("B62_D1_REPORT_ROWS=read_count_metadata_only")
    return 0


COMMANDS = {
    "inventory": cmd_inventory,
    "binding-id": cmd_binding_id,
    "probe": cmd_probe,
    "snapshot-sql": cmd_snapshot_sql,
    "ledger-sql": cmd_ledger_sql,
    "detail-sql": cmd_detail_sql,
    "detail-merge": cmd_detail_merge,
    "classify": cmd_classify,
    "seed-sql": cmd_seed_sql,
    "window": cmd_window,
    "report": cmd_report,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="b62_d1_migrate_gate.py")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, **kwargs: Any) -> Any:
        return sub.add_parser(name, **kwargs)  # type: ignore[arg-type]

    handle = add("inventory")
    handle.add_argument("--app", required=True, choices=sorted(APPS))
    handle.add_argument("--out", required=True)

    handle = add("binding-id")
    handle.add_argument("--settings", required=True)
    handle.add_argument("--binding", required=True)

    handle = add("probe")
    handle.add_argument("--probe", required=True)

    handle = add("snapshot-sql")
    handle.add_argument("--out", required=True)
    handle.add_argument("--probe-out", required=True)

    handle = add("ledger-sql")
    handle.add_argument("--out", required=True)

    handle = add("detail-sql")
    handle.add_argument("--out", required=True)
    handle.add_argument("--inventory", required=True)
    handle.add_argument("--snapshot", required=True)
    handle.add_argument("--up-to", default="")
    handle.add_argument("--plan")

    handle = add("detail-merge")
    handle.add_argument("--dir", required=True)
    handle.add_argument("--out", required=True)

    handle = add("classify")
    handle.add_argument("--app", required=True, choices=sorted(APPS))
    handle.add_argument("--inventory", required=True)
    handle.add_argument("--snapshot", required=True)
    handle.add_argument("--probe", required=True)
    handle.add_argument("--ledger")
    handle.add_argument("--detail")
    handle.add_argument("--up-to", default="", help="empty means the newest file in this checkout")
    handle.add_argument("--allow-table-drop", action="store_true")
    handle.add_argument("--out", required=True)

    handle = add("seed-sql")
    handle.add_argument("--plan", required=True)
    handle.add_argument("--inventory", required=True)
    handle.add_argument("--out", required=True)

    handle = add("window")
    handle.add_argument("--app", required=True, choices=sorted(APPS))
    handle.add_argument("--plan", required=True)
    handle.add_argument("--inventory", required=True)
    handle.add_argument("--dir", required=True)
    handle.add_argument("--allow-table-drop", action="store_true")

    handle = add("report")
    handle.add_argument("--before", required=True)
    handle.add_argument("--before-probe", required=True)
    handle.add_argument("--after", required=True)
    handle.add_argument("--after-probe", required=True)
    handle.add_argument("--detail-before")
    handle.add_argument("--detail-after")
    handle.add_argument("--inventory")
    handle.add_argument("--plan")
    handle.add_argument("--up-to", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GateError, OSError, ValueError, TypeError) as error:
        label = error if isinstance(error, GateError) else f"B62_D1_GATE_FAILED:{type(error).__name__}"
        print(f"B62_D1_GATE=FAIL:{label}", file=sys.stderr)
        raise SystemExit(1) from None
