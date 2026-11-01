"""#6579 → step 2: the shared tus core, exercised on its own.

The protocol is now one module used by every upload lane, so these tests drive
it through a fake lane and pin the behaviour every lane inherits: creation,
chunk append, resume after an interruption, status, the one-time result pickup,
the two size ceilings, and — the isolation rule — another user's upload URL
behaving exactly like a missing one.
"""
from __future__ import annotations

import json

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app.tus_core import TusLane, tus_creation, tus_resource

CHUNK = "application/offset+octet-stream"


class FakeLane:
    """One lane whose only real job is remembering who uploaded what."""

    def __init__(self) -> None:
        self.current_user = "user-a"
        self.finalized: list[tuple[str, dict]] = []
        self.fail_finalize = False

    async def identity(self, request):
        user = self.current_user
        return ({"user_id": user}, None) if user else (None, _unauthorized())

    async def finalize(self, request, data_path, meta):
        if self.fail_finalize:
            raise RuntimeError("lane store down")
        with open(data_path, "rb") as handle:
            body = handle.read()
        self.finalized.append((data_path, dict(meta)))
        return {"status": 201, "body": {"ok": True, "bytes": len(body)}}

    def lane(self) -> TusLane:
        return TusLane(
            name="fake",
            identity=self.identity,
            finalize=self.finalize,
            accepts=lambda media_type: media_type in {"application/pdf"},
            location=lambda request, meta: "/api/fake/tus/" + meta["upload_id"],
            not_found_message="업로드를 찾을 수 없습니다.",
        )

    def app(self) -> TestClient:
        lane = self.lane()

        async def collection(request):
            return await tus_creation(request, lane)

        async def item(request):
            return await tus_resource(request, lane)

        app = Starlette(routes=[
            Route("/api/fake/tus", collection, methods=["POST", "OPTIONS"]),
            Route("/api/fake/tus/{upload_id}", item, methods=["HEAD", "PATCH", "GET"]),
        ])
        return TestClient(app)


def _unauthorized():
    from starlette.responses import JSONResponse

    return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)


def _metadata(filename="보고서.pdf", media_type="application/pdf") -> str:
    import base64

    return ("filename " + base64.b64encode(filename.encode()).decode()
            + ",filetype " + base64.b64encode(media_type.encode()).decode())


def _create(client, length, *, metadata=None):
    return client.post(
        "/api/fake/tus",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Length": str(length),
            "Upload-Metadata": metadata if metadata is not None else _metadata(),
        },
    )


def _patch(client, location, offset, body):
    return client.patch(location, headers={
        "Tus-Resumable": "1.0.0",
        "Upload-Offset": str(offset),
        "Content-Type": CHUNK,
    }, content=body)


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_TUS_UPLOAD_DIR", str(tmp_path / "tus"))
    return FakeLane()


def test_creation_returns_an_unguessable_id_and_the_shared_ceilings(lane):
    client = lane.app()
    response = _create(client, 2_000)
    assert response.status_code == 201
    body = response.json()
    assert body["offset_bytes"] == 0 and body["length_bytes"] == 2_000
    assert len(body["upload_id"]) >= 32
    assert body["chunk_max_bytes"] <= 100 * 1024 * 1024
    assert body["max_upload_bytes"] == 1024 * 1024 * 1024
    assert response.headers["Location"].endswith(body["upload_id"])


def test_options_advertises_the_protocol_and_the_shared_limits(lane):
    response = lane.app().options("/api/fake/tus")
    assert response.status_code == 204
    assert response.headers["Tus-Version"] == "1.0.0"
    assert response.headers["Tus-Max-Size"] == str(1024 * 1024 * 1024)
    assert "creation" in response.headers["Tus-Extension"]
    assert int(response.headers["X-Padiem-Tus-Chunk-Max"]) <= 100 * 1024 * 1024


def test_a_whole_upload_completes_and_hands_off_to_the_lane(lane):
    client = lane.app()
    location = client.post("/api/fake/tus", headers={
        "Tus-Resumable": "1.0.0", "Upload-Length": "6",
        "Upload-Metadata": _metadata(),
    }).headers["Location"]
    assert _patch(client, location, 0, b"abcdef").status_code == 204
    assert lane.finalized and lane.finalized[-1][1]["length_bytes"] == 6
    picked = client.get(location)
    assert picked.status_code == 201
    assert picked.json() == {"ok": True, "bytes": 6}


def test_an_interrupted_upload_resumes_from_the_server_offset(lane):
    client = lane.app()
    created = _create(client, 10).json()
    location = "/api/fake/tus/" + created["upload_id"]
    assert _patch(client, location, 0, b"0123").status_code == 204
    # The browser reconnects and asks where it left off.
    status = client.head(location)
    assert status.headers["Upload-Offset"] == "4"
    assert status.headers["Upload-Length"] == "10"
    # A replay of the chunk already accepted is refused, not appended twice.
    assert _patch(client, location, 0, b"0123").status_code == 409
    assert _patch(client, location, 4, b"456789").status_code == 204
    assert lane.finalized[-1][1]["offset_bytes"] == 10


def test_another_users_upload_url_looks_exactly_like_a_missing_one(lane):
    client = lane.app()
    created = _create(client, 4).json()
    location = "/api/fake/tus/" + created["upload_id"]
    assert _patch(client, location, 0, b"ab").status_code == 204
    lane.current_user = "user-b"
    for response in (client.head(location),
                     _patch(client, location, 2, b"cd"),
                     client.get(location)):
        assert response.status_code == 404
        assert len(response.content) < 200
    # Nothing of user A's upload was readable, and nothing completed for B.
    assert all(meta["scope"]["user_id"] == "user-a" for _, meta in lane.finalized)


def test_a_missing_upload_id_is_the_same_404(lane):
    client = lane.app()
    assert client.head("/api/fake/tus/not-a-real-upload").status_code == 404


def test_both_size_ceilings_are_refused_before_anything_is_written(lane, monkeypatch):
    client = lane.app()
    assert _create(client, 1024 * 1024 * 1024 + 1).status_code == 413
    monkeypatch.setenv("PADIEM_TUS_CHUNK_MAX_BYTES", "8")
    location = _create(client, 20).headers["Location"]
    too_big = _patch(client, location, 0, b"x" * 9)
    assert too_big.status_code == 413
    # The refused chunk left the offset untouched.
    assert client.head(location).headers["Upload-Offset"] == "0"


def test_an_unaccepted_media_type_and_a_bad_metadata_header_are_refused(lane):
    client = lane.app()
    assert _create(client, 10, metadata=_metadata(media_type="text/plain")).status_code == 422
    assert _create(client, 10, metadata="not-base64").status_code == 422
    assert _create(client, 0).status_code == 413


def test_an_unsigned_request_is_refused_by_the_lane(lane):
    client = lane.app()
    lane.current_user = ""
    assert _create(client, 10).status_code == 401


def test_a_failing_lane_store_keeps_the_upload_answerable(lane):
    client = lane.app()
    lane.fail_finalize = True
    location = _create(client, 2).headers["Location"]
    assert _patch(client, location, 0, b"ab").status_code == 204
    picked = client.get(location)
    assert picked.status_code == 503
    assert picked.json()["error"]["code"] == "upload_unavailable"
