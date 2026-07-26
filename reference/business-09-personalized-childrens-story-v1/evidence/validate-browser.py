from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence" / "validation.json"
VERSION = "personalized-childrens-story-20260726-1"


def local_path_from_url(url: str) -> Path:
    clean = urlsplit(url).path
    return (ROOT / clean).resolve()


def build_in_memory_document() -> tuple[str, dict]:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    resolved_assets: list[str] = []
    missing_assets: list[str] = []

    def replace_stylesheet(match: re.Match[str]) -> str:
        href = match.group(1)
        path = local_path_from_url(href)
        if not path.exists():
            missing_assets.append(href)
            return ""
        resolved_assets.append(href)
        return f'<style data-local-source="{href}">\n{path.read_text(encoding="utf-8")}\n</style>'

    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*>',
        replace_stylesheet,
        html,
    )

    deferred_scripts: list[str] = []

    def replace_script(match: re.Match[str]) -> str:
        src = match.group(1)
        path = local_path_from_url(src)
        if not path.exists():
            missing_assets.append(src)
            return ""
        resolved_assets.append(src)
        deferred_scripts.append(path.read_text(encoding="utf-8"))
        return ""

    html = re.sub(
        r'<script\s+src="([^"]+)"\s+defer></script>',
        replace_script,
        html,
    )

    def replace_image(match: re.Match[str]) -> str:
        before, src, after = match.group(1), match.group(2), match.group(3)
        path = local_path_from_url(src)
        if not path.exists():
            missing_assets.append(src)
            return match.group(0)
        resolved_assets.append(src)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'{before}data:image/svg+xml;base64,{encoded}{after}'

    html = re.sub(r'(<img\s+[^>]*src=")([^"]+)("[^>]*>)', replace_image, html)
    inline_script = "\n".join(f"<script>\n{script}\n</script>" for script in deferred_scripts)
    html = html.replace("</body>", inline_script + "\n</body>")

    refs = re.findall(r'(?:href|src)="([^"]+\.(?:css|js)(?:\?[^"]*)?)"', (ROOT / "index.html").read_text(encoding="utf-8"))
    unversioned = [ref for ref in refs if f"?v={VERSION}" not in ref]
    stale = [ref for ref in refs if "?v=" in ref and f"?v={VERSION}" not in ref]

    authored_extensions = {".html", ".css", ".js", ".md", ".svg", ".py", ".json"}
    line_counts = {}
    over_limit = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and path.suffix in authored_extensions:
            rel = path.relative_to(ROOT).as_posix()
            count = len(path.read_text(encoding="utf-8").splitlines())
            line_counts[rel] = count
            if count > 500:
                over_limit.append(rel)

    return html, {
        "resolved_local_asset_references": sorted(set(resolved_assets)),
        "missing_local_asset_references": sorted(set(missing_assets)),
        "version_token": VERSION,
        "unversioned_css_js_references": unversioned,
        "stale_version_references": stale,
        "line_counts": line_counts,
        "files_over_500_lines": over_limit,
    }


async def inspect_page(browser, html: str, width: int, height: int, reduced_motion: str = "no-preference"):
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion=reduced_motion,
        device_scale_factor=1,
    )
    page = await context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[dict] = []
    external_requests: list[str] = []

    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("requestfailed", lambda request: failed_requests.append({"url": request.url, "failure": request.failure}))
    page.on("request", lambda request: external_requests.append(request.url) if request.url.startswith(("http://", "https://")) else None)

    await page.set_content(html, wait_until="load")
    await page.wait_for_timeout(150)

    state_count = await page.locator("[data-state]").count()
    tab_count = await page.locator("[data-state-target]").count()
    active_state = await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.getActiveState()")
    horizontal_overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

    await page.keyboard.press("ArrowRight")
    keyboard_state = await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.getActiveState()")
    focused_target = await page.evaluate("document.activeElement && document.activeElement.getAttribute('data-state-target')")
    if width <= 760:
        await page.locator("#previous-state").focus()
        focused_target = await page.evaluate("document.activeElement && document.activeElement.id")
    focus_outline = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle")

    await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.showStateByName('bloom')")
    await page.wait_for_timeout(760)
    bloom_ready = await page.locator("#bloom-stage").get_attribute("data-bloom-ready")
    bloom_cloud_opacity = await page.locator(".bloom-cloud-one").evaluate("el => getComputedStyle(el).opacity")
    bloom_transform = await page.locator(".bloom-cloud-one").evaluate("el => getComputedStyle(el).transform")

    images = await page.locator("img").evaluate_all(
        "els => els.map(img => ({complete: img.complete, width: img.naturalWidth, height: img.naturalHeight}))"
    )
    broken_images = [item for item in images if not item["complete"] or item["width"] == 0]

    result = {
        "viewport": {"width": width, "height": height},
        "reduced_motion": reduced_motion,
        "navigation_mode": "Chromium page.set_content with exact local CSS/JS/SVG inlined because direct local navigation is blocked by the execution environment",
        "state_count": state_count,
        "tab_count": tab_count,
        "initial_state": active_state,
        "keyboard_next_state": keyboard_state,
        "focused_state_target": focused_target,
        "visible_focus_outline": focus_outline not in {"none", "hidden", ""},
        "horizontal_overflow_px": horizontal_overflow,
        "bloom_ready": bloom_ready == "true",
        "bloom_cloud_opacity": bloom_cloud_opacity,
        "bloom_cloud_transform": bloom_transform,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed_requests,
        "external_runtime_requests": external_requests,
        "broken_browser_images": broken_images,
    }

    await context.close()
    return result


async def main():
    html, static_checks = build_in_memory_document()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        desktop = await inspect_page(browser, html, 1440, 1000)
        mobile = await inspect_page(browser, html, 390, 844)
        reduced = await inspect_page(browser, html, 1440, 1000, reduced_motion="reduce")
        await browser.close()

    payload = {
        "artifact": "Business 9 Personalized Children’s Story Phase 1 visual UI reference",
        "validated_at": "2026-07-26",
        "expected_states": 7,
        "static_checks": static_checks,
        "desktop": desktop,
        "mobile": mobile,
        "reduced_motion": reduced,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
