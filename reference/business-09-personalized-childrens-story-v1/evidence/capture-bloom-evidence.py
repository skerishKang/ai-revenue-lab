from __future__ import annotations

import argparse
import asyncio
import importlib.util
import io
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

VALIDATOR_PATH = Path(__file__).with_name("validate-browser.py")
SPEC = importlib.util.spec_from_file_location("business09_validator", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load validate-browser.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
build_in_memory_document = VALIDATOR.build_in_memory_document

FRAME_TIMES_MS = [0, 85, 170, 255, 340, 425, 510, 595, 680]


async def capture_standard(html: str, output: Path) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.showStateByName('bloom')")
        await page.wait_for_timeout(720)

        # Establish the replay start frame: full book visible, fixed boot visible, motion layers hidden.
        await page.evaluate("""() => {
          const stage = document.getElementById('bloom-stage');
          stage.dataset.bloomReady = 'false';
          void stage.offsetWidth;
        }""")
        await page.screenshot(path=output / "desktop-1440-story-bloom-start.png")

        frames: list[Image.Image] = []
        first_png = await page.screenshot()
        frames.append(Image.open(io.BytesIO(first_png)).convert("RGB"))

        await page.locator("#replay-bloom").click()
        await page.wait_for_function("document.getElementById('bloom-stage').dataset.bloomReady === 'true'")
        elapsed = 0
        for target in FRAME_TIMES_MS[1:]:
            await page.wait_for_timeout(target - elapsed)
            elapsed = target
            png = await page.screenshot()
            frames.append(Image.open(io.BytesIO(png)).convert("RGB"))

        frames[-1].save(output / "desktop-1440-story-bloom-final.png")
        durations = [85] * (len(frames) - 1) + [320]
        frames[0].save(
            output / "story-bloom-680ms.gif",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=False,
            disposal=2,
        )
        await context.close()
        await browser.close()


async def capture_reduced(html: str, output: Path) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            reduced_motion="reduce",
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.showStateByName('bloom')")
        await page.wait_for_timeout(40)
        await page.locator("#replay-bloom").click()
        await page.wait_for_timeout(20)
        await page.screenshot(path=output / "reduced-motion-final-state.png")
        await context.close()
        await browser.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    html, _ = build_in_memory_document()
    await capture_standard(html, args.output)
    await capture_reduced(html, args.output)


if __name__ == "__main__":
    asyncio.run(main())
