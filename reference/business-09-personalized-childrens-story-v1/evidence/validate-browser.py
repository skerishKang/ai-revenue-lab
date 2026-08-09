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
VERSION = "personalized-childrens-story-20260726-2"
STALE = "personalized-childrens-story-20260726-1"
STATIC = ['[data-state="bloom"]', '.bloom-book', '.bloom-copy', '.bloom-stage', '.bloom-base-image', '#bloom-title']
LAYERS = ['.bloom-cloud-one', '.bloom-cloud-two', '.bloom-sail', '.bloom-path-one', '.bloom-path-two', '.bloom-path-three']


def local_path(url: str) -> Path:
    return (ROOT / urlsplit(url).path).resolve()


def build_document() -> tuple[str, dict]:
    source = (ROOT / "index.html").read_text(encoding="utf-8")
    html = source
    resolved, missing, scripts = [], [], []

    def css(match: re.Match[str]) -> str:
        href = match.group(1); path = local_path(href)
        if not path.exists(): missing.append(href); return ""
        resolved.append(href)
        return f'<style data-source="{href}">\n{path.read_text(encoding="utf-8")}\n</style>'

    def js(match: re.Match[str]) -> str:
        src = match.group(1); path = local_path(src)
        if not path.exists(): missing.append(src); return ""
        resolved.append(src); scripts.append(path.read_text(encoding="utf-8")); return ""

    def image(match: re.Match[str]) -> str:
        before, src, after = match.groups(); path = local_path(src)
        if not path.exists(): missing.append(src); return match.group(0)
        resolved.append(src)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'{before}data:image/svg+xml;base64,{data}{after}'

    html = re.sub(r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*>', css, html)
    html = re.sub(r'<script\s+src="([^"]+)"\s+defer></script>', js, html)
    html = re.sub(r'(<img\s+[^>]*src=")([^"]+)("[^>]*>)', image, html)
    html = html.replace("</body>", "\n".join(f"<script>{s}</script>" for s in scripts) + "\n</body>")

    refs = re.findall(r'(?:href|src)="([^"]+\.(?:css|js)(?:\?[^"]*)?)"', source)
    extensions = {".html", ".css", ".js", ".md", ".svg", ".py", ".json"}
    counts = {p.relative_to(ROOT).as_posix(): len(p.read_text(encoding="utf-8").splitlines())
              for p in sorted(ROOT.rglob("*")) if p.is_file() and p.suffix in extensions}
    return html, {
        "version_token": VERSION,
        "resolved_local_assets": sorted(set(resolved)),
        "missing_local_assets": sorted(set(missing)),
        "unversioned_css_js": [r for r in refs if f"?v={VERSION}" not in r],
        "stale_v1_loading_refs": [r for r in refs if STALE in r],
        "files_over_500_lines": [p for p, n in counts.items() if n > 500],
        "line_counts": counts,
    }


async def snap(page, selectors: list[str]) -> dict:
    return await page.evaluate("""selectors => Object.fromEntries(selectors.map(selector => {
      const el = document.querySelector(selector); const s = getComputedStyle(el); const r = el.getBoundingClientRect();
      return [selector, {opacity:s.opacity, transform:s.transform, animation:s.animationName,
        rect:[r.x,r.y,r.width,r.height].map(v => Number(v.toFixed(2)))}];
    }))""", selectors)


def static_stable(reference: dict, *samples: dict) -> bool:
    for selector, start in reference.items():
        if start["opacity"] != "1": return False
        for sample in samples:
            item = sample[selector]
            if item["opacity"] != "1" or item["transform"] != start["transform"] or item["rect"] != start["rect"]:
                return False
    return True


def layers_changed(*samples: dict) -> bool:
    return any(len({(sample[s]["opacity"], sample[s]["transform"]) for sample in samples}) > 1 for s in LAYERS)


async def inspect(browser, html: str, width: int, height: int, reduced: bool = False) -> dict:
    context = await browser.new_context(viewport={"width": width, "height": height},
                                        reduced_motion="reduce" if reduced else "no-preference")
    page = await context.new_page(); console, errors, failed, external = [], [], [], []
    page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: failed.append(r.url))
    page.on("request", lambda r: external.append(r.url) if r.url.startswith(("http://", "https://")) else None)
    await page.set_content(html, wait_until="load"); await page.wait_for_timeout(100)

    states = await page.locator("[data-state]").count(); tabs = await page.locator("[data-state-target]").count()
    overflow = await page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth")
    await page.keyboard.press("ArrowRight")
    keyboard_state = await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.getActiveState()")
    await page.locator("#previous-state" if width <= 760 else '[data-state-target="spread"]').focus()
    focus = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle")

    await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.showStateByName('bloom')")
    await page.wait_for_timeout(40 if reduced else 720)
    entry_state = await page.evaluate("window.__PERSONALIZED_STORY_REVIEW__.getActiveState()")
    section_animation = await page.locator('[data-state="bloom"]').evaluate("e=>getComputedStyle(e).animationName")
    before = await snap(page, STATIC); layers_before = await snap(page, LAYERS)
    ready_before = await page.locator("#bloom-stage").get_attribute("data-bloom-ready")

    await page.locator("#replay-bloom").click()  # actual second replay
    await page.wait_for_timeout(20 if not reduced else 0); early = await snap(page, STATIC); layer_early = await snap(page, LAYERS)
    await page.wait_for_timeout(280 if not reduced else 10); middle = await snap(page, STATIC); layer_middle = await snap(page, LAYERS)
    await page.wait_for_timeout(420 if not reduced else 10); final = await snap(page, STATIC); layer_final = await snap(page, LAYERS)
    ready_final = await page.locator("#bloom-stage").get_attribute("data-bloom-ready")

    images = await page.locator("img").evaluate_all("els=>els.map(i=>[i.complete,i.naturalWidth])")
    final_layers = all(v["opacity"] == "1" and (not reduced or v["transform"] == "none") for v in layer_final.values())
    assertions = {
        "entry_state_is_bloom": entry_state == "bloom",
        "generic_state_enter_absent": section_animation == "none",
        "entry_book_copy_base_opacity_one": all(before[s]["opacity"] == "1" for s in STATIC),
        "before_replay_active_state_is_bloom": entry_state == "bloom",
        "before_replay_book_opacity_one": before[".bloom-book"]["opacity"] == "1",
        "book_copy_base_and_geometry_stable": static_stable(before, early, middle, final),
        "only_bloom_layers_show_motion_change": reduced or layers_changed(layers_before, layer_early, layer_middle, layer_final),
        "second_replay_reaches_final_state": ready_final == "true" and final_layers,
        "reduced_motion_immediate_final": final_layers if reduced else None,
    }
    result = {
        "viewport": [width, height], "reduced_motion": reduced, "state_count": states, "tab_count": tabs,
        "keyboard_next_state": keyboard_state, "visible_focus": focus not in {"none", "hidden", ""},
        "horizontal_overflow_px": overflow, "ready_before_replay": ready_before,
        "actual_second_replay_button_click": True, "assertions": assertions,
        "errors": {"console": console, "page": errors, "failed_requests": failed,
                   "external_runtime_requests": external, "broken_images": [i for i in images if not i[0] or i[1] == 0]},
        "representative_layer_timeline": {
            "before": layers_before[".bloom-cloud-one"], "early": layer_early[".bloom-cloud-one"],
            "middle": layer_middle[".bloom-cloud-one"], "final": layer_final[".bloom-cloud-one"]},
    }
    await context.close(); return result


def passes(payload: dict) -> bool:
    static = payload["static_checks"]
    if any(static[k] for k in ("missing_local_assets", "unversioned_css_js", "stale_v1_loading_refs", "files_over_500_lines")):
        return False
    for key in ("desktop", "mobile", "reduced_motion"):
        result = payload[key]
        if result["state_count"] != 7 or result["tab_count"] != 7 or result["horizontal_overflow_px"] != 0 or not result["visible_focus"]:
            return False
        if any(result["errors"].values()): return False
        if any(v is False for v in result["assertions"].values() if v is not None): return False
    return True


async def main() -> None:
    html, static = build_document()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        desktop = await inspect(browser, html, 1440, 1000)
        mobile = await inspect(browser, html, 390, 844)
        reduced = await inspect(browser, html, 1440, 1000, True)
        await browser.close()
    payload = {"artifact": "Business 9 focused Story Bloom correction", "validated_at": "2026-07-26",
               "signature_sequence_ms": 680, "static_checks": static,
               "desktop": desktop, "mobile": mobile, "reduced_motion": reduced}
    payload["all_required_checks_passed"] = passes(payload)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["all_required_checks_passed"]: raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
