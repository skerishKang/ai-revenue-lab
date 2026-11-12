"""#6579 → step 2: the shared tus core, exercised on its own.

The protocol is now one module used by every upload lane, so these tests drive
it through a fake lane and pin the behaviour every lane inherits: creation,
chunk append, resume after an interruption, status, the one-time result pickup,
the two size ceilings, and — the isolation rule — another user's upload URL
behaving exactly like a missing one.

#7543 S08 adds the cross-process half of "one PATCH at a time per upload": the
last section runs real second processes against the same upload directory, the
way two workers of one host would meet on a retried chunk.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import tus_core
from app.tus_core import _DATA_NAME, _LOCK_NAME, TusLane, tus_creation, tus_resource

CHUNK = "application/offset+octet-stream"
PATCH_PROCESS = Path(__file__).parent / "fixtures" / "tus_patch_process_261112.py"


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


# ── #7543 S08: one PATCH at a time per upload, across worker processes ───────


def _error_code(response) -> str:
    if not response.content:
        return ""
    return (response.json().get("error") or {}).get("code", "")


def _stored_bytes(upload_id: str) -> bytes:
    return (Path(tus_core.upload_root()) / upload_id / _DATA_NAME).read_bytes()


def _wait_until(predicate, seconds=30):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("the worker process did not get there in time")


class PatchProcess:
    """One worker process sending one PATCH; see the fixture's docstring."""

    def __init__(self, tmp_path, name, upload_id, *, fill, size, offset=0, hold=False):
        self.result = tmp_path / f"{name}.result.json"
        self.finalize_log = tmp_path / "finalize.log"
        self.hold = tmp_path / f"{name}.hold"
        self._release = tmp_path / f"{name}.release"
        job = {
            "upload_id": upload_id, "user_id": "user-a", "offset": offset,
            "fill": fill, "size": size, "result": str(self.result),
            "finalize_log": str(self.finalize_log),
        }
        if hold:
            job.update(hold=str(self.hold), release=str(self._release))
        job_file = tmp_path / f"{name}.job.json"
        job_file.write_text(json.dumps(job), encoding="utf-8")
        # PADIEM_TUS_UPLOAD_DIR is already in os.environ (the ``lane`` fixture),
        # so the child sees the same upload directory as this process.
        self.process = subprocess.Popen(
            [sys.executable, str(PATCH_PROCESS), str(job_file)],
            env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )

    def wait_until_inside_the_patch(self) -> None:
        def inside() -> bool:
            if self.process.poll() is not None:
                answer = self.result.read_text() if self.result.exists() else "no answer"
                raise AssertionError(
                    f"the worker left before holding the chunk open: {answer}"
                    f" {self.process.stderr.read()[-2000:]}")
            return self.hold.exists()
        _wait_until(inside)

    def release(self) -> None:
        self._release.touch()

    def answer(self) -> dict:
        _stdout, stderr = self.process.communicate(timeout=30)
        assert self.process.returncode == 0, stderr[-2000:]
        return json.loads(self.result.read_text(encoding="utf-8"))

    def kill(self) -> None:
        """SIGKILL / TerminateProcess; a no-op for a worker that already left."""
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        for pipe in (self.process.stdout, self.process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()


def _finalize_lines(tmp_path) -> list[dict]:
    log = tmp_path / "finalize.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def test_the_same_chunk_from_two_worker_processes_lets_exactly_one_through(lane, tmp_path):
    """S08: a retried chunk that lands on another worker while the first one is
    still writing answers 409 upload_busy there; the upload completes once."""
    client = lane.app()
    upload_id = _create(client, 64).json()["upload_id"]
    location = "/api/fake/tus/" + upload_id

    first = PatchProcess(tmp_path, "first", upload_id, fill="A", size=64, hold=True)
    second = None
    try:
        first.wait_until_inside_the_patch()
        # Same upload, same offset, same length, from a second process — while
        # the first is still in the middle of that very chunk.
        second = PatchProcess(tmp_path, "second", upload_id, fill="B", size=64)
        second_answer = second.answer()
        first.release()
        first_answer = first.answer()
    finally:
        first.kill()
        if second is not None:
            second.kill()

    assert len({first_answer["pid"], second_answer["pid"], os.getpid()}) == 3
    assert sorted([first_answer["status"], second_answer["status"]]) == [204, 409], (
        first_answer, second_answer)
    assert (first_answer["status"], first_answer["code"]) == (204, "")
    assert (second_answer["status"], second_answer["code"]) == (409, "upload_busy")

    # Completed exactly once, by the process that held the chunk, over exactly
    # its own bytes: the refused chunk wrote nothing.
    completions = _finalize_lines(tmp_path)
    assert [line["pid"] for line in completions] == [first_answer["pid"]], completions
    assert completions[0]["stored"] == "A" * 64
    assert _stored_bytes(upload_id) == b"A" * 64
    status = client.head(location)
    assert status.headers["Upload-Offset"] == "64"
    assert status.headers["X-Padiem-Upload-Complete"] == "1"
    assert client.get(location).json() == {"ok": True, "bytes": 64}


def test_a_worker_process_that_dies_mid_chunk_leaves_no_lock_behind(lane, tmp_path):
    """The lock is the OS's, held by the open descriptor: a killed worker takes
    it down with it, even though ``patch.lock`` itself stays on disk."""
    client = lane.app()
    upload_id = _create(client, 64).json()["upload_id"]
    location = "/api/fake/tus/" + upload_id
    lock_file = Path(tus_core.upload_root()) / upload_id / _LOCK_NAME

    doomed = PatchProcess(tmp_path, "doomed", upload_id, fill="A", size=64, hold=True)
    try:
        doomed.wait_until_inside_the_patch()
        # This test process is the other worker. While the first one lives,
        # its chunk keeps everyone else out.
        busy = _patch(client, location, 0, b"B" * 64)
        assert (busy.status_code, _error_code(busy)) == (409, "upload_busy")
        assert client.head(location).headers["Upload-Offset"] == "0"
    finally:
        # No ``finally`` block and no exit handler ever runs in the worker.
        doomed.kill()

    assert not doomed.result.exists()  # it never answered
    assert lock_file.exists()          # the file stays; the lock does not
    retried = _patch(client, location, 0, b"B" * 64)
    assert retried.status_code == 204, retried.text
    assert _stored_bytes(upload_id) == b"B" * 64
    assert len(lane.finalized) == 1 and _finalize_lines(tmp_path) == []
    assert client.get(location).json() == {"ok": True, "bytes": 64}


@pytest.mark.parametrize("winner_chunk,code", [
    (b"A" * 8, "upload_completed"),   # the other worker finished the upload
    (b"A" * 4, "offset_mismatch"),    # the other worker appended one chunk
])
def test_the_chunk_is_judged_by_what_is_on_disk_once_the_lock_is_held(
        lane, monkeypatch, winner_chunk, code):
    """A request reads the metadata on arrival and takes the lock afterwards.
    A chunk another worker stored in between must decide, not the stale read —
    otherwise the same range is written twice and the upload completes twice."""
    client = lane.app()
    upload_id = _create(client, 8).json()["upload_id"]
    location = "/api/fake/tus/" + upload_id
    real_load = tus_core._load_meta
    raced: list[int] = []

    def read_then_lose_the_race(requested_id):
        meta = real_load(requested_id)
        if not raced:
            # Right after this request's first read — before it holds any
            # lock — another worker receives the same offset and finishes.
            raced.append(1)
            assert _patch(lane.app(), location, 0, winner_chunk).status_code == 204
        return meta

    monkeypatch.setattr(tus_core, "_load_meta", read_then_lose_the_race)
    late = _patch(client, location, 0, b"B" * len(winner_chunk))

    assert (late.status_code, _error_code(late)) == (409, code)
    assert _stored_bytes(upload_id) == winner_chunk
    assert client.head(location).headers["Upload-Offset"] == str(len(winner_chunk))
    assert len(lane.finalized) == (1 if len(winner_chunk) == 8 else 0)
