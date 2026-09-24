"""#2827 bounded PDFium full-page rendering tests."""

from __future__ import annotations

from importlib import import_module
from io import BytesIO
from pathlib import Path

import pytest

from padiem_ai_core.document_normalization import DocumentNormalizationError
from padiem_ai_core.pdf_render import (
    MAX_PDF_RENDER_PAGE_EDGE,
    PDF_RENDER_OUTPUT_FORMAT,
    PDF_RENDER_SCOPE,
    render_pdf_pages,
)

pypdf = pytest.importorskip("pypdf")
Image = pytest.importorskip("PIL.Image")
pytest.importorskip("pypdfium2")
pypdf_generic = import_module("pypdf.generic")
PdfWriter = pypdf.PdfWriter
NameObject = pypdf_generic.NameObject
NumberObject = pypdf_generic.NumberObject
image_helpers = import_module("padiem_ai_core.image_helpers")
image_to_pdf = image_helpers.image_to_pdf


def _image_pdf() -> bytes:
    image = Image.new("RGB", (64, 48), (20, 40, 60))
    encoded = BytesIO()
    image.save(encoded, format="PNG")
    return image_to_pdf((encoded.getvalue(),)).data


def _text_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=144, height=96)
    page[NameObject("/Rotate")] = NumberObject(90)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_full_page_rendering_is_bounded_and_provenanced() -> None:
    result = render_pdf_pages(name="report.pdf", payload=_image_pdf())

    assert result.scope == PDF_RENDER_SCOPE
    assert result.full_page_render_claimed is True
    assert result.page_count == 1
    assert result.output_byte_size > 0
    page = result.pages[0]
    assert page.page_number == 1
    assert page.data.startswith(b"\x89PNG")
    assert page.image_format == PDF_RENDER_OUTPUT_FORMAT
    assert 1 <= page.width <= MAX_PDF_RENDER_PAGE_EDGE
    assert 1 <= page.height <= MAX_PDF_RENDER_PAGE_EDGE


def test_text_page_rendering_records_rotation() -> None:
    result = render_pdf_pages(name="text.pdf", payload=_text_pdf())

    assert result.page_count == 1
    assert result.pages[0].rotation == 90
    assert result.pages[0].data.startswith(b"\x89PNG")


def test_public_projection_excludes_rendered_bytes() -> None:
    result = render_pdf_pages(name="report.pdf", payload=_image_pdf())
    public = result.safe_dict()

    assert "data" not in public
    assert str(result.pages[0].data) not in str(public)


def test_render_bounds_and_invalid_inputs_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DocumentNormalizationError) as invalid:
        render_pdf_pages(name="report.pdf", payload=b"not a pdf")
    assert invalid.value.code == "pdf_render_reader_failed"

    with pytest.raises(DocumentNormalizationError) as media:
        render_pdf_pages(name="report.txt", media_type="text/plain", payload=b"text")
    assert media.value.code == "unsupported_binary_media_type"

    with monkeypatch.context() as context:
        context.setattr("padiem_ai_core.pdf_render.MAX_PDF_RENDER_PAGES", 0)
        with pytest.raises(DocumentNormalizationError) as pages:
            render_pdf_pages(name="report.pdf", payload=_image_pdf())
        assert pages.value.code == "pdf_render_page_limit"

    with monkeypatch.context() as context:
        context.setattr("padiem_ai_core.pdf_render.MAX_PDF_RENDER_PAGE_EDGE", 1)
        with pytest.raises(DocumentNormalizationError) as dimensions:
            render_pdf_pages(name="report.pdf", payload=_image_pdf())
        assert dimensions.value.code == "pdf_render_page_size_limit"

    with monkeypatch.context() as context:
        context.setattr("padiem_ai_core.pdf_render.MAX_PDF_RENDER_OUTPUT_BYTES", 1)
        with pytest.raises(DocumentNormalizationError) as output:
            render_pdf_pages(name="report.pdf", payload=_image_pdf())
        assert output.value.code == "pdf_render_output_limit"


def test_render_source_has_no_external_renderer_or_ocr_authority() -> None:
    source = (
        Path(__file__)
        .parents[1]
        .joinpath("padiem_ai_core", "pdf_render.py")
        .read_text(encoding="utf-8")
    )
    for token in ("subprocess", "fitz", "pymupdf", "ghostscript", "ocr", "http"):
        assert token not in source.lower()
