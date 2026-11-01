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
    Path(__file__).resolve().parents[1] / "migrations" / "002_projects.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "009_claw_run_history.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "014_claw_run_history_conversation.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "015_claw_run_history_workspace.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "042_conversation_product_scope.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "047_oracle_mesh_dispatch.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "048_oracle_mesh_command.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "049_oracle_mesh_command_result_meta.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "063_oracle_mesh_dispatch_tool_call_scope.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "074_oracle_mesh_dispatch_claim_lease.sql",
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


def test_command_result_meta_columns_persist_termination(tmp_path):
    """#5015/049: termination/exit_code travel with the pinned result."""
    store, _ = fixture(tmp_path)
    dispatch_id = _stage(store)
    raw = "drive payload"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert asyncio.run(store.record_oracle_mesh_first_result(
        dispatch_id=dispatch_id, content_sha256=digest,
        content_bytes=len(raw.encode("utf-8")),
        termination="no_exit_code", exit_code=None,
    )) is True
    row = asyncio.run(store.get_oracle_mesh_dispatch_for_owner(
        user_id=OWNER, dispatch_id=dispatch_id))
    assert row is not None
    assert row["termination"] == "no_exit_code"
    assert row["exit_code"] is None
    assert row["result_sha256"] == digest


def test_chat_pc_drive_run_stages_b62_conversation_and_run(tmp_path):
    """#5015 review: Chat lane staging keeps the b62-chat scope and run link."""
    store, _ = fixture(tmp_path)
    run_id = "chat_pcq_" + "a" * 24
    cid = asyncio.run(store.record_chat_pc_drive_run(
        user_id=OWNER, run_id=run_id, workspace_id="ws-1",
        user_text="내 PC 드라이브 알려줘", conversation_id=None,
    ))
    assert cid.startswith("chat_")
    run = asyncio.run(store.get_claw_run(OWNER, run_id))
    assert run is not None
    assert run["conversation_id"] == cid
    assert run["workspace_id"] == "ws-1"


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


@pytest.mark.parametrize("method", ["store_oracle_mesh_original", "store_oracle_mesh_command_result"])
@pytest.mark.parametrize("kind,root", [
    ("read", "pc_files_read"), ("read", "other_read"), ("command", "pc_files_read"),
])
def test_twenty_mb_original_storage_is_bound_to_the_verified_pc_read_row(tmp_path, method, kind, root):
    store, bucket = fixture(tmp_path)
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=RUN, channel="web", action="txt_read",
        title="Claw: probe", status="pending", conversation_id=CONVERSATION,
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs(
        kind=kind, root_ref=root, command_text="hostname.exe" if kind == "command" else None,
        path_relative="large.txt", file_path="C:/verified/large.txt",
    )))
    raw = "a" * (20_000_000 - 8) + "END_FILE"
    body = raw.encode()
    digest = _pin(store, row["dispatch_id"], body)
    fields = dict(user_id=OWNER, dispatch_id=row["dispatch_id"],
                  conversation_id=CONVERSATION, message_id=MID, raw=raw,
                  expected_sha256=digest, expected_bytes=len(body))
    with pytest.raises(HistoryForbidden):
        asyncio.run(getattr(store, method)(**{**fields, "user_id": FOREIGN}))
    if kind != "read" or root != "pc_files_read":
        with pytest.raises(HistoryError, match="bounded storage envelope"):
            asyncio.run(getattr(store, method)(**fields))
        assert not bucket.objects
        return
    asyncio.run(getattr(store, method)(**fields))
    returned, pinned = asyncio.run(store.read_oracle_mesh_original(
        user_id=OWNER, dispatch_id=row["dispatch_id"],
        conversation_id=CONVERSATION, message_id=MID,
    ))
    assert returned == body
    assert pinned == digest
    assert asyncio.run(store.read_oracle_mesh_original(
        user_id=FOREIGN, dispatch_id=row["dispatch_id"],
        conversation_id=CONVERSATION, message_id=MID,
    )) is None


@pytest.mark.parametrize("method", ["store_oracle_mesh_original", "store_oracle_mesh_command_result"])
def test_com2_command_over_six_mb_is_stored_and_returned(tmp_path, method):
    store, bucket = fixture(tmp_path)
    store.mesh_command_output_max_bytes = None
    dispatch_id = _stage(store)
    raw = "가" * 2_000_001
    body = raw.encode("utf-8")
    assert len(body) > 6_000_000
    digest = _pin(store, dispatch_id, body)
    fields = dict(user_id=OWNER, dispatch_id=dispatch_id, conversation_id=CONVERSATION,
                  message_id=MID, raw=raw, expected_sha256=digest, expected_bytes=len(body))
    asyncio.run(getattr(store, method)(**fields))
    payload, pinned = asyncio.run(store.read_oracle_mesh_original(
        user_id=OWNER, dispatch_id=dispatch_id, conversation_id=CONVERSATION, message_id=MID))
    assert payload == body
    assert pinned == digest
    assert len(bucket.objects) == 1
    with pytest.raises(HistoryForbidden):
        asyncio.run(getattr(store, method)(**{**fields, "user_id": FOREIGN}))


def test_com2_command_limit_can_be_configured_without_changing_pc_read_bound():
    from app.history import _oracle_mesh_original_max_bytes
    assert _oracle_mesh_original_max_bytes({"kind": "command"}, None) is None
    assert _oracle_mesh_original_max_bytes({"kind": "command"}, 8_000_000) == 8_000_000
    # #5882 A: the PC read lane keeps no product store cap of its own — the
    # bytes are pinned by size + digest above this point, and a file larger
    # than one answer is paged by the Engine instead of refused here.
    assert _oracle_mesh_original_max_bytes({"kind": "read", "root_ref": "pc_files_read"}, None) is None
    assert _oracle_mesh_original_max_bytes({"kind": "read", "root_ref": "other"}, None) == 6_000_000


def test_com2_command_limit_environment(monkeypatch):
    from app.config import ConfigError
    from app.local_cpython import _mesh_command_output_limit
    name = "PADIEM_CHAT_PC_COMMAND_OUTPUT_MAX_BYTES"
    monkeypatch.delenv(name, raising=False)
    assert _mesh_command_output_limit() is None
    monkeypatch.setenv(name, "8000000")
    assert _mesh_command_output_limit() == 8_000_000
    for invalid in ("0", "-1", "abc"):
        monkeypatch.setenv(name, invalid)
        with pytest.raises(ConfigError):
            _mesh_command_output_limit()


def test_com2_large_command_round_trip_through_local_disk(tmp_path):
    from app.local_r2 import ThreadedLocalDiskR2
    store = D1HistoryStore(_D1(tmp_path / "local.sqlite3"),
                           full_context_bucket=ThreadedLocalDiskR2(tmp_path / "objects"),
                           mesh_command_output_max_bytes=None)
    dispatch_id = _stage(store)
    raw = "가" * 2_000_001
    body = raw.encode()
    digest = _pin(store, dispatch_id, body)
    asyncio.run(store.store_oracle_mesh_original(
        user_id=OWNER, dispatch_id=dispatch_id, conversation_id=CONVERSATION,
        message_id=MID, raw=raw, expected_sha256=digest, expected_bytes=len(body)))
    payload, _ = asyncio.run(store.read_oracle_mesh_original(
        user_id=OWNER, dispatch_id=dispatch_id, conversation_id=CONVERSATION, message_id=MID))
    assert payload == body
