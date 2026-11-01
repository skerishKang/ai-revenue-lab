"""#5881 follow-on — the queue database must survive being opened a second time.

The 2026-10-30 cutover attempt showed what the ledger-less version of schema.apply() meant
in practice: the queue could start only on a database it had just created, so the first
restart after the state copy crash-looped on `duplicate column name: kind` and the door
served nobody. These tests pin the opposite behaviour — a restart runs no DDL at all, a
database built without the ledger is backfilled rather than replayed, a file that has not
run yet still runs, a half-run file cannot wedge the next start, and a database that is
missing a column says so instead of failing on its first real call.
"""
from __future__ import annotations

import pathlib
import shutil
import sqlite3
import sys

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

import schema  # noqa: E402
from app.d1_sqlite import connect  # noqa: E402

NAMES = schema.QUEUE_MIGRATIONS
USER = "usr_" + "b" * 32


class _Counting:
    """Forwards execute() and remembers what was run, so "no DDL on restart" is checkable."""

    def __init__(self, connection):
        self.connection = connection
        self.statements: list[str] = []

    def execute(self, sql, *values):
        self.statements.append(" ".join(str(sql).split())[:120])
        return self.connection.execute(sql, *values)


def _migrations(tmp_path):
    """A copy of the nine files, so a test can rewrite one; the repository's stay untouched."""

    target = tmp_path / "migrations"
    target.mkdir()
    for name in NAMES:
        shutil.copyfile(schema.MIGRATION_DIR / name, target / name)
    return target


def _open(tmp_path, name="queue.sqlite3"):
    return connect(str(tmp_path / name))


def _raw_run(connection, names):
    """The ledger-less behaviour — used to build "a database from before the ledger". """

    for name in names:
        connection.executescript((schema.MIGRATION_DIR / name).read_text(encoding="utf-8"))


def _ledger_names(connection):
    return {
        str(row[0])
        for row in connection.execute("select name from %s" % schema.LEDGER_TABLE)
    }


def _sha(text):
    return (text * 64)[:64]


def _seed_pairing_code(connection):
    connection.execute(
        "insert into pc_pairing_codes (code_id, code_sha256, tag_sha256, user_id, state,"
        " mesh_node_id, issued_at, expires_at) values (?, ?, ?, ?, 'pending', ?,"
        " '2026-10-30T00:00:00Z', '2026-10-30T00:30:00Z')",
        ("pc_1", _sha("a"), _sha("b"), USER, "node_1"),
    )


def _ddl(statements):
    """Migration DDL only — the ledger table's own creation is not a replay."""

    return [
        s
        for s in statements
        if schema.LEDGER_TABLE not in s
        and ("ADD COLUMN" in s or "DROP TABLE" in s or "RENAME TO" in s or "CREATE TABLE" in s)
    ]


def test_reopening_a_database_replays_no_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "MIGRATION_DIR", _migrations(tmp_path))
    connection = _open(tmp_path)
    schema.apply(connection)
    connection.close()

    second = _Counting(_open(tmp_path))
    schema.apply(second)

    assert _ddl(second.statements) == []
    assert _ledger_names(second.connection) == set(NAMES)


def test_a_database_built_without_the_ledger_is_backfilled_not_replayed(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "MIGRATION_DIR", _migrations(tmp_path))
    connection = _open(tmp_path)
    _raw_run(connection, NAMES)
    _seed_pairing_code(connection)

    schema.apply(connection)  # without the backfill: "duplicate column name: kind"

    states = [
        str(row[0])
        for row in connection.execute("select state from pc_pairing_codes where code_id = 'pc_1'")
    ]
    assert states == ["pending"]
    assert _ledger_names(connection) == set(NAMES)


def test_a_migration_that_has_never_run_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "MIGRATION_DIR", _migrations(tmp_path))
    connection = _open(tmp_path)
    try:
        schema.apply(connection, migrations=NAMES[:-1])
    except schema.QueueSchemaIncomplete:
        pass  # The final migration owns a required table/column.
    assert NAMES[-1] not in _ledger_names(connection)

    counting = _Counting(connection)
    schema.apply(counting)

    assert NAMES[-1] in _ledger_names(counting.connection)
    columns = {
        str(r[1]) for r in counting.connection.execute("pragma table_info(oracle_mesh_dispatch)")
    }
    assert "claimed_until" in columns
    assert connection.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 0
    replayed = [s for s in counting.statements if "mesh_device_drives" not in s]
    assert _ddl(replayed) == []


def test_086_on_a_pre_ledger_database_does_not_rebuild_or_erase_old_tables(tmp_path):
    connection = _open(tmp_path)
    _raw_run(connection, NAMES[:-1])
    _seed_pairing_code(connection)
    counting = _Counting(connection)
    schema.apply(counting)
    assert _ledger_names(connection) == set(NAMES)
    assert connection.execute("SELECT state FROM pc_pairing_codes").fetchone()[0] == "pending"
    assert connection.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 0
    assert not any("DROP TABLE" in sql or "RENAME TO" in sql for sql in counting.statements)


def test_a_file_rewritten_after_it_ran_is_skipped_and_named(tmp_path, monkeypatch, capsys):
    migrations = _migrations(tmp_path)
    monkeypatch.setattr(schema, "MIGRATION_DIR", migrations)
    connection = _open(tmp_path)
    schema.apply(connection)
    before = str(
        connection.execute(
            "select sha256 from %s where name = ?" % schema.LEDGER_TABLE, (NAMES[1],)
        ).fetchone()[0]
    )

    (migrations / NAMES[1]).write_text(
        "-- rewritten after it was applied\n"
        "ALTER TABLE oracle_mesh_dispatch ADD COLUMN kind TEXT NOT NULL DEFAULT 'read';\n",
        encoding="utf-8",
    )
    schema.apply(connection)  # D1 skips an applied migration; so does the queue

    assert NAMES[1] in capsys.readouterr().err
    after = str(
        connection.execute(
            "select sha256 from %s where name = ?" % schema.LEDGER_TABLE, (NAMES[1],)
        ).fetchone()[0]
    )
    assert after == before


def test_a_statement_that_fails_for_a_real_reason_raises_and_is_not_recorded(
    tmp_path, monkeypatch
):
    migrations = _migrations(tmp_path)
    monkeypatch.setattr(schema, "MIGRATION_DIR", migrations)
    (migrations / NAMES[0]).write_text(
        "CREATE TABLE oracle_mesh_dispatch (dispatch_id TEXT);\n"
        "CREATE INDEX bad_index ON oracle_mesh_dispatch (user_id);\n",
        encoding="utf-8",
    )
    connection = _open(tmp_path)
    try:
        schema.apply(connection)
    except sqlite3.OperationalError as exc:
        assert not schema._already_satisfied(str(exc))  # a real failure, not a repeat
    else:
        raise AssertionError("broken SQL must not be tolerated")
    assert NAMES[0] not in _ledger_names(connection)


def test_a_file_interrupted_halfway_does_not_wedge_the_next_start(tmp_path, monkeypatch):
    migrations = _migrations(tmp_path)
    monkeypatch.setattr(schema, "MIGRATION_DIR", migrations)
    connection = _open(tmp_path)
    _raw_run(connection, [NAMES[0]])
    for statement in schema._statements((migrations / NAMES[1]).read_text(encoding="utf-8")):
        connection.execute(statement)
        break  # 048's first ALTER landed before the process died; the ledger never saw 048
    connection.close()

    reopened = _open(tmp_path)
    schema.apply(reopened)

    assert NAMES[1] in _ledger_names(reopened)
    columns = {str(r[1]) for r in reopened.execute("pragma table_info(oracle_mesh_dispatch)")}
    assert {"kind", "command_text"} <= columns


def test_a_half_database_says_so_instead_of_failing_on_its_first_call(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "MIGRATION_DIR", _migrations(tmp_path))
    connection = _open(tmp_path)
    try:
        schema.apply(connection, migrations=())
    except schema.QueueSchemaIncomplete as exc:
        assert "oracle_mesh_dispatch" in str(exc)
        assert "queue database is missing" in str(exc)
    else:
        raise AssertionError("an empty database must be refused")
