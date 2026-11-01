"""The 10 MiB boundary on the web XLSX lane, and the streaming store beneath it.

Owner's decision: at or below ``WEB_XLSX_INLINE_MAX_BYTES`` the existing
in-memory store call stays; above it the archive is judged from the file and the
store receives the file itself, so a large original never becomes one `bytes`.
"""
from __future__ import annotations

import base64
import tracemalloc

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import tus_web_xlsx_upload as lane_module
from app.local_r2 import LocalDiskR2, put_stream
from app.workspace_storage import WEB_XLSX_INLINE_MAX_BYTES, XLSX_MEDIA_TYPE

CHUNK = "application/offset+octet-stream"


class RecordingStore:
    """Records which store entry point the boundary chose."""

    def __init__(self) -> None:
        self.inline: list[dict] = []
        self.streamed: list[dict] = []

    async def put_web_xlsx(self, **kwargs):
        self.inline.append(kwargs)
        return {"document_id": "doc_" + "i" * 32,
                "filename": kwargs["filename"], "size_bytes": len(kwargs["body"])}

    async def put_web_xlsx_from_path(self, **kwargs):
        self.streamed.append(kwargs)
        return {"document_id": "doc_" + "s" * 32,
                "filename": kwargs["filename"]}


def _metadata() -> str:
    return ("filename " + base64.b64encode("큰보고서.xlsx".encode()).decode()
            + ",filetype " + base64.b64encode(XLSX_MEDIA_TYPE.encode()).decode())


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_UPLOAD_DIR", str(tmp_path / "tus"))
    store = RecordingStore()
    monkeypatch.setattr(lane_module, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane_module, "current_user_id", lambda request: "owner-a")

    async def workspace(request, owner):
        return "ws-a"

    monkeypatch.setattr(lane_module, "_resolve_memory_workspace", workspace)
    app = Starlette(routes=[
        Route(lane_module.WEB_XLSX_TUS_COLLECTION_PATH,
              lane_module.web_xlsx_tus_collection, methods=["POST", "OPTIONS"]),
        Route(lane_module.WEB_XLSX_TUS_ITEM_PATH,
              lane_module.web_xlsx_tus_item, methods=["HEAD", "PATCH", "GET"]),
    ])
    app.state.workspace_document_store = store
    return TestClient(app), store


def _upload(client, length):
    created = client.post(lane_module.WEB_XLSX_TUS_COLLECTION_PATH, headers={
        "Tus-Resumable": "1.0.0", "Upload-Length": str(length),
        "Upload-Metadata": _metadata(),
    })
    assert created.status_code == 201, created.text
    return created.json()["upload_id"]


def _send(client, upload_id, offset, body):
    return client.patch(
        lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id),
        headers={"Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
                 "Content-Type": CHUNK}, content=body)


def test_exactly_at_the_boundary_stays_in_memory(lane):
    client, store = lane
    upload_id = _upload(client, WEB_XLSX_INLINE_MAX_BYTES)
    assert _send(client, upload_id, 0, b"x" * WEB_XLSX_INLINE_MAX_BYTES).status_code == 204
    assert len(store.inline) == 1 and not store.streamed
    assert len(store.inline[0]["body"]) == WEB_XLSX_INLINE_MAX_BYTES


def test_one_byte_over_the_boundary_streams_from_disk(lane):
    client, store = lane
    size = WEB_XLSX_INLINE_MAX_BYTES + 1
    upload_id = _upload(client, size)
    assert _send(client, upload_id, 0, b"x" * size).status_code == 204
    assert len(store.streamed) == 1 and not store.inline
    streamed = store.streamed[0]
    # The store is handed the file itself, never its bytes.
    assert isinstance(streamed["source_path"], str)
    assert streamed["filename"] == "큰보고서.xlsx"
    assert streamed["owner_id"] == "owner-a" and streamed["workspace_id"] == "ws-a"


def test_both_boundaries_answer_with_the_same_projection(lane):
    client, store = lane
    for size in (8, WEB_XLSX_INLINE_MAX_BYTES + 1):
        upload_id = _upload(client, size)
        assert _send(client, upload_id, 0, b"x" * size).status_code == 204
        picked = client.get(
            lane_module.WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id))
        assert picked.status_code == 201
        body = picked.json()
        assert body["contract_version"] == "claw-web-xlsx-source.v1"
        assert body["p01_approved"] is False and body["ok"] is True
    assert store.inline and store.streamed


def test_put_stream_moves_a_file_on_the_same_disk(tmp_path):
    bucket = LocalDiskR2(tmp_path / "objects")
    source = tmp_path / "chunk.bin"
    source.write_bytes(b"payload-a")
    put_stream(bucket, "a/b/object", source)
    assert bucket.get("a/b/object").body == b"payload-a"
    # A same-filesystem write is a move: the staged chunk is gone, not copied.
    assert not source.exists()


def test_put_stream_copies_across_filesystems_in_bounded_blocks(tmp_path, monkeypatch):
    import app.local_r2 as module

    # The sync disk store: `put_stream` is the sync entry point, so the async
    # host binding is exercised by its own delegation, not here.
    bucket = module.LocalDiskR2(tmp_path / "objects")
    source = tmp_path / "chunk.bin"
    source.write_bytes(b"z" * (3 * 1024 * 1024 + 5))

    import os

    real_replace = os.replace

    def refuse_same_disk_move(src, dst):
        if str(src).endswith("chunk.bin"):
            raise OSError("cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, "replace", refuse_same_disk_move)
    module.put_stream(bucket, "a/b/copied", source)
    assert bucket.get("a/b/copied").size == 3 * 1024 * 1024 + 5
    # The copy path consumes the staged original once it is safely stored.
    assert not source.exists()


def test_a_store_without_streaming_refuses_instead_of_faking_success(tmp_path):
    class BytesOnly:
        def put(self, key, body, httpMetadata=None):
            raise AssertionError("must not be called for a streamed write")

    source = tmp_path / "chunk.bin"
    source.write_bytes(b"x")
    with pytest.raises(NotImplementedError):
        put_stream(BytesOnly(), "a/b", source)
    assert source.exists()  # nothing was consumed by a refused write


def test_streaming_a_200mb_file_keeps_the_process_memory_flat(tmp_path):
    """The whole point of #6579 step 2: the size never becomes one allocation."""
    bucket = LocalDiskR2(tmp_path / "objects")
    source = tmp_path / "big.bin"
    block = b"0" * (1024 * 1024)
    with source.open("wb") as handle:
        for _ in range(200):
            handle.write(block)
    assert source.stat().st_size == 200 * 1024 * 1024

    tracemalloc.start()
    try:
        put_stream(bucket, "a/b/big", source)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert bucket.get("a/b/big").size == 200 * 1024 * 1024
    # Bounded blocks: a whole-file buffer would show ~200 MiB here.
    assert peak < 32 * 1024 * 1024, peak


def test_disk_store_keeps_colon_workspace_ids_inside_the_bucket(tmp_path):
    """#6579 — `owner:usr_...` 워크스페이스 ID가 든 키도 저장된다.

    Windows는 ':'가 든 파일 이름을 만들 수 없다. 어댑터가 키 조각을 퍼센트
    인코딩해 두 OS 모두에서 같은 객체를 만들지 않으면, 웹 XLSX·채팅 첨부 저장이
    실제 라우트에서 503으로 닫힌다(측정 중 실제로 재현됨). 경로 탈출 검사는
    그대로다.
    """
    import io
    import pytest
    from app.local_r2 import LocalDiskR2

    store = LocalDiskR2(tmp_path / "bucket")
    key = "workspaces/owner:usr_a/claw/web-office/doc_1/x.xlsx"
    store.put(key, b"body")
    assert store.get(key).body == b"body"
    assert store.get(key).size == 4
    store.put_stream(key + ".2", io.BytesIO(b"streamed"))
    assert store.get(key + ".2").body == b"streamed"
    # 저장된 이름은 OS 공통 안전 문자지만 논리 키는 그대로다.
    assert all(":" not in entry.name for entry in (tmp_path / "bucket").rglob("*"))

    for bad in ("../escape", "/abs", "a/../../b", "a\b"):
        with pytest.raises(ValueError):
            store.put(bad, b"x")
