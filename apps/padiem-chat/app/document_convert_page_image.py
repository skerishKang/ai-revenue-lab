"""One page of a stored original PDF, rendered for the compare view (#7834).

Why this module exists
----------------------
The compare view put the original in a same-origin ``<iframe>`` and let the
browser's own PDF viewer paint it. Two things went wrong with that: the page
policy has no ``frame-src`` allowance for this origin, so the browser refused
the frame and the pane stayed empty; and a browser without an inline PDF
viewer shows nothing at all. Rendering the page here removes both — the pane
receives one image of exactly the page the owner is comparing.

What it deliberately does not do
--------------------------------
* It never renders more than one page per request, so a 200 page original
  cannot be rasterised by accident.
* It reuses the reviewed PyMuPDF renderer the scan lane already ships
  (``pdfmd_scan_ocr.render_page_jpeg``); no second PDF dependency, no new
  page-detection rule.
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
from .pdfmd_scan_ocr import render_page_jpeg

#: Long edge of the rendered page. Chosen for on-screen reading of body text in
#: a half-width pane; well inside the renderer's own 400..2000 bound.
PREVIEW_PAGE_LONG_EDGE_PX = 1200

#: A page request beyond this is not answered by rendering anything. The route
#: also refuses numbers above the item's own page count.
MAX_PREVIEW_PAGE = 200

JPEG_MEDIA_TYPE = "image/jpeg"


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
    try:
        obj = await _r2_call(bucket, "get", item.original_key)
        payload = await _object_bytes(obj)
    except Exception:
        return _unavailable()
    try:
        image = await asyncio.to_thread(
            render_page_jpeg, payload, number, PREVIEW_PAGE_LONG_EDGE_PX
        )
    except Exception:
        return _not_found()
    return Response(image, media_type=JPEG_MEDIA_TYPE, headers=dict(_NO_STORE))