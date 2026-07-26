from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def bundled_html() -> str:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    script_sources = re.findall(r'<script src="([^"]+)" defer></script>', html)

    def inline_style(match: re.Match[str]) -> str:
        source = match.group(1).split("?", 1)[0].removeprefix("./")
        css = (ROOT / source).read_text(encoding="utf-8")
        return f'<style data-local-source="{source}">\n{css}\n</style>'

    def inline_image(match: re.Match[str]) -> str:
        source = match.group(1).removeprefix("./")
        raw = (ROOT / source).read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return f'src="data:image/svg+xml;base64,{encoded}"'

    html = re.sub(r'<link rel="stylesheet" href="([^"]+)">', inline_style, html)
    html = re.sub(r'<script src="([^"]+)" defer></script>', '', html)
    html = re.sub(r'src="(\./assets/images/[^"]+\.svg)"', inline_image, html)
    scripts = []
    for raw_source in script_sources:
        source = raw_source.split("?", 1)[0].removeprefix("./")
        scripts.append((ROOT / source).read_text(encoding="utf-8"))
    return html.replace('</body>', '<script>\n' + '\n'.join(scripts) + '\n</script>\n</body>')


async def load_page(page) -> dict[str, list[str]]:
    errors = {"console": [], "page": [], "failed": [], "external": []}
    page.on("console", lambda message: errors["console"].append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors["page"].append(str(error)))
    page.on("requestfailed", lambda request: errors["failed"].append(request.url))
    page.on("request", lambda request: errors["external"].append(request.url))
    await page.set_content(bundled_html(), wait_until="load")
    await page.wait_for_timeout(80)
    return errors


async def inspect_state(page, state: str, width: int, height: int) -> dict:
    await page.set_viewport_size({"width": width, "height": height})
    ok = await page.evaluate("name => window.__PMM_REVIEW__.setStateByName(name)", state)
    await page.wait_for_timeout(80)
    metrics = await page.evaluate("""() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      stateCount: window.__PMM_REVIEW__.stateCount,
      activeState: window.__PMM_REVIEW__.getActiveState(),
      visibleStates: [...document.querySelectorAll('[data-review-state]')].filter(el => !el.hidden).length,
      focusableControls: [...document.querySelectorAll('button, [tabindex]')].filter(el => !el.hidden).length
    })""")
    return {
        "state_found": ok,
        "viewport": {"width": width, "height": height},
        "horizontal_overflow": max(0, metrics["scrollWidth"] - metrics["clientWidth"]),
        "metrics": metrics,
    }


async def main(_: str) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium",
            args=["--no-sandbox"],
        )
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        errors = await load_page(page)
        states = {}
        for name in ["overview", "person", "place", "event-object", "explanation", "mobile", "ripple"]:
            states[name] = await inspect_state(page, name, 1440, 1000)

        mobile = await inspect_state(page, "mobile", 390, 844)
        await page.keyboard.press("Home")
        home_state = await page.evaluate("window.__PMM_REVIEW__.getActiveState()")
        await page.keyboard.press("ArrowRight")
        arrow_state = await page.evaluate("window.__PMM_REVIEW__.getActiveState()")
        await page.evaluate("document.querySelector('[data-review-state-button][aria-selected=\"true\"]').focus()")
        focus_style = await page.evaluate("""() => {
          const style = getComputedStyle(document.activeElement);
          return {tag: document.activeElement.tagName, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth};
        }""")
        focus_pass = focus_style['outlineStyle'] != 'none' and focus_style['outlineWidth'] != '0px'
        keyboard = {"home": home_state, "arrow_right": arrow_state, "focus_visible": focus_style, "pass": home_state == "overview" and arrow_state == "person" and focus_pass}

        reduced_context = await browser.new_context(reduced_motion="reduce", viewport={"width": 1440, "height": 1000})
        reduced_page = await reduced_context.new_page()
        reduced_errors = await load_page(reduced_page)
        await reduced_page.evaluate("window.__PMM_REVIEW__.setStateByName('ripple')")
        await reduced_page.wait_for_timeout(40)
        reduced = await reduced_page.evaluate("""() => ({
          query: window.__PMM_REVIEW__.reducedMotion(),
          mode: document.querySelector('[data-ripple-sheet]').dataset.motionMode,
          active: window.__PMM_REVIEW__.getActiveState(),
          visibleRings: [...document.querySelectorAll('.ripple-ring')].filter(el => getComputedStyle(el).display !== 'none').length
        })""")

        result = {
            "validation_method": "Playwright Chromium page.set_content with exact local HTML/CSS/JS and repository SVG bytes inlined; direct URL navigation was blocked by the execution environment administrator policy",
            "states": states,
            "mobile": mobile,
            "keyboard": keyboard,
            "reduced_motion": reduced,
            "motion_duration": await page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ripple-duration').trim()"),
            "console_errors": errors["console"] + reduced_errors["console"],
            "page_errors": errors["page"] + reduced_errors["page"],
            "failed_requests": errors["failed"] + reduced_errors["failed"],
            "runtime_requests": errors["external"] + reduced_errors["external"],
        }
        result["pass"] = (
            all(value["state_found"] and value["horizontal_overflow"] == 0 and value["metrics"]["visibleStates"] == 1 for value in states.values())
            and mobile["horizontal_overflow"] == 0
            and keyboard["pass"]
            and reduced["query"] and reduced["mode"] == "reduced" and reduced["visibleRings"] == 0
            and not result["console_errors"]
            and not result["page_errors"]
            and not result["failed_requests"]
            and not result["runtime_requests"]
        )
        (EVIDENCE / "browser-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        await reduced_context.close()
        await context.close()
        await browser.close()
        raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="blocked-direct-navigation")
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
