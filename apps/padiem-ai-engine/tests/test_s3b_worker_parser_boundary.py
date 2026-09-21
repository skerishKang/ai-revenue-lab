"""#2824 S3-B: Engine Worker binary parser boundary.

The Engine trusted document path (``app.trusted_document_resolver``) no longer
calls the Core parser directly. It goes through the same shared
parser-authority boundary as Chat, so a production Worker without a reviewed
isolated parser authority fails closed **before** the Core parser runs.

These tests assert the invocation count and the fail-closed ordering:

* production Worker binary document -> bounded fail closed, Core parser count 0
* the async ``resolve_and_normalize`` route cannot bypass the authority
* the module holds no direct Core parser call any more
* the text document route is unchanged by the binary parser gate
* the error projection leaks no traceback, host path or document body
* local CPython still normalizes binary and text documents
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import sys
from unittest import mock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.document_byte_store import (
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
    StoredDocumentRecord,
)
from app.trusted_document_resolver import (
    DurableDocumentStoragePort,
    ResolvedDocumentMeta,
    TrustedDocumentResolver,
    normalize_resolved_document,
    resolve_and_normalize,
)
import padiem_ai_core.document_parser_boundary as boundary
from padiem_ai_core.document_normalization import DocumentNormalizationError, NormalizedDocument
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    PRODUCTION_WORKER_PLATFORM,
    DocumentParserAuthorityUnavailable,
)

PDF_MEDIA = "application/pdf"
TEXT_MEDIA = "text/plain"
REF = "doc_s3bboundarytest0001"
SECRET_BODY_TEXT = "SECRET-BODY-DO-NOT-ECHO"

T0 = datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)
SCOPE = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}


def _worker_runtime():
    """Deterministic production Worker simulation: no network, no subprocess."""

    return mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM)


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


def _binary_meta(payload: bytes, *, name: str = "report.pdf", media_type: str = PDF_MEDIA) -> ResolvedDocumentMeta:
    return ResolvedDocumentMeta(
        media_type=media_type,
        name=name,
        byte_size=len(payload),
        **SCOPE,
    )


def _text_meta(payload: bytes, *, name: str = "notes.txt") -> ResolvedDocumentMeta:
    return ResolvedDocumentMeta(
        media_type=TEXT_MEDIA,
        name=name,
        byte_size=len(payload),
        **SCOPE,
    )


def _resolver(payload: bytes, meta: ResolvedDocumentMeta, *, ref: str = REF) -> TrustedDocumentResolver:
    async def scenario() -> TrustedDocumentResolver:
        port = InMemoryDocumentByteStore()
        await port.put(
            StoredDocumentRecord(
                document_ref=ref,
                app_id=meta.app_id,
                tenant_id=meta.tenant_id,
                subject_id=meta.subject_id,
                media_type=meta.media_type,
                name=meta.name,
                byte_size=meta.byte_size,
                created_at=T0,
                expires_at=T0 + timedelta(hours=24),
            ),
            payload,
        )
        return TrustedDocumentResolver(
            storage=DurableDocumentStoragePort(ScopedDocumentByteStore(port=port, clock=lambda: T0))
        )

    return asyncio.run(scenario())


def _call() -> dict[str, str]:
    return dict(SCOPE)


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


# --- C/D: production Worker fails closed, Core parser count 0 ------------------


def test_production_worker_binary_normalization_fails_closed_before_the_parser() -> None:
    payload = _minimal_text_pdf("quarterly")
    spy = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentNormalizationError) as info:
            normalize_resolved_document(payload, _binary_meta(payload))
    assert spy.calls == 0
    assert info.value.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE
    assert isinstance(info.value, DocumentParserAuthorityUnavailable)


def test_production_worker_trusted_resolver_route_cannot_bypass_the_authority() -> None:
    payload = _minimal_text_pdf("quarterly")
    resolver = _resolver(payload, _binary_meta(payload))
    spy = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentNormalizationError) as info:
            asyncio.run(resolve_and_normalize(resolver, REF, **_call()))
    assert spy.calls == 0
    assert info.value.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE


def test_production_worker_cannot_fall_back_to_the_local_direct_parser() -> None:
    payload = _minimal_text_pdf("quarterly")
    canary = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "_LOCAL_REVIEWED_PARSER", canary):
        with pytest.raises(DocumentParserAuthorityUnavailable):
            normalize_resolved_document(payload, _binary_meta(payload))
    assert canary.calls == 0


# --- the resolver module no longer owns a direct Core parser call --------------


def test_resolver_module_holds_no_direct_core_parser_call() -> None:
    import app.trusted_document_resolver as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.__file__))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("document_normalization"):
            imported.update(alias.name for alias in node.names)
    assert "extract_binary_document" not in imported
    assert "normalize_text_document" in imported  # the text route is unchanged
    # the one binary parse entry point is the shared authority
    assert "parse_binary_document_via_authority" in source
    assert "extract_binary_document(" not in source


# --- G: the text document route is unchanged -----------------------------------


def test_text_document_route_is_unchanged_in_the_worker_runtime() -> None:
    payload = b"meeting notes"
    with _worker_runtime():
        document = normalize_resolved_document(payload, _text_meta(payload))
    assert document.text == "meeting notes"
    assert document.source_kind != "binary"


def test_text_document_route_is_unchanged_end_to_end_in_the_worker_runtime() -> None:
    payload = b"meeting notes"
    resolver = _resolver(payload, _text_meta(payload))
    with _worker_runtime():
        document = asyncio.run(resolve_and_normalize(resolver, REF, **_call()))
    assert document.text == "meeting notes"


# --- J/K: bounded, sanitized error projection ----------------------------------


def test_fail_closed_projection_leaks_no_traceback_path_or_body() -> None:
    payload = _minimal_text_pdf(SECRET_BODY_TEXT)
    meta = _binary_meta(payload, name=r"C:\Users\operator\payroll-2026.pdf")
    with _worker_runtime(), pytest.raises(DocumentNormalizationError) as info:
        normalize_resolved_document(payload, meta)
    error = info.value
    projection = " ".join((str(error), error.code, error.safe_message, repr(error), repr(error.args)))
    for leaked in ("Traceback", "C:\\", "payroll", SECRET_BODY_TEXT, "extract_binary_document"):
        assert leaked not in projection
    assert error.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE


# --- control: local CPython still normalizes both media ------------------------


def test_local_binary_normalization_still_works() -> None:
    payload = _minimal_text_pdf("quarterly")
    document = normalize_resolved_document(payload, _binary_meta(payload))
    assert "quarterly" in document.text
    assert document.source_kind == "binary"


def test_local_trusted_resolver_route_still_works() -> None:
    payload = _minimal_text_pdf("quarterly")
    resolver = _resolver(payload, _binary_meta(payload))
    document = asyncio.run(resolve_and_normalize(resolver, REF, **_call()))
    assert "quarterly" in document.text
