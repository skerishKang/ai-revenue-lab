"""Phone hero lead must keep a readable backing over photo pockets (#7778).

The base veil fades out to the right and is fully transparent past 64% of the
band width, so a full-width phone paragraph used to lose its backing over the
right third (measured 3.97:1 worst-case against 9px-wide photo pockets at 390px
in light theme). The 900px block already declares a vertical veil, but its
plain-class selector cannot outrank the base ``[data-theme="light"]`` veil, so
light theme kept the horizontal one; the phone block now restates it with the
same attribute selector.

Contract: in light theme the paragraph's darkest 9px-wide backdrop pocket at
390/820/1440 keeps >=4.5:1 against the declared lead color; in dark theme the
brightest 9px-wide pocket does; and the phone block really carries the override
rule.
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
WIDTHS = ((390, 844), (820, 1180), (1440, 900))
POCKET = 9  # px; a patch narrower than this cannot sit behind whole glyphs
MIN_CONTRAST = 4.5


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
    out = tmp_path_factory.mktemp("lead-contrast-dist")
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


def lead_pocket_contrast(page, bright_pocket: bool) -> float:
    """Declared .hero-lead color vs an extreme 9px-wide backdrop pocket.

    bright_pocket=False (light theme, dark glyphs): the 5th percentile of the
    window-maximum grid — a window whose whole 9x9 extent stays dark, i.e. a
    photo pocket wide enough to sit behind whole glyphs.  bright_pocket=True
    (dark theme, light glyphs): the 95th percentile of the window-minimum grid —
    the brightest such pocket.  Window edges extend the border pixels, like the
    canvas filters do.
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
    half = POCKET // 2
    rows = [lums[y * w:(y + 1) * w] for y in range(h)]
    grid = []
    for y in range(h):
        for x in range(w):
            best = None
            for dy in range(-half, half + 1):
                yy = min(max(y + dy, 0), h - 1)
                row = rows[yy]
                for dx in range(-half, half + 1):
                    v = row[min(max(x + dx, 0), w - 1)]
                    # dark pocket: the window maximum (any light pixel disqualifies it);
                    # bright pocket: the window minimum (any dark pixel disqualifies it).
                    if best is None or (v < best if bright_pocket else v > best):
                        best = v
            grid.append(best)
    grid.sort()
    q = 0.95 if bright_pocket else 0.05
    pocket = grid[min(len(grid) - 1, int(len(grid) * q))]
    return _contrast(text_lum, pocket)


def test_phone_lead_keeps_a_backing_over_dark_photo_pockets(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".hero-lead")
        for w, hgt in WIDTHS:
            page.set_viewport_size({"width": w, "height": hgt})
            page.evaluate("() => document.fonts.ready")
            page.wait_for_timeout(300)
            worst = lead_pocket_contrast(page, bright_pocket=False)
            assert worst >= MIN_CONTRAST, (
                f"{w}px: darkest 9px backdrop pocket behind the paragraph is "
                f"{worst:.2f}:1 against the declared lead color"
            )
    finally:
        page.close()


def test_dark_theme_lead_keeps_clear_of_bright_photo_pockets(browser, base_url):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    context.add_init_script("try{localStorage.setItem('theme','dark')}catch(e){}")
    page = context.new_page()
    try:
        page.goto(base_url + "index.html", wait_until="load")
        page.wait_for_selector(".hero-lead")
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark", (
            "the dark fixture did not apply"
        )
        for w, hgt in WIDTHS:
            page.set_viewport_size({"width": w, "height": hgt})
            page.evaluate("() => document.fonts.ready")
            page.wait_for_timeout(300)
            worst = lead_pocket_contrast(page, bright_pocket=True)
            assert worst >= MIN_CONTRAST, (
                f"{w}px: brightest 9px backdrop pocket behind the paragraph is "
                f"{worst:.2f}:1 against the declared dark-theme lead color"
            )
    finally:
        page.close()
        context.close()


def _media_blocks(css: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"@media[ ]*[(]([^)]*)[)][ ]*[{]", css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append((m.group(1), css[m.end(): i - 1]))
    return out


def test_the_phone_block_carries_the_light_veil_override():
    """The tablet block's plain-class selector loses the cascade in light theme;
    the phone block must restate the veil with the attribute selector."""
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    joined = chr(10).join(
        body for cond, body in _media_blocks(styles) if cond.replace(" ", "") == "max-width:760px"
    )
    assert re.search(
        r"\[data-theme=[\"']light[\"']\]\s*\.hero-bg::after\s*\{[^}]*linear-gradient\(180deg",
        joined,
    ), "the phone block must override the base light veil with a vertical gradient"
