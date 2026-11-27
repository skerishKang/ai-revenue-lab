"""공용 시험 준비 — 확인 카드 만료 픽스처.

test_7603_confirmation_card_expiry가 들고 있던 픽스처를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from _support.migrated_db_template import migrated_connection

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


def _fixture(tmp_path, *, memory=False):
    # 테스트마다 마이그레이션을 파일에 다시 적용하면 디스크가 느린 CI에서
    # 수십 초가 걸릴 수 있다. 파일 내용을 단언하지 않는 시험은 메모리 DB를
    # 써도 검증하는 동작이 그대로다(기본값은 파일 — 기존 호출부 유지).
    target = ":memory:" if memory else str(tmp_path / "chat.sqlite3")
    connection = migrated_connection(
        target, loader="local_cpython", isolation_level=None,
        row_factory=sqlite3.Row,
    )
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
