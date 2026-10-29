"""#5881 follow-on — the schema of the 컴2 PC queue database.

Only the migrations that own the tables the queue is responsible for are applied here:
`oracle_mesh_dispatch` (047·048·049·063·074), `mesh_device_presence` (067·070) and the
pairing directory `pc_pairing_codes` + `pc_device_links` (072·073). Conversation rows —
runs, messages, tool calls, the preferred-PC selection — stay in Cloudflare D1, which is
the split the design was approved on.

The files are applied in name order, exactly as the D1 migration ledger applies them, so
a column that a guard depends on cannot be missing on one side only.
"""
from __future__ import annotations

import os
import pathlib

from app.d1_sqlite import SqliteD1, connect


def migration_dir(base: pathlib.Path | None = None) -> pathlib.Path:
    """Where the Chat migrations are, in whichever layout this file is running.

    The repository layout puts this file at apps/padiem-mesh-queue/schema.py, one level
    below the Chat app. On 컴2 the same file is installed at $ROOT/schema.py, where that
    relative path would be /opt/padiem/padiem-chat — so the installed `app` link is
    used instead: $ROOT/app resolves to <chat>/app, and its parent holds migrations.
    An explicit MESH_QUEUE_MIGRATIONS_DIR wins over both.
    """

    override = os.environ.get("MESH_QUEUE_MIGRATIONS_DIR", "").strip()
    if override:
        return pathlib.Path(override)
    here = pathlib.Path(base) if base is not None else pathlib.Path(__file__).resolve().parent
    # Resolve the app link and take its parent: "../" after a symlink is lexical on
    # Windows and physical on Linux, and this file runs on both.
    through_app = here / "app"
    if through_app.is_dir():
        candidate = through_app.resolve().parent / "migrations"
        if candidate.is_dir():
            return candidate
    return here.parent / "padiem-chat" / "migrations"


MIGRATION_DIR = migration_dir()

QUEUE_MIGRATIONS = (
    "047_oracle_mesh_dispatch.sql",
    "048_oracle_mesh_command.sql",
    "049_oracle_mesh_command_result_meta.sql",
    "063_oracle_mesh_dispatch_tool_call_scope.sql",
    "067_mesh_device_presence.sql",
    "070_mesh_device_presence_source.sql",
    "072_pc_device_pairing.sql",
    "073_pc_device_link_pause.sql",
    "074_oracle_mesh_dispatch_claim_lease.sql",
)

QUEUE_TABLES = (
    "oracle_mesh_dispatch",
    "mesh_device_presence",
    "pc_pairing_codes",
    "pc_device_links",
)

__all__ = ["MIGRATION_DIR", "QUEUE_MIGRATIONS", "QUEUE_TABLES", "apply", "open_queue"]


def apply(connection, *, migrations: tuple[str, ...] = QUEUE_MIGRATIONS) -> None:
    for name in migrations:
        path = MIGRATION_DIR / name
        if not path.is_file():
            raise FileNotFoundError("queue migration missing: %s" % path)
        connection.executescript(path.read_text(encoding="utf-8"))


def open_queue(path: str):
    """Open (creating if needed) the queue database and its D1-shaped surface."""

    connection = connect(path)
    apply(connection)
    return connection, SqliteD1(connection)
