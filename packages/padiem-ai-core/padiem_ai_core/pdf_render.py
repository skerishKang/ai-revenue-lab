"""Bounded full-page raster rendering through an adopted PDFium adapter."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
    validate_document_identity,
)

MAX_PDF_RENDER_PAGES = 32
MAX_PDF_RENDER_PIXELS = 4_000_000
MAX_PDF_RENDER_PAGE_EDGE = 4096
MAX_PDF_RENDER_OUTPUT_BYTES = 8 * 1024 * 1024
PDF_RENDER_SCALE = 1.0
PDF_RENDER_OUTPUT_FORMAT = "PNG"
PDF_RENDER_SCOPE = "full_page_raster_preview"
PDF_RENDERER = "pypdfium2_pdfium"


@dataclass(frozen=True, slots=True)
class PdfRenderedPage:
    """One bounded rendered page and its non-byte provenance."""

    page_number: int
    width: int
    height: int
    rotation: int
    data: bytes = field(repr=False)
    image_format: str = PDF_RENDER_OUTPUT_FORMAT

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("PDF rendered page number is invalid.")
        if (
            not isinstance(self.width, int)
            or not isinstance(self.height, int)
            or self.width < 1
            or self.height < 1
            or self.width > MAX_PDF_RENDER_PAGE_EDGE
            or self.height > MAX_PDF_RENDER_PAGE_EDGE
            or self.width * self.height > MAX_PDF_RENDER_PIXELS
        ):
            raise ValueError("PDF rendered page dimensions are invalid.")
        if not isinstance(self.rotation, int) or self.rotation not in {0, 90, 180, 270}:
            raise ValueError("PDF rendered page rotation is invalid.")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("PDF rendered page data is invalid.")
        if self.image_format != PDF_RENDER_OUTPUT_FORMAT:
            raise ValueError("PDF rendered page format is invalid.")

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "format": self.image_format,
            "byte_size": len(self.data),
        }


@dataclass(frozen=True, slots=True)
class PdfRenderResult:
    """Bounded rendered pages with a stable payload-free projection."""

    pages: tuple[PdfRenderedPage, ...]
    page_count: int
    output_byte_size: int
    scope: str = PDF_RENDER_SCOPE
    renderer: str = PDF_RENDERER
    full_page_render_claimed: bool = True

    def __post_init__(self) -> None:
        if self.page_count < 1 or len(self.pages) != self.page_count:
            raise ValueError("PDF render page count is invalid.")
        if [page.page_number for page in self.pages] != list(
            range(1, self.page_count + 1)
        ):
            raise ValueError("PDF render page numbers are not contiguous.")
        if self.output_byte_size != sum(len(page.data) for page in self.pages):
            raise ValueError("PDF render output byte count is invalid.")
        if self.output_byte_size > MAX_PDF_RENDER_OUTPUT_BYTES:
            raise ValueError("PDF render output byte count exceeds the limit.")
        if self.scope != PDF_RENDER_SCOPE or self.renderer != PDF_RENDERER:
            raise ValueError("PDF render scope is invalid.")
        if not self.full_page_render_claimed:
            raise ValueError("PDF render result must identify its full-page scope.")

    def safe_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "renderer": self.renderer,
            "full_page_render_claimed": self.full_page_render_claimed,
            "page_count": self.page_count,
            "output_byte_size": self.output_byte_size,
            "pages": [page.safe_dict() for page in self.pages],
        }


def _render_error(code: str, message: str) -> DocumentNormalizationError:
    return DocumentNormalizationError(code, message)


def _close_resource(resource: Any, pdfium: Any) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except (OSError, RuntimeError, TypeError, ValueError, pdfium.PdfiumError):
        return


def render_pdf_pages(
    *,
    name: Any,
    media_type: Any = "application/pdf",
    payload: Any,
) -> PdfRenderResult:
    """Render admitted PDF pages to bounded PNG previews in memory."""

    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError as error:
        raise _render_error(
            "pdf_render_dependency_unavailable",
            "PDF rendering dependency is unavailable.",
        ) from error

    _, safe_media = validate_document_identity(
        name=name, media_type=media_type, source_kind="binary"
    )
    if safe_media != "application/pdf":
        raise _render_error(
            "pdf_render_media_type_invalid", "PDF rendering requires a PDF document."
        )
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise _render_error(
            "pdf_render_payload_invalid", "PDF rendering payload is invalid."
        )
    binary = bytes(payload)
    if len(binary) > MAX_BINARY_DOCUMENT_BYTES:
        raise _render_error(
            "pdf_render_payload_limit", "PDF rendering payload exceeds the byte limit."
        )

    document = None
    rendered_pages: list[PdfRenderedPage] = []
    output_byte_size = 0
    try:
        try:
            document = pdfium.PdfDocument(binary)
            page_count = len(document)
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            pdfium.PdfiumError,
        ) as error:
            raise _render_error(
                "pdf_render_reader_failed", "PDF renderer could not open the document."
            ) from error
        if page_count < 1:
            raise _render_error(
                "pdf_render_no_pages", "PDF rendering requires at least one page."
            )
        if page_count > MAX_PDF_RENDER_PAGES:
            raise _render_error(
                "pdf_render_page_limit", "PDF rendering page count exceeds the limit."
            )

        for page_index in range(page_count):
            page = None
            bitmap = None
            image = None
            try:
                page = document[page_index]
                page_width, page_height = page.get_size()
                width = math.ceil(float(page_width) * PDF_RENDER_SCALE)
                height = math.ceil(float(page_height) * PDF_RENDER_SCALE)
                rotation = int(page.get_rotation())
                if (
                    width < 1
                    or height < 1
                    or width > MAX_PDF_RENDER_PAGE_EDGE
                    or height > MAX_PDF_RENDER_PAGE_EDGE
                    or width * height > MAX_PDF_RENDER_PIXELS
                ):
                    raise _render_error(
                        "pdf_render_page_size_limit",
                        "PDF rendered page dimensions exceed the limit.",
                    )
                bitmap = page.render(
                    scale=PDF_RENDER_SCALE,
                    rotation=0,
                    draw_annots=False,
                    may_draw_forms=False,
                )
                image = bitmap.to_pil()
                output = BytesIO()
                image.save(output, format=PDF_RENDER_OUTPUT_FORMAT, optimize=False)
                encoded = output.getvalue()
                if not encoded:
                    raise _render_error(
                        "pdf_render_page_encode_failed",
                        "PDF rendered page could not be encoded.",
                    )
                output_byte_size += len(encoded)
                if output_byte_size > MAX_PDF_RENDER_OUTPUT_BYTES:
                    raise _render_error(
                        "pdf_render_output_limit",
                        "PDF rendered output exceeds the byte limit.",
                    )
                rendered_pages.append(
                    PdfRenderedPage(
                        page_number=page_index + 1,
                        width=width,
                        height=height,
                        rotation=rotation,
                        data=encoded,
                    )
                )
            except DocumentNormalizationError:
                raise
            except (
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                pdfium.PdfiumError,
            ) as error:
                raise _render_error(
                    "pdf_render_page_failed", "PDF rendered page could not be produced."
                ) from error
            finally:
                _close_resource(image, pdfium)
                _close_resource(bitmap, pdfium)
                _close_resource(page, pdfium)
    finally:
        _close_resource(document, pdfium)

    return PdfRenderResult(
        pages=tuple(rendered_pages),
        page_count=len(rendered_pages),
        output_byte_size=output_byte_size,
    )


__all__ = [
    "MAX_PDF_RENDER_OUTPUT_BYTES",
    "MAX_PDF_RENDER_PAGES",
    "MAX_PDF_RENDER_PAGE_EDGE",
    "MAX_PDF_RENDER_PIXELS",
    "PDF_RENDERER",
    "PDF_RENDER_OUTPUT_FORMAT",
    "PDF_RENDER_SCALE",
    "PDF_RENDER_SCOPE",
    "PdfRenderResult",
    "PdfRenderedPage",
    "render_pdf_pages",
]
