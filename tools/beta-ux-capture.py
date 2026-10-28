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
        --out ../../padiem-reports/2026-10-29

The script only reads; it fills no real form data beyond the mock-generation
it triggers on the SNS screen, and it never claims product visibility the
mock cannot grant: the quote launcher stays hidden without a runtime grant,
so the quote captures unhide it explicitly to inspect the dialog content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

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


def js_click(page, selector):
    page.evaluate("(s) => document.querySelector(s)?.click()", selector)


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
            js_click(page, "#mobileMenu")
            page.wait_for_timeout(400)
        js_click(page, "#utilNavButton")
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
        js_click(page, "#mobileMenu")
        page.wait_for_timeout(400)


def capture_quote(page, out, width):
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
    page.screenshot(path=str(out / f"quote-dialog-{width}.png"), full_page=True)
    page.locator("#b66QuoteClose").click()
    page.wait_for_timeout(300)
    return summary


def capture_speech(page, out, width):
    open_util(page, "speech")
    page.wait_for_selector("#utilSpeechForm", timeout=5_000)
    summary = {
        "pcPick": check(page, "#utilSpeechPcRef .util-pc-ref-pick"),
        "pcSave": check(page, "#utilSpeechPcSave"),
    }
    page.screenshot(path=str(out / f"util-speech-{width}.png"), full_page=True)
    return summary


def capture_sns(page, out, width, with_result):
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
    }
    page.screenshot(path=str(out / f"util-sns-{width}.png"), full_page=True)

    # The shared import dialog, opened from the SNS pick button.
    page.locator("#utilSnsForm .util-pc-ref-pick").click()
    try:
        page.wait_for_selector(".pc-exchange-dialog", timeout=6_000)
        page.wait_for_timeout(600)
        summary["pcExchangeDialog"] = check(page, ".pc-exchange-dialog")
        page.screenshot(path=str(out / f"pc-exchange-dialog-{width}.png"), full_page=True)
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
        page.screenshot(path=str(out / f"util-sns-result-{width}.png"))
    return summary


def run(width_name, size, base_url, out, screens):
    page_results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size[0], "height": size[1]})
        page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(1_500)
        if "quote" in screens:
            page_results["quote"] = capture_quote(page, out, width_name)
        if "speech" in screens:
            page_results["speech"] = capture_speech(page, out, width_name)
        if "sns" in screens:
            page_results["sns"] = capture_sns(page, out, width_name, with_result=True)
        browser.close()
    return page_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8795")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "padiem-reports" / "2026-10-29"))
    parser.add_argument("--screens", default="quote,speech,sns")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    screens = [s.strip() for s in args.screens.split(",") if s.strip()]

    report = {}
    for width_name, size in WIDTHS.items():
        report[width_name] = run(width_name, size, args.base_url, out, screens)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
