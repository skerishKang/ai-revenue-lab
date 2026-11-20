"""One page of a stored original PDF, rendered for the compare view (#7834, #7955).

Why this module exists
----------------------
The compare view put the original in a same-origin ``<iframe>`` and let the
browser's own PDF viewer paint it. Two things went wrong with that: the page
policy has no ``frame-src`` allowance for this origin, so the browser refused
the frame and the pane stayed empty; and a browser without an inline PDF
viewer shows nothing at all. Rendering the page here removes both — the pane
receives one image of exactly the page the owner is comparing.

#7955: the renderer is pypdfium2 (Apache-2.0/BSD), not PyMuPDF (AGPL). Both the
dev/test venv and the COM2 host install it explicitly; where it is missing the
route answers 404 and the pane falls back to its notice and download button.

What it deliberately does not do
--------------------------------
* It never renders more than one page per request, so a 200 page original
  cannot be rasterised by accident.
* It reads the founder's own object only, through the same owner-scoped
  resolution every other item route uses, and answers ``private, no-store``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.responses import Response

from .document_convert_routes import (
    _NO_STORE,
    _not_found,
    _object_bytes,
    _r2_call,
    _resolve_item,
    _unavailable,
)
from .document_page_render import (
    DEFAULT_PAGE_LONG_EDGE_PX,
    PageRenderFailed,
    PageRenderUnavailable,
    render_page_jpeg,
)

#: Long edge of the rendered page. Chosen for on-screen reading of body text in
#: a half-width pane; the renderer clamps this to its own 200..2000 bound.
PREVIEW_PAGE_LONG_EDGE_PX = DEFAULT_PAGE_LONG_EDGE_PX

#: A page request beyond this is not answered by rendering anything. The route
#: also refuses numbers above the item's own page count.
MAX_PREVIEW_PAGE = 200

JPEG_MEDIA_TYPE = "image/jpeg"

#: #8148: the native PDFium mutex in ``document_page_render`` must never have a
#: queue of stuck ``to_thread`` jobs waiting on it. A single async gate admits
#: one render at a time, and a caller that waits longer than this gets the same
#: fallback the pane already shows instead of an unbounded wait.
PAGE_RENDER_WAIT_SECONDS = 10.0
_render_gate: asyncio.Semaphore | None = None


def _gate() -> asyncio.Semaphore:
    """The gate is bound to the running loop, so create it on first use."""

    global _render_gate
    if _render_gate is None:
        _render_gate = asyncio.Semaphore(1)
    return _render_gate


async def _enter_gate() -> bool:
    try:
        await asyncio.wait_for(
            _gate().acquire(), timeout=PAGE_RENDER_WAIT_SECONDS,
        )
    except asyncio.TimeoutError:
        return False
    return True


def _page_number(raw: Any, page_count: int) -> int | None:
    text = str(raw or "").strip()
    if not text.isdigit():
        return None
    number = int(text)
    if number < 1 or number > MAX_PREVIEW_PAGE:
        return None
    if page_count and number > page_count:
        return None
    return number


async def convert_item_original_page(request):
    """Render one page of the item's own original PDF as a JPEG.

    A page that cannot be rendered (beyond the document, damaged original,
    renderer unavailable) answers 404 so the view falls back to the download
    link instead of showing a broken image.
    """

    resolved = await _resolve_item(request)
    if resolved[-1] is not None:
        return resolved[-1]
    _uid, _ledger, bucket, item, _job, _error = resolved
    number = _page_number(request.path_params.get("page_no"), int(item.page_count or 0))
    if number is None:
        return _not_found()
    # #8148: take the turn before reading the original, so a queued request does
    # not hold a 50..200MB PDF while another render is in progress.
    if not await _enter_gate():
        return _unavailable()
    try:
        try:
            obj = await _r2_call(bucket, "get", item.original_key)
            payload = await _object_bytes(obj)
        except Exception:
            return _unavailable()
        try:
            image = await asyncio.to_thread(
                render_page_jpeg, payload, number,
                long_edge_px=PREVIEW_PAGE_LONG_EDGE_PX,
            )
        except (PageRenderFailed, PageRenderUnavailable):
            return _not_found()
        return Response(image, media_type=JPEG_MEDIA_TYPE, headers=dict(_NO_STORE))
    finally:
        _gate().release()
