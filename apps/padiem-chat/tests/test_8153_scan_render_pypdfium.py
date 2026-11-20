"""#8153 — scan-page rendering uses the shared pypdfium2 renderer.

The scan path must not import PyMuPDF (AGPL, absent on the COM2 host). It goes
through document_page_render, which owns the process-wide PDFium mutex from
#8148. Fixtures are built here with Pillow; no other test file is imported and
no real sleep or network is involved.
"""
from __future__ import annotations

import io
import sys

import pytest

pdfium = pytest.importorskip("pypdfium2", reason="renderer extra is host-only")
from PIL import Image
from padiem_ai_core.document_normalization import DocumentNormalizationError

from app import document_page_render as page_render
from app.pdfmd_scan_ocr import _render_scan_pages, plan_scan_pages


def _scan_pdf(width: int = 400, height: int = 600) -> bytes:
    """One image-only page: a scan with no native text layer."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (245, 244, 240)).save(buffer, format="PDF")
    return buffer.getvalue()


def test_rendered_page_size_follows_the_long_edge_bound():
    payload = _scan_pdf(400, 600)
    rendered = page_render.render_page(payload, 1, long_edge_px=200)
    assert (rendered.width, rendered.height) == (134, 200)
    assert rendered.jpeg.startswith(page_render.JPEG_MAGIC)


def test_scan_pages_render_through_the_shared_renderer():
    payload = _scan_pdf(400, 600)
    images = _render_scan_pages(payload, [1], 200)
    assert set(images) == {1}
    assert images[1].startswith(page_render.JPEG_MAGIC)

    plan = plan_scan_pages(name="scan.pdf", media_type="application/pdf",
                           payload=payload, enabled=True, long_edge_px=400)
    assert plan.page_count == 1
    assert len(plan.scan_pages) == 1
    assert plan.scan_pages[0].image_jpeg.startswith(page_render.JPEG_MAGIC)


def test_missing_renderer_falls_back_to_a_bounded_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(DocumentNormalizationError) as caught:
        _render_scan_pages(_scan_pdf(), [1], 200)
    assert caught.value.code == "document_dependency_unavailable"


def test_scan_render_shares_the_process_mutex(monkeypatch):
    # The scan path has no private pdfium call: it goes through render_page,
    # which holds the one lock every consumer shares (#8148).
    assert hasattr(page_render, "_RENDER_LOCK")
    assert isinstance(page_render._RENDER_LOCK, type(__import__("threading").Lock()))
    source = __import__("inspect").getsource(_render_scan_pages)
    assert "fitz" not in source
    assert "page_render.render_page" in source

    # The lock is actually acquired on a scan render (tracked, no real sleep).
    acquired = []

    class TrackingLock:
        def __enter__(self):
            acquired.append("enter")
            return self

        def __exit__(self, *args):
            acquired.append("exit")
            return False

    monkeypatch.setattr(page_render, "_RENDER_LOCK", TrackingLock())
    _render_scan_pages(_scan_pdf(), [1], 200)
    assert acquired.count("enter") == 1
    assert acquired.count("exit") == 1
