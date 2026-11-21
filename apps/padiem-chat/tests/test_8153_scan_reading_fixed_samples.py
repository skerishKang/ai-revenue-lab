"""#8153 — the scan-reading inputs are pinned against fixed sample documents.

#8156 moved scan-page rendering from PyMuPDF to the shared pypdfium2 renderer.
The reading pipeline consumes what this lane produces, so three deterministic
sample scans pin exactly what the reader receives: the page classification of
the plan, each page's rendered size and the ink a page carries. The samples
are drawn with fixed shapes (no randomness), so any drift in the render path —
a swapped page order, a scale change, a wrong page — moves a pinned number.

Exact JPEG bytes are deliberately not pinned: the rasteriser may re-encode
across pypdfium2 versions. The ink counts use a ±2% band for the same reason.
"""
from __future__ import annotations

import io

import pytest

pdfium = pytest.importorskip("pypdfium2", reason="renderer extra is host-only")
from PIL import Image, ImageDraw  # noqa: E402

from app.pdfmd_scan_ocr import plan_scan_pages  # noqa: E402

JPEG_MAGIC = b"\xff\xd8\xff"


def _page_a() -> Image.Image:
    """400×600: one filled rectangle, top-left third."""
    image = Image.new("RGB", (400, 600), (250, 249, 246))
    draw = ImageDraw.Draw(image)
    draw.rectangle([50, 40, 190, 150], fill=(20, 20, 20))
    return image


def _page_b() -> Image.Image:
    """300×500: three horizontal rules."""
    image = Image.new("RGB", (300, 500), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for top in (80, 200, 320):
        draw.rectangle([30, top, 270, top + 10], fill=(10, 10, 10))
    return image


def _page_c() -> Image.Image:
    """500×400: one thick diagonal stroke."""
    image = Image.new("RGB", (500, 400), (245, 244, 240))
    draw = ImageDraw.Draw(image)
    draw.line([40, 360, 460, 40], fill=(15, 15, 15), width=18)
    return image


def _fixed_scan_pdf() -> bytes:
    images = [_page_a(), _page_b(), _page_c()]
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True,
                   append_images=images[1:], resolution=72.0)
    return buffer.getvalue()


def _dark_pixels(jpeg: bytes) -> int:
    image = Image.open(io.BytesIO(jpeg)).convert("L")
    return sum(1 for value in image.getdata() if value < 64)


def _decoded_size(jpeg: bytes) -> tuple[int, int]:
    image = Image.open(io.BytesIO(jpeg))
    return image.size


def test_the_fixed_scan_plan_reads_three_scan_pages():
    plan = plan_scan_pages(name="fixed-samples.pdf", media_type="application/pdf",
                           payload=_fixed_scan_pdf(), enabled=True, long_edge_px=400)
    assert plan.page_count == 3
    assert plan.long_edge_px == 400
    assert [page.kind for page in plan.pages] == ["scan", "scan", "scan"]
    assert [page.text_characters for page in plan.pages] == [0, 0, 0]
    assert [page.number for page in plan.pages] == [1, 2, 3]


def test_each_sample_page_arrives_in_order_at_the_pinned_size():
    plan = plan_scan_pages(name="fixed-samples.pdf", media_type="application/pdf",
                           payload=_fixed_scan_pdf(), enabled=True, long_edge_px=400)
    sizes = []
    for page in plan.pages:
        assert page.image_jpeg is not None
        assert page.image_jpeg.startswith(JPEG_MAGIC)
        sizes.append(_decoded_size(page.image_jpeg))
    # The long edge is bounded at 400 and the short edge keeps the aspect:
    # 400×600 → 267×400, 300×500 → 240×400, 500×400 → 400×320.
    assert sizes == [(267, 400), (240, 400), (400, 320)]


def test_each_sample_page_carries_its_own_ink():
    plan = plan_scan_pages(name="fixed-samples.pdf", media_type="application/pdf",
                           payload=_fixed_scan_pdf(), enabled=True, long_edge_px=400)
    counts = [_dark_pixels(page.image_jpeg) for page in plan.pages]
    # Pinned at 6789/5208/5490; the band absorbs pdfium's edge antialiasing
    # across versions. Page order is already proven by the size pins above.
    assert 6300 <= counts[0] <= 7250   # 140×110 rectangle at a two-thirds scale
    assert 4800 <= counts[1] <= 5600   # three 240×10 rules
    assert 5100 <= counts[2] <= 5900   # one 18px diagonal


def test_a_longer_edge_scales_the_same_fixed_page():
    plan = plan_scan_pages(name="fixed-samples.pdf", media_type="application/pdf",
                           payload=_fixed_scan_pdf(), enabled=True, long_edge_px=600)
    page = plan.pages[0]
    assert _decoded_size(page.image_jpeg) == (400, 600)
