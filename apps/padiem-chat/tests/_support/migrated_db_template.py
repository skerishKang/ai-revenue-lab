"""Session-scoped, migration-fingerprinted SQLite templates for non-migration tests.

Every subprocess / pytest worker has its own template cache. Build a closed SQLite
file once per distinct migration manifest, copy to a new file or back it up into
a fresh in-memory connection for each test. Do not reuse a writable connection.
Migration tests keep calling the real loader; this helper is for ordinary fixtures.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Literal

DEFAULT_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
_TEMPLATE_DIR: tempfile.TemporaryDirectory[str] | None = None
_TEMPLATES: dict[tuple[str, str, str], tuple[Path, int]] = {}
_LOCK = threading.RLock()


def _files(migrations_dir: Path, excluded: tuple[str, ...]) -> tuple[Path, ...]:
    files = tuple(
        path for path in sorted(Path(migrations_dir).glob("*.sql"))
        if not any(path.name.startswith(prefix) for prefix in excluded)
    )
    if not files:
        raise ValueError("No Chat migration SQL files were found")
    return files


def _content_hash(files: tuple[Path, ...]) -> str:
    # Include *both* the ordered manifest and each file's actual bytes. A rename,
    # addition, removal, or in-place edit invalidates the cached schema template.
    digest = hashlib.sha256()
    for path in files:
        body = path.read_bytes()
        name = path.name.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return digest.hexdigest()


def migrated_template(
    migrations_dir: Path = DEFAULT_MIGRATIONS,
    *,
    loader: Literal["scripts", "local_cpython"] = "scripts",
    exclude_prefixes: tuple[str, ...] = (),
) -> tuple[Path, int]:
    """Return (closed file, foreign_keys pragma) for the current migration bytes."""
    if loader == "local_cpython" and exclude_prefixes:
        raise ValueError("local_cpython loader must use the full migration set")
    migrations_dir = Path(migrations_dir).resolve()
    files = _files(migrations_dir, tuple(exclude_prefixes))
    fingerprint = _content_hash(files)
    key = (str(migrations_dir), loader, fingerprint)
    global _TEMPLATE_DIR
    with _LOCK:
        cached = _TEMPLATES.get(key)
        if cached is not None:
            return cached
        if _TEMPLATE_DIR is None:
            _TEMPLATE_DIR = tempfile.TemporaryDirectory(prefix="padiem-chat-test-db-")
        template = Path(_TEMPLATE_DIR.name) / f"{len(_TEMPLATES):04d}-{fingerprint}.sqlite3"
        connection = sqlite3.connect(template, isolation_level=None)
        # The template is private disposable test setup; avoid fsync on 142 DDL scripts.
        # A cloned test connection keeps its normal synchronous setting.
        connection.execute("PRAGMA synchronous=OFF")
        try:
            if loader == "scripts":
                for sql in files:
                    connection.executescript(sql.read_text(encoding="utf-8"))
            elif loader == "local_cpython":
                # Preserve the local loader's migration ledger and initial rows.
                from app.local_cpython import apply_migrations
                applied = apply_migrations(connection, migrations_dir)
                if applied != len(files):
                    raise AssertionError("Fresh local template did not apply every migration")
            else:
                raise ValueError(f"Unknown migration loader: {loader}")
            foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise AssertionError(f"Invalid SQL migration template: {integrity}")
            connection.execute("PRAGMA journal_mode=DELETE")
        except BaseException:
            connection.close()
            template.unlink(missing_ok=True)
            raise
        else:
            connection.close()
        record = (template, foreign_keys)
        _TEMPLATES[key] = record
        return record


def copy_migrated_database(
    path: Path,
    migrations_dir: Path = DEFAULT_MIGRATIONS,
    *,
    loader: Literal["scripts", "local_cpython"] = "scripts",
    exclude_prefixes: tuple[str, ...] = (),
) -> int:
    """Copy the immutable migrated file before a test opens its own SQLite handle."""
    template, foreign_keys = migrated_template(
        migrations_dir, loader=loader, exclude_prefixes=exclude_prefixes,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        raise FileExistsError(f"Refusing to overwrite an existing test DB: {path}")
    shutil.copyfile(template, path)
    return foreign_keys


def migrated_connection(
    path: str | Path = ":memory:",
    migrations_dir: Path = DEFAULT_MIGRATIONS,
    *,
    loader: Literal["scripts", "local_cpython"] = "scripts",
    exclude_prefixes: tuple[str, ...] = (),
    isolation_level: str | None = None,
    check_same_thread: bool = True,
    timeout: float = 30,
    row_factory=None,
) -> sqlite3.Connection:
    """Fresh isolated connection, file-copy for paths and SQLite backup for :memory:."""
    template, foreign_keys = migrated_template(
        migrations_dir, loader=loader, exclude_prefixes=exclude_prefixes,
    )
    if str(path) == ":memory:":
        connection = sqlite3.connect(
            ":memory:", isolation_level=isolation_level,
            check_same_thread=check_same_thread, timeout=timeout,
        )
        with closing(sqlite3.connect(template)) as source:
            source.backup(connection)
    else:
        copy_migrated_database(
            Path(path), migrations_dir, loader=loader,
            exclude_prefixes=exclude_prefixes,
        )
        connection = sqlite3.connect(
            str(path), isolation_level=isolation_level,
            check_same_thread=check_same_thread, timeout=timeout,
        )
    connection.execute(f"PRAGMA foreign_keys={foreign_keys}")
    if row_factory is not None:
        connection.row_factory = row_factory
    return connection


def fill_empty_connection(
    connection: sqlite3.Connection,
    migrations_dir: Path = DEFAULT_MIGRATIONS,
    *,
    loader: Literal["scripts", "local_cpython"] = "scripts",
) -> int:
    """Back up a file template into an empty in-memory D1 adapter connection."""
    template, foreign_keys = migrated_template(migrations_dir, loader=loader)
    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view','index','trigger')"
    ).fetchone()
    if existing is not None or connection.in_transaction:
        raise ValueError("Migrated template can only fill an unused SQLite connection")
    with closing(sqlite3.connect(template)) as source:
        source.backup(connection)
    connection.execute(f"PRAGMA foreign_keys={foreign_keys}")
    return len(_files(migrations_dir, ()))


def apply_copied_migrations(
    connection: sqlite3.Connection,
    migrations_dir: Path = DEFAULT_MIGRATIONS,
) -> int:
    """Fixture substitute for apply_migrations on an *empty* connection.

    If a test intentionally constructed existing schema or rows, retain the real
    incremental loader's semantics rather than overwrite preexisting state.
    """
    existing = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view','index','trigger')"
    ).fetchone()
    if existing is not None or connection.in_transaction:
        from app.local_cpython import apply_migrations
        return apply_migrations(connection, migrations_dir)
    return fill_empty_connection(connection, migrations_dir, loader="local_cpython")


def close_templates() -> None:
    """Release session-owned immutable template files after the last test."""
    global _TEMPLATE_DIR
    with _LOCK:
        _TEMPLATES.clear()
        if _TEMPLATE_DIR is not None:
            _TEMPLATE_DIR.cleanup()
            _TEMPLATE_DIR = None
