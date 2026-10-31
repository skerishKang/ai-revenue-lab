"""#2824: async isolated parser contract on the Worker request path.

These tests cover the exact wire contract the Chat Worker uses over the
``DOCUMENT_PARSER_SERVICE`` Service Binding, and prove it against the real
reviewed Core parser for all four binary formats:

* the async client sends only the bounded identity + payload envelope;
* the parser-side handler invokes the existing ``extract_binary_document``;
* success responses preserve page/slide/table-row/sheet-cell provenance;
* failure responses are bounded reason codes, not provider messages;
* raw transport exceptions collapse to one code with no chained cause;
* the async authority slot fails closed without trusted composition and is
  never satisfied by a synchronous composition;
* readiness reflects the async slot the request path actually resolves.

Nothing here starts a network listener or emulates production Cloudflare
traffic; the Service Binding transport itself is exercised in the Chat tests.
"""

from __future__ import annotations

import ast
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import padiem_ai_core.isolated_parser_async_client as async_client_module
from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    PRODUCTION_WORKER_PLATFORM,
    DocumentParserAuthorityUnavailable,
    binary_document_parser_ready,
    binary_document_parser_ready_async,
    parse_binary_document_via_authority_async,
)
from padiem_ai_core.document_semantics import (
    DocumentLocator,
    DocumentNormalizationError,
    DocumentSegment,
    ExtractionStatus,
    LocatorKind,
    LocatorPrecision,
)
from padiem_ai_core.isolated_parser_async_client import (
    AsyncIsolatedParserTransport,
    IsolatedParserAsyncClient,
)
from padiem_ai_core.isolated_parser_composition import (
    compose_worker_isolated_parser_authority,
    compose_worker_isolated_parser_authority_async,
    reset_worker_isolated_parser_async_composition,
    reset_worker_isolated_parser_composition,
)
from padiem_ai_core.isolated_parser_contract import (
    ISOLATED_PARSER_MAX_RESPONSE_BYTES,
    ISOLATED_PARSER_RESPONSE_INVALID,
    ISOLATED_PARSER_RESPONSE_UNBOUNDED,
    ISOLATED_PARSER_TRANSPORT_FAILED,
    decode_response,
    encode_request,
)
from padiem_ai_core.isolated_parser_service import handle_isolated_parser_request

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ASYNC_CLIENT_SOURCE = Path(async_client_module.__file__).read_text(encoding="utf-8")
ASYNC_CLIENT_TREE = ast.parse(ASYNC_CLIENT_SOURCE, filename=str(async_client_module.__file__))


@pytest.fixture(autouse=True)
def _clean_worker_composition():
    reset_worker_isolated_parser_async_composition()
    reset_worker_isolated_parser_composition()
    yield
    reset_worker_isolated_parser_async_composition()
    reset_worker_isolated_parser_composition()


# --- synthetic document fixtures (same bytes the Core parser tests use) -------


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


class _ServiceHandlerTransport:
    """Async transport fake backed by the real parser-side handler."""

    def __init__(self) -> None:
        self.requests: list[bytes] = []

    async def exchange(self, request: bytes) -> bytes:
        assert isinstance(request, (bytes, bytearray))
        self.requests.append(bytes(request))
        return handle_isolated_parser_request(bytes(request))


class _CannedTransport:
    def __init__(self, response: bytes | Exception) -> None:
        self.requests: list[bytes] = []
        self._response = response

    async def exchange(self, request: bytes) -> bytes:
        self.requests.append(bytes(request))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _locators(document: NormalizedDocument) -> list[tuple[str | None, str | None]]:
    return [
        (segment.locator.kind.value, segment.locator.value)
        if segment.locator is not None
        else (None, None)
        for segment in document.segments
    ]


# --- A: wire request carries identity + payload only --------------------------


async def test_async_request_envelope_carries_only_identity_and_payload() -> None:
    transport = _CannedTransport(b"{}")
    client = IsolatedParserAsyncClient(transport=transport)
    with pytest.raises(DocumentNormalizationError):
        await client.parse_binary_document(
            name="report.pdf",
            media_type=PDF_MIME,
            payload=b"%PDF-1.7 fixture",
        )
    assert len(transport.requests) == 1
    envelope = json.loads(transport.requests[0].decode("utf-8"))
    assert set(envelope) == {"type", "name", "media_type", "payload_b64"}
    assert envelope["type"] == "isolated_parser_request"
    assert base64.b64decode(envelope["payload_b64"]) == b"%PDF-1.7 fixture"
    lowered = transport.requests[0].lower()
    for leaked in (b"endpoint", b"https://", b"http://", b"timeout", b"command"):
        assert leaked not in lowered


async def test_async_client_requires_a_transport_with_exchange() -> None:
    with pytest.raises(ValueError):
        IsolatedParserAsyncClient(transport=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IsolatedParserAsyncClient(transport=object())  # type: ignore[arg-type]
    assert isinstance(_CannedTransport(b"{}"), AsyncIsolatedParserTransport)


# --- B: real Core parser through the handler for all four formats -------------


async def test_pdf_pages_round_trip_through_the_async_contract() -> None:
    transport = _ServiceHandlerTransport()
    client = IsolatedParserAsyncClient(transport=transport)
    payload = _text_pdf(
        [
            "Padiem page one token 4317",
            "The launch code on page two is 2824.",
        ]
    )

    document = await client.parse_binary_document(
        name="report.pdf", media_type=PDF_MIME, payload=payload
    )

    assert document.status is ExtractionStatus.COMPLETE
    assert document.byte_size == len(payload)
    assert _locators(document) == [("page", "1"), ("page", "2")]
    assert "Padiem page one token 4317" in document.text
    assert "The launch code on page two is 2824." in document.text


async def test_docx_body_and_table_rows_round_trip_through_the_async_contract() -> None:
    transport = _ServiceHandlerTransport()
    client = IsolatedParserAsyncClient(transport=transport)
    payload = _zip_bytes({"word/document.xml": _docx_xml()})

    document = await client.parse_binary_document(
        name="report.docx", media_type=DOCX_MIME, payload=payload
    )

    assert _locators(document) == [
        (None, None),
        ("row", "1.1"),
        ("row", "1.2"),
        (None, None),
    ]
    assert "Padiem body paragraph" in document.text
    assert "Alpha | 42" in document.text
    assert "Padiem closing paragraph" in document.text


async def test_pptx_slide_numbers_round_trip_through_the_async_contract() -> None:
    transport = _ServiceHandlerTransport()
    client = IsolatedParserAsyncClient(transport=transport)
    payload = _zip_bytes(
        {
            "ppt/slides/slide2.xml": _pptx_xml("Slide two: budget 2824"),
            "ppt/slides/slide1.xml": _pptx_xml("Slide one: overview"),
        }
    )

    document = await client.parse_binary_document(
        name="deck.pptx", media_type=PPTX_MIME, payload=payload
    )

    assert _locators(document) == [("slide", "1"), ("slide", "2")]
    assert document.text == "Slide one: overview\nSlide two: budget 2824"


async def test_xlsx_sheet_cell_and_formula_round_trip_through_the_async_contract() -> None:
    transport = _ServiceHandlerTransport()
    client = IsolatedParserAsyncClient(transport=transport)
    payload = _xlsx_bytes()

    document = await client.parse_binary_document(
        name="book.xlsx", media_type=XLSX_MIME, payload=payload
    )

    assert "[Revenue!A1] Month" in document.text
    assert "[Revenue!B2] 10" in document.text
    # The formula and the missing computed cache are both explicit; the wire
    # must not turn a cached value into a calculated one.
    assert "[Revenue!B4] =SUM(B2:B3) => (no cached value)" in document.text


async def test_parser_handler_returns_a_bounded_document_envelope() -> None:
    payload = _text_pdf(["Handler envelope page one"])
    raw = handle_isolated_parser_request(
        encode_request(name="report.pdf", media_type=PDF_MIME, payload=payload)
    )
    envelope = json.loads(raw.decode("utf-8"))

    assert envelope["type"] == "document"
    assert set(envelope) == {
        "type",
        "name",
        "media_type",
        "text",
        "byte_size",
        "source_kind",
        "status",
        "warnings",
        "segments",
    }
    assert envelope["segments"][0]["locator"] == {
        "kind": "page",
        "value": "1",
        "precision": "exact",
    }


# --- C: segments survive the response decoder unchanged -----------------------


async def test_segment_provenance_survives_encode_and_decode() -> None:
    payload = b"%PDF-1.7 provenance-fixture"
    document = NormalizedDocument(
        name="report.pdf",
        media_type=PDF_MIME,
        text="page one\npage two",
        byte_size=len(payload),
        source_kind="binary",
        segments=(
            DocumentSegment(
                text="page one",
                order=0,
                locator=DocumentLocator(
                    kind=LocatorKind.PAGE,
                    value="1",
                    precision=LocatorPrecision.EXACT,
                ),
            ),
            DocumentSegment(
                text="page two",
                order=1,
                locator=DocumentLocator(
                    kind=LocatorKind.PAGE,
                    value="2",
                    precision=LocatorPrecision.EXACT,
                ),
            ),
        ),
    )
    from padiem_ai_core.isolated_parser_contract import encode_document

    decoded = decode_response(
        encode_document(document),
        name="report.pdf",
        media_type=PDF_MIME,
        byte_size=len(payload),
    )
    assert _locators(decoded) == [("page", "1"), ("page", "2")]
    assert decoded.segments[1].text == "page two"
    assert decoded.segments[1].order == 1


# --- D: bounded failures never carry provider detail --------------------------


async def test_error_envelope_becomes_a_bounded_document_error() -> None:
    raw = handle_isolated_parser_request(
        encode_request(
            name="broken.pdf",
            media_type=PDF_MIME,
            payload=b"%PDF-1.7 not-a-real-document",
        )
    )
    envelope = json.loads(raw.decode("utf-8"))
    assert envelope["type"] == "error"

    client = IsolatedParserAsyncClient(transport=_CannedTransport(raw))
    with pytest.raises(DocumentNormalizationError) as info:
        await client.parse_binary_document(
            name="broken.pdf",
            media_type=PDF_MIME,
            payload=b"%PDF-1.7 not-a-real-document",
        )
    assert info.value.code == envelope["code"]
    assert "Traceback" not in str(info.value)


async def test_malformed_request_is_answered_not_raised() -> None:
    for bad in (b"", b"not-json", b'{"type": "isolated_parser_request"}', b"[]"):
        raw = handle_isolated_parser_request(bad)
        envelope = json.loads(raw.decode("utf-8"))
        assert envelope["type"] == "error"
        assert envelope["code"].startswith(("isolated_parser_", "invalid_", "empty_"))


async def test_oversized_response_is_rejected_as_unbounded() -> None:
    client = IsolatedParserAsyncClient(
        transport=_CannedTransport(b"x" * (ISOLATED_PARSER_MAX_RESPONSE_BYTES + 1))
    )
    with pytest.raises(DocumentNormalizationError) as info:
        await client.parse_binary_document(
            name="report.pdf", media_type=PDF_MIME, payload=b"%PDF-1.7 fixture"
        )
    assert info.value.code == ISOLATED_PARSER_RESPONSE_UNBOUNDED


async def test_transport_exception_is_sanitized_without_chained_cause() -> None:
    hostile = RuntimeError(r"C:\Users\operator\payroll-2026.pdf credential=abc")
    client = IsolatedParserAsyncClient(transport=_CannedTransport(hostile))
    with pytest.raises(DocumentNormalizationError) as info:
        await client.parse_binary_document(
            name="report.pdf", media_type=PDF_MIME, payload=b"%PDF-1.7 fixture"
        )
    error = info.value
    assert error.code == ISOLATED_PARSER_TRANSPORT_FAILED
    projection = " ".join(
        (str(error), error.code, error.safe_message, repr(error), repr(error.args))
    )
    for leaked in ("Traceback", "C:\\", "payroll", "credential=abc", "RuntimeError"):
        assert leaked not in projection
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is False


async def test_bounded_document_error_from_transport_passes_through() -> None:
    original = DocumentNormalizationError("pdf_encrypted", "Encrypted PDF documents are not supported.")
    client = IsolatedParserAsyncClient(transport=_CannedTransport(original))
    with pytest.raises(DocumentNormalizationError) as info:
        await client.parse_binary_document(
            name="report.pdf", media_type=PDF_MIME, payload=b"%PDF-1.7 fixture"
        )
    assert info.value is original


# --- E: async authority slot is separate and fail-closed ---------------------


async def test_async_path_fails_closed_without_composition() -> None:
    with mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM):
        assert binary_document_parser_ready_async() is False
        with pytest.raises(DocumentParserAuthorityUnavailable) as info:
            await parse_binary_document_via_authority_async(
                name="report.pdf",
                media_type=PDF_MIME,
                payload=_text_pdf(["fail closed"]),
            )
    assert info.value.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE


async def test_async_composition_is_required_and_reported_by_readiness() -> None:
    transport = _ServiceHandlerTransport()
    with mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM):
        assert binary_document_parser_ready_async() is False
        compose_worker_isolated_parser_authority_async(transport=transport)
        try:
            assert binary_document_parser_ready_async() is True
            document = await parse_binary_document_via_authority_async(
                name="report.pdf",
                media_type=PDF_MIME,
                payload=_text_pdf(["composed authority"]),
            )
            assert "composed authority" in document.text
            # The sync slot stays untouched: one composition is not the other.
            assert binary_document_parser_ready() is False
        finally:
            reset_worker_isolated_parser_async_composition()
        assert binary_document_parser_ready_async() is False


class _SyncTransport:
    def exchange(self, request: bytes) -> bytes:
        raise AssertionError("sync transport must not be called on the async path")


async def test_sync_composition_never_satisfies_the_async_request_path() -> None:
    compose_worker_isolated_parser_authority(transport=_SyncTransport())
    with mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM):
        assert binary_document_parser_ready_async() is False
        with pytest.raises(DocumentParserAuthorityUnavailable):
            await parse_binary_document_via_authority_async(
                name="report.pdf",
                media_type=PDF_MIME,
                payload=_text_pdf(["not used"]),
            )


# --- F: source guards ---------------------------------------------------------


def test_async_client_has_no_network_or_process_authority() -> None:
    imported: set[str] = set()
    referenced: set[str] = set()
    parameter_names: set[str] = set()
    for node in ast.walk(ASYNC_CLIENT_TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
        if isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parameter_names.update(arg.arg for arg in node.args.args)
            parameter_names.update(arg.arg for arg in node.args.kwonlyargs)

    assert imported <= {"__future__", "typing"}
    assert not referenced & {
        "Popen",
        "Process",
        "Thread",
        "create_subprocess_exec",
        "environ",
        "getenv",
        "urlopen",
        "wait_for",
    }
    assert not parameter_names & {
        "base_url",
        "baseurl",
        "command",
        "deadline",
        "endpoint",
        "headers",
        "host",
        "parser",
        "runtime_mode",
        "timeout",
        "timeout_seconds",
        "url",
    }
    assert "https://" not in ASYNC_CLIENT_SOURCE
    assert "http://" not in ASYNC_CLIENT_SOURCE
