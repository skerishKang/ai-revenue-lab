from __future__ import annotations

import asyncio
import base64
import io
import re
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path('/mnt/data/personal-meaning-map-artifacts')


def bundled_html() -> str:
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    script_sources = re.findall(r'<script src="([^"]+)" defer></script>', html)

    def inline_style(match: re.Match[str]) -> str:
        source = match.group(1).split('?', 1)[0].removeprefix('./')
        css = (ROOT / source).read_text(encoding='utf-8')
        return f'<style data-local-source="{source}">\n{css}\n</style>'

    def inline_image(match: re.Match[str]) -> str:
        source = match.group(1).removeprefix('./')
        encoded = base64.b64encode((ROOT / source).read_bytes()).decode('ascii')
        return f'src="data:image/svg+xml;base64,{encoded}"'

    html = re.sub(r'<link rel="stylesheet" href="([^"]+)">', inline_style, html)
    html = re.sub(r'<script src="([^"]+)" defer></script>', '', html)
    html = re.sub(r'src="(\./assets/images/[^"]+\.svg)"', inline_image, html)
    scripts = []
    for raw_source in script_sources:
        source = raw_source.split('?', 1)[0].removeprefix('./')
        scripts.append((ROOT / source).read_text(encoding='utf-8'))
    return html.replace('</body>', '<script>\n' + '\n'.join(scripts) + '\n</script>\n</body>')


async def prepare(page, state: str) -> None:
    await page.set_content(bundled_html(), wait_until='load')
    await page.evaluate('name => window.__PMM_REVIEW__.setStateByName(name)', state)
    await page.wait_for_timeout(100)


async def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
        page = await context.new_page()

        for state, filename in [
            ('overview', '1440-overview.png'),
            ('place', '1440-place.png'),
            ('explanation', '1440-explanation.png'),
        ]:
            await prepare(page, state)
            await page.screenshot(path=str(OUTPUT / filename), full_page=True)

        mobile_context = await browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=1)
        mobile_page = await mobile_context.new_page()
        await prepare(mobile_page, 'mobile')
        await mobile_page.screenshot(path=str(OUTPUT / '390x844-mobile.png'), full_page=False)

        await prepare(page, 'ripple')
        frames: list[Image.Image] = []
        await page.evaluate('window.__PMM_REVIEW__.playRipple()')
        for delay in [0, 90, 100, 110, 120, 130, 150, 170]:
            if delay:
                await page.wait_for_timeout(delay)
            raw = await page.screenshot(full_page=False)
            frames.append(Image.open(io.BytesIO(raw)).convert('P', palette=Image.Palette.ADAPTIVE))
        frames[0].save(
            OUTPUT / 'meaning-ripple.gif',
            save_all=True,
            append_images=frames[1:],
            duration=[90, 100, 110, 120, 130, 150, 170, 180],
            loop=0,
            optimize=True,
        )

        reduced_context = await browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        reduced_page = await reduced_context.new_page()
        await prepare(reduced_page, 'ripple')
        await reduced_page.screenshot(path=str(OUTPUT / 'reduced-motion.png'), full_page=True)

        await reduced_context.close()
        await mobile_context.close()
        await context.close()
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
