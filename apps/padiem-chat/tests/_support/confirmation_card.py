"""공용 시험 준비 — 확인 카드 만료 픽스처.

test_7603_confirmation_card_expiry가 들고 있던 픽스처를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.local_cpython import apply_migrations

UID = "usr_" + "8" * 32
WORKSPACE = "ws-7603"
PC_CONTEXT = {"workspace_id": WORKSPACE, "pc_tools": {"device_id": "device-1"}}


class _Bucket:
    """Private full-text store stand-in (put/get/delete by key)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key, body, httpMetadata=None):
        self.objects[key] = bytes(body)

    def delete(self, key):
        self.objects.pop(key, None)

    def get(self, key):
        return self.objects.get(key)


def _fixture(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', 'sub_7603', "
        "'owner@example.test', '', '', '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z')",
        (UID,),
    )
    store = D1HistoryStore(SqliteD1(connection), full_context_bucket=_Bucket())
    return store, connection


def _age(connection, run_id: str, seconds: int) -> None:
    """Move the card's created_at into the past; the tests never sleep."""

    stamp = (datetime.now(timezone.utc) - timedelta(seconds=seconds))
    value = stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    connection.execute(
        "UPDATE claw_run_history SET created_at=? WHERE run_id=? AND user_id=?",
        (value, run_id, UID),
    )


def _status(connection, run_id: str) -> str:
    row = connection.execute(
        "SELECT status FROM claw_run_history WHERE run_id=? AND user_id=?",
        (run_id, UID),
    ).fetchone()
    return str(row["status"])
