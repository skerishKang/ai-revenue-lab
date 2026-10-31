from __future__ import annotations

import base64
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import time

import anyio
import pytest
from starlette.testclient import TestClient

from padiem_file_lane.app import create_app
from padiem_file_lane import storage
from padiem_file_lane.tickets import PROOF_HEADER, TIME_HEADER, TICKET_HEADER, verify_ticket

SECRET = "offline-file-lane-test-secret-000000000000"


def ticket(user="usr_alice", maximum=10_000_000, *, expires=None, secret=SECRET, stamp=None):
    stamp = str(int(time.time())) if stamp is None else stamp
    raw = json.dumps({"user_id": user, "max_bytes": maximum,
                      "expires": int(time.time()) + 600 if expires is None else expires}, separators=(",", ":")).encode()
    proof = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {TICKET_HEADER: base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
            TIME_HEADER: stamp, PROOF_HEADER: proof}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(root=tmp_path, secret=SECRET)) as client:
        yield client


def upload(client, data=b"hello", name="hello.txt", headers=None):
    return client.post("/files", params={"filename": name}, content=data,
                       headers=headers if headers is not None else ticket())


def test_proof_matches_existing_chat_b14_construction():
    root = Path(__file__).resolve().parents[2]
    existing = runpy.run_path(str(root / "padiem-chat/app/b14_service_proof.py"))
    raw = json.dumps({"user_id": "usr_alice", "max_bytes": 100, "expires": int(time.time()) + 600}).encode()
    proof = existing["service_proof_headers"](SECRET, raw)
    headers = {TICKET_HEADER: base64.urlsafe_b64encode(raw).decode(),
               TIME_HEADER: proof["X-Padiem-B14-Time"], PROOF_HEADER: proof["X-Padiem-B14-Proof"]}
    assert verify_ticket(headers, SECRET).user_id == "usr_alice"


@pytest.mark.parametrize("headers", [
    {}, ticket(secret="different-deployment-secret-000000000000000"),
    ticket(expires=1), ticket(stamp="not-a-time"), ticket(stamp=str(int(time.time()) + 3600)),
    ticket(user="../escape"), ticket(user=".."), ticket(user="alice/bob"),
    ticket(maximum=-1), ticket(maximum=True),
])
def test_invalid_tickets_cannot_store_or_read(client, tmp_path, headers):
    response = upload(client, headers=headers)
    assert response.status_code == 401
    assert client.get("/files/file_" + "a" * 32 + "/meta", headers=headers).status_code == 401
    # The request journal (#6338 follow-up) is the one allowed disk trace; an
    # unauthenticated attempt still creates no owner directory and stores no bytes.
    assert [path.name for path in tmp_path.iterdir() if path.name != "journal"] == []


def test_tampering_any_signed_claim_is_rejected(client):
    headers = ticket()
    headers[TICKET_HEADER] = ticket(user="usr_other")[TICKET_HEADER]
    assert upload(client, headers=headers).status_code == 401


@pytest.mark.parametrize("name,data,kind", [
    ("한글.txt", "한글🙂".encode(), "txt"), ("report.md", b"# report\n", "md"),
    ("table.csv", b"\xef\xbb\xbfcol1,col2\n1,2\n", "csv"),
])
def test_upload_hash_size_owner_meta_and_text(client, tmp_path, name, data, kind):
    result = upload(client, data, name).json()
    assert result["ok"] is True and result["size_bytes"] == len(data)
    assert result["sha256"] == hashlib.sha256(data).hexdigest() and result["kind"] == kind
    file_id = result["file_id"]
    saved = tmp_path / hashlib.sha256(b"usr_alice").hexdigest() / file_id
    assert (saved / "data").read_bytes() == data
    meta = client.get(f"/files/{file_id}/meta", headers=ticket()).json()
    assert meta == result
    response = client.get(f"/files/{file_id}/text", headers=ticket())
    assert response.status_code == 200 and response.text == data.decode("utf-8-sig")
    assert response.headers["cache-control"] == "no-store"
    assert client.get(f"/files/{file_id}/meta", headers=ticket(user="usr_bob")).status_code == 404
    assert client.get(f"/files/{file_id}/text", headers=ticket(user="usr_bob")).status_code == 404
    # A second process can read the durable metadata and cached parse result.
    with TestClient(create_app(root=tmp_path, secret=SECRET)) as restarted:
        assert restarted.get(f"/files/{file_id}/text", headers=ticket()).text == response.text


def pdf_bytes():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (COM2 PDF text) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_text_is_extracted_on_disk(client):
    result = upload(client, pdf_bytes(), "sample.pdf").json()
    response = client.get(f'/files/{result["file_id"]}/text', headers=ticket())
    assert response.status_code == 200 and "COM2 PDF text" in response.text


@pytest.mark.parametrize("name,data,status", [("sample.hwp", b"unsupported", 415),
    ("../evil.txt", b"x", 400), ("empty.txt", b"", 422), ("fake.pdf", b"not pdf", 422)])
def test_invalid_uploads_leave_no_partial_files(client, tmp_path, name, data, status):
    assert upload(client, data, name).status_code == status
    assert not list(tmp_path.rglob("data*")) and not list(tmp_path.rglob("meta*"))


def test_size_ticket_and_disk_space_are_enforced(client, tmp_path, monkeypatch):
    assert upload(client, b"1234", headers=ticket(maximum=3)).status_code == 413
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 0})())
    assert upload(client).status_code == 507
    assert not list(tmp_path.rglob("data*"))


def test_parser_failure_does_not_publish_partial_text(client, tmp_path):
    file_id = upload(client, b"\xff\xfeinvalid", "bytes.txt").json()["file_id"]
    assert client.get(f"/files/{file_id}/text", headers=ticket()).status_code == 422
    assert not list(tmp_path.rglob("*.part")) and not list(tmp_path.rglob("text-v2.txt"))


@pytest.mark.parametrize("mode", ["complete", "oversize", "disconnect", "disk_full"])
def test_asgi_chunks_are_written_before_reading_the_next_chunk(tmp_path, monkeypatch, mode):
    app = create_app(root=tmp_path, secret=SECRET)
    received, sent, written = [], [], []
    original_write = storage.Upload.write
    def write(self, block, maximum):
        original_write(self, block, maximum)
        written.append(block)
    monkeypatch.setattr(storage.Upload, "write", write)
    data = [b"abc", "🙂".encode(), b"tail"]
    async def receive():
        index = len(received)
        if index:
            partial = list(tmp_path.rglob("data.part"))
            assert len(partial) == 1
            assert written == data[:index]  # Storage was called before receive.
        received.append(index)
        if mode == "disconnect" and index == 1:
            return {"type": "http.disconnect"}
        if mode == "disk_full" and index == 1:
            monkeypatch.setattr(storage.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 0})())
        return {"type": "http.request", "body": data[index], "more_body": index < 2}
    async def send(event):
        sent.append(event)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/files", "raw_path": b"/files", "query_string": b"filename=chunks.txt",
        "headers": [(k.encode(), v.encode()) for k,v in ticket(maximum=5 if mode == "oversize" else 100).items()],
        "server": ("localhost", 8788), "client": ("localhost", 1234)}
    async def run():
        await app(scope, receive, send)
    anyio.run(run)
    status = sent[0]["status"]
    assert status == {"complete": 201, "oversize": 413, "disconnect": 400, "disk_full": 507}[mode]
    if mode == "complete":
        result = json.loads(sent[1]["body"])
        assert result["sha256"] == hashlib.sha256(b"".join(data)).hexdigest()
    else:
        assert len(received) == 2 and not list(tmp_path.rglob("data*"))
    assert not list(tmp_path.rglob("*.part"))


def test_default_startup_is_local_and_access_log_disabled(tmp_path, monkeypatch):
    from padiem_file_lane.__main__ import server
    monkeypatch.setenv("FILE_LANE_ROOT", str(tmp_path))
    monkeypatch.setenv("FILE_LANE_TICKET_SECRET", SECRET)
    instance = server()
    assert instance.config.host == "127.0.0.1" and not instance.config.access_log
    assert not instance.config.proxy_headers


def test_windows_service_wrapper_is_importable_without_installing():
    from padiem_file_lane import windows_service
    if sys.platform == "win32":
        assert windows_service.FileLaneService._svc_name_ == "PadiemFileLane"
    else:
        with pytest.raises(SystemExit):
            windows_service.main()


def test_real_local_process_serves_health_and_stops(tmp_path, monkeypatch):
    import os
    import httpx
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, FILE_LANE_ROOT=str(tmp_path), FILE_LANE_TICKET_SECRET=SECRET, FILE_LANE_PORT=str(port))
    process = subprocess.Popen([sys.executable, "-m", "padiem_file_lane"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("local service process exited before health")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", trust_env=False).json() == {"ok": True}:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            pytest.fail("local service did not become ready")
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.parametrize("other", ["usr_ALICE", "usr_alice."])
def test_windows_path_aliases_do_not_share_an_owner_namespace(client, other):
    file_id = upload(client).json()["file_id"]
    assert client.get(f"/files/{file_id}/meta", headers=ticket(user=other)).status_code == 404


def test_browser_preflight_accepts_only_configured_chat_origin(tmp_path):
    with TestClient(create_app(root=tmp_path, secret=SECRET, origins=["https://chat.example.test"])) as client:
        response = client.options("/files", headers={"Origin": "https://chat.example.test",
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": TICKET_HEADER + "," + TIME_HEADER + "," + PROOF_HEADER})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://chat.example.test"
        assert response.headers["access-control-allow-credentials"] == "true"
        response = client.options("/files", headers={"Origin": "https://elsewhere.example.test", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in response.headers


def test_upload_above_worker_scale_is_stored_without_a_fixed_ten_mb_ceiling(client):
    data = b"x" * (11 * 1024 * 1024)
    response = upload(client, data, headers=ticket(maximum=len(data)))
    assert response.status_code == 201
    assert response.json()["size_bytes"] == len(data)
    assert response.json()["sha256"] == hashlib.sha256(data).hexdigest()
