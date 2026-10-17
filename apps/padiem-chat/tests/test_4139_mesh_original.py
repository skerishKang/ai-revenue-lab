"""#4139 mesh originals — real storage helper through real committed migrations.

The dispatch state machine, the pin guard and the private R2 original store
are exercised for real (SQLite D1 double created from the committed 047/048
migration files, in-memory private R2). Only the D1/R2 bindings are doubles;
every helper under test is production code.
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.history import (
    D1HistoryStore, HistoryError, HistoryForbidden,
)

MIGRATIONS = (
    Path(__file__).resolve().parents[1] / "migrations" / "001_auth_history.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "009_claw_run_history.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "014_claw_run_history_conversation.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "015_claw_run_history_workspace.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "047_oracle_mesh_dispatch.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "048_oracle_mesh_command.sql",
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


def _stage(store, run_id=RUN):
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=run_id, channel="web", action="txt_read",
        title="Claw: probe", status="pending", conversation_id=CONVERSATION,
        workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs(run_id=run_id)))
    return row["dispatch_id"]


def _pin(store, dispatch_id, raw: bytes):
    digest = hashlib.sha256(raw).hexdigest()
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=digest,
        content_bytes=len(raw),
    )) is True
    return digest


def test_context_key_accepts_mesh_result_ids():
    good = [
        "msg_" + "a" * 32,
        "msg_ltr_" + "b" * 40,
        "msg_ltr_" + "c" * 40 + "_p0",
        "msg_ltr_" + "d" * 40 + "_p257",
    ]
    for mid in good:
        key = D1HistoryStore._context_key(CONVERSATION, mid)
        assert key == "claw-model-context/v1/%s/%s.utf8" % (CONVERSATION, mid)
    bad = [
        "msg_ltr_" + "e" * 39,
        "msg_ltr_" + "e" * 41,
        "msg_ltr_",
        "msg_ltr_" + "f" * 40 + "_p",
        "msg_ltr_" + "f" * 40 + "_px",
        "msg_",
        "browser-chosen-key",
        "../../../etc/passwd",
        "msg_" + "A" * 32,
    ]
    for mid in bad:
        with pytest.raises(HistoryError):
            D1HistoryStore._context_key(CONVERSATION, mid)
    with pytest.raises(HistoryError):
        D1HistoryStore._context_key("not-a-conversation", "msg_" + "a" * 32)


def test_pin_guard_first_same_and_different(tmp_path):
    store, _ = fixture(tmp_path)
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=RUN, channel="web", action="txt_read",
        title="Claw: probe", status="pending",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs()))
    nothing = hashlib.sha256(b"").hexdigest()
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=row["dispatch_id"], content_sha256=nothing, content_bytes=0,
    )) is True
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=row["dispatch_id"], content_sha256=nothing, content_bytes=0,
    )) is True
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=row["dispatch_id"], content_sha256="f" * 64, content_bytes=1,
    )) is False
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id="dsp-unknown", content_sha256=nothing, content_bytes=0,
    )) is False


def test_original_round_trip_bytes_and_digest_match(tmp_path):
    store, bucket = fixture(tmp_path)
    raw = "Padiem-Command-Center\r\n" + "한글 출력 행\n" * 1200
    body = raw.encode("utf-8")
    assert len(raw) > 8000  # over one message: the store path under test
    body_digest = hashlib.sha256(body).hexdigest()
    second_id = _stage(store, run_id="run-original-2")
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=second_id, content_sha256=body_digest,
        content_bytes=len(body),
    )) is True
    key = asyncio.run(store.store_oracle_mesh_original(
        user_id=OWNER, dispatch_id=second_id, conversation_id=CONVERSATION,
        message_id=MID, raw=raw,
        expected_sha256=body_digest, expected_bytes=len(body),
    ))
    assert key == "claw-model-context/v1/%s/%s.utf8" % (CONVERSATION, MID)
    assert set(bucket.objects) == {key}
    found = asyncio.run(store.read_oracle_mesh_original(
        user_id=OWNER, dispatch_id=second_id, conversation_id=CONVERSATION,
        message_id=MID,
    ))
    assert found is not None
    payload, pinned = found
    assert payload == body
    assert pinned == body_digest
    # Whitespace, CRLF and UTF-8 survive byte-for-byte.
    assert payload.decode("utf-8") == raw


def test_original_is_owner_scoped(tmp_path):
    store, _ = fixture(tmp_path)
    dispatch_id = _stage(store)
    raw = "Padiem-Command-Center\r\n"
    digest = _pin(store, dispatch_id, raw.encode("utf-8"))
    with pytest.raises(HistoryForbidden):
        asyncio.run(store.store_oracle_mesh_original(
            user_id=FOREIGN, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION, message_id=MID, raw=raw,
            expected_sha256=digest, expected_bytes=23,
        ))
    assert asyncio.run(store.read_oracle_mesh_original(
        user_id=FOREIGN, dispatch_id=dispatch_id,
        conversation_id=CONVERSATION, message_id=MID,
    )) is None
    assert asyncio.run(store.get_oracle_mesh_dispatch_for_owner(
        user_id=FOREIGN, dispatch_id=dispatch_id)) is None
    assert asyncio.run(store.get_oracle_mesh_dispatch_for_owner(
        user_id=OWNER, dispatch_id="dsp-unknown")) is None


def test_original_pin_mismatch_is_refused(tmp_path):
    store, _ = fixture(tmp_path)
    dispatch_id = _stage(store)
    digest = _pin(store, dispatch_id, "Padiem-Command-Center\r\n".encode("utf-8"))
    with pytest.raises(HistoryError):
        asyncio.run(store.store_oracle_mesh_original(
            user_id=OWNER, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION, message_id=MID,
            raw="tampered\r\n",
            expected_sha256=digest, expected_bytes=23,
        ))


def test_original_missing_or_corrupt_is_loud_not_silent(tmp_path):
    store, bucket = fixture(tmp_path)
    dispatch_id = _stage(store)
    raw = "Padiem-Command-Center\r\n" + "y" * 9000
    digest = _pin(store, dispatch_id, raw.encode("utf-8"))
    asyncio.run(store.store_oracle_mesh_original(
        user_id=OWNER, dispatch_id=dispatch_id, conversation_id=CONVERSATION,
        message_id=MID, raw=raw,
        expected_sha256=digest, expected_bytes=len(raw.encode("utf-8")),
    ))
    key = next(iter(bucket.objects))
    bucket.objects[key] = b"corrupt"
    with pytest.raises(HistoryError):
        asyncio.run(store.read_oracle_mesh_original(
            user_id=OWNER, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION, message_id=MID,
        ))
    del bucket.objects[key]
    with pytest.raises(HistoryError):
        asyncio.run(store.read_oracle_mesh_original(
            user_id=OWNER, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION, message_id=MID,
        ))


def test_original_envelope_bound_is_the_wire_envelope(tmp_path):
    store, _ = fixture(tmp_path)
    dispatch_id = _stage(store)
    too_big = "x" * (6_000_001)
    with pytest.raises(HistoryError):
        asyncio.run(store.store_oracle_mesh_original(
            user_id=OWNER, dispatch_id=dispatch_id,
            conversation_id=CONVERSATION, message_id=MID, raw=too_big,
            expected_sha256="0" * 64, expected_bytes=len(too_big.encode("utf-8")),
        ))
