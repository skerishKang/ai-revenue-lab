"""Account-deletion survey guard (internal audit follow-up, 2026-11-11).

The 2026-11-03 route shipped with a hand-maintained table list, and the
operations doc's own survey row (``claw_task_alert``) proved the two can drift:
the doc promised a deletion the code never performed. This guard closes that
gap from both sides, mechanically:

1. migrations -> live user/subject-keyed tables. A new migration that adds a
   ``user_id``/``member_id``/``owner_id``/``product_user_id`` column (or a
   subject-family column) makes this suite fail until the table joins a delete
   list or ``_DELETION_EXCEPTIONS`` with a reason;
2. operations doc -> code. A table the doc says is deleted but the code does
   not delete fails, and so does the reverse;
3. code -> schema. Every listed table and key column must exist in the
   migration-derived schema;
4. the subject-keyed statements actually delete the account's claw
   automation chain and BookAI rows, and no one else's.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.account_deletion import (
    _DELETION_EXCEPTIONS,
    _IDENTITY_SCRUBBED_USER_KEYED_TABLES,
    _SUBJECT_KEYED_TABLES,
    _USER_KEYED_TABLES,
    _delete_batch,
)

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent.parent
OPERATIONS_DOC = (
    REPO_ROOT / "docs" / "operations" / "ACCOUNT_DELETION_20261103.md"
)

USER_KEY_COLUMNS = {"user_id", "member_id", "owner_id", "product_user_id"}
SUBJECT_KEY_COLUMNS = {
    "subject", "canonical_subject_id", "provider_subject",
    "account_ref", "account_id", "approved_by", "workspace_ref", "owner_subject",
}
#: Tables the batch handles outside the delete lists, plus the audit INSERT.
SPECIAL_HANDLED = frozenset({"users", "account_deletion_audit"})


# ---------------------------------------------------------------------------
# Mechanical migration survey (the same traversal the 2026-11-03 doc used,
# re-run on every test execution instead of trusted as prose).
# ---------------------------------------------------------------------------


def _strip_sql_comments(sql: str) -> str:
    out: list[str] = []
    in_string = None
    index, length = 0, len(sql)
    while index < length:
        char = sql[index]
        if in_string:
            out.append(char)
            if char == in_string:
                in_string = None
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if sql.startswith("/*", index):
            closing = sql.find("*/", index + 2)
            index = length if closing < 0 else closing + 2
            continue
        if char in ("'", '"'):
            in_string = char
        out.append(char)
        index += 1
    return "".join(out)


def _split_statements(sql: str) -> list[str]:
    statements, buffer, depth, in_string = [], [], 0, None
    for char in sql:
        if in_string:
            buffer.append(char)
            if char == in_string:
                in_string = None
            continue
        if char in ("'", '"'):
            in_string = char
            buffer.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == ";" and depth <= 0:
            statements.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    if buffer:
        statements.append("".join(buffer))
    return [item for item in statements if item.strip()]


_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?\s*\(", re.I
)
_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+[\"'`]?(\w+)[\"'`]?\s+ADD\s+(?:COLUMN\s+)?[\"'`]?(\w+)[\"'`]?", re.I
)
_RENAME = re.compile(
    r"ALTER\s+TABLE\s+[\"'`]?(\w+)[\"'`]?\s+RENAME\s+TO\s+[\"'`]?(\w+)[\"'`]?", re.I
)
_DROP = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[\"'`]?(\w+)[\"'`]?", re.I)
_COLUMN_LINE = re.compile(r"^\s*[\"'`]?(\w+)[\"'`]?\s+(?:TEXT|INTEGER|BLOB|REAL|NUMERIC)", re.I)


def _live_tables() -> dict[str, list[str]]:
    """Every live Chat-DB table with its full column list."""
    tables: dict[str, dict] = {}
    order: list[str] = []
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        migration = path.stem
        for statement in _split_statements(_strip_sql_comments(path.read_text(encoding="utf-8"))):
            created = _CREATE.search(statement)
            if created is not None:
                name = created.group(1)
                columns: dict[str, str] = {}
                for line in statement[created.end(): statement.rfind(")")].splitlines():
                    column = _COLUMN_LINE.match(line)
                    if column is None or re.match(
                        r"^\s*(PRIMARY|UNIQUE|CHECK|FOREIGN|CONSTRAINT)\b",
                        line.strip(), re.I,
                    ):
                        continue
                    columns.setdefault(column.group(1), migration)
                if name in tables:
                    tables[name]["columns"].update(columns)
                else:
                    tables[name] = {"columns": columns, "migration": migration}
                    order.append(name)
                continue
            added = _ADD_COLUMN.search(statement)
            if added is not None and added.group(1) in tables:
                tables[added.group(1)]["columns"].setdefault(added.group(2), migration)
            renamed = _RENAME.search(statement)
            if renamed is not None and renamed.group(1) in tables:
                tables[renamed.group(2)] = tables.pop(renamed.group(1))
                order = [renamed.group(2) if item == renamed.group(1) else item for item in order]
            dropped = _DROP.search(statement)
            if dropped is not None and dropped.group(1) in tables:
                tables.pop(dropped.group(1), None)
                order = [item for item in order if item != dropped.group(1)]
    return {name: list(tables[name]["columns"]) for name in order}


def _live_tables_with_user_keys() -> dict[str, list[str]]:
    """The subset whose columns name a person (directly or by subject)."""
    return {
        name: [column for column in cols
               if column in USER_KEY_COLUMNS or column in SUBJECT_KEY_COLUMNS]
        for name, cols in _live_tables().items()
        if any(column in USER_KEY_COLUMNS or column in SUBJECT_KEY_COLUMNS
               for column in cols)
    }


def _code_delete_names() -> set[str]:
    return (
        {table for table, _ in _USER_KEYED_TABLES}
        | {table for table, _ in _SUBJECT_KEYED_TABLES}
        | {table for table, _ in _IDENTITY_SCRUBBED_USER_KEYED_TABLES}
    )


def _doc_declared_tables() -> set[str]:
    """Every table name the operations doc names inside its survey (section 2)."""
    text = OPERATIONS_DOC.read_text(encoding="utf-8")
    survey = text.split("## 2. 사용자 데이터 테이블 전수 조사")[1].split("## 3.")[0]
    names = set()
    for line in survey.splitlines():
        if not line.startswith("|"):
            continue
        first = line.strip("|").split("|")[0].strip().strip("`")
        if re.fullmatch(r"[a-z][a-z0-9_]*", first):
            names.add(first)
    return names


# ---------------------------------------------------------------------------
# 1. migrations -> delete lists or reasoned exceptions.
# ---------------------------------------------------------------------------


def test_every_live_user_keyed_table_is_deleted_or_exceptioned_with_a_reason():
    live = _live_tables_with_user_keys()
    assert live, "survey found no user-keyed tables; the parser is broken"
    covered = set(_code_delete_names()) | set(_DELETION_EXCEPTIONS)
    uncovered = sorted(set(live) - covered)
    assert not uncovered, (
        "새 사용자 키 표가 마이그레이션에 생겼다면 account_deletion 삭제 목록에 넣거나 "
        f"_DELETION_EXCEPTIONS에 남기는 이유를 적어야 한다: {uncovered}"
    )


def test_every_exception_names_a_real_table_and_a_reason():
    live = _live_tables_with_user_keys()
    covered = set(_code_delete_names())
    for table, reason in _DELETION_EXCEPTIONS.items():
        assert isinstance(reason, str) and reason.strip(), table
        # An exception must describe a table that exists and is genuinely not
        # deleted by the simple lists; a stale entry would hide a deletion.
        assert table in live, (
            f"_DELETION_EXCEPTIONS[{table!r}] names a table the migrations "
            "no longer define; remove the stale entry"
        )
        assert table not in covered, (
            f"_DELETION_EXCEPTIONS[{table!r}] duplicates an entry in the "
            "delete lists"
        )


# ---------------------------------------------------------------------------
# 2. operations doc <-> code, both directions.
# ---------------------------------------------------------------------------


def test_operations_doc_promises_match_the_code_lists():
    doc = _doc_declared_tables()
    assert doc, "could not read table names from the operations doc survey"
    handled = set(_code_delete_names()) | set(_DELETION_EXCEPTIONS) | SPECIAL_HANDLED
    missing = sorted(doc - handled)
    assert not missing, (
        "운영 문서가 지운다고 적었지만 코드가 지우지 않는 표: "
        f"{missing} — 삭제 목록에 넣거나 문서와 예외 목록을 고쳐라"
    )


def test_code_lists_are_named_in_the_operations_doc():
    doc = _doc_declared_tables()
    handled = set(_code_delete_names()) | set(_DELETION_EXCEPTIONS) | SPECIAL_HANDLED
    undeclared = sorted(handled - doc)
    assert not undeclared, (
        "코드가 지우는 표가 운영 문서 전수표에 없다: "
        f"{undeclared} — 문서 2장 표에 추가해라"
    )


# ---------------------------------------------------------------------------
# 3. code -> migration-derived schema.
# ---------------------------------------------------------------------------


def test_delete_lists_never_name_a_table_or_column_the_schema_lacks():
    live = _live_tables()
    for table, where in (*_USER_KEYED_TABLES, *_SUBJECT_KEYED_TABLES,
                         *_IDENTITY_SCRUBBED_USER_KEYED_TABLES):
        assert table in live, f"delete list names unknown table {table}"
        selector = where.split(" IN (")[0].split(" = ")[0].strip()
        column = selector.strip()
        assert column in live[table], (
            f"{table}: delete key {column!r} is not a live column"
        )


# ---------------------------------------------------------------------------
# 4. the subject-keyed statements delete the account's claw chain.
# ---------------------------------------------------------------------------


class _Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _Statement(self.db, self.sql, params)

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return {"changes": cursor.rowcount}


class _MiniD1:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, sql):
        return _Statement(self, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                self.conn.execute(statement.sql, statement.params)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


def test_subject_keyed_statements_clear_the_claw_automation_chain():
    import sqlite3

    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    from types import SimpleNamespace

    from test_6446_account_isolation_sweep import apply_all_migrations

    apply_all_migrations(SimpleNamespace(conn=conn))
    conn.execute("PRAGMA foreign_keys=OFF")
    now = "2026-11-11T00:00:00Z"
    mine, other = "sub_owner", "sub_stranger"
    for account, prefix in ((mine, "a"), (other, "b")):
        conn.execute(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name,"
            " picture_url, created_at, updated_at)"
            " VALUES (?, 'google', ?, ?, '', '', ?, ?)",
            (f"usr_{prefix}0000000000000000000000000000",
             "shared:" + account, f"{prefix}@example.test", now, now),
        )
        for workspace in (f"tenant_{prefix}1", f"tenant_{prefix}2"):
            rule = f"rule_{prefix}_{workspace}"
            conn.execute(
                "INSERT INTO claw_rules (rule_id, workspace_id, name, schedule_kind,"
                " schedule_expression, schedule_timezone, target_source, output_type,"
                " enabled, notification_channels, created_at, updated_at,"
                " canonical_subject_id) VALUES (?,?,'n','daily','0 9 * * *','UTC',"
                "'inbox','message',1,'[]',?,?,?)",
                (rule, workspace, now, now, account),
            )
            run = f"run_{prefix}_{workspace}"
            conn.execute(
                "INSERT INTO claw_runs (run_id, workspace_id, rule_id, status,"
                " scheduled_time, started_at) VALUES (?,?,?,'PENDING',?,?)",
                (run, workspace, rule, now, now),
            )
            conn.execute(
                "INSERT INTO claw_occurrences (occurrence_key, run_id, workspace_id)"
                " VALUES (?,?,?)",
                (f"occ_{prefix}_{workspace}", run, workspace),
            )
            conn.execute(
                "INSERT INTO claw_proposals (proposal_id, workspace_id, rule_id, channel,"
                " title, summary, created_at) VALUES (?,?,?,'email','t','s',?)",
                (f"prop_{prefix}_{workspace}", workspace, rule, now),
            )
    conn.execute(
        "INSERT INTO claw_proposals (proposal_id, workspace_id, rule_id, channel,"
        " title, summary, approved_by, created_at) VALUES"
        " ('prop_approved_by_mine', 'tenant_b1', 'rule_b_tenant_b1', 'email', 't', 's', ?, ?)",
        (mine, now),
    )
    conn.execute(
        "INSERT INTO bookai_records (subject, record_id, book_id, locator, kind,"
        " payload, updated_at) VALUES (?, 'rec-mine', 'book-1', 'p.1', 'note', '{}', 1)",
        (mine,),
    )

    import asyncio

    async def run_batch():
        await _MiniD1(conn).batch(
            _delete_batch(
                _MiniD1(conn), "usr_a0000000000000000000000000000",
                bookai_subjects=(mine,),
            )
        )

    asyncio.run(run_batch())

    assert conn.execute("SELECT COUNT(*) FROM claw_rules").fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_rules WHERE canonical_subject_id = ?", (mine,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_runs WHERE run_id LIKE 'run_a%'", ()
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_runs WHERE run_id LIKE 'run_b%'", ()
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_occurrences WHERE occurrence_key LIKE 'occ_a%'", ()
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_occurrences WHERE occurrence_key LIKE 'occ_b%'", ()
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_proposals WHERE proposal_id LIKE 'prop_a%'", ()
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_proposals WHERE approved_by = ?", (mine,)
    ).fetchone()[0] == 0
    # The stranger's rule chain and its proposals survive untouched.
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_proposals WHERE proposal_id LIKE 'prop_b%'", ()
    ).fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM bookai_records").fetchone()[0] == 0
