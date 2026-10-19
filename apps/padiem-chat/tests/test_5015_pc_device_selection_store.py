"""#5015: the saved PC target is a bounded, owner-scoped D1 preference."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.claw_pc_device_selection_store import (
    D1PcDeviceSelectionStore,
    PcDeviceSelectionStoreError,
)

OWNER = "usr_" + "a" * 32
WORKSPACE = "owner:" + OWNER
OTHER = "usr_" + "b" * 32


class Statement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values = ()

    def bind(self, *values):
        self.values = values
        return self

    async def first(self):
        return self.db.row

    async def run(self):
        self.db.runs.append((self.sql, self.values))
        if "INSERT" in self.sql and self.db.persist:
            # Simulate the upsert for the exact bound key/value.
            self.db.row = {
                "user_id": self.values[0], "workspace_id": self.values[1],
                "device_id": self.values[2],
            }
        return {"success": True}


class D1:
    def __init__(self, row=None, *, persist=True):
        self.row = row
        self.persist = persist
        self.statements = []
        self.runs = []

    def prepare(self, sql):
        statement = Statement(self, sql)
        self.statements.append(statement)
        return statement


def store_with(row=None):
    db = D1(row)
    return D1PcDeviceSelectionStore(db), db


def test_load_is_owner_workspace_scoped_and_grammar_checked():
    store, db = store_with({"device_id": "office"})
    assert asyncio.run(store.load(owner_id=OWNER, workspace_id=WORKSPACE)) == "office"
    sql, values = db.statements[0].sql, None
    assert "WHERE user_id=? AND workspace_id=?" in sql
    # A malformed stored value is no preference, never a device.
    for value in ("bad/path", 42, None, ""):
        store, _ = store_with({"device_id": value})
        assert asyncio.run(store.load(owner_id=OWNER, workspace_id=WORKSPACE)) is None


def test_save_binds_values_and_confirms_readback():
    store, db = store_with()
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert asyncio.run(store.save(
        owner_id=OWNER, workspace_id=WORKSPACE, device_id="office-pc", now=now,
    )) is True
    sql, values = db.runs[0]
    assert "INSERT INTO claw_pc_device_selection" in sql
    assert "ON CONFLICT(user_id, workspace_id) DO UPDATE" in sql
    assert values == (OWNER, WORKSPACE, "office-pc", "2026-10-19T00:00:00Z")
    # Readback must return the exact saved identifier.
    store, _ = (lambda db: (D1PcDeviceSelectionStore(db), db))(
        D1({"device_id": "another-pc"}, persist=False)
    )
    assert asyncio.run(store.save(
        owner_id=OWNER, workspace_id=WORKSPACE, device_id="office-pc", now=now,
    )) is False


def test_save_rejects_invalid_bounds_and_naive_time():
    store, db = store_with()
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    for kwargs in (
        {"owner_id": "", "workspace_id": WORKSPACE, "device_id": "pc", "now": now},
        {"owner_id": OWNER, "workspace_id": "", "device_id": "pc", "now": now},
        {"owner_id": OWNER, "workspace_id": WORKSPACE, "device_id": "bad/path", "now": now},
        {"owner_id": OWNER, "workspace_id": WORKSPACE, "device_id": "x" * 129, "now": now},
        {"owner_id": OWNER, "workspace_id": WORKSPACE, "device_id": "pc",
         "now": datetime(2026, 10, 19)},
    ):
        with pytest.raises(PcDeviceSelectionStoreError):
            asyncio.run(store.save(**kwargs))
    assert db.runs == []


def test_store_requires_a_d1_binding():
    with pytest.raises(ValueError):
        D1PcDeviceSelectionStore(None)


def test_migration_declares_the_owner_workspace_scoped_table():
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "054_claw_pc_device_selection.sql").read_text(encoding="utf-8")
    for fragment in (
        "CREATE TABLE IF NOT EXISTS claw_pc_device_selection",
        "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE",
        "workspace_id TEXT NOT NULL",
        "device_id TEXT NOT NULL",
        "updated_at TEXT NOT NULL",
        "PRIMARY KEY(user_id, workspace_id)",
    ):
        assert fragment in sql, fragment
    # A preference row, not a credential/consent/authority row.
    body = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    ).lower()
    assert "credential" not in body
    assert "secret" not in body
