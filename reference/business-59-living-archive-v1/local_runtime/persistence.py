"""Durable local persistence primitives for the B59 Living Archive runtime.

This module is SQLite + filesystem plumbing only; it holds no product policy.
It keeps the three authoritative layers of ``PRODUCT_CONTRACT.md`` physically
separate:

1. **original source** — immutable ``sources`` rows plus byte-for-byte blobs
   under ``<root>/originals/<source_id>/v<version>.<ext>``. A blob is written
   once per ``(source_id, source_version)`` and is never rewritten by
   re-indexing; database triggers reject ``UPDATE``/``DELETE`` on ``sources``.
2. **derived / index data** — ``derived_artifacts`` and ``derived_anchors``
   rows. Fully regenerable and deletable without touching the other layers.
3. **user records** — ``user_*`` rows. Never written by the re-index path.

Conventions deliberately mirror ``apps/living-fiction/app/db.py`` (create the
parent directory, ``row_factory = sqlite3.Row``, ``PRAGMA foreign_keys = ON``,
an applied-version ``schema_migrations`` table driven by ordered SQL) and
``apps/living-fiction/app/database/sqlite.py`` without importing that package.
Standard library only; no network access is possible from this module.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence

from .source_index import ImportFailure


DEFAULT_DB_FILENAME = "living_archive.sqlite3"
ORIGINALS_DIRNAME = "originals"

# Original blobs never use the raw filename; only a whitelisted suffix derived
# from the validated extension is appended to the source-id/version path.
BLOB_SUFFIX_BY_EXTENSION = {
    ".txt": ".txt",
    ".md": ".md",
    ".markdown": ".md",
    ".pdf": ".pdf",
}
FALLBACK_BLOB_SUFFIX = ".bin"

MAX_FILENAME_LENGTH = 255
# Characters Windows forbids in a filename plus ASCII control characters.
_FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)

_UNSAFE_FILENAME = "UNSAFE_FILENAME"
_INVALID_FILENAME = "INVALID_FILENAME"


class MigrationError(RuntimeError):
    """A migration failed; the database is left at its previous version."""

    def __init__(self, version: str, original_error: Exception) -> None:
        self.version = version
        self.original_error = original_error
        super().__init__(f"migration {version} failed: {original_error}")


class ArchiveError(ImportFailure):
    """A bounded, non-secret failure from the durable runtime.

    The message *is* the safe error code (for example ``ORIGINAL_WRITE_FAILED``),
    so nothing here can leak file content, paths or credentials. ``retryable``
    records whether re-running the same operation could plausibly succeed.
    """

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class UnsafeSourcePath(ArchiveError):
    """A filename or path that could escape the store, rejected before storage."""


class StorageFailure(ArchiveError):
    """The original bytes could not be written to local storage."""

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code, retryable=retryable)


class OriginalUnreadable(ArchiveError):
    """The stored original can no longer be read back."""


class OriginalIntegrityError(ArchiveError):
    """The stored original no longer matches its recorded checksum."""


def error_code(error: BaseException) -> str:
    """Return the safe code for *error*, never a raw exception payload."""
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    message = str(error)
    return message if message else type(error).__name__.upper()


def is_retryable(error: BaseException) -> bool:
    return bool(getattr(error, "retryable", False))


# --------------------------------------------------------------------------- #
# Ordered SQL + applied-version migration runner
# --------------------------------------------------------------------------- #

def _migrations() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return ordered ``(version, statements)`` migrations.

    Each migration is a tuple of complete SQL statements so no SQL parsing is
    needed; ordering is the declared tuple order.
    """
    stage_names = (
        "'RECEIVED','VALIDATED','STORED','TEXT_EXTRACTED','PREVIEW_RENDERED',"
        "'INDEXED','READY','PARTIAL','FAILED'"
    )
    artifact_status = "'READY','FAILED','DEFERRED'"
    return (
        (
            "0001_durable_local_runtime",
            (
                # ---- layer 1: original source (immutable per version) -------
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL CHECK (source_version >= 1),
                    checksum TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
                    imported_at TEXT NOT NULL,
                    original_reference TEXT NOT NULL,
                    PRIMARY KEY (source_id, source_version)
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_sources_checksum ON sources(checksum)",
                # Re-index must never change original bytes or provenance.
                """
                CREATE TRIGGER IF NOT EXISTS sources_immutable_update
                BEFORE UPDATE ON sources
                BEGIN
                    SELECT RAISE(ABORT, 'original source rows are immutable');
                END
                """,
                """
                CREATE TRIGGER IF NOT EXISTS sources_immutable_delete
                BEFORE DELETE ON sources
                BEGIN
                    SELECT RAISE(ABORT, 'original source rows are immutable');
                END
                """,
                # ---- lifecycle: one row per import or re-index run ---------
                """
                CREATE TABLE IF NOT EXISTS import_runs (
                    run_id TEXT PRIMARY KEY,
                    run_kind TEXT NOT NULL CHECK (run_kind IN ('IMPORT','REINDEX')),
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL CHECK (source_version >= 1),
                    implementation_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('READY','PARTIAL','FAILED')),
                    error_code TEXT,
                    retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
                    original_readable INTEGER NOT NULL CHECK (original_readable IN (0, 1)),
                    outputs TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_import_runs_source ON import_runs(source_id, source_version)",
                # No foreign key to sources on purpose: a run that failed before
                # STORED must still be auditable even though no source row exists.
                """
                CREATE TABLE IF NOT EXISTS import_stage_events (
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (stage IN (""" + stage_names + """)),
                    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
                    status TEXT NOT NULL CHECK (status IN ('PASSED','FAILED','DEFERRED')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    detail TEXT,
                    outputs TEXT NOT NULL,
                    PRIMARY KEY (run_id, stage),
                    FOREIGN KEY (run_id) REFERENCES import_runs(run_id) ON DELETE CASCADE
                )
                """,
                # ---- layer 2: derived / index data (regenerable) -----------
                """
                CREATE TABLE IF NOT EXISTS derived_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    artifact_type TEXT NOT NULL,
                    implementation_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (""" + artifact_status + """)),
                    error_code TEXT,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_id, source_version)
                        REFERENCES sources(source_id, source_version) ON DELETE CASCADE
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_derived_artifacts_source
                ON derived_artifacts(source_id, source_version, artifact_type)
                """,
                """
                CREATE TABLE IF NOT EXISTS derived_anchors (
                    anchor_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
                    page_or_section TEXT NOT NULL,
                    text TEXT NOT NULL,
                    text_checksum TEXT NOT NULL,
                    FOREIGN KEY (artifact_id) REFERENCES derived_artifacts(artifact_id)
                        ON DELETE CASCADE
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_derived_anchors_source
                ON derived_anchors(source_id, source_version, ordinal)
                """,
                # ---- layer 3: user records (never rewritten by re-index) ---
                """
                CREATE TABLE IF NOT EXISTS user_titles (
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, source_version),
                    FOREIGN KEY (source_id, source_version)
                        REFERENCES sources(source_id, source_version)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS user_tags (
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, source_version, tag),
                    FOREIGN KEY (source_id, source_version)
                        REFERENCES sources(source_id, source_version)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS user_annotations (
                    annotation_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    page_or_section TEXT NOT NULL,
                    anchor_start INTEGER NOT NULL CHECK (anchor_start >= 0),
                    anchor_end INTEGER NOT NULL CHECK (anchor_end > anchor_start),
                    anchor_text TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_id, source_version)
                        REFERENCES sources(source_id, source_version)
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_user_annotations_source
                ON user_annotations(source_id, source_version, page_or_section)
                """,
                """
                CREATE TABLE IF NOT EXISTS user_bookmarks (
                    bookmark_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    page_or_section TEXT NOT NULL,
                    anchor_start INTEGER NOT NULL CHECK (anchor_start >= 0),
                    anchor_end INTEGER NOT NULL CHECK (anchor_end > anchor_start),
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_id, source_version)
                        REFERENCES sources(source_id, source_version)
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_user_bookmarks_source
                ON user_bookmarks(source_id, source_version, page_or_section)
                """,
                """
                CREATE TABLE IF NOT EXISTS user_reading_positions (
                    source_id TEXT NOT NULL,
                    source_version INTEGER NOT NULL,
                    page_or_section TEXT NOT NULL,
                    char_offset INTEGER NOT NULL CHECK (char_offset >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, source_version),
                    FOREIGN KEY (source_id, source_version)
                        REFERENCES sources(source_id, source_version)
                )
                """,
            ),
        ),
    )


MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = _migrations()

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
)
"""


def get_connection(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open a SQLite connection with the repository's local-runtime conventions.

    The parent directory is created when missing, ``row_factory`` is
    ``sqlite3.Row`` and foreign keys are enforced. ``isolation_level=None``
    puts the connection in autocommit mode so this module can drive explicit
    ``BEGIN IMMEDIATE`` transactions through :func:`transaction`.
    """
    resolved = str(db_path)
    if resolved != ":memory:":
        parent = Path(resolved).expanduser()
        parent.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in one ``BEGIN IMMEDIATE`` transaction. Not re-entrant."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    connection.commit()


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[tuple[str, Sequence[str]]] = MIGRATIONS,
) -> list[str]:
    """Apply ordered migrations, tracking applied versions in ``schema_migrations``."""
    connection.execute(SCHEMA_MIGRATIONS_DDL)
    applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
    applied_versions: list[str] = []
    for version, statements in migrations:
        if version in applied:
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                connection.execute(statement)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError(
                    version,
                    RuntimeError(f"foreign key violations after migration: {violations}"),
                )
            connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            connection.commit()
        except MigrationError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise MigrationError(version, exc) from exc
        applied_versions.append(version)
    return applied_versions


def applied_versions(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return applied migration versions in deterministic order."""
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return tuple(row["version"] for row in rows)


# --------------------------------------------------------------------------- #
# Filename / path safety (fails closed)
# --------------------------------------------------------------------------- #

def validate_source_filename(filename: str) -> tuple[str, str]:
    """Validate a caller-supplied filename and return ``(name, extension)``.

    Rejects, with the safe code ``UNSAFE_FILENAME`` or ``INVALID_FILENAME``,
    anything that could escape the store or break Windows: path separators,
    absolute paths, ``..``, NUL and other control characters, ``:`` (so no
    drive letters or alternate data streams), ``<>"|?*``, trailing dot or
    space, reserved device names, and over-long names. The returned name is a
    plain filename and is never used to build a path.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise UnsafeSourcePath(_INVALID_FILENAME)
    name = filename.strip()
    if any(character in _FORBIDDEN_FILENAME_CHARACTERS for character in name):
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    if "/" in name or "\\" in name or ".." in name:
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    if name in {".", ".."} or name.endswith(".") or name.endswith(" "):
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    if len(name) > MAX_FILENAME_LENGTH:
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    if name.split(".")[0].upper() in _WINDOWS_RESERVED_STEMS:
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    extension = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return name, extension


def _safe_component(value: str) -> str:
    if not value or "/" in value or "\\" in value or ".." in value or "\x00" in value:
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    return value


def blob_relative_path(source_id: str, source_version: int, extension: str) -> str:
    """Return the store-relative original blob path for a source version.

    Derived from the source id/version (never from the raw filename) so a
    hostile filename cannot influence where bytes land.
    """
    safe_source_id = _safe_component(source_id)
    suffix = BLOB_SUFFIX_BY_EXTENSION.get(extension, FALLBACK_BLOB_SUFFIX)
    return f"{ORIGINALS_DIRNAME}/{safe_source_id}/v{int(source_version)}{suffix}"


def resolve_blob_path(root: str | os.PathLike[str], relative_path: str) -> Path:
    """Resolve a store-relative blob path, rejecting absolute/escaping input."""
    if not isinstance(relative_path, str) or not relative_path:
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    if relative_path.startswith("/") or "\\" in relative_path or ":" in relative_path:
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafeSourcePath(_UNSAFE_FILENAME)
    return Path(root).expanduser().joinpath(*parts)


def blob_exists(root: str | os.PathLike[str], relative_path: str) -> bool:
    try:
        return resolve_blob_path(root, relative_path).is_file()
    except UnsafeSourcePath:
        return False


def write_blob(root: str | os.PathLike[str], relative_path: str, data: bytes) -> bool:
    """Write original bytes once, atomically.

    Returns ``True`` when the blob was newly created and ``False`` when an
    identical blob already existed (idempotent re-import of the same bytes).
    Raises ``StorageFailure`` when the location already holds different bytes
    (``ORIGINAL_WRITE_CONFLICT``, not retryable) or when the write fails
    (``ORIGINAL_WRITE_FAILED``, retryable).
    """
    target = resolve_blob_path(root, relative_path)
    expected = hashlib.sha256(data).hexdigest()
    if target.exists():
        try:
            existing = target.read_bytes()
        except OSError as exc:
            raise StorageFailure("ORIGINAL_WRITE_FAILED") from exc
        if hashlib.sha256(existing).hexdigest() != expected:
            raise StorageFailure("ORIGINAL_WRITE_CONFLICT", retryable=False)
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageFailure("ORIGINAL_WRITE_FAILED") from exc
    temporary = target.parent / (target.name + ".tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise StorageFailure("ORIGINAL_WRITE_FAILED") from exc
    return True


def read_blob(root: str | os.PathLike[str], relative_path: str) -> bytes:
    """Read original bytes back; ``OriginalUnreadable`` when unavailable."""
    target = resolve_blob_path(root, relative_path)
    if not target.is_file():
        raise OriginalUnreadable("ORIGINAL_NOT_READABLE")
    try:
        return target.read_bytes()
    except OSError as exc:
        raise OriginalUnreadable("ORIGINAL_NOT_READABLE") from exc


def remove_blob(root: str | os.PathLike[str], relative_path: str) -> bool:
    """Best-effort removal of an orphaned blob (never masks the caller's error)."""
    try:
        target = resolve_blob_path(root, relative_path)
    except UnsafeSourcePath:
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True


__all__ = [
    "ArchiveError",
    "DEFAULT_DB_FILENAME",
    "FALLBACK_BLOB_SUFFIX",
    "MIGRATIONS",
    "MigrationError",
    "ORIGINALS_DIRNAME",
    "OriginalIntegrityError",
    "OriginalUnreadable",
    "SCHEMA_MIGRATIONS_DDL",
    "StorageFailure",
    "UnsafeSourcePath",
    "applied_versions",
    "apply_migrations",
    "blob_exists",
    "blob_relative_path",
    "error_code",
    "get_connection",
    "is_retryable",
    "read_blob",
    "remove_blob",
    "resolve_blob_path",
    "transaction",
    "validate_source_filename",
    "write_blob",
]
