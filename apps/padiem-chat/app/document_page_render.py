"""#7955 ① — render one original PDF page to a JPEG for the compare view.

The compare pane needs a raster of the page it is comparing. Framing the PDF
depended on a CSP exception and on the browser having an inline viewer, and a
browser without one showed an empty pane (#7834). This renders the page on the
CPython host instead.

pypdfium2 is used deliberately: it is Apache-2.0/BSD, while PyMuPDF is AGPL and
would put the server code at risk. It is a native wheel, so it is declared in
an optional extra and installed on COM2 through
``deploy/host-com2/chat/requirements.txt``, not through the Worker bundle.
"""

from __future__ import annotations

import io
import math
import threading
from dataclasses import dataclass
from typing import Any

#: On-screen reading in a half-width pane; inside the renderer's own bound.
DEFAULT_PAGE_LONG_EDGE_PX = 1200
MIN_PAGE_LONG_EDGE_PX = 200
MAX_PAGE_LONG_EDGE_PX = 2000
MAX_PAGE_PIXELS = 4_000_000
JPEG_QUALITY = 82
JPEG_MAGIC = b"\xff\xd8\xff"

#: #8148: PDFium is not thread-safe. Every page render on this host — the
#: compare view and the scan reader alike — must go through one process-wide
#: mutex, or concurrent renders SIGSEGV and take Chat down. The lock lives
#: next to the only pdfium caller so every consumer shares the same one.
_RENDER_LOCK = threading.Lock()


class PageRenderUnavailable(Exception):
    """The renderer is not installed on this host — callers show the fallback."""


class PageRenderFailed(Exception):
    """The document or the requested page could not be rendered safely."""


@dataclass(frozen=True, slots=True)
class RenderedPage:
    number: int
    width: int
    height: int
    jpeg: bytes


def bounded_long_edge(raw: Any) -> int:
    """Clamp the requested long edge to the renderer's reviewed bound."""

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_LONG_EDGE_PX
    return max(MIN_PAGE_LONG_EDGE_PX, min(MAX_PAGE_LONG_EDGE_PX, value))


def _close(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except (OSError, RuntimeError, TypeError, ValueError):
            pass


def render_page(
    payload: Any, number: Any, *, long_edge_px: Any = DEFAULT_PAGE_LONG_EDGE_PX
) -> RenderedPage:
    """Rasterise exactly one page, returning its JPEG and its pixel size.

    #8148: the whole pdfium call sequence is serialised here, so the compare
    view and the scan reader can never overlap renders on this process.
    """
    with _RENDER_LOCK:
        return _render_page(payload, number, long_edge_px=long_edge_px)


def _render_page(
    payload: Any, number: Any, *, long_edge_px: Any = DEFAULT_PAGE_LONG_EDGE_PX
) -> RenderedPage:
    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError as error:
        raise PageRenderUnavailable("PDF page renderer is unavailable.") from error

    try:
        page_number = int(number)
    except (TypeError, ValueError) as error:
        raise PageRenderFailed("Page number is invalid.") from error

    source = bytes(payload) if isinstance(payload, (bytes, bytearray)) else b""
    if not source:
        raise PageRenderFailed("PDF payload is empty.")

    document = None
    page = None
    bitmap = None
    image = None
    try:
        try:
            document = pdfium.PdfDocument(source)
        except Exception as error:
            raise PageRenderFailed("PDF could not be opened for rendering.") from error
        try:
            page_count = len(document)
            if page_number < 1 or page_number > page_count:
                raise PageRenderFailed("Page number is outside the document.")
            page = document[page_number - 1]
            page_width, page_height = page.get_size()
            if page_width <= 0 or page_height <= 0:
                raise PageRenderFailed("Page geometry is invalid.")

            scale = bounded_long_edge(long_edge_px) / max(page_width, page_height)
            width = max(1, math.ceil(page_width * scale))
            height = max(1, math.ceil(page_height * scale))
            if width * height > MAX_PAGE_PIXELS:
                scale *= math.sqrt(MAX_PAGE_PIXELS / (width * height))
                width = max(1, math.ceil(page_width * scale))
                height = max(1, math.ceil(page_height * scale))

            bitmap = page.render(
                scale=scale, rotation=0, draw_annots=False, may_draw_forms=False
            )
            image = bitmap.to_pil()
            if image.mode in ("RGBA", "LA"):
                from PIL import Image

                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=False)
            jpeg = output.getvalue()
            if not jpeg.startswith(JPEG_MAGIC):
                raise PageRenderFailed("Page could not be encoded as JPEG.")
            return RenderedPage(number=page_number, width=width, height=height, jpeg=jpeg)
        except PageRenderFailed:
            raise
        except Exception as error:
            raise PageRenderFailed("Page could not be rendered safely.") from error
    finally:
        _close(image)
        _close(bitmap)
        _close(page)
        _close(document)


def render_page_jpeg(
    payload: Any, number: Any, *, long_edge_px: Any = DEFAULT_PAGE_LONG_EDGE_PX
) -> bytes:
    """The JPEG bytes only — the shape the existing route passes to Response."""

    return render_page(payload, number, long_edge_px=long_edge_px).jpeg
