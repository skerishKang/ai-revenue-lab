"""Shared oracle-mesh dispatch fixtures for the 4139/5895/75xx storage tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.history import D1HistoryStore

MIGRATIONS = (
    Path(__file__).resolve().parents[2] / "migrations" / "001_auth_history.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "002_projects.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "009_claw_run_history.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "014_claw_run_history_conversation.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "015_claw_run_history_workspace.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "042_conversation_product_scope.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "047_oracle_mesh_dispatch.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "048_oracle_mesh_command.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "049_oracle_mesh_command_result_meta.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "063_oracle_mesh_dispatch_tool_call_scope.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "074_oracle_mesh_dispatch_claim_lease.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "102_oracle_mesh_dispatch_user_mode.sql",
    Path(__file__).resolve().parents[2] / "migrations" / "112_oracle_mesh_dispatch_read_only.sql",
)

OWNER = "usr_owner_4139"
FOREIGN = "usr_foreign_4139"
CONVERSATION = "chat_" + "c" * 32
RUN = "run-original-1"
MID = "msg_ltr_" + "d" * 40


class _Statement:
    def __init__(self, path: Path, sql: str) -> None:
        self._path = path
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values: Any) -> "_Statement":
        self._values = values
        return self

    async def first(self) -> dict[str, Any] | None:
        conn = sqlite3.connect(self._path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(self._sql, self._values).fetchone()
            return dict(row) if row is not None else None
        finally:
            conn.close()

    async def run(self) -> dict[str, Any]:
        conn = sqlite3.connect(self._path)
        try:
            # The same row shape `first()` gives and the same shape a real D1
            # `results` array carries: without it, any multi-column SELECT read
            # through this shim died converting a plain tuple of values as a dict.
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(self._sql, self._values)
            rows = [dict(row) for row in cursor.fetchall()]
            conn.commit()
            return {"results": rows, "meta": {"changes": cursor.rowcount}}
        finally:
            conn.close()


class _D1:
    def __init__(self, db_path: Path) -> None:
        conn = sqlite3.connect(db_path)
        try:
            for migration in MIGRATIONS:
                conn.executescript(migration.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()
        self._path = db_path

    def prepare(self, sql: str) -> _Statement:
        return _Statement(self._path, sql)


class PrivateR2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key, payload, **_kwargs):
        self.objects[key] = bytes(payload)

    async def get(self, key):
        data = self.objects.get(key)
        return None if data is None else SimpleNamespace(
            size=len(data), arrayBuffer=lambda: data,
        )

    async def delete(self, key):
        self.objects.pop(key, None)


def fixture(tmp_path):
    bucket = PrivateR2()
    store = D1HistoryStore(_D1(tmp_path / "d1.sqlite3"), full_context_bucket=bucket)
    return store, bucket


def _dispatch_kwargs(**overrides):
    fields = dict(
        user_id=OWNER, run_id=RUN, command_id="cmd-1", tool_request_ref="t",
        request_id="r", revision_ref="rev", evidence_ref=None,
        request_fingerprint="f", account_ref="acc", workspace_ref="ws",
        device_id="dev", binding_ref=None, node_ref="node",
        root_ref="mesh_terminal", path_relative="command",
        file_path="command", expires_at="2099-01-01T00:00:00Z",
        kind="command", command_text="hostname.exe",
    )
    fields.update(overrides)
    return fields
