"""#5881: a parser refusal keeps its constant reason code on the way out.

Core refuses a document with a constant reason code and Chat already carries
per-code guidance for those codes (#6316). The lane used to flatten every
parser exception into parse_failed, so the owner read "읽지 못했습니다" for a
password they set themselves. Only the code crosses here: an exception's
message text can carry document content and is never passed, logged or echoed.
"""

from __future__ import annotations

from io import BytesIO
import importlib
import json
from pathlib import Path
import sys
import time
import base64
import hashlib
import hmac

import pytest
from starlette.testclient import TestClient

from padiem_file_lane import storage
from padiem_file_lane.app import create_app
from padiem_file_lane.tickets import PROOF_HEADER, TIME_HEADER, TICKET_HEADER

SECRET = "offline-file-lane-test-secret-000000000000"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


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


def upload(client, data, name):
    return client.post("/files", params={"filename": name}, content=data, headers=ticket())


def text_response(client, file_id):
    return client.get(f"/files/{file_id}/text", headers=ticket())


def _docx_xml(text: str = "SAFE") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    ).encode()


def _ole_encrypted_package() -> bytes:
    """OLE signature plus a UTF-16LE ``EncryptedPackage`` directory name.

    Office writes a password-protected package this way; the fixture only has
    to reach Core's classifier, exactly as the Chat-side suite builds it.
    """

    return OLE_MAGIC + b"\x00" * 504 + "EncryptedPackage".encode("utf-16-le") + b"\x00\x00"


def _docx_local_header_encrypted() -> bytes:
    from zipfile import ZIP_DEFLATED, ZipFile

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", _docx_xml())
    data = bytearray(output.getvalue())
    index = data.find(b"PK\x03\x04")
    data[index + 6] |= 0x01
    return bytes(data)


def _plain_docx() -> bytes:
    from zipfile import ZIP_DEFLATED, ZipFile

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", _docx_xml())
    return output.getvalue()


def _encrypted_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("padiem-test")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("secret.docx", _ole_encrypted_package()),
        ("locked.docx", _docx_local_header_encrypted()),
    ],
)
def test_encrypted_docx_keeps_ooxml_encrypted_end_to_end(client, tmp_path, name, payload):
    result = upload(client, payload, name).json()
    response = text_response(client, result["file_id"])
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": {"code": "ooxml_encrypted"}}
    # The body carries the code and nothing else: no parser message text, no
    # marker from the document itself.
    assert "Password-protected" not in response.text
    assert "EncryptedPackage" not in response.text
    assert not list(tmp_path.rglob("*.part")) and not list(tmp_path.rglob("text-v2.txt"))


def test_encrypted_pdf_keeps_pdf_encrypted_end_to_end(client, tmp_path):
    result = upload(client, _encrypted_pdf(), "locked.pdf").json()
    response = text_response(client, result["file_id"])
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": {"code": "pdf_encrypted"}}
    # Core's message text ("Encrypted PDF documents are not supported.") never
    # reaches the body; only the lower-case code constant does.
    assert "Encrypted" not in response.text
    assert not list(tmp_path.rglob("*.part")) and not list(tmp_path.rglob("text-v2.txt"))


def test_exception_outside_the_allowlist_stays_parse_failed(client, tmp_path):
    # Not a Core rejection code at all: the text reader fails before Core, and
    # nothing here is allowed to invent a reason for it.
    file_id = upload(client, b"\xff\xfeinvalid", "bytes.txt").json()["file_id"]
    response = text_response(client, file_id)
    assert response.status_code == 422
    assert response.json() == {"ok": False, "error": {"code": "parse_failed"}}
    assert not list(tmp_path.rglob("text-v2.txt"))


def test_plain_docx_still_extracts_after_the_passthrough(client):
    result = upload(client, _plain_docx(), "report.docx").json()
    response = text_response(client, result["file_id"])
    assert response.status_code == 200 and "SAFE" in response.text


def test_reason_code_allowlist_is_codes_only_and_within_the_core_catalog():
    codes = storage.PARSER_REASON_CODES
    # Every entry is a bare code string, never a message.
    assert all(isinstance(code, str) and " " not in code for code in codes)
    for expected in ("ooxml_encrypted", "pdf_encrypted", "ooxml_link_entry",
                     "ooxml_malformed", "ooxml_entry_size"):
        assert expected in codes
    # Identity/caller codes and formats the lane never parses stay out.
    for outside in ("invalid_name", "name_required", "unsupported_binary_media_type",
                    "media_extension_mismatch", "invalid_binary_payload", "hwpx_missing_part",
                    "parse_failed", "disk_full"):
        assert outside not in codes


def test_chat_guidance_picks_the_encrypted_copy_for_the_real_core_code():
    # The Chat half of the round trip: the real Core parser refuses the same
    # bytes with the real exception, and Chat's per-code translation (#6316)
    # selects the encrypted-document wording from that code alone.
    from padiem_ai_core.document_normalization import DocumentNormalizationError, extract_binary_document

    chat_root = Path(__file__).resolve().parents[2] / "padiem-chat"
    if str(chat_root) not in sys.path:
        sys.path.insert(0, str(chat_root))
    binary_documents = importlib.import_module("app.binary_documents")

    with pytest.raises(DocumentNormalizationError) as refused:
        extract_binary_document(name="file.docx", media_type=DOCX_MIME,
                                payload=_ole_encrypted_package())
    assert refused.value.code == "ooxml_encrypted"

    translated = binary_documents._translate_binary_error(refused.value, DOCX_MIME)
    assert str(translated) == "암호화된 DOCX는 현재 첨부할 수 없습니다."

    with pytest.raises(DocumentNormalizationError) as locked:
        extract_binary_document(name="file.docx", media_type=DOCX_MIME,
                                payload=_docx_local_header_encrypted())
    assert locked.value.code == "ooxml_encrypted"
    assert str(binary_documents._translate_binary_error(locked.value, DOCX_MIME)) == (
        "암호화된 DOCX는 현재 첨부할 수 없습니다.")
