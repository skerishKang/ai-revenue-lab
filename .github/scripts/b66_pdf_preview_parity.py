from __future__ import annotations

import asyncio
import http.server
import os
from pathlib import Path
import socketserver
import threading

import fitz
from PIL import Image, ImageChops, ImageFilter, ImageStat
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
B66 = ROOT / "reference" / "business-66-padiem-quote-v1"
OUT = ROOT / "padiem-reports" / "2026-10-06" / "b66-pdf-preview-parity"
OUT.mkdir(parents=True, exist_ok=True)

RECIPIENT = "\uB300\uD55C\uAC74\uC124"
ITEM = "\uBC30\uAD00"
UNIT = "\uBBF8\uD130"
REP = "\uAE40\uBC94\uC2E0"
SENDER = "CGI \uD14C\uC2A4\uD2B8 \uACF5\uAE09\uC790"
PERSON = "\uAD6C\uB9E4\uB2F4\uB2F9"
MEMO = "\uD654\uBA74-PDF \uB3D9\uC77C\uC131 \uAC80\uC99D"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class Server(socketserver.TCPServer):
    allow_reuse_address = True


def start_server():
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(B66), **kwargs)
    srv = Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread


def normalized_text(value: str) -> str:
    return " ".join(value.split())


async def main() -> int:
    server, thread = start_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    browser_path = os.environ.get("B66_PARITY_BROWSER", "").strip() or None
    screen_path = OUT / "screen-quote-paper.png"
    pdf_path = OUT / "quote.pdf"
    pdf_png_path = OUT / "pdf-page-1.png"
    diff_path = OUT / "diff.png"

    try:
        async with async_playwright() as pw:
            launch_args = {"headless": True}
            if browser_path:
                launch_args["executable_path"] = browser_path
            browser = await pw.chromium.launch(**launch_args)
            context = await browser.new_context(
                viewport={"width": 1600, "height": 1400},
                device_scale_factor=1,
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_function(
                "window.B66QuoteAppBridge && window.B66QuoteAppBridge.getDraft"
            )

            await page.evaluate(
                """([recipient, item, unit, rep, sender, person, memo]) => {
                  const bridge = window.B66QuoteAppBridge;
                  const draft = bridge.getDraft();
                  draft.meta.quoteNo = 'CGI-PARITY-001';
                  draft.meta.issueDate = '2026-10-06';
                  draft.meta.validDays = 30;
                  draft.sender.company = sender;
                  draft.sender.rep = rep;
                  draft.recipient.company = recipient;
                  draft.recipient.person = person;
                  draft.items = [{
                    id: 'item-parity-1',
                    name: item,
                    qty: 100,
                    unit: unit,
                    unitPrice: 18000
                  }];
                  draft.tax.mode = 'EXCLUSIVE';
                  draft.memo = memo;
                  bridge.replaceDraft(draft);
                }""",
                [RECIPIENT, ITEM, UNIT, REP, SENDER, PERSON, MEMO],
            )
            await page.evaluate(
                """() => {
                  document.getElementById('directView').hidden = false;
                  document.getElementById('easyView').hidden = true;
                }"""
            )
            await page.wait_for_timeout(300)

            metrics = await page.locator("#quotePaper").evaluate(
                """el => {
                  const r = el.getBoundingClientRect();
                  const s = getComputedStyle(el);
                  return {
                    width: r.width,
                    height: r.height,
                    paddingTop: s.paddingTop,
                    paddingRight: s.paddingRight,
                    paddingBottom: s.paddingBottom,
                    paddingLeft: s.paddingLeft,
                    pageWidth: s.getPropertyValue('--quote-page-width').trim(),
                    pageHeight: s.getPropertyValue('--quote-page-height').trim(),
                    pageMargin: s.getPropertyValue('--quote-page-margin').trim(),
                    text: el.innerText
                  };
                }"""
            )
            await page.locator("#quotePaper").screenshot(path=str(screen_path))
            await page.pdf(
                path=str(pdf_path),
                print_background=True,
                prefer_css_page_size=True,
                scale=1,
            )
            await browser.close()

        doc = fitz.open(pdf_path)
        if doc.page_count != 1:
            raise AssertionError(f"PDF_PAGE_COUNT={doc.page_count}")
        pdf_page = doc[0]
        pdf_text = normalized_text(pdf_page.get_text("text"))
        matrix = fitz.Matrix(96 / 72, 96 / 72)
        pix = pdf_page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(str(pdf_png_path))
        pdf_rect = pdf_page.rect
        doc.close()

        screen = Image.open(screen_path).convert("RGB")
        pdf_img = Image.open(pdf_png_path).convert("RGB")

        print(f"SCREEN_SIZE={screen.width}x{screen.height}")
        print(f"PDF_RENDER_SIZE={pdf_img.width}x{pdf_img.height}")
        print(f"SCREEN_CSS_WIDTH={metrics['width']:.3f}")
        print(f"SCREEN_CSS_HEIGHT={metrics['height']:.3f}")
        print(f"SCREEN_PAGE_WIDTH_VAR={metrics['pageWidth']}")
        print(f"SCREEN_PAGE_HEIGHT_VAR={metrics['pageHeight']}")
        print(f"SCREEN_PAGE_MARGIN_VAR={metrics['pageMargin']}")
        print(
            "SCREEN_PADDING="
            + "|".join(
                [
                    metrics["paddingTop"],
                    metrics["paddingRight"],
                    metrics["paddingBottom"],
                    metrics["paddingLeft"],
                ]
            )
        )
        print(f"PDF_MEDIA_BOX_PT={pdf_rect.width:.3f}x{pdf_rect.height:.3f}")

        if abs(screen.width - pdf_img.width) > 1 or abs(screen.height - pdf_img.height) > 1:
            raise AssertionError("SCREEN_PDF_PAGE_DIMENSION_MISMATCH")

        required = (RECIPIENT, ITEM, "1,980,000")
        screen_text = normalized_text(metrics["text"])
        for token in required:
            if token not in screen_text:
                raise AssertionError("SCREEN_TEXT_MISSING")
            if token not in pdf_text:
                raise AssertionError("PDF_TEXT_MISSING")

        if screen.size != pdf_img.size:
            pdf_img = pdf_img.resize(screen.size)

        small_size = (max(1, screen.width // 4), max(1, screen.height // 4))
        a = screen.convert("L").resize(small_size).filter(ImageFilter.GaussianBlur(0.7))
        b = pdf_img.convert("L").resize(small_size).filter(ImageFilter.GaussianBlur(0.7))
        diff = ImageChops.difference(a, b)
        mean_abs = ImageStat.Stat(diff).mean[0] / 255.0
        diff.resize(screen.size).save(diff_path)

        print(f"SCREEN_PDF_MEAN_ABS_DIFF={mean_abs:.6f}")
        print("SCREEN_PDF_KEY_TEXT_PARITY=PASS")
        print("SCREEN_PDF_PAGE_DIMENSION_PARITY=PASS")

        if mean_abs > 0.035:
            raise AssertionError(f"SCREEN_PDF_VISUAL_DIFF_TOO_HIGH={mean_abs:.6f}")

        print("B66_SCREEN_PDF_WYSIWYG_PARITY=PASS")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
