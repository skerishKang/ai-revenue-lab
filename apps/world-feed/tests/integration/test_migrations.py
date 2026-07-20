from app.db import apply_migrations, get_connection


def test_migrations_apply_on_fresh_db(conn):
    rows = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [r["version"] for r in rows] == ["001_initial.sql"]


def test_migrations_are_idempotent(db_path):
    conn = get_connection(db_path)
    try:
        applied1 = apply_migrations(conn, "migrations")
        applied2 = apply_migrations(conn, "migrations")
    finally:
        conn.close()
    assert applied1 == ["001_initial.sql"]
    assert applied2 == []


def test_required_tables_exist(conn):
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for t in (
        "sources",
        "canonical_events",
        "readers",
        "feedback",
        "briefs",
        "generation_runs",
        "pilot_evidence",
        "schema_migrations",
    ):
        assert t in tables


def test_canonical_key_unique_constraint(db_path):
    conn = get_connection(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS canonical_events ("
            "id TEXT PRIMARY KEY, canonical_key TEXT UNIQUE NOT NULL)"
        )
        conn.execute(
            "INSERT INTO canonical_events VALUES ('a', 'k')"
        )
        try:
            conn.execute("INSERT INTO canonical_events VALUES ('b', 'k')")
            assert False, "UNIQUE constraint should have fired"
        except Exception:
            pass
    finally:
        conn.close()
