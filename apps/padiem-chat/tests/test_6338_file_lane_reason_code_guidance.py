"""#6338: the file-lane resolve path speaks the lane's reason code.

The lane answers a failed text read with ``{"ok": false, "error": {"code": ...}}``
and only a constant reason code may cross (the #5881 lane allowlist). This file
pins the last hop the production check found missing: Chat's ``FileLaneClient.
resolve`` picks the per-code guidance (#6316 wording, one authority in
``binary_documents.guidance_for_reason_code``) from that code, and anything
unmapped or unparseable keeps the generic wording. Every round trip here runs
the real lane app over real HTTPS, the real ``FileLaneClient``, and the real
``/api/chat`` route — no parser doubles.
"""

from __future__ import annotations

import datetime
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time

import httpx
import pytest
from starlette.testclient import TestClient
import uvicorn

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.file_lane import ticket_headers

ROOT = Path(__file__).resolve().parents[1]
LANE_SRC = ROOT.parent / "padiem-file-lane" / "src"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
LANE_SECRET = "chat-file-lane-roundtrip-test-secret-00000000"
GENERAL_WORDING = "첨부 문서의 텍스트를 읽지 못했습니다."
ENCRYPTED_DOCX_WORDING = "암호화된 DOCX는 현재 첨부할 수 없습니다."


def _encrypted_docx() -> bytes:
    """OLE wrapper + ``EncryptedPackage`` marker: Core classifies it encrypted."""
    return (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
            + "EncryptedPackage".encode("utf-16-le") + b"\x00\x00")


def _plain_docx() -> bytes:
    from zipfile import ZIP_DEFLATED, ZipFile

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SAFE</w:t></w:r></w:p>'
            "</w:body></w:document>".encode(),
        )
    return output.getvalue()


_CERT: dict = {}


def _self_signed_context() -> tuple[ssl.SSLContext, Path, Path]:
    """One loopback certificate the lane serves and every client trusts."""
    if _CERT:
        return _CERT["context"], _CERT["cert_path"], _CERT["key_path"]
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    directory = Path(tempfile.mkdtemp(prefix="lane-6338-cert-"))
    cert_path = directory / "lane-test-cert.pem"
    key_path = directory / "lane-test-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    context = ssl.create_default_context(cadata=cert.public_bytes(serialization.Encoding.PEM).decode())
    _CERT.update(context=context, cert_path=cert_path, key_path=key_path)
    return context, cert_path, key_path


@pytest.fixture(scope="module")
def lane_origin(tmp_path_factory):
    """The real lane app serving real HTTPS on a loopback port."""
    import sys

    sys.path.insert(0, str(LANE_SRC))
    from padiem_file_lane.app import create_app as create_lane_app

    root = tmp_path_factory.mktemp("lane-root")
    context, cert_path, key_path = _self_signed_context()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(
        create_lane_app(root=root, secret=LANE_SECRET),
        host="127.0.0.1", port=port, log_level="error", access_log=False,
        ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "real lane did not start"
    yield f"https://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def chat_client(lane_origin):
    """The real Chat app wired to the real lane origin, with a signed-in owner."""
    transport = httpx.AsyncHTTPTransport(verify=_self_signed_context()[0])

    class _HistoryStore:
        async def get_user(self, user_id):
            return {"user_id": user_id}

        async def get_conversation(self, user_id, conversation_id):
            return None

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="file-lane-reason-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret="synthetic-secret-for-tests-only-not-real",
        session_max_age_seconds=3600,
    )
    from app.file_lane import FileLaneClient

    client = FileLaneClient(lane_origin, LANE_SECRET, transport=transport)
    app = create_app(settings=settings, history_store=_HistoryStore(), file_lane_client=client)
    test = TestClient(app, base_url="https://chat.example.test")
    user = "usr_" + "6" * 32
    test.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, user),
        domain="chat.example.test",
        path="/",
    )
    test.padiem_user = user
    with test:
        yield test


def _upload_to_lane(user: str, name: str, data: bytes) -> str:
    """The browser's own upload step: ticket mint -> POST /files -> file_id."""
    headers, _expires = ticket_headers(LANE_SECRET, user, 10_000_000)
    response = httpx.post(
        f"https://127.0.0.1:{_lane_port()}/files", params={"filename": name},
        content=data, headers=headers, verify=_self_signed_context()[0], timeout=10,
    )
    assert response.status_code == 201, response.text
    return response.json()["file_id"]


_PORT_HOLDER = {}


def _lane_port() -> int:
    return _PORT_HOLDER["port"]


@pytest.fixture(scope="module", autouse=True)
def _remember_port(lane_origin):
    _PORT_HOLDER["port"] = int(lane_origin.rsplit(":", 1)[1])
    yield


def _chat_with_attachment(chat_client, file_id: str):
    return chat_client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "첨부한 문서를 요약해 주세요."}],
              "attachments": [{"type": "file", "file_id": file_id}]},
    )


def test_encrypted_docx_guidance_reaches_the_api_chat_response(chat_client):
    file_id = _upload_to_lane(chat_client.padiem_user, "secret.docx", _encrypted_docx())
    response = _chat_with_attachment(chat_client, file_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["message"] == ENCRYPTED_DOCX_WORDING
    # The lane body's marker and any parser text stay behind: the code alone crossed.
    assert "EncryptedPackage" not in response.text
    assert "ooxml_encrypted" not in response.text


def test_plain_docx_still_parses_through_the_full_chain(chat_client):
    file_id = _upload_to_lane(chat_client.padiem_user, "report.docx", _plain_docx())
    response = _chat_with_attachment(chat_client, file_id)
    # A readable document must NOT fail at the attachment boundary: the mock
    # runtime answers the turn instead of returning a 422 refusal.
    assert response.status_code != 422, response.text
    assert GENERAL_WORDING not in response.text


def test_lane_code_outside_the_allowlist_keeps_the_generic_wording(chat_client):
    # A non-UTF8 text document makes the lane answer parse_failed (its own
    # pre-Core read failure), which is not an allowlisted reason code.
    file_id = _upload_to_lane(chat_client.padiem_user, "bytes.txt", b"\xff\xfeinvalid")
    response = _chat_with_attachment(chat_client, file_id)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["message"] == GENERAL_WORDING


def test_unparseable_lane_body_keeps_the_generic_wording():
    # The defensive branch of the refusal reader: a body that never becomes a
    # code keeps the generic wording. Scoped to the helper — the lane round
    # trips above cover the real lane's own responses.
    import asyncio

    from app.file_lane import _lane_refusal_message

    class _StubResponse:
        async def aread(self):
            return b"<html>not the lane json</html>"

    message = asyncio.run(_lane_refusal_message(_StubResponse(), DOCX_MIME))
    assert message == GENERAL_WORDING


def test_chat_allowlist_matches_the_lane_allowlist_source():
    """One catalog: the Chat set equals the lane's PARSER_REASON_CODES (#6338)."""
    from app.file_lane import REASON_CODES

    lane_storage = (ROOT.parent / "padiem-file-lane" / "src" / "padiem_file_lane" / "storage.py").read_text(
        encoding="utf-8"
    )
    start = lane_storage.index("PARSER_REASON_CODES = frozenset({")
    end = lane_storage.index("})", start)
    import re

    lane_codes = set(re.findall(r'"([a-z_]+)"', lane_storage[start:end]))
    assert lane_codes == set(REASON_CODES)
    assert "ooxml_encrypted" in REASON_CODES and "parse_failed" not in REASON_CODES



@pytest.mark.parametrize("encrypted", [True, False], ids=["encrypted-docx", "ordinary-parser-failure"])
def test_lane_refusal_survives_browser_transport(chat_client, encrypted):
    """Pass a real lane/Chat refusal through the actual browser transport."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to exercise the browser transport")
    name, data = ("secret.docx", _encrypted_docx()) if encrypted else ("bytes.txt", b"\xff\xfeinvalid")
    file_id = _upload_to_lane(chat_client.padiem_user, name, data)
    response = _chat_with_attachment(chat_client, file_id)
    assert response.status_code == 422
    script = r"""
      const fs = require("fs");
      global.window = {};
      const payload = JSON.parse(fs.readFileSync(0, "utf8"));
      global.fetch = async () => ({ok: false, status: 422, json: async () => payload});
      require(process.argv[1]);
      window.PadiemChatTransport.requestCompleted({messages: []})
        .then(() => { process.exitCode = 1; })
        .catch(error => { process.stdout.write(JSON.stringify({message: error.message, code: error.code})); });
    """
    result = subprocess.run(
        [node, "-e", script, str(ROOT / "static" / "chat-transport.js")],
        input=response.text, text=True, encoding="utf-8", capture_output=True, check=True,
    )
    error = json.loads(result.stdout)
    assert error == {
        "message": ENCRYPTED_DOCX_WORDING if encrypted else GENERAL_WORDING,
        "code": "invalid_request",
    }
    assert "EncryptedPackage" not in result.stdout
    assert "ooxml_encrypted" not in result.stdout
