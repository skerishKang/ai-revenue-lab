import os
import sqlite3
from pathlib import Path


class MigrationError(RuntimeError):
    def __init__(self, filename: str, original_error: sqlite3.Error):
        self.filename = filename
        self.original_error = original_error
        super().__init__(f"migration {filename} failed: {original_error}")


def get_connection(db_path: str) -> sqlite3.Connection:
    db_path = str(db_path)
    if db_path != ":memory:":
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def iter_sql_statements(sql: str):
    buffer: list[str] = []
    for line in sql.splitlines(keepends=True):
        buffer.append(line)
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            stmt = candidate.strip()
            if stmt:
                yield stmt
            buffer.clear()
    remainder = "".join(buffer).strip()
    if remainder:
        raise ValueError(f"incomplete SQL statement near: {remainder[:80]}")


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str = "migrations",
) -> list[str]:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    applied = set()
    for row in conn.execute("SELECT version FROM schema_migrations"):
        applied.add(row["version"])

    migrations_path = Path(migrations_dir)
    files = sorted(migrations_path.glob("*.sql"))
    applied_versions: list[str] = []

    for f in files:
        filename = f.name
        if filename in applied:
            continue

        sql = f.read_text()

        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in iter_sql_statements(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (filename,),
            )
            conn.commit()
            applied_versions.append(filename)
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationError(filename, exc) from exc

    return applied_versions
