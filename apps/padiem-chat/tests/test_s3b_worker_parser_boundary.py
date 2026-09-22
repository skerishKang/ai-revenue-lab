"""#2824 S3-B: Chat Worker binary parser boundary.

Every Chat binary document path (chat attachment and project file) must pass
through the one shared parser-authority boundary. In the production Worker
runtime there is no reviewed isolated parser authority, so the common intake
gate runs and then the Core parser is **never invoked**.

These tests assert the invocation count, not just an error string:

* production Worker chat attachment -> fail closed, Core parser count == 0
* production Worker project-file upload -> same single policy, count == 0
* the production Worker cannot fall back to the in-process parser
* request/browser input cannot select a parser or a runtime mode
* text and image routes are unchanged by the binary parser gate
* local CPython keeps parsing binary documents (both direct paths)
* the fail-closed error projection is bounded and sanitized
"""

from __future__ import annotations

import base64
from pathlib import Path
import sys
from io import BytesIO
from unittest import mock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import binary_documents as binary_documents_module
from app.attachments import AttachmentValidationError, parse_attachments
from app.binary_documents import BinaryDocumentValidationError, parse_binary_document_item
from app.project_file_routes import _parse_project_file_item
import padiem_ai_core.document_parser_boundary as boundary
from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    PRODUCTION_WORKER_PLATFORM,
    DocumentParserAuthorityUnavailable,
    parse_binary_document_via_authority,
)

PDF_MEDIA = "application/pdf"
TEXT_MEDIA = "text/plain"
PNG_MEDIA = "image/png"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

AUTHORITY_MESSAGE = "현재 실행 환경에서는 격리된 문서 파서를 사용할 수 없어 문서를 처리할 수 없습니다."


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


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


def _binary_item(name: str, media_type: str, payload: bytes) -> dict[str, str]:
    return {"type": "document", "name": name, "media_type": media_type, "base64": _b64(payload)}


def _worker_runtime():
    """Deterministic production Worker simulation: no network, no subprocess."""

    return mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM)


class _CoreParserSpy:
    """Canary for ``padiem_ai_core.document_normalization.extract_binary_document``."""

    def __init__(self, result: NormalizedDocument | None = None) -> None:
        self.calls = 0
        self._result = result

    def __call__(self, *, name: object, media_type: object, payload: object) -> NormalizedDocument:
        self.calls += 1
        if self._result is None:
            raise AssertionError("Core binary parser must not run on this path")
        return self._result


# --- A/D: production Worker chat attachment fails closed, parser count 0 -------


def test_production_worker_attachment_fails_closed_before_the_core_parser() -> None:
    spy = _CoreParserSpy()
    item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(AttachmentValidationError) as info:
            parse_attachments([item])
    assert spy.calls == 0
    assert str(info.value) == AUTHORITY_MESSAGE


def test_production_worker_attachment_adapter_never_reaches_the_core_parser() -> None:
    spy = _CoreParserSpy()
    item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(BinaryDocumentValidationError) as info:
            parse_binary_document_item(item)
    assert spy.calls == 0
    assert info.value.args[0] == AUTHORITY_MESSAGE


# --- the common intake gate still runs first -----------------------------------


def test_intake_gate_rejects_before_the_parser_authority_gate() -> None:
    spy = _CoreParserSpy()
    item = _binary_item("payload.exe", "application/x-msdownload", _minimal_text_pdf("x"))
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(BinaryDocumentValidationError) as info:
            parse_binary_document_item(item)
    assert spy.calls == 0
    # the intake gate rejected the media type, so the authority message never ran
    assert str(info.value) != AUTHORITY_MESSAGE


def test_intake_gate_size_limit_still_applies_under_the_worker_gate() -> None:
    oversize = b"a" * (3 * 1024 * 1024)
    spy = _CoreParserSpy()
    payload = _b64(oversize)
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(BinaryDocumentValidationError):
            binary_documents_module._decode_payload(payload)
    assert spy.calls == 0


# --- B/M4: project-file binary upload uses the same single policy --------------


def test_project_file_binary_upload_cannot_bypass_the_authority() -> None:
    spy = _CoreParserSpy()
    raw = {
        "name": "report.pdf",
        "media_type": PDF_MEDIA,
        "base64": _b64(_minimal_text_pdf("quarterly")),
    }
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(ValueError) as info:
            _parse_project_file_item(raw)
    assert spy.calls == 0
    assert str(info.value) == AUTHORITY_MESSAGE


def test_both_chat_binary_call_sites_share_one_authority_decision() -> None:
    spy = _CoreParserSpy()
    attachment_item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    project_raw = {
        "name": "report.pdf",
        "media_type": PDF_MEDIA,
        "base64": _b64(_minimal_text_pdf("quarterly")),
    }
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(AttachmentValidationError):
            parse_attachments([attachment_item])
        with pytest.raises(ValueError):
            _parse_project_file_item(project_raw)
    assert spy.calls == 0


# --- F: no production Worker fallback to the in-process parser -----------------


def test_production_worker_cannot_fall_back_to_the_local_direct_parser() -> None:
    canary = _CoreParserSpy()
    item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    with _worker_runtime(), mock.patch.object(boundary, "_LOCAL_REVIEWED_PARSER", canary):
        with pytest.raises(BinaryDocumentValidationError):
            parse_binary_document_item(item)
    assert canary.calls == 0


# --- E: request/browser input cannot inject a parser or a runtime mode ---------


def test_request_input_cannot_add_a_parser_or_mode_field() -> None:
    spy = _CoreParserSpy()
    item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    item["parser"] = "local"  # a hostile/browser-supplied extra field
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(AttachmentValidationError):
            parse_attachments([item])
    assert spy.calls == 0


def test_request_input_cannot_switch_the_runtime_mode() -> None:
    spy = _CoreParserSpy()
    item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    item["runtime_mode"] = "cpython"
    item["isolation"] = "asyncio.wait_for"
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(AttachmentValidationError):
            parse_attachments([item])
    assert spy.calls == 0
    assert boundary.production_worker_runtime() is False  # nothing was overridden


def test_authority_entry_point_takes_document_identity_only() -> None:
    import inspect

    signature = inspect.signature(parse_binary_document_via_authority)
    assert set(signature.parameters) == {"name", "media_type", "payload"}


# --- G/H: text and image routes are unchanged ----------------------------------


def test_text_document_route_is_unchanged_in_the_worker_runtime() -> None:
    text_item = {"type": "document", "name": "notes.txt", "media_type": TEXT_MEDIA, "text": "hello"}
    with _worker_runtime():
        parsed = parse_attachments([text_item])
    assert parsed[0].text == "hello"


def test_image_route_is_unchanged_in_the_worker_runtime() -> None:
    image_item = {
        "type": "image",
        "name": "shot.png",
        "media_type": PNG_MEDIA,
        "base64": _b64(PNG_BYTES),
    }
    with _worker_runtime():
        parsed = parse_attachments([image_item])
    assert parsed[0].media_type == PNG_MEDIA
    assert parsed[0].byte_size == len(PNG_BYTES)


# --- control: local CPython still parses through both call sites ---------------


def test_local_attachment_path_still_parses_binary_documents() -> None:
    item = _binary_item("report.pdf", PDF_MEDIA, _minimal_text_pdf("quarterly"))
    document = parse_binary_document_item(item)
    assert "quarterly" in document.text
    assert document.media_type == PDF_MEDIA


def test_local_project_file_path_still_parses_binary_documents() -> None:
    raw = {
        "name": "report.pdf",
        "media_type": PDF_MEDIA,
        "base64": _b64(_minimal_text_pdf("quarterly")),
    }
    name, media_type, text = _parse_project_file_item(raw)
    assert name == "report.pdf"
    assert media_type.endswith("/pdf")
    assert "quarterly" in text


# --- J/K: bounded, sanitized error projection ----------------------------------


def test_fail_closed_projection_leaks_no_traceback_path_or_body() -> None:
    secret_name = r"C:\Users\operator\payroll-2026.pdf"
    secret_body = _minimal_text_pdf("SECRET-BODY-DO-NOT-ECHO")
    item = _binary_item(secret_name, PDF_MEDIA, secret_body)
    with _worker_runtime(), pytest.raises(BinaryDocumentValidationError) as info:
        parse_binary_document_item(item)
    assert str(info.value) == AUTHORITY_MESSAGE
    projection = " ".join((str(info.value), repr(info.value), repr(info.value.args)))
    for leaked in ("Traceback", "C:\\", "payroll", "SECRET-BODY", DOCUMENT_PARSER_ISOLATION_UNAVAILABLE):
        assert leaked not in projection


def test_authority_failure_is_a_bounded_document_error() -> None:
    error = DocumentParserAuthorityUnavailable()
    assert error.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE
    assert isinstance(error, binary_documents_module.DocumentNormalizationError)


# --- one shared policy, not two ad-hoc gates -----------------------------------


def test_chat_and_engine_share_one_parser_authority_policy() -> None:
    root = Path(__file__).resolve().parents[3]
    chat_source = (root / "apps" / "padiem-chat" / "app" / "binary_documents.py").read_text(
        encoding="utf-8"
    )
    engine_source = (
        root / "apps" / "padiem-ai-engine" / "app" / "trusted_document_resolver.py"
    ).read_text(encoding="utf-8")
    for source in (chat_source, engine_source):
        assert "padiem_ai_core.document_parser_boundary" in source
        assert "parse_binary_document_via_authority" in source
        assert "extract_binary_document(" not in source
