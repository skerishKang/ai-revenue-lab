"""#5805 header design comparison capture — BEFORE/AFTER, Chrome/Edge, 390/820.

Starts from two already-running local mock servers (the pre-#6153 checkout and
the comparison worktree), drives phone/tablet emulation in Chromium and Edge,
and records screenshots plus layout metrics for every variant:

    before    8866  main before #6153 (the #5804 surface band)
    default   8865  merged glass menu (production default, no parameter)
    floating  8865  ?mobileHeader=floating  (button only, no reserved row)
    collapse  8865  ?mobileHeader=collapse  (row shrinks away on scroll)

Read-only evidence: no deployment, no production call.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AFTER = os.environ.get("B5805_AFTER_URL", "http://127.0.0.1:8865")
BEFORE = os.environ.get("B5805_BEFORE_URL", "http://127.0.0.1:8866")
OUT = Path(os.environ.get(
    "B5805_OUT_DIR",
    Path(__file__).resolve().parents[3] / "padiem-reports" / "2026-10-30" / "5805-header-variants",
))

TARGETS = [
    ("before", BEFORE, ""),
    ("default", AFTER, ""),
    ("floating", AFTER, "?mobileHeader=floating"),
    ("collapse", AFTER, "?mobileHeader=collapse"),
]
BROWSERS = [
    ("chrome", "chrome-131", "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36", None),
    ("edge", "edge-155", "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36 EdgA/131.0.0.0", "msedge"),
]
WIDTHS = [(390, 844, 2), (820, 1180, 2)]

SCROLLABLE_CANDIDATES = ".conversation, .claw-workspace, .claw-inbox"

FIND_SCROLLER = """
() => {
  const cands = document.querySelectorAll('%s');
  for (const el of cands) {
    if (el.offsetParent === null) continue;
    if (el.scrollHeight - el.clientHeight > 120) return el;
  }
  return null;
}
""" % SCROLLABLE_CANDIDATES

METRICS = """
() => {
  const bar = document.querySelector('.app-shell .main-panel > .topbar');
  const btn = document.getElementById('mobileMenu');
  const shell = document.querySelector('.app-shell');
  const barRect = bar ? bar.getBoundingClientRect() : null;
  const btnRect = btn ? btn.getBoundingClientRect() : null;
  const barStyle = bar ? getComputedStyle(bar) : null;
  const btnStyle = btn ? getComputedStyle(btn) : null;
  return {
    state: shell ? shell.dataset.state : null,
    variant: document.documentElement.dataset.mobileHeader || null,
    collapsed: shell ? ('headerCollapsed' in shell.dataset) : null,
    bar: barRect ? {y: Math.round(barRect.y), h: Math.round(barRect.height)} : null,
    barPosition: barStyle ? barStyle.position : null,
    barBackground: barStyle ? barStyle.backgroundColor : null,
    barShadow: barStyle ? barStyle.boxShadow : null,
    btn: btnRect ? {x: Math.round(btnRect.x), y: Math.round(btnRect.y), w: Math.round(btnRect.width), h: Math.round(btnRect.height)} : null,
    btnRadius: btnStyle ? btnStyle.borderRadius : null,
    btnBackdrop: btnStyle ? btnStyle.backdropFilter : null,
    convScrollTop: (() => {
      const conv = document.querySelector('.conversation');
      return conv ? Math.round(conv.scrollTop) : null;
    })(),
  };
}
"""


SEND_MESSAGE = """
(text) => {
  const input = document.getElementById('messageInput');
  const send = document.getElementById('sendButton');
  if (!input || !send) return false;
  input.value = text;
  input.dispatchEvent(new Event('input', {bubbles: true}));
  send.click();
  return true;
}
"""

def _fill_thread(page, turns: int) -> None:
    """Send mock chat turns so the conversation column actually scrolls.

    The phone landing is shorter than the viewport, which made the scrolled
    state meaningless; a real thread is the state the #5804 defect lived in.
    """
    for i in range(turns):
        page.evaluate(SEND_MESSAGE, f"모바일 헤더 스크롤 비교용 메시지 {i + 1}")
        try:
            page.wait_for_selector(".assistant-message", timeout=15000)
        except Exception:
            break
        page.wait_for_timeout(1500)


def capture_target(playwright, name: str, url: str, query: str, browser_name: str,
                   ua: str, channel: str | None) -> list[Path]:
    engine = playwright.chromium
    shots: list[Path] = []
    for (width, height, dpr) in WIDTHS:
        browser = engine.launch(channel=channel, headless=True)
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=dpr,
            is_mobile=True,
            has_touch=True,
            user_agent=ua,
            locale="ko-KR",
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # Chat: the home landing first (reserved-space comparison), then a real
        # thread for the scrolled state the variants are compared in.
        page.goto(f"{url}/{query}", wait_until="load")
        page.wait_for_timeout(1200)
        for scroll in ("top", "scrolled"):
            if scroll == "scrolled":
                _fill_thread(page, turns=2)
                page.wait_for_timeout(4000)
                scroller = page.evaluate_handle(FIND_SCROLLER).as_element()
                if scroller is None:
                    print(f"  {name}/{browser_name}/{width}/chat: no scroller, keep top")
                else:
                    scroller.evaluate("el => el.scrollTo(0, 0)")
                    page.wait_for_timeout(300)
                    scroller.evaluate("el => el.scrollBy(0, 700)")
                    page.wait_for_timeout(600)
            shot = OUT / f"5805-{name}-{browser_name}-{width}-chat-{scroll}.png"
            page.screenshot(path=str(shot), full_page=False)
            shots.append(shot)
            metrics = page.evaluate(METRICS)
            metrics.update(target=name, browser=browser_name, width=width,
                           surface="chat", scroll=scroll, page_errors=errors)
            print(json.dumps(metrics, ensure_ascii=False))
            (OUT / shot.with_suffix(".metrics.json").name).write_text(
                json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")

        page.goto(f"{url}/{query}", wait_until="load")
        page.wait_for_timeout(1200)
        page.click("#mobileMenu")
        page.wait_for_timeout(400)
        page.click("#clawNavButton")
        page.wait_for_selector('.app-shell[data-state="claw"]', timeout=8000)
        page.wait_for_timeout(700)
        shot = OUT / f"5805-{name}-{browser_name}-{width}-claw-top.png"
        page.screenshot(path=str(shot), full_page=False)
        shots.append(shot)
        metrics = page.evaluate(METRICS)
        metrics.update(target=name, browser=browser_name, width=width,
                       surface="claw", scroll="top", page_errors=errors)
        print(json.dumps(metrics, ensure_ascii=False))
        (OUT / shot.with_suffix(".metrics.json").name).write_text(
            json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")

        context.close()
        browser.close()
    return shots


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    with sync_playwright() as playwright:
        for (name, url, query) in TARGETS:
            for (browser_name, _, ua, channel) in BROWSERS:
                print(f"== {name} / {browser_name} ==")
                made += capture_target(playwright, name, url, query, browser_name, ua, channel)
    print(f"captured {len(made)} screenshots -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
