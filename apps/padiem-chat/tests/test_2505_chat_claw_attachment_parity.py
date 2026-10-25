"""#2505 Task A: the Claw turn reads the same attachment as the Chat turn.

The owner decision (2026-10-21) makes the ten Chat/Claw capabilities shared, and
the #2505 audit found file attachment MISSING on Claw. This file proves the fix
on the contract the audit named, not on a new one:

* ``POST /api/claw/general`` accepts the SAME ``attachments`` array Chat accepts
  and reads it through the same parser (``app/attachments.py``);
* a document becomes the same untrusted reference context Chat builds
  (``app/documents.py`` ``build_document_context``) and travels on the existing
  ``additional_system_context`` seam, so the Engine request type is unchanged;
* a binary original (PDF/DOCX/PPTX/XLSX) uses the same octet-stream frame Chat
  already accepts, decoded by the one shared decoder;
* the Chat lane keeps its own behaviour: same request shape, same route, same
  document context;
* an image is refused on Claw because the canonical P01 Engine execution request
  has no image input yet — it is refused before quota, dispatch or provider.

Network-free: the adapter is a fake and no model/provider is called.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.binary_attachment_frame import decode_binary_attachment_frame
from app.claw_attachment_context import (
    CLAW_IMAGE_ATTACHMENT_UNSUPPORTED,
    parse_claw_turn_attachments,
)
from app.config import Settings
from app.documents import build_document_context
from app.attachments import AttachmentValidationError, parse_attachments

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
LOCALE_JS = (ROOT / "static" / "locale.js").read_text(encoding="utf-8")
TRANSPORT_JS = (ROOT / "static" / "chat-transport.js").read_text(encoding="utf-8")
CHAT_ROUTES = (ROOT / "app" / "chat_routes.py").read_text(encoding="utf-8")
GENERAL = (ROOT / "app" / "claw_general_routes.py").read_text(encoding="utf-8")

DOCUMENT_TEXT = "2026년 3분기 매출은 1억 2천만원입니다."
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _minimal_text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=320, height=180)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 14 Tf 36 90 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class _AuthStore:
    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id):
        return None


def _settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="claw-attachment-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret="synthetic-secret-for-tests-only-not-real",
        session_max_age_seconds=3600,
    )


@contextmanager
def _client(adapter):
    settings = _settings()
    app = create_app(settings=settings, history_store=_AuthStore(), claw_p01_adapter=adapter)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, "usr_" + "9" * 32),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


class _Adapter:
    """The canonical P01 adapter surface this route calls, without an Engine."""

    subject_identity_lane = False

    def __init__(self):
        self.calls = []

    async def execute(self, run, **kwargs):
        self.calls.append(kwargs)

        class _Projection:
            status = type("S", (), {"value": "completed"})()
            run_id = "run_attachment"

        class _Outcome:
            projection = _Projection()
            answer = "문서를 읽었습니다."
            p01_run_id = "p01_attachment"
            p01_event_count = 1

        return _Outcome()


def _payload(text: str = "첨부한 문서를 요약해 주세요", **extra):
    payload = {"messages": [{"role": "user", "content": text}]}
    payload.update(extra)
    return payload


def _binary_frame(metadata: dict, original: bytes) -> bytes:
    header = json.dumps(metadata).encode("utf-8")
    return len(header).to_bytes(4, "big") + header + original


# ── server: the shared attachment boundary ───────────────────────────────────


def test_the_claw_turn_reads_a_document_with_the_chat_parser():
    context, images = parse_claw_turn_attachments(
        [{"type": "document", "name": "report.txt", "media_type": "text/plain", "text": DOCUMENT_TEXT}]
    )
    # The same public projection Chat renders, produced by the same builder.
    expected = build_document_context(
        parse_attachments(
            [{"type": "document", "name": "report.txt", "media_type": "text/plain", "text": DOCUMENT_TEXT}]
        )[0]
    )
    assert context == expected
    assert images == ()
    # The document is reference data, never an instruction.
    assert "신뢰되지 않은 참고 데이터" in context
    assert DOCUMENT_TEXT in context


def test_the_claw_turn_keeps_the_chat_attachment_refusals():
    for bad in (
        [{"type": "document", "name": "a.exe", "media_type": "application/x-msdownload", "text": "x"}],
        [{"type": "document", "name": "a.txt", "media_type": "text/plain", "text": "x"},
         {"type": "document", "name": "b.txt", "media_type": "text/plain", "text": "y"}],
        "not-a-list",
    ):
        with pytest.raises(AttachmentValidationError):
            parse_claw_turn_attachments(bad)


def test_the_claw_turn_reports_an_image_for_the_route_to_refuse():
    _, images = parse_claw_turn_attachments(
        [{
            "type": "image",
            "name": "shot.png",
            "media_type": "image/png",
            "base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AGtNwAAAABJRU5ErkJggg==",
        }]
    )
    assert len(images) == 1


def test_a_document_is_sent_to_the_engine_as_shared_reference_context():
    adapter = _Adapter()
    with _client(adapter) as client:
        response = client.post(
            "/api/claw/general",
            json=_payload(
                attachments=[{
                    "type": "document", "name": "report.txt",
                    "media_type": "text/plain", "text": DOCUMENT_TEXT,
                }],
            ),
        )
    assert response.status_code == 200
    assert len(adapter.calls) == 1
    context = adapter.calls[0]["additional_system_context"]
    assert isinstance(context, str)
    assert DOCUMENT_TEXT in context
    assert "신뢰되지 않은 참고 데이터" in context
    # The Engine request type is untouched: no attachment argument exists.
    assert "attachments" not in adapter.calls[0]


def test_a_binary_document_travels_in_the_frame_chat_already_accepts():
    # A PDF text object is ASCII here: the point is the shared frame and the
    # shared decoder, not a Korean font embedding.
    pdf = _minimal_text_pdf("Q3 2026 revenue 120M")
    adapter = _Adapter()
    frame = _binary_frame(
        {
            "messages": [{"role": "user", "content": "이 PDF를 요약해 주세요"}],
            "attachments": [
                {"type": "document", "name": "report.pdf", "media_type": "application/pdf"}
            ],
        },
        pdf,
    )
    with _client(adapter) as client:
        response = client.post(
            "/api/claw/general",
            content=frame,
            headers={"content-type": "application/octet-stream"},
        )
    assert response.status_code == 200, response.text
    context = adapter.calls[0]["additional_system_context"]
    assert "report.pdf" in context
    assert "application/pdf" in context


def test_the_chat_and_claw_lanes_decode_the_same_binary_frame():
    pdf = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
    frame = _binary_frame(
        {
            "messages": [{"role": "user", "content": "요약"}],
            "attachments": [{"type": "document", "name": "a.pdf", "media_type": "application/pdf"}],
        },
        pdf,
    )
    parsed = decode_binary_attachment_frame(frame)
    assert parsed["attachments"][0]["raw_bytes"] == pdf
    # Chat keeps its own module-level alias, so both lanes share one decoder.
    from app.chat_routes import _decode_completed_binary_attachment

    assert _decode_completed_binary_attachment(frame)["attachments"][0]["raw_bytes"] == pdf


def test_an_image_is_refused_before_dispatch_on_the_claw_lane():
    adapter = _Adapter()
    with _client(adapter) as client:
        response = client.post(
            "/api/claw/general",
            json=_payload(
                attachments=[{
                    "type": "image", "name": "shot.png", "media_type": "image/png",
                    "base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AGtNwAAAABJRU5ErkJggg==",
                }],
            ),
        )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "claw_image_attachment_unsupported"
    assert body["message"] == CLAW_IMAGE_ATTACHMENT_UNSUPPORTED
    assert adapter.calls == []


def test_an_invalid_attachment_is_refused_before_dispatch():
    adapter = _Adapter()
    with _client(adapter) as client:
        response = client.post(
            "/api/claw/general",
            json=_payload(attachments=[{"type": "document", "name": "a.exe",
                                        "media_type": "application/x-msdownload", "text": "x"}]),
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_attachment"
    assert adapter.calls == []


def test_a_document_is_not_silently_dropped_on_a_pc_lane():
    adapter = _Adapter()
    with _client(adapter) as client:
        response = client.post(
            "/api/claw/general",
            json=_payload(
                "내 PC에 데이터베이스가 있나?",
                attachments=[{
                    "type": "document", "name": "report.txt",
                    "media_type": "text/plain", "text": DOCUMENT_TEXT,
                }],
            ),
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "attachment_lane_unsupported"
    assert adapter.calls == []


def test_the_claw_route_reuses_the_shared_parser_and_builder():
    # Reuse, not a second attachment implementation.
    assert "parse_claw_turn_attachments" in GENERAL
    assert "decode_binary_attachment_frame" in GENERAL
    assert "build_document_context" not in GENERAL  # the helper owns it
    assert "from .binary_attachment_frame import decode_binary_attachment_frame" in CHAT_ROUTES


# ── browser: one composer, one attachment wire ───────────────────────────────


def test_a_claw_submit_sends_the_attachment_on_the_claw_lane():
    submit = APP_JS[APP_JS.index("async function requestAnswer("):]
    submit = submit[: submit.index("\n  }")]
    # The Claw lane no longer refuses an attachment…
    assert "claw-model-text-only-error" not in APP_JS
    assert "claw-model-text-only-error" not in LOCALE_JS
    # …and the attachment never silently moves to the Chat route.
    assert "if (attachments && !clawGeneralRequest)" in APP_JS
    assert "if (clawGeneralRequest && attachments)" not in APP_JS
    assert "payload.attachments = attachments;" in APP_JS


def test_the_two_lanes_share_one_attachment_request_body():
    assert "function attachmentRequestBody(wire)" in TRANSPORT_JS
    request_completed = TRANSPORT_JS[TRANSPORT_JS.index("async function requestCompleted("):]
    request_claw = TRANSPORT_JS[TRANSPORT_JS.index("async function requestClawGeneral("):]
    assert "attachmentRequestBody(wire)" in request_completed
    assert "attachmentRequestBody(wired)" in request_claw
    assert '"Content-Type": requestContentType' in request_claw
    # Chat's route is unchanged.
    assert 'fetch("/api/chat"' in request_completed


def test_the_browser_refuses_a_claw_image_before_upload():
    assert "claw-image-attachment-unsupported" in LOCALE_JS
    assert "Claw는 아직 사진 첨부를 모델에 전달할 수 없습니다" in LOCALE_JS
    select = APP_JS[APP_JS.index("async function selectAttachment("):]
    select = select[: select.index("\n  }")]
    assert "conversationProduct === PRODUCT_CLAW" in select
    assert 'uiT("claw-image-attachment-unsupported")' in select
