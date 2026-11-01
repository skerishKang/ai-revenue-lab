"""#6460 D1~D3: the shared tus core's hostile-input and per-account bounds.

`app/tus_core.py` is the one definition every upload lane uses (project files,
Chat attachments, web XLSX), so these scenes are driven through a fake lane and
each lane inherits them unchanged.

D1 — `Upload-Length` that is not a plain decimal, or is longer than any ceiling,
never reaches `int()`: a malformed value answers 400, a huge one answers 413,
and no exception text is ever echoed.

D2 — `Upload-Offset` is a boundary too: a missing or malformed header answers
400, an offset that cannot equal the server's (negative, mismatched, or a
5,000-digit number) answers 409, and a chunk that would run past the declared
length answers 413 without a single byte being appended.

D3 — one account cannot open unbounded unfinished uploads: the open count and
the declared bytes are bounded by env settings, a creation that would cross
either answers 429 with its own reason code, and completed, expired or removed
uploads are not counted. Another account's uploads never enter the total.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import tus_core
from app.tus_core import (
    _DATA_NAME,
    TusLane,
    active_usage_for_user,
    remove_upload,
    tus_creation,
    tus_resource,
)

CHUNK = "application/offset+octet-stream"
HUGE = "9" * 5000


class FakeLane:
    """One lane whose only job is remembering who uploaded what."""

    def __init__(self) -> None:
        self.current_user: str | None = "user-a"
        self.finalized: list[dict] = []

    async def identity(self, request):
        user = self.current_user
        if not user:
            return None, JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
        return {"user_id": user}, None

    async def finalize(self, request, data_path, meta):
        with open(data_path, "rb") as handle:
            body = handle.read()
        self.finalized.append({"meta": dict(meta), "bytes": len(body)})
        return {"status": 201, "body": {"ok": True, "bytes": len(body)}}

    def lane(self) -> TusLane:
        return TusLane(
            name="fake",
            identity=self.identity,
            finalize=self.finalize,
            accepts=lambda media_type: media_type == "application/pdf",
            location=lambda request, meta: "/api/fake/tus/" + meta["upload_id"],
            not_found_message="업로드를 찾을 수 없습니다.",
        )

    def client(self) -> TestClient:
        lane = self.lane()

        async def collection(request):
            return await tus_creation(request, lane)

        async def item(request):
            return await tus_resource(request, lane)

        app = Starlette(routes=[
            Route("/api/fake/tus", collection, methods=["POST", "OPTIONS"]),
            Route("/api/fake/tus/{upload_id}", item, methods=["HEAD", "PATCH", "GET"]),
        ])
        return TestClient(app, raise_server_exceptions=False)


def metadata(name="보고서.pdf", media_type="application/pdf") -> str:
    return ("filename " + base64.b64encode(name.encode()).decode()
            + ",filetype " + base64.b64encode(media_type.encode()).decode())


MISSING = object()


def create(client, length, *, name="보고서.pdf", media_type="application/pdf",
           raw_length=MISSING):
    headers = {"Tus-Resumable": "1.0.0", "Upload-Metadata": metadata(name, media_type)}
    value = str(length) if raw_length is MISSING else raw_length
    if value is not None:
        headers["Upload-Length"] = value
    return client.post("/api/fake/tus", headers=headers)


def patch(client, location, offset, body: bytes, *, raw_offset=MISSING):
    headers = {"Tus-Resumable": "1.0.0", "Content-Type": CHUNK}
    value = str(offset) if raw_offset is MISSING else raw_offset
    if value is not None:
        headers["Upload-Offset"] = value
    return client.patch(location, headers=headers, content=body)


def data_path(upload_id: str) -> Path:
    return Path(tus_core.upload_root()) / upload_id / _DATA_NAME


def data_size(upload_id: str) -> int:
    try:
        return data_path(upload_id).stat().st_size
    except OSError:
        return -1


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_UPLOAD_DIR", str(tmp_path / "tus"))
    monkeypatch.delenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", raising=False)
    monkeypatch.delenv("PADIEM_TUS_MAX_ACTIVE_BYTES_PER_USER", raising=False)
    monkeypatch.delenv("PADIEM_TUS_CLEANUP_SECONDS", raising=False)
    return FakeLane()


# ── D1: Upload-Length ───────────────────────────────────────────────────────


@pytest.mark.parametrize("raw_length,status,code", [
    ("abc", 400, "invalid_upload"),
    (None, 400, "invalid_upload"),
    ("-5", 400, "invalid_upload"),
    ("10,11", 400, "invalid_upload"),
    ("1 2", 400, "invalid_upload"),
    ("0", 413, "upload_too_large"),
    (HUGE, 413, "upload_too_large"),
    (str(1024 * 1024 * 1024 + 1), 413, "upload_too_large"),
])
def test_upload_length_values_answer_a_reason_code_not_an_exception(
        lane, raw_length, status, code):
    answer = create(lane.client(), 10, raw_length=raw_length)
    assert answer.status_code == status, (raw_length and raw_length[:20], answer.text[:200])
    assert answer.json()["error"]["code"] == code
    # No driver text and no traceback ever reaches the browser.
    body = answer.text
    assert "ValueError" not in body and "Traceback" not in body
    # Nothing was created on disk.
    root = Path(tus_core.upload_root())
    assert not root.exists() or list(root.iterdir()) == []


def test_a_huge_upload_length_creates_no_upload_directory(lane):
    client = lane.client()
    assert create(client, 10, raw_length=HUGE).status_code == 413
    root = Path(tus_core.upload_root())
    assert not root.exists() or list(root.iterdir()) == []


# ── D2: Upload-Offset and chunk boundaries ──────────────────────────────────


def test_a_missing_or_malformed_offset_is_a_400(lane):
    client = lane.client()
    location = create(client, 10).headers["Location"]
    for raw in (None, "", "abc", "1,2"):
        answer = patch(client, location, 0, b"abcd", raw_offset=raw)
        assert answer.status_code == 400, raw
        assert answer.json()["error"]["code"] == "invalid_offset"
    assert data_size(location.rsplit("/", 1)[-1]) == 0


def test_offsets_that_cannot_match_the_server_answer_409_and_append_nothing(lane):
    client = lane.client()
    created = create(client, 64).json()
    upload_id = created["upload_id"]
    location = "/api/fake/tus/" + upload_id
    for raw in ("-1", "5", "128", HUGE):
        answer = patch(client, location, 0, b"X" * 8, raw_offset=raw)
        assert answer.status_code == 409, raw[:12]
        assert answer.json()["error"]["code"] == "offset_mismatch"
        assert data_size(upload_id) == 0, raw[:12]
    assert client.head(location).headers["Upload-Offset"] == "0"


def test_a_chunk_that_would_pass_the_declared_length_is_refused_whole(lane):
    client = lane.client()
    upload_id = create(client, 10).json()["upload_id"]
    location = "/api/fake/tus/" + upload_id

    over = patch(client, location, 0, b"0123456789ABCDEF")
    assert over.status_code == 413
    assert over.json()["error"]["code"] == "chunk_too_large"
    assert data_size(upload_id) == 0
    assert client.head(location).headers["Upload-Offset"] == "0"

    exact = patch(client, location, 0, b"0123456789")
    assert exact.status_code == 204
    assert client.head(location).headers["Upload-Offset"] == "10"


def test_the_second_chunk_cannot_overflow_the_remaining_length(lane):
    client = lane.client()
    upload_id = create(client, 10).json()["upload_id"]
    location = "/api/fake/tus/" + upload_id
    assert patch(client, location, 0, b"01234567").status_code == 204

    over = patch(client, location, 8, b"89ABCDEF")
    assert over.status_code == 413
    assert client.head(location).headers["Upload-Offset"] == "8"
    assert data_size(upload_id) == 8

    assert patch(client, location, 8, b"89").status_code == 204
    assert lane.finalized and lane.finalized[-1]["bytes"] == 10


def test_a_lying_content_length_cannot_advance_the_offset(lane):
    client = lane.client()
    upload_id = create(client, 64).json()["upload_id"]
    location = "/api/fake/tus/" + upload_id
    over = client.request("PATCH", location, content=b"abcde", headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": "0", "Content-Type": CHUNK,
        "Content-Length": "100",
    })
    assert over.status_code == 413
    assert data_size(upload_id) == 0
    under = client.request("PATCH", location, content=b"abcde", headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": "0", "Content-Type": CHUNK,
        "Content-Length": "32",
    })
    assert under.status_code == 204
    assert client.head(location).headers["Upload-Offset"] == "5"


# ── D3: per-account open-upload bounds ──────────────────────────────────────


def test_the_open_upload_count_is_bounded_per_account(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "2")
    client = lane.client()
    assert create(client, 10).status_code == 201
    assert create(client, 10).status_code == 201
    refused = create(client, 10)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "upload_limit_reached"
    assert "ValueError" not in refused.text


def test_a_completed_upload_frees_its_slot(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "2")
    client = lane.client()
    first = create(client, 4).json()["upload_id"]
    assert create(client, 10).status_code == 201
    assert create(client, 10).status_code == 429

    location = "/api/fake/tus/" + first
    assert patch(client, location, 0, b"abcd").status_code == 204
    assert create(client, 10).status_code == 201


def test_the_declared_bytes_of_open_uploads_are_bounded(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_BYTES_PER_USER", "1000")
    client = lane.client()
    assert create(client, 600).status_code == 201
    refused = create(client, 600)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "upload_bytes_limit_reached"
    # Exactly at the ceiling is allowed; only crossing it is refused.
    assert create(client, 400).status_code == 201
    assert create(client, 1).status_code == 429


def test_another_account_is_never_affected(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "1")
    client = lane.client()
    assert create(client, 10).status_code == 201
    assert create(client, 10).status_code == 429

    lane.current_user = "user-b"
    assert create(client, 10).status_code == 201
    assert create(client, 10).status_code == 429
    lane.current_user = "user-a"
    assert create(client, 10).status_code == 429


def test_expired_and_removed_uploads_are_not_counted(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "1")
    monkeypatch.setenv("PADIEM_TUS_CLEANUP_SECONDS", "60")
    client = lane.client()

    stale = create(client, 10).json()["upload_id"]
    marker = Path(tus_core.upload_root()) / stale / "upload.json"
    old = time.time() - 3600
    os.utime(marker, (old, old))
    assert active_usage_for_user("user-a") == (0, 0)
    fresh = create(client, 10)
    assert fresh.status_code == 201
    fresh_id = fresh.json()["upload_id"]
    assert not (Path(tus_core.upload_root()) / stale).exists()

    active = client.head("/api/fake/tus/" + stale)
    assert active.status_code == 404

    assert create(client, 10).status_code == 429
    remove_upload(fresh_id)
    assert active_usage_for_user("user-a") == (0, 0)
    assert create(client, 10).status_code == 201


def test_zero_switches_each_bound_off(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "0")
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_BYTES_PER_USER", "0")
    client = lane.client()
    for _ in range(8):
        assert create(client, 1024).status_code == 201


def test_completed_bytes_are_not_counted(lane, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_BYTES_PER_USER", "100")
    client = lane.client()
    upload_id = create(client, 100).json()["upload_id"]
    assert active_usage_for_user("user-a") == (1, 100)
    assert patch(client, "/api/fake/tus/" + upload_id, 0, b"x" * 100).status_code == 204
    assert active_usage_for_user("user-a") == (0, 0)
    assert create(client, 100).status_code == 201


def test_the_three_lanes_all_go_through_the_shared_core():
    here = Path(__file__).resolve().parents[1] / "app"
    for name in ("tus_project_upload.py", "tus_chat_attachment.py", "tus_web_xlsx_upload.py"):
        source = (here / name).read_text(encoding="utf-8")
        assert "tus_creation(" in source or "tus_creation," in source, name
        assert "tus_resource(" in source or "tus_resource," in source, name
