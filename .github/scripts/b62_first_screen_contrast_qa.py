"""#7817 — 게스트 첫 화면의 카드·제목 둘째 줄 대비를 브라우저에서 숫자로 확인한다.

계산된 글자색(cumulative opacity 포함)과, 그 글자가 실제로 놓인 표면(글자 바로
아래 띠의 지배색) 사이의 WCAG 대비를 잰다. 기준: 카드 제목 4.5, 카드 설명 3.0,
제목 둘째 줄 4.5.

같은 화면을 로그인 상태 표현으로 바꿔 다시 재고, 값이 그대로인지 확인한다(색은
계정 상태에 따라 달라지지 않는다). 실제 로그인은 하지 않는다 — 고객·운영 계정을
쓰지 않는 규칙 때문에 화면이 쓰는 속성만 바꾼다.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_A11Y_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_A11Y_QA_OUT_DIR", ".tmp/b62-accessibility-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
# 기준선: 카드 제목, 카드 설명, 제목 둘째 줄.
TARGETS = (
    (".starter strong", 4.5, "card-title"),
    (".starter small", 3.0, "card-desc"),
    (".empty-state h1 br + span", 4.5, "hero-line2"),
)

_EXTRACT = """(el) => {
  const style = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  let opacity = 1;
  for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
    const value = Number.parseFloat(getComputedStyle(node).opacity);
    if (Number.isFinite(value)) opacity *= value;
  }
  return {
    color: style.color,
    font_px: Number.parseFloat(style.fontSize) || 0,
    weight: style.fontWeight,
    opacity: Number(opacity.toFixed(3)),
    visible: !el.hidden && style.display !== 'none' && style.visibility !== 'hidden'
      && rect.width > 0 && rect.height > 0,
    box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
    text: (el.textContent || '').trim().slice(0, 40),
  };
}"""


def _parse_color(value: str) -> tuple[tuple[int, int, int], float]:
    inner = value[value.index("(") + 1:value.index(")")]
    parts = [p.strip() for p in inner.replace(",", " ").replace("/", " ").split()]
    rgb = tuple(int(round(float(p))) for p in parts[:3])
    alpha = float(parts[3]) if len(parts) > 3 else 1.0
    return rgb, alpha


def _lin(v: float) -> float:
    s = v / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def _lum(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * _lin(rgb[0]) + 0.7152 * _lin(rgb[1]) + 0.0722 * _lin(rgb[2])


def _contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    hi, lo = max(_lum(fg), _lum(bg)), min(_lum(fg), _lum(bg))
    return round((hi + 0.05) / (lo + 0.05), 2)


def _dominant(png: bytes) -> tuple[int, int, int]:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    counts = image.getcolors(maxcolors=1 << 24) or [(0, (0, 0, 0))]
    return max(counts, key=lambda item: item[0])[1]


async def _backdrop(page: Page, box: dict[str, float], viewport: dict[str, int]) -> tuple[int, int, int]:
    """Sample the paint just under the glyphs: that strip is the text's surface."""
    y = box["y"] + box["height"] + 4
    if y + 8 > viewport["height"]:
        y = max(0.0, box["y"] - 10)
    x = max(0.0, box["x"])
    clip = {
        "x": x,
        "y": y,
        "width": max(8.0, min(box["width"], viewport["width"] - x)),
        "height": 8.0,
    }
    return _dominant(await page.screenshot(clip=clip))


async def _measure(page: Page, label: str) -> dict[str, Any]:
    viewport = page.viewport_size or {"width": 1440, "height": 1000}
    rows: dict[str, Any] = {}
    for selector, minimum, name in TARGETS:
        element = page.locator(selector).first
        if await element.count() == 0:
            raise AssertionError(f"{label}: {selector} 없음")
        read = await element.evaluate(_EXTRACT)
        if not read["visible"]:
            raise AssertionError(f"{label}: {selector} 가 보이지 않는다")
        if read["opacity"] < 0.99:
            raise AssertionError(f"{label}: {selector} 투명도 {read['opacity']}")
        rgb, alpha = _parse_color(read["color"])
        surface = await _backdrop(page, read["box"], viewport)
        if alpha < 1:
            rgb = tuple(round(c * alpha + s * (1 - alpha)) for c, s in zip(rgb, surface))
        ratio = _contrast(rgb, surface)
        rows[name] = {
            "selector": selector,
            "text": read["text"],
            "color": read["color"],
            "surface": list(surface),
            "ratio": ratio,
            "minimum": minimum,
            "pass": ratio >= minimum,
        }
    return rows


async def _audit_view(page: Page, theme: str, width: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": 1000 if width >= 1440 else 844})
    url = f"{BASE_URL}/?theme={theme}" + ("&glass=female" if theme == "padiem-glass" else "")
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(300)

    actual = await page.locator("html").get_attribute("data-theme")
    if actual != theme:
        raise AssertionError(f"theme did not activate: expected={theme}, actual={actual}")

    guest = await _measure(page, f"{theme}-{width}-guest")
    failed = [f"{name} {row['ratio']} < {row['minimum']}" for name, row in guest.items() if not row["pass"]]
    if failed:
        raise AssertionError(f"{theme} {width} 게스트 첫 화면 대비 미달: " + ", ".join(failed))

    # 로그인 상태 표현으로 바꿔도 같은 값이어야 한다(색은 계정 상태와 무관).
    await page.evaluate(
        """() => {
          const account = document.getElementById('accountContainer');
          if (account) account.dataset.accountState = 'signed_in';
          const hint = document.getElementById('guestLoginHint');
          if (hint) hint.hidden = true;
          const chip = document.querySelector('.sidebar-account');
          if (chip) { chip.hidden = false; chip.style.display = 'grid'; }
        }"""
    )
    await page.wait_for_timeout(150)
    signed_in = await _measure(page, f"{theme}-{width}-signed-in")
    drift = [
        f"{name}: guest={guest[name]['color']} signed_in={signed_in[name]['color']}"
        for name in guest
        if guest[name]["color"] != signed_in[name]["color"]
    ]
    if drift:
        raise AssertionError(f"{theme} {width} 로그인 상태에서 색이 달라짐: " + ", ".join(drift))

    shot = f"first-screen-{theme}-{width}.png"
    await page.screenshot(path=str(OUT_DIR / shot))
    return {
        "theme": theme,
        "width": width,
        "guest": guest,
        "signed_in_same": True,
        "screenshot": shot,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "scope": "#7817 first-screen guest contrast (cards + hero second line)",
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
    (OUT_DIR / "first-screen-contrast-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for key, view in report["views"].items():
        row = " ".join(f"{name}={view['guest'][name]['ratio']}" for _, _, name in TARGETS)
        print(f"{key:22s} {row}")


if __name__ == "__main__":
    asyncio.run(main())
