"""#5573 stage 2 — the Chat app on plain CPython, behind PADIEM_LOCAL_DEV=1.

`worker.py` (Cloudflare) and this module compose the SAME `create_app`; the
only difference is where the D1/R2 bindings come from. Here they are a local
SQLite file and a disk folder, wired through the shared `SqliteD1` facade —
no fourth store dialect, no second app factory, and the production path is
untouched: this module refuses to build unless the explicit local flag is
set, and the Worker binding path can never set it (app/worker_config.py
calls Settings.from_values without the flag).

Lanes that need workerd stay fail-closed exactly as in production when a
binding is absent: connector WSS, cron telemetry export, Drive/P01 service
bindings, Web Push. The password-auth → conversations → mock-chat lane is
what this entry point is for.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .app_factory import create_app
from .config import ConfigError, Settings
from .d1_sqlite import SqliteD1
from .history import D1HistoryStore
from .local_r2 import LocalDiskR2
from .project_files import D1ProjectFileStore
from .saved_outputs import D1SavedOutputStore
from .usage_gate import D1UsageCounterStore

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

#: Own ledger instead of wrangler's `d1_migrations`: the local file must never
#: look "already migrated" to a future wrangler run and must never rewrite the
#: production ledger shape. Same order guarantee — filenames sort 001…076.
LOCAL_LEDGER_TABLE = "padiem_local_migration_ledger"


def local_data_dir() -> Path:
    raw = os.getenv("PADIEM_CHAT_LOCAL_DATA_DIR")
    base = Path(raw) if raw else Path(__file__).resolve().parents[1] / "local_dev_data"
    return base


def apply_migrations(connection: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Apply every pending migration in filename order; return how many ran."""

    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {LOCAL_LEDGER_TABLE} ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in connection.execute(f"SELECT name FROM {LOCAL_LEDGER_TABLE}")}
    count = 0
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute(
            f"INSERT INTO {LOCAL_LEDGER_TABLE} (name, applied_at) VALUES (?, ?)",
            (path.name, datetime.now(timezone.utc).isoformat()),
        )
        count += 1
    return count


def _ensure_session_secret(data_dir: Path) -> None:
    """Persist one dev session key next to the local database.

    The value never leaves the file; nothing here prints it. A process
    restart keeps existing cookies valid, which a random per-boot secret
    would not.
    """
    configured = os.getenv("PADIEM_CHAT_SESSION_SECRET", "").strip()
    if len(configured) >= 32:
        return
    secret_file = data_dir / "session_secret"
    if secret_file.exists():
        existing = secret_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            os.environ["PADIEM_CHAT_SESSION_SECRET"] = existing
            return
    generated = secrets.token_hex(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(generated, encoding="utf-8")
    os.environ["PADIEM_CHAT_SESSION_SECRET"] = generated


def build_app():
    """Compose the Chat ASGI app over the local SQLite + disk-R2 bindings."""

    if os.getenv("PADIEM_LOCAL_DEV", "").strip().lower() not in {"1", "true"}:
        raise ConfigError(
            "app.local_cpython is the explicit local-run entry point: "
            "set PADIEM_LOCAL_DEV=1 (see tools/run_chat_local_cpython.py)"
        )
    data_dir = local_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _ensure_session_secret(data_dir)

    settings = Settings.from_env()
    if not settings.local_dev:
        raise ConfigError("PADIEM_LOCAL_DEV did not reach Settings — from_env regression")

    # Same autocommit stance as the shared facade's connect(), minus the
    # foreign_keys pragma: production D1 never enforces it and the migration
    # set was built under that assumption.
    connection = sqlite3.connect(
        str(data_dir / "chat.sqlite3"), isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    applied = apply_migrations(connection)
    if applied:
        print(f"[local] migrations applied: {applied}")

    db = SqliteD1(connection)
    r2 = LocalDiskR2(data_dir / "objects")

    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db, full_context_bucket=r2),
        d1_binding=db,
        r2_binding=r2,
        project_file_store=D1ProjectFileStore(db),
        saved_output_store=D1SavedOutputStore(db),
        usage_store=D1UsageCounterStore(db),
    )
    return app
