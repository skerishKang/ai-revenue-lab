"""#2824: Chat Worker -> isolated Parser Authority transport contract.

The real parser runs in the standalone ``padiem-document-parser`` Worker. This
suite proves the Chat side of that boundary without deploying it:

* the Service Binding transport sends exactly one bounded Core envelope to the
  fixed internal URL and returns the bounded response bytes;
* the async authority is installed by trusted composition and fails closed
  when the binding is absent;
* real synthetic PDF/DOCX/PPTX/XLSX bytes cross the wire, are parsed by the
  real Core parser through the parser-side handler, and keep their provenance;
* a service outage or a non-success status becomes one clear bounded error;
* text/image attachments and the existing Chat attachment grammar are
  unchanged;
* request input cannot smuggle an owner/account field or bypass the intake
  gate, and the wire carries no user or workspace identity;
* ``/health`` reports the readiness the request path actually resolves.

These are contract/integration tests with an in-memory fake binding. The
production Worker deployment and live service-binding invocation are verified
separately after the CTO freeze is released.
"""

from __future__ import annotations

import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from app.attachments import AttachmentValidationError, parse_attachments_async
from app.document_parser_transport import (
    DOCUMENT_PARSER_SERVICE_ORIGIN,
    DOCUMENT_PARSER_SERVICE_PATH,
    CloudflareDocumentParserServiceTransport,
)
from app.documents import build_document_context
from padiem_ai_core.document_parser_boundary import (
    PRODUCTION_WORKER_PLATFORM,
    clear_worker_isolated_parser_async_composition,
    binary_document_parser_ready_async,
    install_worker_isolated_parser_async_composition,
)
from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.isolated_parser_async_client import IsolatedParserAsyncClient
from padiem_ai_core.isolated_parser_composition import (
    compose_worker_isolated_parser_authority,
    compose_worker_isolated_parser_authority_async,
    reset_worker_isolated_parser_async_composition,
    reset_worker_isolated_parser_composition,
)
from padiem_ai_core.isolated_parser_contract import ISOLATED_PARSER_RESPONSE_UNBOUNDED
from padiem_ai_core.isolated_parser_service import handle_isolated_parser_request

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

AUTHORITY_MESSAGE = "현재 실행 환경에서는 격리된 문서 파서를 사용할 수 없어 문서를 처리할 수 없습니다."
OUTAGE_MESSAGE = "문서 파서 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
RESPONSE_INVALID_MESSAGE = "문서 파서 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요."

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_parser_composition():
    reset_worker_isolated_parser_async_composition()
    reset_worker_isolated_parser_composition()
    yield
    reset_worker_isolated_parser_async_composition()
    reset_worker_isolated_parser_composition()


# --- synthetic documents ------------------------------------------------------


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _text_pdf(pages: list[str]) -> bytes:
    PdfWriter = pytest.importorskip("pypdf").PdfWriter
    generic = pytest.importorskip("pypdf.generic")
    writer = PdfWriter()
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
            generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=320, height=180)
        page[generic.NameObject("/Resources")] = generic.DictionaryObject(
            {
                generic.NameObject("/Font"): generic.DictionaryObject(
                    {generic.NameObject("/F1"): font_ref}
                )
            }
        )
        content = generic.DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.set_data(f"BT /F1 14 Tf 36 90 Td ({escaped}) Tj ET".encode("ascii"))
        page[generic.NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _docx_xml() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>Padiem body paragraph</w:t></w:r></w:p>"
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Item</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>Alpha</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "</w:tbl>"
        "<w:p><w:r><w:t>Padiem closing paragraph</w:t></w:r></w:p>"
        "</w:body></w:document>"
    ).encode()


def _pptx_xml(text: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>'
        + text
        + "</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    ).encode()


def _xlsx_bytes() -> bytes:
    Workbook = pytest.importorskip("openpyxl").Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Revenue"
    sheet["A1"] = "Month"
    sheet["B1"] = "Amount"
    sheet["A2"] = "January"
    sheet["B2"] = 10
    sheet["A3"] = "February"
    sheet["B3"] = 20
    sheet["B4"] = "=SUM(B2:B3)"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


# --- Service Binding fakes ----------------------------------------------------


class _FakeWorkersRequest:
    def __init__(self, url: str, method: str = "GET", headers: Any = None, body: Any = None) -> None:
        self.url = url
        self.method = method
        self.headers = headers or {}
        self.body = body
        self.js_object = self


class _FakeServiceResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = None
        self._body = body

    async def text(self) -> str:
        return self._body.decode("utf-8")


class _RaisingTextResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.body = None

    async def text(self) -> str:
        raise RuntimeError(r"read failed C:\Users\operator\secret.pdf")


class _ParserBinding:
    """Binding fake that routes the envelope to the real parser-side handler."""

    def __init__(self) -> None:
        self.calls: list[_FakeWorkersRequest] = []

    async def fetch(self, js_request: Any):
        self.calls.append(js_request)
        body = js_request.body.encode("utf-8")
        return _FakeServiceResponse(200, handle_isolated_parser_request(body))


class _FailingBinding:
    def __init__(self, error: Exception) -> None:
        self.calls = 0
        self._error = error

    async def fetch(self, js_request: Any):
        self.calls += 1
        raise self._error


class _StatusBinding:
    def __init__(self, status: int, body: bytes = b"{}") -> None:
        self.calls: list[Any] = []
        self._status = status
        self._body = body

    async def fetch(self, js_request: Any):
        self.calls.append(js_request)
        return _FakeServiceResponse(self._status, self._body)


def _transport(binding: Any) -> CloudflareDocumentParserServiceTransport:
    return CloudflareDocumentParserServiceTransport(binding, _FakeWorkersRequest)


def _binary_item(name: str, media_type: str, payload: bytes) -> dict[str, str]:
    return {
        "type": "document",
        "name": name,
        "media_type": media_type,
        "base64": base64.b64encode(payload).decode("ascii"),
    }


def _worker_runtime():
    return mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM)


async def _parse_through_service(name: str, media_type: str, payload: bytes):
    binding = _ParserBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    with _worker_runtime():
        parsed = await parse_attachments_async([_binary_item(name, media_type, payload)])
    assert len(parsed) == 1
    return parsed[0], binding


# --- A: transport request/response contract -----------------------------------


async def test_transport_posts_the_envelope_to_the_fixed_binding_url() -> None:
    envelope = json.dumps({"type": "error", "code": "pdf_invalid"}).encode("utf-8")
    binding = _StatusBinding(200, envelope)
    transport = _transport(binding)

    assert await transport.exchange(b"{\"type\":\"isolated_parser_request\"}") == envelope
    assert len(binding.calls) == 1
    request = binding.calls[0]
    assert request.url == DOCUMENT_PARSER_SERVICE_ORIGIN + DOCUMENT_PARSER_SERVICE_PATH
    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Accept"] == "application/json"
    assert request.body == "{\"type\":\"isolated_parser_request\"}"


async def test_transport_requires_a_binding_and_a_request_factory() -> None:
    with pytest.raises(ValueError):
        CloudflareDocumentParserServiceTransport(None, _FakeWorkersRequest)
    with pytest.raises(ValueError):
        CloudflareDocumentParserServiceTransport(_ParserBinding(), None)
    with pytest.raises(ValueError):
        await _transport(_ParserBinding()).exchange("not-bytes")  # type: ignore[arg-type]


async def test_non_success_status_is_a_bounded_transport_failure() -> None:
    binding = _StatusBinding(503, b'{"type":"error","code":"unavailable"}')
    client = IsolatedParserAsyncClient(transport=_transport(binding))
    with pytest.raises(DocumentNormalizationError) as info:
        await client.parse_binary_document(
            name="report.pdf", media_type=PDF_MIME, payload=b"%PDF-1.7 fixture"
        )
    assert info.value.code == "isolated_parser_transport_failed"


async def test_unreadable_response_is_a_bounded_transport_failure() -> None:
    class _Binding:
        async def fetch(self, js_request: Any):
            return _RaisingTextResponse()

    client = IsolatedParserAsyncClient(transport=_transport(_Binding()))
    with pytest.raises(DocumentNormalizationError) as info:
        await client.parse_binary_document(
            name="report.pdf", media_type=PDF_MIME, payload=b"%PDF-1.7 fixture"
        )
    assert info.value.code == "isolated_parser_transport_failed"
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


async def test_oversized_service_response_is_refused_before_buffering() -> None:
    from padiem_ai_core.isolated_parser_contract import ISOLATED_PARSER_MAX_RESPONSE_BYTES

    oversized = b"x" * (ISOLATED_PARSER_MAX_RESPONSE_BYTES + 1)
    transport = _transport(_StatusBinding(200, oversized))
    with pytest.raises(DocumentNormalizationError) as info:
        await transport.exchange(b"{}")
    assert info.value.code == ISOLATED_PARSER_RESPONSE_UNBOUNDED


# --- B: real Core parser through the isolated service -------------------------


async def test_pdf_pages_reach_the_model_context_through_the_service() -> None:
    attachment, binding = await _parse_through_service(
        "report.pdf",
        PDF_MIME,
        _text_pdf(
            [
                "Padiem page one token 4317",
                "The launch code on page two is 2824.",
            ]
        ),
    )
    context = build_document_context(attachment)

    assert len(binding.calls) == 1
    assert [segment.locator.value for segment in attachment.segments if segment.locator] == ["1", "2"]
    assert "[페이지 1]" in context
    assert "[페이지 2]" in context
    assert "The launch code on page two is 2824." in context


async def test_docx_body_and_table_rows_reach_the_model_context_through_the_service() -> None:
    attachment, _ = await _parse_through_service(
        "report.docx",
        DOCX_MIME,
        _zip_bytes({"word/document.xml": _docx_xml()}),
    )
    context = build_document_context(attachment)

    assert "Padiem body paragraph" in context
    assert "[표 1 행 2]" in context
    assert "Alpha | 42" in context
    assert "Padiem closing paragraph" in context


async def test_pptx_slide_numbers_reach_the_model_context_through_the_service() -> None:
    attachment, _ = await _parse_through_service(
        "deck.pptx",
        PPTX_MIME,
        _zip_bytes(
            {
                "ppt/slides/slide2.xml": _pptx_xml("Slide two: budget 2824"),
                "ppt/slides/slide1.xml": _pptx_xml("Slide one: overview"),
            }
        ),
    )
    context = build_document_context(attachment)

    assert [segment.locator.value for segment in attachment.segments if segment.locator] == ["1", "2"]
    assert "[슬라이드 1]" in context
    assert "[슬라이드 2]" in context
    assert "Slide two: budget 2824" in context


async def test_xlsx_sheet_cell_and_formula_reach_the_model_context_through_the_service() -> None:
    attachment, _ = await _parse_through_service("book.xlsx", XLSX_MIME, _xlsx_bytes())
    context = build_document_context(attachment)

    assert "[Revenue!B2] 10" in context
    assert "[Revenue!B4] =SUM(B2:B3) => (no cached value)" in context


# --- C: fail closed and clear outage errors -----------------------------------


async def test_binary_attachment_without_an_authority_fails_closed() -> None:
    item = _binary_item("report.pdf", PDF_MIME, _text_pdf(["blocked"]))
    with _worker_runtime():
        with pytest.raises(AttachmentValidationError) as info:
            await parse_attachments_async([item])
    assert str(info.value) == AUTHORITY_MESSAGE


async def test_parser_service_outage_is_one_clear_bounded_error() -> None:
    binding = _FailingBinding(RuntimeError(r"C:\Users\operator\payroll.pdf credential=abc"))
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    item = _binary_item("report.pdf", PDF_MIME, _text_pdf(["outage"]))

    with _worker_runtime():
        with pytest.raises(AttachmentValidationError) as info:
            await parse_attachments_async([item])

    assert str(info.value) == OUTAGE_MESSAGE
    projection = " ".join((str(info.value), repr(info.value), repr(info.value.args)))
    for leaked in ("Traceback", "C:\\", "payroll", "credential=abc"):
        assert leaked not in projection
    assert binding.calls == 1


async def test_parser_error_envelope_is_a_document_error_not_a_crash() -> None:
    binding = _ParserBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    item = _binary_item("broken.pdf", PDF_MIME, b"%PDF-1.7 not-a-real-document")

    with _worker_runtime():
        with pytest.raises(AttachmentValidationError) as info:
            await parse_attachments_async([item])

    message = str(info.value)
    assert message != OUTAGE_MESSAGE
    assert "Traceback" not in message


# --- D: text/image and request-input boundary ---------------------------------


async def test_text_and_image_attachments_do_not_touch_the_parser_service() -> None:
    binding = _ParserBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))

    text = await parse_attachments_async(
        [{"type": "document", "name": "notes.txt", "media_type": "text/plain", "text": "hello"}]
    )
    image = await parse_attachments_async(
        [
            {
                "type": "image",
                "name": "shot.png",
                "media_type": "image/png",
                "base64": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode("ascii"),
            }
        ]
    )

    assert text[0].text == "hello"
    assert image[0].media_type == "image/png"
    assert binding.calls == []


async def test_request_input_cannot_smuggle_an_owner_or_parser_field() -> None:
    binding = _ParserBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    item = _binary_item("report.pdf", PDF_MIME, _text_pdf(["owner"]))
    item["owner_id"] = "user-a"
    item["parser"] = "local"

    with _worker_runtime():
        with pytest.raises(AttachmentValidationError):
            await parse_attachments_async([item])

    assert binding.calls == []


async def test_wire_carries_no_user_or_workspace_identity() -> None:
    binding = _ParserBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    item = _binary_item("report-a.pdf", PDF_MIME, _text_pdf(["account A private token AAA"]))

    with _worker_runtime():
        parsed = await parse_attachments_async([item])

    envelope = json.loads(binding.calls[0].body)
    assert set(envelope) == {"type", "name", "media_type", "payload_b64"}
    for forbidden in ("owner", "account", "user", "workspace", "tenant", "session"):
        assert forbidden not in json.dumps(envelope).lower()
    # Account B material never appears in account A's parsed document.
    assert "BBB" not in parsed[0].text
    assert "AAA" in parsed[0].text


# --- E: /health reports the readiness the request path resolves ---------------


async def test_health_reports_async_parser_readiness_without_lying() -> None:
    from app.app_factory import create_app
    from app.config import Settings

    app = create_app(Settings(runtime_mode="mock", web_provider="mock"))

    async def _readiness() -> bool:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 200
        return response.json()["binary_document_attachment_ready"]

    assert await _readiness() is True  # CPython local/test authority
    with _worker_runtime():
        assert binary_document_parser_ready_async() is False
        assert await _readiness() is False  # production Worker without binding
        compose_worker_isolated_parser_authority_async(transport=_transport(_ParserBinding()))
        try:
            assert await _readiness() is True
        finally:
            clear_worker_isolated_parser_async_composition()
        assert await _readiness() is False


def test_health_handler_reads_the_async_readiness_signal() -> None:
    source = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert '"binary_document_attachment_ready": binary_document_parser_ready_async()' in source


# --- F: startup composition order and deployment wiring -----------------------


def test_worker_composes_the_async_authority_before_create_app() -> None:
    source = (ROOT / "worker.py").read_text(encoding="utf-8")
    compose_at = source.index("compose_worker_isolated_parser_authority_async(")
    create_at = source.index("_worker_app = create_app(")
    assert compose_at < create_at
    assert "CloudflareDocumentParserServiceTransport(" in source
    assert "reset_worker_isolated_parser_async_composition()" in source
    assert "DOCUMENT_PARSER_SERVICE_BINDING_NAME" in source


def test_wrangler_declares_the_private_parser_service_binding() -> None:
    source = (ROOT / "wrangler.toml").read_text(encoding="utf-8")
    assert 'binding = "DOCUMENT_PARSER_SERVICE"' in source
    assert 'service = "padiem-document-parser"' in source
