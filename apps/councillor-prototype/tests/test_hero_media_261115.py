"""First-screen hero and home media thumbnails, measured in a real browser from
the dist build.

The tablet band (761-900px) used to keep the desktop two-column hero, where the
growing band pushed the portrait box left into the paragraph (measured 3,740
px^2 of box overlap at 820px, with glyphs landing on the portrait's dark hair).
The stacked hero now starts at the 900px nav breakpoint, and the home media
column shows 120x90 thumbnails instead of the desktop 60x45 list on touch
screens.

Contract: no paragraph/portrait box overlap at any width, >=4.5:1 paragraph
contrast against its rendered backdrop, and >=44px-tall media rows with
recognizable thumbnails on phone/tablet.
"""
from __future__ import annotations

import http.server
import os
import re
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path
from css_source import read_site_css

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
CHROME = next(
    (
        candidate
        for candidate in (
            os.environ.get("B61_CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        if candidate and Path(candidate).is_file()
    ),
    None,
)
PNG_SIG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
WIDTHS = ((390, 844), (820, 1180), (1024, 768), (1440, 900))


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BUILD_DIR), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


BUILD_DIR = None


@pytest.fixture(scope="module")
def build_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("hero-media-dist")
    result = subprocess.run(
        [sys.executable, "scripts/build-dist", "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture(scope="module")
def base_url(build_dir):
    global BUILD_DIR
    BUILD_DIR = build_dir
    server = StaticServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None or not CHROME:
        pytest.skip("playwright or Chrome is not installed")
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(headless=True, executable_path=CHROME)
        yield launched
        launched.close()


HERO_METRICS = """() => {
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {l: r.left, t: r.top, r: r.left + r.width, b: r.top + r.height};
  };
  const inter = (a, b) => {
    if (!a || !b) return null;
    const dx = Math.min(a.r, b.r) - Math.max(a.l, b.l);
    const dy = Math.min(a.b, b.b) - Math.max(a.t, b.t);
    return Math.max(0, dx) * Math.max(0, dy);
  };
  return {
    interLeadPortrait: inter(rect('.hero-lead'), rect('.hero-portrait')),
    interActionsPortrait: inter(rect('.hero-actions'), rect('.hero-portrait')),
  };
}"""


def _png_rgb(png: bytes) -> tuple[int, int, list]:
    """Decode an 8-bit non-interlaced RGB/RGBA PNG into (w, h, flat RGBA list)."""
    assert png[:8] == PNG_SIG, "screenshot is not a PNG"
    pos, idat, w, h, ct = 8, b"", 0, 0, 0
    while pos < len(png):
        (ln,) = struct.unpack(">I", png[pos:pos + 4])
        typ = png[pos + 4:pos + 8]
        chunk = png[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ct = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8 and chunk[10] == 0, "expect 8-bit non-interlaced PNG"
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    nch = {0: 1, 2: 3, 6: 4}[ct]
    raw = zlib.decompress(idat)
    stride = w * nch
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    p = 0
    for row in range(h):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(nch, stride):
                line[i] = (line[i] + line[i - nch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                left = line[i - nch] if i >= nch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                b = prev[i]
                c = prev[i - nch] if i >= nch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        base = row * w * 4
        for i in range(w):
            o = base + i * 4
            s = i * nch
            out[o] = line[s]
            out[o + 1] = line[s + 1 if nch > 1 else s]
            out[o + 2] = line[s + 2 if nch > 2 else s]
            out[o + 3] = line[s + 3] if nch == 4 else 255
        prev = line
    return w, h, list(out)


def _lum(r: int, g: int, b: int) -> float:
    def ch(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def lead_worst_contrast(page) -> float:
    """Declared .hero-lead color vs the darkest row backdrop behind its glyphs.

    Per text row: the backdrop is the 85th percentile of that row's light pixels
    (clear of antialiased glyph edges); the worst row is the reported value.
    """
    clip, color = page.evaluate(
        """() => { const el = document.querySelector('.hero-lead');
                   const r = el.getBoundingClientRect();
                   return [{x: Math.max(0, r.left), y: Math.max(0, r.top),
                            width: Math.min(r.width, innerWidth - Math.max(0, r.left)),
                            height: r.height},
                           getComputedStyle(el).color]; }"""
    )
    text_lum = _lum(*[int(float(p)) for p in color[color.index("(") + 1:color.rindex(")")].split(",")[:3]])
    w, h, px = _png_rgb(page.screenshot(clip=clip, scale="css"))
    lums = [_lum(px[i], px[i + 1], px[i + 2]) for i in range(0, len(px), 4)]
    worst = None
    for y in range(h):
        row = lums[y * w:(y + 1) * w]
        if not any(abs(v - text_lum) < 0.06 for v in row):
            continue  # a row without glyphs is not behind any text
        light = sorted(v for v in row if v > text_lum + 0.25)
        if len(light) < w * 0.2:
            continue  # photo-covered row; the overlap test guards this case
        bg = light[int(0.85 * (len(light) - 1))]
        value = _contrast(text_lum, bg)
        worst = value if worst is None else min(worst, value)
    assert worst is not None, "no text rows found in the paragraph box"
    return worst


def test_the_hero_copy_never_meets_the_portrait(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".hero-lead")
        for w, hgt in WIDTHS:
            page.set_viewport_size({"width": w, "height": hgt})
            page.wait_for_timeout(200)
            m = page.evaluate(HERO_METRICS)
            assert m["interLeadPortrait"] == 0, (
                f"{w}px: the paragraph box meets the portrait box "
                f"({m['interLeadPortrait']:.0f}px^2)"
            )
            if w <= 900:
                assert m["interActionsPortrait"] == 0, (
                    f"{w}px: the stacked hero must keep the actions off the portrait too"
                )
    finally:
        page.close()


def test_the_hero_lead_contrast_stays_above_4_5(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".hero-lead")
        for w, hgt in WIDTHS:
            page.set_viewport_size({"width": w, "height": hgt})
            page.wait_for_timeout(200)
            worst = lead_worst_contrast(page)
            assert worst >= 4.5, f"{w}px: worst paragraph row contrast is {worst:.2f}"
    finally:
        page.close()


def test_media_thumbs_are_readable_on_touch_screens(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".col-thumb")
        for w, hgt in ((390, 844), (820, 1180)):
            page.set_viewport_size({"width": w, "height": hgt})
            page.wait_for_timeout(200)
            m = page.evaluate(
                """() => ({
                     thumbs: [...document.querySelectorAll('.col-thumb')]
                       .map((el) => el.getBoundingClientRect())
                       .map((r) => ({w: r.width, h: r.height})),
                     rows: [...document.querySelectorAll('.col-item')]
                       .map((el) => el.getBoundingClientRect())
                       .map((r) => ({w: r.width, h: r.height})),
                   })"""
            )
            assert m["thumbs"], f"{w}px: no media thumbnails rendered"
            for t in m["thumbs"]:
                assert t["w"] >= 120 and t["h"] >= 90, (
                    f"{w}px: thumbnail {t['w']:.0f}x{t['h']:.0f} is not recognizable"
                )
            for r in m["rows"]:
                assert min(r["w"], r["h"]) >= 44, (
                    f"{w}px: media row {r['w']:.0f}x{r['h']:.0f} is under the tap minimum"
                )
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(200)
        desktop = page.evaluate(
            """() => [...document.querySelectorAll('.col-thumb')]
                      .map((el) => el.getBoundingClientRect())
                      .map((r) => ({w: r.width, h: r.height}))"""
        )
        assert desktop, "no media thumbnails rendered at 1440px"
        for t in desktop:
            # the desktop list keeps its compact 60x45 slot
            assert t["w"] == 60 and t["h"] == 45, f"1440px: desktop thumb drifted to {t}"
    finally:
        page.close()


def _media_blocks(css: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"@media[ ]*[(]([^)]*)[)][ ]*[{]", css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append((m.group(1), css[m.end(): i - 1]))
    return out


def test_the_stacked_hero_starts_at_the_nav_breakpoint():
    """The tablet band must not render the desktop arrangement any more."""
    styles = read_site_css()
    joined = chr(10).join(
        body for cond, body in _media_blocks(styles) if cond.replace(" ", "") == "max-width:900px"
    )
    assert re.search(r"[.]hero[ ]*[{][^}]*flex-direction:[ ]*column", joined), (
        "no stacked hero in the 900px block"
    )
    assert re.search(r"[.]hero-portrait[ ]*[{][^}]*position:[ ]*static", joined), (
        "the portrait must leave its absolute desktop position in the 900px block"
    )
    assert re.search(r"[.]col-thumb[ ]*[{][^}]*width:[ ]*120px", joined), (
        "the 900px block must enlarge the media thumbnails"
    )
