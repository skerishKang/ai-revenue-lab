# -*- coding: utf-8 -*-
"""Beta UX capture — one driver for the util screens, the quote dialog and the
shared PC file-exchange dialog, at desktop and mobile widths.

Prerequisites
  * a Padiem Chat server (mock mode is enough):
      PADIEM_CHAT_RUNTIME_MODE=mock PADIEM_CHAT_LIVE_ENABLED=false \
        .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8795
    (run from apps/padiem-chat)
  * Playwright with Chromium:  python -m pip install playwright  +
    python -m playwright install --only-shell chromium

Usage (from apps/padiem-chat):
    python ../../tools/beta-ux-capture.py --base-url http://127.0.0.1:8795 \
        --out ../../padiem-reports/2026-10-29 [--tag before]

--tag prefixes every file name (before-…/after-…) so one fix can ship its own
BEFORE/AFTER pair from the same driver.

The script only reads; it fills no real form data beyond the mock-generation
it triggers on the SNS screen, and it never claims product visibility the
mock cannot grant: the quote launcher stays hidden without a runtime grant,
so the quote captures unhide it explicitly to inspect the dialog content.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

WIDTHS = {"desktop": (1440, 1000), "mobile": (390, 844)}

VISIBILITY_JS = """
(selector) => {
  const n = document.querySelector(selector);
  if (!n) return null;
  const style = getComputedStyle(n);
  const rect = n.getBoundingClientRect();
  return {
    exists: true,
    visible: !n.hidden && style.display !== 'none' && style.visibility !== 'hidden'
      && rect.width > 0 && rect.height > 0,
    text: (n.textContent || '').trim().slice(0, 40),
  };
}
"""


def check(page, selector):
    return page.evaluate(VISIBILITY_JS, selector)


def tag_name(tag, name, width):
    return (tag + "-" if tag else "") + name + "-" + width + ".png"


def shot(page, out, tag, name, width, full_page=True):
    page.screenshot(path=str(out / tag_name(tag, name, width)), full_page=full_page)


CONTRAST_RECT_JS = """
(selector) => {
  const node = document.querySelector(selector);
  if (!node) return null;
  const rect = node.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) return null;
  return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
}
"""


def _luminance(rgb):
    def channel(value):
        value /= 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = rgb
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def _contrast_ratio(a, b):
    lighter = max(_luminance(a), _luminance(b))
    darker = min(_luminance(a), _luminance(b))
    return (lighter + 0.05) / (darker + 0.05)


def border_contrast(page, selector):
    """Rendered non-text contrast of a control's top border against its own
    fill, read back from the actual pixels — semi-transparent tokens, the
    theme's blur and the compositing underneath all land in the number, so
    the report never argues from declared colors alone."""
    page.evaluate("(s) => document.querySelector(s)?.scrollIntoView({ block: 'center' })", selector)
    page.wait_for_timeout(150)
    rect = page.evaluate(CONTRAST_RECT_JS, selector)
    if not rect:
        return None
    clip = {"x": rect["x"], "y": rect["y"], "width": rect["width"], "height": min(rect["height"], 12)}
    strip = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")
    strip_width, strip_height = strip.size
    fill = strip.getpixel((int(strip_width * 0.72), strip_height - 2))
    edge, spread = None, -1.0
    # A 1px border can land on either side of a fractional device pixel; the
    # top rows are all border candidates, and the one farthest from the fill
    # is the border the eye actually gets.
    for y in range(0, min(3, strip_height)):
        pixel = strip.getpixel((strip_width // 2, y))
        distance = sum((p - q) ** 2 for p, q in zip(pixel, fill)) ** 0.5
        if distance > spread:
            edge, spread = pixel, distance
    return {
        "declared": page.evaluate(
            "(s) => { const n = document.querySelector(s); return n ? getComputedStyle(n).borderTopColor : null; }",
            selector,
        ),
        "border": "#%02x%02x%02x" % edge,
        "fill": "#%02x%02x%02x" % fill,
        "ratio": round(_contrast_ratio(edge, fill), 2),
    }


def open_util(page, key):
    """Enter the util view and activate a tool by the shell's own events.
    Geometry-independent on purpose: the sidebar can sit off-canvas while a
    closed dialog's focus settles, and real pointer clicks then stall."""
    in_util = page.evaluate("() => !(document.getElementById('utilView')?.hidden ?? true)")
    if not in_util:
        nav_offscreen = page.evaluate(
            """() => {
              const n = document.getElementById('utilNavButton');
              if (!n) return true;
              const s = getComputedStyle(n);
              const r = n.getBoundingClientRect();
              return s.display === 'none' || s.visibility === 'hidden' || r.width === 0;
            }"""
        )
        if nav_offscreen:
            page.evaluate("(s) => document.querySelector(s)?.click()", "#mobileMenu")
            page.wait_for_timeout(400)
        page.evaluate("(s) => document.querySelector(s)?.click()", "#utilNavButton")
        page.wait_for_timeout(500)
    page.evaluate(
        """(key) => {
          const item = document.querySelector('.util-submenu-item[data-util="' + key + '"]')
            || document.querySelector('.util-tab[data-util="' + key + '"]');
          if (item) item.click();
        }""",
        key,
    )
    page.wait_for_timeout(600)
    # Close the off-canvas sidebar again so it never covers the panel.
    if page.evaluate("document.querySelector('.app-shell')?.classList.contains('sidebar-open') ?? false"):
        page.evaluate("(s) => document.querySelector(s)?.click()", "#mobileMenu")
        page.wait_for_timeout(400)


def capture_quote(page, out, tag, width):
    """The quote dialog. The launcher is force-shown: without a runtime grant
    the product keeps it hidden, and this capture is a content inspection."""
    summary = {}
    # The capabilities projection completes asynchronously and re-disables the
    # hidden launcher; unhide and click in one go so no event lands between.
    page.evaluate(
        """() => {
          const b = document.getElementById('b66QuoteNavButton');
          b.hidden = false;
          b.disabled = false;
          b.setAttribute('aria-disabled', 'false');
          b.click();
        }"""
    )
    page.wait_for_selector("#b66QuoteDialog[open]", timeout=5_000)
    page.wait_for_timeout(400)
    summary["dialogOpen"] = True
    summary["pcFormSection"] = check(page, "#b66QuoteForm .b66-quote-pcform")
    summary["pcPick"] = check(page, "#b66QuotePcPick")
    summary["pcPickText"] = page.evaluate(
        "() => document.getElementById('b66QuotePcPick')?.textContent ?? null"
    )
    summary["emptySelectLabels"] = page.evaluate(
        """() => {
          const labels = [...document.querySelectorAll('#b66QuoteForm .b66-quote-field')]
            .filter((l) => l.querySelector('select'));
          return labels.map((l) => ({ hidden: l.hidden, selectOptions: l.querySelector('select').options.length }));
        }"""
    )
    summary["signinHint"] = check(page, ".b66-quote-signin-hint")
    summary["generateVisible"] = check(page, "#b66QuoteGenerate")
    summary["selectContrast"] = quote_select_contrast(page)
    shot(page, out, tag, "quote-dialog", width)
    page.locator("#b66QuoteClose").click()
    page.wait_for_timeout(300)
    return summary


def quote_select_contrast(page):
    """The logged-out dialog hides the select fields behind the sign-in hint
    (that hiding is the fix under test), so a rendered border reading needs
    the same content inspection the launcher already gets: unhide, read the
    pixels, restore the exact hidden state. The screenshot this pass saves is
    taken after the restore and shows the product's own state."""
    was_hidden = page.evaluate(
        """() => {
          const select = document.getElementById('b66QuoteModelSelect');
          const label = select && select.closest('label');
          if (!label) return null;
          const was = label.hidden;
          label.hidden = false;
          return was;
        }"""
    )
    try:
        return border_contrast(page, "#b66QuoteModelSelect")
    finally:
        if was_hidden:
            page.evaluate(
                """() => {
                  const select = document.getElementById('b66QuoteModelSelect');
                  const label = select && select.closest('label');
                  if (label) label.hidden = true;
                }"""
            )


def capture_speech(page, out, tag, width):
    open_util(page, "speech")
    page.wait_for_selector("#utilSpeechForm", timeout=5_000)
    summary = {
        "pcPick": check(page, "#utilSpeechPcRef .util-pc-ref-pick"),
        "pcSave": check(page, "#utilSpeechPcSave"),
        "refLegend": check(page, "#utilSpeechRef legend"),
        "refIsFirstChild": page.evaluate(
            "() => document.getElementById('utilSpeechForm')?.firstElementChild?.id === 'utilSpeechRef'"
        ),
        "inputContrast": border_contrast(page, '#utilSpeechForm input[name="event"]'),
    }
    shot(page, out, tag, "util-speech", width)
    return summary


def capture_sns(page, out, tag, width, with_result):
    open_util(page, "sns")
    page.wait_for_selector("#utilSnsForm", timeout=5_000)
    page.wait_for_timeout(400)
    summary = {
        "refLegend": check(page, "#utilSnsRef legend"),
        "pcPick": check(page, "#utilSnsForm .util-pc-ref-pick"),
        "pcPickLane": page.evaluate(
            """() => {
              const box = document.querySelector('#utilSnsForm .util-pc-ref');
              if (!box) return null;
              const section = box.closest('fieldset');
              if (!section) return null;
              const formRect = document.getElementById('utilSnsForm').getBoundingClientRect();
              return Math.abs(section.getBoundingClientRect().width - formRect.width) < 2;
            }"""
        ),
        "pcSave": check(page, "#utilSnsPcSave"),
        "inputSkin": page.evaluate(
            """() => {
              const input = document.querySelector('#utilSnsForm input[name="event"]');
              if (!input) return null;
              const s = getComputedStyle(input);
              return { borderColor: s.borderColor, background: s.backgroundColor };
            }"""
        ),
        "inputContrast": border_contrast(page, '#utilSnsForm input[name="event"]'),
    }
    shot(page, out, tag, "util-sns", width)

    # The shared import dialog, opened from the SNS pick button.
    page.locator("#utilSnsForm .util-pc-ref-pick").click()
    try:
        page.wait_for_selector(".pc-exchange-dialog", timeout=6_000)
        page.wait_for_timeout(600)
        summary["pcExchangeDialog"] = check(page, ".pc-exchange-dialog")
        summary["backAtRoot"] = page.evaluate(
            """() => {
              const b = document.querySelector('.pc-exchange-back');
              if (!b) return null;
              return { disabled: b.disabled, ariaDisabled: b.getAttribute('aria-disabled') };
            }"""
        )
        summary["toolsRowOneLine"] = page.evaluate(
            """() => {
              const row = document.querySelector('.pc-exchange-tools');
              if (!row) return null;
              const styles = getComputedStyle(row);
              const line = parseFloat(styles.fontSize) * 1.2 + 44;
              return row.getBoundingClientRect().height < line;
            }"""
        )
        shot(page, out, tag, "pc-exchange-dialog", width)
        close = page.locator(".pc-exchange-cancel")
        if close.count() > 0:
            close.first.click()
        else:
            page.keyboard.press("Escape")
    except Exception as exc:  # noqa: BLE001 — the state itself is the finding
        summary["pcExchangeDialog"] = {"error": str(exc).splitlines()[0][:120]}
    page.wait_for_timeout(400)

    if with_result:
        page.fill('#utilSnsForm [name="event"]', "캡처 점검 행사")
        page.fill('#utilSnsForm [name="content"]', "화면 점검용 내용입니다.")
        page.locator('#utilSnsForm button[type="submit"]').first.click()
        page.wait_for_timeout(5_000)
        summary["snsResult"] = check(page, "#utilSnsResult")
        summary["retry"] = check(page, "#utilSnsRetry")
        summary["outputHead"] = page.evaluate(
            "() => (document.getElementById('utilSnsOutput')?.value || '').slice(0, 80)"
        )
        # The app scrolls inside its own panel; full_page never reaches the
        # result lane, so bring it into the panel viewport first.
        page.evaluate("document.getElementById('utilSnsResult')?.scrollIntoView({ block: 'start' })")
        page.wait_for_timeout(400)
        page.screenshot(path=str(out / tag_name(tag, "util-sns-result", width)))
    return summary


def run(width_name, size, base_url, out, screens, tag, theme):
    page_results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size[0], "height": size[1]})
        url = base_url + ("?theme=" + theme if theme else "")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1_500)
        if "quote" in screens:
            page_results["quote"] = capture_quote(page, out, tag, width_name)
        if "speech" in screens:
            page_results["speech"] = capture_speech(page, out, tag, width_name)
        if "sns" in screens:
            page_results["sns"] = capture_sns(page, out, tag, width_name, with_result=True)
        browser.close()
    return page_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8795")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "padiem-reports" / "2026-10-29"))
    parser.add_argument("--screens", default="quote,speech,sns")
    parser.add_argument("--tag", default="")
    parser.add_argument("--theme", default="", help="apply a product theme, e.g. padiem-glass")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    screens = [s.strip() for s in args.screens.split(",") if s.strip()]

    report = {}
    for width_name, size in WIDTHS.items():
        report[width_name] = run(width_name, size, args.base_url, out, screens, args.tag, args.theme)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
