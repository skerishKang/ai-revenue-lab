"""#2827 bounded embedded-image PDF preview tests."""

from __future__ import annotations

from importlib import import_module
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from padiem_ai_core.document_normalization import DocumentNormalizationError

Image = pytest.importorskip("PIL.Image")
pdf_preview = import_module("padiem_ai_core.pdf_preview")
image_helpers = import_module("padiem_ai_core.image_helpers")
image_to_pdf = image_helpers.image_to_pdf
MAX_PDF_PREVIEW_EDGE = pdf_preview.MAX_PDF_PREVIEW_EDGE
PDF_PREVIEW_PAGE_STATUS_EMBEDDED = pdf_preview.PDF_PREVIEW_PAGE_STATUS_EMBEDDED
PDF_PREVIEW_PAGE_STATUS_NONE = pdf_preview.PDF_PREVIEW_PAGE_STATUS_NONE
PDF_PREVIEW_SCOPE = pdf_preview.PDF_PREVIEW_SCOPE
render_pdf_embedded_image_previews = pdf_preview.render_pdf_embedded_image_previews


def _image_bytes(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (64, 40),
    color: tuple[int, int, int] = (30, 60, 90),
) -> bytes:
    image = Image.new("RGB", size, color)
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def _image_backed_pdf() -> bytes:
    return image_to_pdf((_image_bytes(), _image_bytes("JPEG", size=(40, 64)))).data


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_embedded_image_previews_are_bounded_and_provenanced() -> None:
    result = render_pdf_embedded_image_previews(
        name="report.pdf",
        media_type="application/pdf",
        payload=_image_backed_pdf(),
    )

    assert result.scope == PDF_PREVIEW_SCOPE
    assert result.full_page_render_claimed is False
    assert result.page_count == 2
    assert result.embedded_image_count == 2
    assert result.output_byte_size > 0
    assert [page.page_number for page in result.pages] == [1, 2]
    assert all(page.status == PDF_PREVIEW_PAGE_STATUS_EMBEDDED for page in result.pages)
    assert all(
        image.data.startswith(b"\x89PNG")
        and image.width <= MAX_PDF_PREVIEW_EDGE
        and image.height <= MAX_PDF_PREVIEW_EDGE
        for page in result.pages
        for image in page.images
    )


def test_blank_pdf_returns_explicit_no_embedded_image_state() -> None:
    result = render_pdf_embedded_image_previews(
        name="blank.pdf",
        media_type="application/pdf",
        payload=_blank_pdf(),
    )

    assert result.status == PDF_PREVIEW_PAGE_STATUS_NONE
    assert result.embedded_image_count == 0
    assert result.output_byte_size == 0
    assert result.pages[0].status == PDF_PREVIEW_PAGE_STATUS_NONE


def test_public_projection_excludes_preview_bytes() -> None:
    result = render_pdf_embedded_image_previews(
        name="report.pdf",
        media_type="application/pdf",
        payload=_image_backed_pdf(),
    )
    public = result.safe_dict()

    assert public["full_page_render_claimed"] is False
    assert "data" not in public
    assert str(result.pages[0].images[0].data) not in str(public)


def test_invalid_identity_and_pdf_inputs_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as media:
        render_pdf_embedded_image_previews(
            name="report.txt",
            media_type="text/plain",
            payload=b"text",
        )
    assert media.value.code == "unsupported_binary_media_type"

    with pytest.raises(DocumentNormalizationError) as malformed:
        render_pdf_embedded_image_previews(
            name="report.pdf",
            media_type="application/pdf",
            payload=b"not a pdf",
        )
    assert malformed.value.code == "pdf_magic_mismatch"

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    encrypted = BytesIO()
    writer.write(encrypted)
    with pytest.raises(DocumentNormalizationError) as locked:
        render_pdf_embedded_image_previews(
            name="locked.pdf",
            media_type="application/pdf",
            payload=encrypted.getvalue(),
        )
    assert locked.value.code == "pdf_encrypted"


def test_preview_bounds_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _image_backed_pdf()

    with monkeypatch.context() as context:
        context.setattr(pdf_preview, "MAX_PDF_PREVIEW_PAGES", 1)
        with pytest.raises(DocumentNormalizationError) as pages:
            render_pdf_embedded_image_previews(
                name="report.pdf", media_type="application/pdf", payload=payload
            )
        assert pages.value.code == "pdf_preview_page_limit"

    with monkeypatch.context() as context:
        context.setattr(pdf_preview, "MAX_PDF_PREVIEW_IMAGES_PER_PAGE", 0)
        with pytest.raises(DocumentNormalizationError) as images:
            render_pdf_embedded_image_previews(
                name="report.pdf", media_type="application/pdf", payload=payload
            )
        assert images.value.code == "pdf_preview_image_count_exceeded"

    with monkeypatch.context() as context:
        context.setattr(pdf_preview, "MAX_PDF_PREVIEW_SOURCE_BYTES", 1)
        with pytest.raises(DocumentNormalizationError) as source:
            render_pdf_embedded_image_previews(
                name="report.pdf", media_type="application/pdf", payload=payload
            )
        assert source.value.code == "pdf_preview_source_bytes_exceeded"

    with monkeypatch.context() as context:
        context.setattr(pdf_preview, "MAX_PDF_PREVIEW_OUTPUT_BYTES", 1)
        with pytest.raises(DocumentNormalizationError) as output:
            render_pdf_embedded_image_previews(
                name="report.pdf", media_type="application/pdf", payload=payload
            )
        assert output.value.code == "pdf_preview_output_bytes_exceeded"


def test_preview_source_has_no_external_renderer_or_network_authority() -> None:
    source = Path(pdf_preview.__file__).read_text(encoding="utf-8")
    for token in ("fitz", "pymupdf", "ghostscript", "subprocess", "Popen", "urllib"):
        assert token not in source
