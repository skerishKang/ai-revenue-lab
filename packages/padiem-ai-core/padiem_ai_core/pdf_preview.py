"""Bounded embedded-image preview extraction from canonical PDF pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    DocumentNormalizationError,
    _open_pdf_reader,
    validate_document_identity,
)
from .image_helpers import ImageContractError, thumbnail_image

MAX_PDF_PREVIEW_PAGES = 32
MAX_PDF_PREVIEW_IMAGES = 64
MAX_PDF_PREVIEW_IMAGES_PER_PAGE = 4
MAX_PDF_PREVIEW_SOURCE_BYTES = 16 * 1024 * 1024
MAX_PDF_PREVIEW_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_PDF_PREVIEW_EDGE = 512
PDF_PREVIEW_OUTPUT_FORMAT = "PNG"
PDF_PREVIEW_SCOPE = "embedded_images_only"
PDF_PREVIEW_PAGE_STATUS_EMBEDDED = "embedded_image_previews"
PDF_PREVIEW_PAGE_STATUS_NONE = "no_embedded_image_preview"


@dataclass(frozen=True, slots=True)
class PdfPreviewImage:
    """One bounded thumbnail with page and image provenance."""

    page_number: int
    image_index: int
    data: bytes = field(repr=False)
    image_format: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.image_index < 1:
            raise ValueError("PDF preview image provenance is invalid.")
        if (
            not isinstance(self.data, bytes)
            or not self.data
            or len(self.data) > MAX_PDF_PREVIEW_OUTPUT_BYTES
        ):
            raise ValueError("PDF preview image data is invalid.")
        if not isinstance(self.image_format, str) or not self.image_format:
            raise ValueError("PDF preview image format is invalid.")
        if (
            not isinstance(self.width, int)
            or not isinstance(self.height, int)
            or self.width < 1
            or self.height < 1
            or self.width > MAX_PDF_PREVIEW_EDGE
            or self.height > MAX_PDF_PREVIEW_EDGE
        ):
            raise ValueError("PDF preview image dimensions are invalid.")

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "image_index": self.image_index,
            "format": self.image_format,
            "width": self.width,
            "height": self.height,
            "byte_size": len(self.data),
        }


@dataclass(frozen=True, slots=True)
class PdfPreviewPage:
    """Bounded preview records for one PDF page."""

    page_number: int
    images: tuple[PdfPreviewImage, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("PDF preview page number is invalid.")
        if len(self.images) > MAX_PDF_PREVIEW_IMAGES_PER_PAGE:
            raise ValueError("PDF preview page image count is invalid.")
        if any(image.page_number != self.page_number for image in self.images):
            raise ValueError("PDF preview image page provenance is invalid.")
        if [image.image_index for image in self.images] != list(
            range(1, len(self.images) + 1)
        ):
            raise ValueError("PDF preview image indices are not contiguous.")

    @property
    def status(self) -> str:
        return (
            PDF_PREVIEW_PAGE_STATUS_EMBEDDED
            if self.images
            else PDF_PREVIEW_PAGE_STATUS_NONE
        )

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "status": self.status,
            "images": [image.safe_dict() for image in self.images],
        }


@dataclass(frozen=True, slots=True)
class PdfPreviewResult:
    """Bounded embedded-image preview result for a PDF."""

    pages: tuple[PdfPreviewPage, ...]
    page_count: int
    embedded_image_count: int
    output_byte_size: int
    scope: str = PDF_PREVIEW_SCOPE
    full_page_render_claimed: bool = False

    def __post_init__(self) -> None:
        if (
            self.page_count < 1
            or self.page_count > MAX_PDF_PREVIEW_PAGES
            or self.embedded_image_count > MAX_PDF_PREVIEW_IMAGES
            or self.output_byte_size > MAX_PDF_PREVIEW_OUTPUT_BYTES
            or len(self.pages) != self.page_count
        ):
            raise ValueError("PDF preview page count is invalid.")
        if [page.page_number for page in self.pages] != list(
            range(1, self.page_count + 1)
        ):
            raise ValueError("PDF preview page numbers are not contiguous.")
        image_count = sum(len(page.images) for page in self.pages)
        if image_count != self.embedded_image_count:
            raise ValueError("PDF preview image count is invalid.")
        if self.output_byte_size != sum(
            len(image.data) for page in self.pages for image in page.images
        ):
            raise ValueError("PDF preview output byte count is invalid.")
        if self.scope != PDF_PREVIEW_SCOPE or self.full_page_render_claimed:
            raise ValueError("PDF preview scope is invalid.")

    @property
    def status(self) -> str:
        return (
            PDF_PREVIEW_PAGE_STATUS_EMBEDDED
            if self.embedded_image_count
            else PDF_PREVIEW_PAGE_STATUS_NONE
        )

    def safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "scope": self.scope,
            "full_page_render_claimed": self.full_page_render_claimed,
            "page_count": self.page_count,
            "embedded_image_count": self.embedded_image_count,
            "output_byte_size": self.output_byte_size,
            "pages": [page.safe_dict() for page in self.pages],
        }


def _preview_error(code: str, message: str) -> DocumentNormalizationError:
    return DocumentNormalizationError(code, message)


def render_pdf_embedded_image_previews(
    *,
    name: Any,
    media_type: Any,
    payload: Any,
) -> PdfPreviewResult:
    """Extract bounded thumbnails for embedded PDF page images."""

    _, safe_media = validate_document_identity(
        name=name, media_type=media_type, source_kind="binary"
    )
    if safe_media != "application/pdf":
        raise _preview_error(
            "pdf_preview_media_type_invalid", "PDF preview requires a PDF document."
        )
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise _preview_error(
            "pdf_preview_payload_invalid", "PDF preview payload is invalid."
        )
    binary = bytes(payload)
    if len(binary) > MAX_BINARY_DOCUMENT_BYTES:
        raise _preview_error(
            "pdf_preview_payload_limit", "PDF preview payload exceeds the byte limit."
        )
    reader = _open_pdf_reader(binary)
    try:
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PREVIEW_PAGES:
            raise _preview_error(
                "pdf_preview_page_limit", "PDF preview page count exceeds the limit."
            )
        pages: list[PdfPreviewPage] = []
        total_images = 0
        total_source_bytes = 0
        total_output_bytes = 0
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                images = tuple(page.images)
            except Exception as error:
                raise _preview_error(
                    "pdf_preview_page_read_failed",
                    "PDF preview page images could not be read.",
                ) from error
            if len(images) > MAX_PDF_PREVIEW_IMAGES_PER_PAGE:
                raise _preview_error(
                    "pdf_preview_image_count_exceeded",
                    "PDF preview page image count exceeds the limit.",
                )
            if total_images + len(images) > MAX_PDF_PREVIEW_IMAGES:
                raise _preview_error(
                    "pdf_preview_image_count_exceeded",
                    "PDF preview image count exceeds the limit.",
                )
            previews: list[PdfPreviewImage] = []
            for image_index, image in enumerate(images, start=1):
                try:
                    source = bytes(image.data)
                except Exception as error:
                    raise _preview_error(
                        "pdf_preview_image_read_failed",
                        "PDF preview image could not be read.",
                    ) from error
                if not source:
                    raise _preview_error(
                        "pdf_preview_image_read_failed", "PDF preview image is empty."
                    )
                total_source_bytes += len(source)
                if total_source_bytes > MAX_PDF_PREVIEW_SOURCE_BYTES:
                    raise _preview_error(
                        "pdf_preview_source_bytes_exceeded",
                        "PDF preview source image bytes exceed the limit.",
                    )
                try:
                    thumbnail = thumbnail_image(
                        source,
                        size=(MAX_PDF_PREVIEW_EDGE, MAX_PDF_PREVIEW_EDGE),
                        output_format=PDF_PREVIEW_OUTPUT_FORMAT,
                    )
                except ImageContractError as error:
                    raise _preview_error(
                        "pdf_preview_image_invalid", "PDF preview image is invalid."
                    ) from error
                total_output_bytes += len(thumbnail.data)
                if total_output_bytes > MAX_PDF_PREVIEW_OUTPUT_BYTES:
                    raise _preview_error(
                        "pdf_preview_output_bytes_exceeded",
                        "PDF preview output bytes exceed the limit.",
                    )
                previews.append(
                    PdfPreviewImage(
                        page_number=page_index,
                        image_index=image_index,
                        data=thumbnail.data,
                        image_format=thumbnail.format,
                        width=thumbnail.width,
                        height=thumbnail.height,
                    )
                )
            pages.append(PdfPreviewPage(page_number=page_index, images=tuple(previews)))
            total_images += len(previews)
        return PdfPreviewResult(
            pages=tuple(pages),
            page_count=page_count,
            embedded_image_count=total_images,
            output_byte_size=total_output_bytes,
        )
    finally:
        reader.close() if hasattr(reader, "close") else None


__all__ = [
    "MAX_PDF_PREVIEW_EDGE",
    "MAX_PDF_PREVIEW_IMAGES",
    "MAX_PDF_PREVIEW_IMAGES_PER_PAGE",
    "MAX_PDF_PREVIEW_OUTPUT_BYTES",
    "MAX_PDF_PREVIEW_PAGES",
    "MAX_PDF_PREVIEW_SOURCE_BYTES",
    "PDF_PREVIEW_OUTPUT_FORMAT",
    "PDF_PREVIEW_PAGE_STATUS_EMBEDDED",
    "PDF_PREVIEW_PAGE_STATUS_NONE",
    "PDF_PREVIEW_SCOPE",
    "PdfPreviewImage",
    "PdfPreviewPage",
    "PdfPreviewResult",
    "render_pdf_embedded_image_previews",
]
