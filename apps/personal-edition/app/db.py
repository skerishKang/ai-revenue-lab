import importlib.util
import os
import re
import sqlite3
from pathlib import Path

# A Python migration is any file named like `NNN_description.py` in the
# migrations directory. It must define ``migrate(conn) -> None``. This lets a
# migration branch on the existing SQLite column layout (which plain SQL cannot
# do safely) while still being tracked by the same schema_migrations table.
_PY_MIGRATION_RE = re.compile(r"^\d+_.*\.py$")


def _is_migration_py(name: str) -> bool:
    return name.endswith(".py") and _PY_MIGRATION_RE.match(name) is not None


def _run_python_migration(path: Path, conn: sqlite3.Connection) -> None:
    module_name = "kilo_migration_" + path.stem
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise MigrationError(
            path.name, RuntimeError("cannot load migration module")
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "migrate"):
        raise MigrationError(
            path.name,
            RuntimeError("migration module must define migrate(conn)"),
        )
    module.migrate(conn)


class MigrationError(RuntimeError):
    def __init__(self, filename: str, original_error: Exception):
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


def is_sql_trivia(value: str) -> bool:
    i = 0
    while i < len(value):
        ch = value[i]
        if ch in (" ", "\t", "\n", "\r"):
            i += 1
        elif ch == "-" and i + 1 < len(value) and value[i + 1] == "-":
            i += 2
            while i < len(value) and value[i] not in ("\n", "\r"):
                i += 1
        elif ch == "/" and i + 1 < len(value) and value[i + 1] == "*":
            i += 2
            closed = False
            while i + 1 < len(value):
                if value[i] == "*" and value[i + 1] == "/":
                    closed = True
                    i += 2
                    break
                i += 1
            if not closed:
                return False
        else:
            return False
    return True


def iter_sql_statements(sql: str):
    buffer: list[str] = []
    for ch in sql:
        buffer.append(ch)
        if ch == ";":
            candidate = "".join(buffer)
            if sqlite3.complete_statement(candidate):
                stmt = candidate.strip()
                if stmt:
                    yield stmt
                buffer.clear()
    remainder = "".join(buffer)
    if remainder.strip() and not is_sql_trivia(remainder):
        raise ValueError(f"incomplete SQL statement near: {remainder[:80]}")


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str = "migrations",
) -> list[str]:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        )
    """)
    conn.commit()

    applied = set()
    for row in conn.execute("SELECT version FROM schema_migrations"):
        applied.add(row["version"])

    migrations_path = Path(migrations_dir)
    sql_files = sorted(migrations_path.glob("*.sql"))
    py_files = sorted(
        p for p in migrations_path.glob("*.py") if _is_migration_py(p.name)
    )
    files = sorted(sql_files + py_files, key=lambda p: p.name)
    applied_versions: list[str] = []

    for f in files:
        filename = f.name
        if filename in applied:
            continue

        if filename.endswith(".sql"):
            try:
                sql = f.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise MigrationError(filename, exc) from exc

            try:
                statements = list(iter_sql_statements(sql))
            except ValueError as exc:
                raise MigrationError(filename, exc) from exc

            try:
                conn.execute("BEGIN IMMEDIATE")
                for stmt in statements:
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
        else:
            try:
                conn.execute("BEGIN IMMEDIATE")
                _run_python_migration(f, conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)",
                    (filename,),
                )
                conn.commit()
                applied_versions.append(filename)
            except Exception as exc:
                conn.rollback()
                raise MigrationError(filename, exc) from exc

    return applied_versions
