"""#6338 observation gap: one journal line per lane HTTP request.

The lane used to leave no per-request trace, so an upload or text-extraction
failure could not be confirmed after the fact (the 05:24 KST upload that
overlapped the Worker 500 burst). These tests drive the real app through the
real on-disk journal: a success request, a 422 parser refusal that journals
its constant reason code, a journal that cannot write without ever failing
the request, and the UTC-day rotation. No row may carry a filename, file
content, ticket or secret value, exception message text or a raw owner
identifier.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
import time

import pytest
from starlette.testclient import TestClient

from padiem_file_lane.app import create_app
from padiem_file_lane.journal import RequestJournal
from padiem_file_lane.tickets import PROOF_HEADER, TIME_HEADER, TICKET_HEADER

# The synthetic encrypted DOCX from the #5881 contract tests drives the real
# Core parser into a constant-code refusal; no fake store is involved.
from test_5881_parser_reason_codes import DOCX_MIME, _ole_encrypted_package

SECRET = "offline-file-lane-test-secret-000000000000"
FIELDS = {"ts", "method", "path", "status", "error_code", "duration_ms", "file_size"}


def ticket(user="usr_alice", maximum=10_000_000):
    stamp = str(int(time.time()))
    raw = json.dumps({"user_id": user, "max_bytes": maximum,
                      "expires": int(time.time()) + 600}, separators=(",", ":")).encode()
    proof = hmac.new(SECRET.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {TICKET_HEADER: base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
            TIME_HEADER: stamp, PROOF_HEADER: proof}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(root=tmp_path, secret=SECRET)) as client:
        yield client


def journal_rows(root: Path):
    directory = root / "journal"
    rows = []
    for path in sorted(directory.glob("requests-*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return rows


def journal_blob(root: Path) -> str:
    directory = root / "journal"
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(directory.glob("requests-*.jsonl")))


def test_success_requests_leave_rows_without_any_forbidden_content(client, tmp_path):
    data = "hello lane".encode()
    result = client.post("/files", params={"filename": "hello lane.txt"}, content=data,
                         headers=ticket())
    assert result.status_code == 201
    file_id = result.json()["file_id"]
    text = client.get(f"/files/{file_id}/text", headers=ticket())
    assert text.status_code == 200
    health = client.get("/health")
    assert health.status_code == 200

    rows = journal_rows(tmp_path)
    by_path = {row["path"]: row for row in rows}
    upload_row = by_path["/files"]
    assert upload_row["method"] == "POST" and upload_row["status"] == 201
    assert upload_row["error_code"] is None and upload_row["file_size"] == len(data)
    text_row = by_path[f"/files/{file_id}/text"]
    assert text_row["status"] == 200 and text_row["file_size"] == len(text.content)
    assert by_path["/health"]["status"] == 200 and by_path["/health"]["file_size"] is None
    for row in rows:
        assert set(row) == FIELDS
        assert isinstance(row["duration_ms"], (int, float)) and row["duration_ms"] >= 0
        datetime.fromisoformat(row["ts"])  # every row carries a parseable UTC stamp
        assert "?" not in row["path"]  # the filename query never reaches the journal
    blob = journal_blob(tmp_path)
    assert "hello lane.txt" not in blob and "hello lane" not in blob  # name and content
    assert "usr_alice" not in blob  # raw owner identifier
    headers = ticket()
    for value in headers.values():
        assert value not in blob  # ticket bytes and proof
    assert SECRET not in blob


def test_a_parser_refusal_journals_its_constant_reason_code(client, tmp_path):
    payload = _ole_encrypted_package()
    result = client.post("/files", params={"filename": "enc.docx"}, content=payload,
                         headers={**ticket(), "Content-Type": DOCX_MIME})
    assert result.status_code == 201
    file_id = result.json()["file_id"]
    response = client.get(f"/files/{file_id}/text", headers=ticket())
    assert response.status_code == 422 and response.json()["error"]["code"] == "ooxml_encrypted"

    text_row = next(row for row in journal_rows(tmp_path) if row["path"] == f"/files/{file_id}/text")
    assert text_row["status"] == 422 and text_row["error_code"] == "ooxml_encrypted"
    assert text_row["file_size"] is None
    assert "EncryptedPackage" not in journal_blob(tmp_path)  # no content or exception text


def test_a_failed_upload_journals_the_attempted_size(tmp_path):
    with TestClient(create_app(root=tmp_path, secret=SECRET)) as client:
        response = client.post("/files", params={"filename": "big.txt"}, content=b"x" * 20,
                               headers=ticket(maximum=10))
        assert response.status_code == 413
    rows = [row for row in journal_rows(tmp_path) if row["path"] == "/files"]
    assert rows[-1]["status"] == 413 and rows[-1]["error_code"] == "ticket_size_exceeded"
    assert rows[-1]["file_size"] == 20  # the attempted upload size survived the failure


def test_a_broken_journal_never_fails_the_request(tmp_path):
    (tmp_path / "journal").write_bytes(b"a file where the directory should go")
    with TestClient(create_app(root=tmp_path, secret=SECRET)) as client:
        result = client.post("/files", params={"filename": "hello.txt"}, content=b"hello",
                             headers=ticket())
        assert result.status_code == 201
        file_id = result.json()["file_id"]
        assert client.get(f"/files/{file_id}/text", headers=ticket()).status_code == 200
    assert journal_rows(tmp_path) == []  # nothing was written, nothing was raised


def test_rows_rotate_one_file_per_utc_day(tmp_path):
    journal = RequestJournal(tmp_path)
    journal.append({"ts": "2026-10-30T22:02:03.000+00:00", "method": "POST", "path": "/files",
                    "status": 201, "error_code": None, "duration_ms": 1.0, "file_size": 5})
    journal.append({"ts": "2026-10-31T05:24:00.000+00:00", "method": "GET",
                    "path": "/files/file_" + "a" * 32 + "/text", "status": 422,
                    "error_code": "ooxml_encrypted", "duration_ms": 2.0, "file_size": None})
    assert sorted(path.name for path in (tmp_path / "journal").iterdir()) == [
        "requests-2026-10-30.jsonl", "requests-2026-10-31.jsonl"]
    first = (tmp_path / "journal" / "requests-2026-10-30.jsonl").read_text(encoding="utf-8")
    assert json.loads(first)["ts"].startswith("2026-10-30")
