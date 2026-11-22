"""PC device pairing shared test preparation (#8061 batch 4).

Lives under tests/_support so the test-to-test import ratchet does not grow
when the pairing lane is carried forward. The hub (test_5573_pc_device_pairing)
re-exports these names for consumers not yet migrated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import httpx

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.app_factory import create_app
from app.pc_device_pairing_routes import (
    PC_PAIRING_CLAIM_PATH,
    PC_PAIRING_PATH,
    PC_PAIRING_ROOTS_PATH,
    PC_PAIRING_ROOT_PATH,
)
from app.pc_device_pairing_store import (
    D1PcPairingStore,
    PcPairingError,
    derive_install_tag,
    drive_root,
    normalize_root_label,
    normalize_root_path,
)

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "072_pc_device_pairing.sql"
MIGRATIONS = MIGRATION.parent
#: Both pairing migrations are one unapplied set: 073 ALTERs the table 072
#: creates, so "before the pairing migration" has to leave 073 out too or the
#: replay itself, not the code under test, is what fails. 089 ALTERs the same
#: table for #6694's supersede columns and belongs to that set for the same
#: reason.
PAIRING_MIGRATION_NUMBERS = {MIGRATION.name[:3], "073", "089", "103", "134"}
OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
NODE = "node//mesh-pc-01"
OTHER_NODE = "node/meshdomain/mesh-pc-02"
SESSION_SECRET = "phase11-pc-pairing-session-secret-not-a-real-key-0000000000"
ORIGIN = "https://chat.example.test"


class D1Statement:
    def __init__(self, conn: sqlite3.Connection, query: str) -> None:
        self.conn = conn
        self.query = query
        self.args: tuple = ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        cursor = self.conn.execute(self.query, self.args)
        return {"results": [dict(row) for row in cursor.fetchall()]}

    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row is not None else None


class RealSQLiteD1:
    """The prepare/bind/run/first surface the D1 stores use."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def prepare(self, query: str) -> D1Statement:
        return D1Statement(self.conn, query)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# #7801: the full migration set is applied once per process and cloned.
# Every call used to re-read and re-execute 130+ migration files
# (~0.14 s each); tests build these stores hundreds of times per run.
# A backup clone has identical schema and data, and writes to a clone
# never touch the template, so per-test isolation is unchanged.
_TEMPLATES: dict[bool, sqlite3.Connection] = {}


def database(*, with_072: bool = True) -> sqlite3.Connection:
    template = _TEMPLATES.get(with_072)
    if template is None:
        template = sqlite3.connect(":memory:", isolation_level=None)
        template.row_factory = sqlite3.Row
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if not with_072 and path.name[:3] in PAIRING_MIGRATION_NUMBERS:
                continue
            template.executescript(path.read_text(encoding="utf-8"))
        _TEMPLATES[with_072] = template
    clone = sqlite3.connect(":memory:", isolation_level=None)
    template.backup(clone)
    clone.row_factory = sqlite3.Row
    return clone


def store(*, with_072: bool = True) -> D1PcPairingStore:
    return D1PcPairingStore(RealSQLiteD1(database(with_072=with_072)))


def app_with(store_value=None, *, verifier=None):
    app = create_app(Settings(
        runtime_mode="mock",
        session_secret=SESSION_SECRET,
        public_base_url=ORIGIN,
    ))
    app.state.pc_device_pairing_store = store_value
    if verifier is not None:
        app.state.pc_pairing_verifier = verifier
    return app


def client(app, *, user_id: str = OWNER):
    token = create_session_token(
        app.state.settings, user_id, now=int(_now().timestamp()),
        canonical_session_id="session_test_a")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        # Cookie-authenticated mutations are covered by the central #3476 origin
        # guard, and these routes are registered by app_factory, so they are
        # guarded: a browser client has to bring the reviewed Origin.
        headers={"Origin": ORIGIN},
        cookies={SESSION_COOKIE: token},
    )


def run(coro):
    import asyncio

    return asyncio.run(coro)


def observed_on_the_mesh(*, node_seen: bool = True):
    """Stand-in for PR-2's server-side Mesh observation of the claimed node."""
    async def verifier(*, mesh_node_id: str, code: str) -> bool:
        return node_seen
    return verifier
