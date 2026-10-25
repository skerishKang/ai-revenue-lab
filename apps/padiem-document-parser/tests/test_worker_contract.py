"""#2824: standalone Parser Authority Worker contract.

This suite executes the real ``padiem-document-parser`` Worker entrypoint with
a minimal in-memory stand-in for the Pyodide ``workers`` module, so the route
and error behavior is exercised before any deployment:

* only ``POST /internal/v1/parse`` with a bounded JSON body is accepted;
* route, method, content-type and size refusals answer a non-200 status;
* document-level failures answer HTTP 200 with the bounded error envelope, so
  the Chat client applies the same code mapping it applies to a local parse;
* real synthetic PDF/DOCX/PPTX/XLSX bytes are parsed by the reviewed Core
  parser inside the Worker handler and keep their provenance;
* the Worker carries no user, workspace, storage or model authority.

The Worker bundle itself (pure-Python Pyodide wheels, byte-identical source
copy) is proven by ``scripts/build_worker_dependencies.py``; actual Cloudflare
deployment is outside the CTO freeze.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from padiem_ai_core.isolated_parser_contract import (
    ISOLATED_PARSER_MAX_REQUEST_BYTES,
    encode_request,
)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = APP_ROOT / "worker.py"
PARSE_URL = "https://padiem-document-parser/internal/v1/parse"


# --- minimal Pyodide ``workers`` stand-in -------------------------------------


class _Response:
    def __init__(self, body: Any, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _WorkerEntrypoint:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


class _Headers(dict):
    def get(self, key: str, default: Any = None) -> Any:
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


class _Request:
    def __init__(
        self,
        url: str,
        method: str = "POST",
        headers: Any = None,
        body: Any = b"",
    ) -> None:
        self.url = url
        self.method = method
        self.headers = _Headers(headers or {})
        self._body = body

    async def text(self) -> str:
        if isinstance(self._body, Exception):
            raise self._body
        if isinstance(self._body, bytes):
            return self._body.decode("utf-8")
        return self._body


@pytest.fixture(scope="module")
def worker_module():
    fake = types.ModuleType("workers")
    fake.Response = _Response
    fake.WorkerEntrypoint = _WorkerEntrypoint

    previous = sys.modules.get("workers")
    sys.modules["workers"] = fake
    try:
        spec = importlib.util.spec_from_file_location(
            "_padiem_document_parser_worker", WORKER_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("workers", None)
        else:
            sys.modules["workers"] = previous
    return module


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


def _json_request(body: bytes, **overrides: Any) -> _Request:
    headers = {"content-type": "application/json"}
    headers.update(overrides.pop("headers", {}))
    return _Request(PARSE_URL, headers=headers, body=body, **overrides)


async def _post(worker_module, name: str, media_type: str, payload: bytes):
    body = encode_request(name=name, media_type=media_type, payload=payload)
    return await worker_module.Default().fetch(_json_request(body))


def _envelope(response: _Response) -> dict:
    assert isinstance(response.body, bytes)
    return json.loads(response.body.decode("utf-8"))


# --- A: route and transport refusals are non-200 ------------------------------


async def test_non_parse_path_is_not_found(worker_module) -> None:
    response = await worker_module.Default().fetch(
        _Request("https://padiem-document-parser/other", body=b"{}")
    )
    assert response.status == 404
    assert _envelope(response) == {"type": "error", "code": "not_found"}


async def test_non_post_method_is_refused(worker_module) -> None:
    response = await worker_module.Default().fetch(
        _Request(PARSE_URL, method="GET", headers={"content-type": "application/json"})
    )
    assert response.status == 405
    assert _envelope(response)["code"] == "method_not_allowed"


async def test_non_json_content_type_is_refused(worker_module) -> None:
    response = await worker_module.Default().fetch(
        _Request(PARSE_URL, headers={"content-type": "text/plain"}, body=b"{}")
    )
    assert response.status == 415
    assert _envelope(response)["code"] == "unsupported_media_type"


async def test_invalid_declared_content_length_is_refused(worker_module) -> None:
    response = await worker_module.Default().fetch(
        _json_request(b"{}", headers={"content-length": "not-a-number"})
    )
    assert response.status == 400
    assert _envelope(response)["code"] == "invalid_content_length"


async def test_declared_oversized_request_is_refused(worker_module) -> None:
    response = await worker_module.Default().fetch(
        _json_request(
            b"{}",
            headers={"content-length": str(ISOLATED_PARSER_MAX_REQUEST_BYTES + 1)},
        )
    )
    assert response.status == 413
    assert _envelope(response)["code"] == "request_too_large"


async def test_actual_oversized_request_is_refused(worker_module, monkeypatch) -> None:
    monkeypatch.setattr(worker_module, "ISOLATED_PARSER_MAX_REQUEST_BYTES", 16)
    response = await worker_module.Default().fetch(_json_request(b"x" * 17))
    assert response.status == 413
    assert _envelope(response)["code"] == "request_too_large"


async def test_empty_body_is_refused(worker_module) -> None:
    response = await worker_module.Default().fetch(_json_request(b""))
    assert response.status == 400
    assert _envelope(response)["code"] == "empty_request_body"


async def test_unreadable_body_is_refused(worker_module) -> None:
    response = await worker_module.Default().fetch(
        _json_request(RuntimeError(r"C:\Users\operator\secret.pdf"))
    )
    assert response.status == 400
    assert _envelope(response)["code"] == "invalid_request_body"


# --- B: document failures are HTTP 200 bounded envelopes ----------------------


async def test_malformed_envelope_is_a_200_error_envelope(worker_module) -> None:
    response = await worker_module.Default().fetch(_json_request(b"not-json"))
    assert response.status == 200
    assert _envelope(response)["type"] == "error"
    assert _envelope(response)["code"] == "isolated_parser_response_invalid"


async def test_unparseable_document_is_a_200_error_envelope(worker_module) -> None:
    response = await _post(worker_module, "broken.pdf", PDF_MIME, b"%PDF-1.7 not-a-document")
    assert response.status == 200
    envelope = _envelope(response)
    assert envelope["type"] == "error"
    assert envelope["code"] != "isolated_parser_transport_failed"


# --- C: real four-format parsing inside the Worker handler --------------------


async def test_pdf_pages_are_parsed_with_provenance(worker_module) -> None:
    response = await _post(
        worker_module,
        "report.pdf",
        PDF_MIME,
        _text_pdf(["Padiem page one token 4317", "The launch code on page two is 2824."]),
    )
    envelope = _envelope(response)

    assert response.status == 200
    assert envelope["type"] == "document"
    assert [segment["locator"] for segment in envelope["segments"]] == [
        {"kind": "page", "value": "1", "precision": "exact"},
        {"kind": "page", "value": "2", "precision": "exact"},
    ]
    assert "The launch code on page two is 2824." in envelope["text"]


async def test_docx_body_and_table_rows_are_parsed(worker_module) -> None:
    response = await _post(
        worker_module,
        "report.docx",
        DOCX_MIME,
        _zip_bytes({"word/document.xml": _docx_xml()}),
    )
    envelope = _envelope(response)

    assert envelope["type"] == "document"
    assert [segment["locator"] for segment in envelope["segments"]] == [
        None,
        {"kind": "row", "value": "1.1", "precision": "exact"},
        {"kind": "row", "value": "1.2", "precision": "exact"},
        None,
    ]
    assert "Alpha | 42" in envelope["text"]


async def test_pptx_slides_keep_actual_slide_numbers(worker_module) -> None:
    response = await _post(
        worker_module,
        "deck.pptx",
        PPTX_MIME,
        _zip_bytes(
            {
                "ppt/slides/slide2.xml": _pptx_xml("Slide two: budget 2824"),
                "ppt/slides/slide1.xml": _pptx_xml("Slide one: overview"),
            }
        ),
    )
    envelope = _envelope(response)

    assert [segment["locator"]["value"] for segment in envelope["segments"]] == ["1", "2"]
    assert envelope["text"] == "Slide one: overview\nSlide two: budget 2824"


async def test_xlsx_sheet_cell_and_formula_are_exact(worker_module) -> None:
    response = await _post(worker_module, "book.xlsx", XLSX_MIME, _xlsx_bytes())
    envelope = _envelope(response)

    assert "[Revenue!B2] 10" in envelope["text"]
    assert "[Revenue!B4] =SUM(B2:B3) => (no cached value)" in envelope["text"]


# --- D: response shape and Worker authority -----------------------------------


async def test_success_response_headers_are_private_and_nosniff(worker_module) -> None:
    response = await _post(worker_module, "report.pdf", PDF_MIME, _text_pdf(["headers"]))
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_worker_has_no_identity_storage_or_logging_surface(worker_module) -> None:
    source = WORKER_PATH.read_text(encoding="utf-8")
    assert worker_module.PARSE_PATH == "/internal/v1/parse"
    for forbidden in ("D1", "R2", "owner", "account", "workspace", "print(", "console.log"):
        assert forbidden not in source
    assert "handle_isolated_parser_request" in source
