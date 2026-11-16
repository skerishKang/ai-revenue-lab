"""#7827 — 게스트 첫 화면 시작 카드의 잘림·겹침을 브라우저에서 숫자로 확인한다.

390 폭에서 카드 설명(`.starter small`)이 잘리는지(scrollWidth > clientWidth
또는 scrollHeight > clientHeight), '지원 형식' 칩의 사각형이 같은 카드의
아이콘·제목·설명과 겹치는지(겹친 넓이 px)를 잰다. 기준: 설명 잘림 0,
칩 겹침 0. 1440은 배치가 그대로인지(잘림 0) 함께 확인한다.

실제 로그인은 하지 않는다 — 고객·운영 계정을 쓰지 않는 규칙 때문에 화면이
쓰는 속성만 바꾼다(게스트 첫 화면이 기본 상태다).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_A11Y_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_A11Y_QA_OUT_DIR", ".tmp/b62-accessibility-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")

_EXTRACT = """() => {
  const cards = [...document.querySelectorAll(
    '.starter-grid > .starter, .starter-grid .document-starter-shell > .starter')];
  const inter = (a, b) => {
    const x = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
    const y = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
    return Math.round(x * y);
  };
  return cards.map((card) => {
    const parts = {};
    for (const [name, sel] of [['title', 'strong'], ['desc', 'small']]) {
      const el = card.querySelector(sel);
      const r = el.getBoundingClientRect();
      parts[name] = {
        text: (el.textContent || '').trim().slice(0, 32),
        clipped: el.scrollWidth > el.clientWidth + 0.5
          || el.scrollHeight > el.clientHeight + 0.5,
      };
    }
    const shell = card.closest('.document-starter-shell');
    const chip = shell ? shell.querySelector('.document-formats-toggle') : null;
    let overlap = 0;
    if (chip) {
      const box = chip.getBoundingClientRect().toJSON();
      for (const sel of ['.starter-icon', 'strong', 'small']) {
        overlap += inter(box, card.querySelector(sel).getBoundingClientRect().toJSON());
      }
    }
    return { id: card.id || null, title: parts.title, desc: parts.desc, chip_px2: overlap };
  });
}"""


async def _audit_view(page: Page, theme: str, width: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": 1000 if width >= 1440 else 844})
    url = f"{BASE_URL}/?theme={theme}" + ("&glass=female" if theme == "padiem-glass" else "")
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(300)
    actual = await page.locator("html").get_attribute("data-theme")
    if actual != theme:
        raise AssertionError(f"theme did not activate: expected={theme}, actual={actual}")
    cards: list[dict[str, Any]] = await page.evaluate(_EXTRACT)
    if len(cards) < 4:
        raise AssertionError(f"{theme} {width} 시작 카드가 4개 미만: {len(cards)}")
    clipped = [c["desc"]["text"] for c in cards if c["desc"]["clipped"]]
    overlapped = [c["id"] or c["title"]["text"] for c in cards if c["chip_px2"] > 0]
    if clipped:
        raise AssertionError(f"{theme} {width} 카드 설명 잘림: " + ", ".join(clipped))
    if overlapped:
        raise AssertionError(f"{theme} {width} 칩 겹침(px²>0): " + ", ".join(overlapped))
    shot = f"first-screen-cards-{theme}-{width}.png"
    await page.screenshot(path=str(OUT_DIR / shot))
    return {"theme": theme, "width": width, "cards": len(cards), "screenshot": shot, "status": "PASS"}


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "scope": "#7827 first-screen starter cards (clip 0, chip overlap 0)",
        "views": {},
        "production_mutation": False,
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme in THEMES:
                for width in (1440, 390):
                    key = f"{theme}-{width}"
                    page = await browser.new_page(viewport={"width": width, "height": 1000})
                    try:
                        report["views"][key] = await _audit_view(page, theme, width)
                    finally:
                        await page.close()
        finally:
            await browser.close()
    report["status"] = "PASS"
    (OUT_DIR / "first-screen-cards-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for key, view in report["views"].items():
        print(f"{key:22s} cards={view['cards']} PASS")


if __name__ == "__main__":
    asyncio.run(main())
