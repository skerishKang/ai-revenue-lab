#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
STATES = ["cover", "sources", "spine", "suite", "adaptation", "trace", "mobile"]
BASE = "in-memory://business-22/index.html"


def build_inline_html() -> str:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for href in re.findall(r'<link rel="stylesheet" href="([^"]+)">', html):
        css = (ROOT / href).read_text(encoding="utf-8")
        html = html.replace(f'<link rel="stylesheet" href="{href}">', f'<style>{css}</style>')
    for src in re.findall(r'<script src="([^"]+)"></script>', html):
        js = (ROOT / src).read_text(encoding="utf-8")
        html = html.replace(f'<script src="{src}"></script>', f'<script>{js}</script>')
    for match in sorted(set(re.findall(r'assets/images/[^"\\]+\.svg', html))):
        payload = base64.b64encode((ROOT / match).read_bytes()).decode("ascii")
        html = html.replace(match, f'data:image/svg+xml;base64,{payload}')
    return html


INLINE_HTML = build_inline_html()


def load_state(page, state: str, skip_relay: bool = True) -> None:
    page.set_content(INLINE_HTML, wait_until="load")
    page.evaluate("([state, skip]) => window.__B22_REVIEW__.setState(state, {skipRelay: skip})", [state, skip_relay])
    page.wait_for_timeout(30)


def capture(page, name: str, full_page: bool = True) -> tuple[str, Image.Image]:
    png_bytes = page.screenshot(full_page=full_page)
    image = Image.open(BytesIO(png_bytes)).convert("RGB")
    return name, image


def write_atlas(filename: str, captures: list[tuple[str, Image.Image]], columns: int, cell_width: int) -> str:
    label_height = 34
    gap = 18
    rows: list[list[tuple[str, Image.Image]]] = [captures[i:i + columns] for i in range(0, len(captures), columns)]
    processed: list[list[tuple[str, Image.Image]]] = []
    row_heights: list[int] = []
    for row in rows:
        converted = []
        max_height = 0
        for name, image in row:
            target_height = max(1, round(image.height * (cell_width / image.width)))
            resized = image.resize((cell_width, target_height), Image.Resampling.LANCZOS)
            converted.append((name, resized))
            max_height = max(max_height, target_height)
        processed.append(converted)
        row_heights.append(label_height + max_height)
    canvas_width = gap + columns * (cell_width + gap)
    canvas_height = gap + sum(height + gap for height in row_heights)
    canvas = Image.new("RGB", (canvas_width, canvas_height), "#111719")
    draw = ImageDraw.Draw(canvas)
    y = gap
    for row, row_height in zip(processed, row_heights):
        x = gap
        for name, image in row:
            draw.text((x + 4, y + 8), name, fill="#f1ead9")
            canvas.paste(image, (x, y + label_height))
            x += cell_width + gap
        y += row_height + gap
    encoded = BytesIO()
    canvas.save(encoded, "WEBP", quality=8, method=6)
    payload = base64.b64encode(encoded.getvalue()).decode("ascii")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" '
        f'viewBox="0 0 {canvas_width} {canvas_height}" role="img" aria-label="Business 22 validation capture atlas {filename}">'
        f'<image width="{canvas_width}" height="{canvas_height}" href="data:image/webp;base64,{payload}"/>'
        '</svg>\n'
    )
    target = EVIDENCE / filename
    target.write_text(svg, encoding="utf-8")
    for _, image in captures:
        image.close()
    return target.name


def state_metrics(page, state: str) -> dict[str, Any]:
    return page.evaluate(
        """
        (state) => {
          const root = document.documentElement;
          const body = document.body;
          const panel = document.querySelector(`[data-state="${state}"]`);
          const images = [...document.images].map(img => ({src: img.getAttribute('src'), complete: img.complete, width: img.naturalWidth}));
          return {
            state,
            active: window.__B22_REVIEW__?.getState?.(),
            visible: panel ? !panel.hidden : false,
            horizontalOverflow: Math.max(root.scrollWidth, body.scrollWidth) - window.innerWidth,
            brokenImages: images.filter(img => !img.complete || img.width === 0),
            scrollHeight: root.scrollHeight,
            viewport: {width: window.innerWidth, height: window.innerHeight}
          };
        }
        """,
        state,
    )


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "kind": "business-22-browser-validation",
        "baseUrl": BASE,
        "browserEnvironment": "Chromium headless with fully inlined set_content; localhost and file navigation blocked by administrator policy",
        "viewports": {},
        "consoleErrors": [],
        "pageErrors": [],
        "failedRequests": [],
        "externalRequests": [],
        "screenshots": [],
        "keyboard": {},
        "motion": {},
        "reducedMotion": {},
    }
    desktop_captures: list[tuple[str, Image.Image]] = []
    responsive_captures: list[tuple[str, Image.Image]] = []
    motion_captures: list[tuple[str, Image.Image]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page = context.new_page()

        page.on("console", lambda msg: report["consoleErrors"].append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: report["pageErrors"].append(str(exc)))
        page.on("requestfailed", lambda req: report["failedRequests"].append({"url": req.url, "failure": req.failure}))
        page.on("request", lambda req: report["externalRequests"].append(req.url) if req.url.startswith(("http://", "https://")) else None)

        desktop_results = []
        for state in STATES:
            load_state(page, state)
            page.wait_for_timeout(80)
            metrics = state_metrics(page, state)
            desktop_results.append(metrics)
            desktop_captures.append(capture(page, f"desktop-{state}-1440"))
        report["viewports"]["1440x1100"] = desktop_results

        # Query state and keyboard tab behavior.
        load_state(page, "cover")
        page.locator("#tab-cover").focus()
        page.keyboard.press("ArrowRight")
        after_right = page.evaluate("window.__B22_REVIEW__.getState()")
        focused_after_right = page.evaluate("document.activeElement?.id")
        page.keyboard.press("End")
        after_end = page.evaluate("window.__B22_REVIEW__.getState()")
        page.keyboard.press("Home")
        after_home = page.evaluate("window.__B22_REVIEW__.getState()")
        report["keyboard"] = {
            "arrowRightState": after_right,
            "arrowRightFocus": focused_after_right,
            "endState": after_end,
            "homeState": after_home,
            "passed": after_right == "sources" and focused_after_right == "tab-sources" and after_end == "mobile" and after_home == "cover",
        }

        # Tablet evidence and metrics.
        page.set_viewport_size({"width": 768, "height": 1024})
        tablet_results = []
        for state in ["sources", "suite", "adaptation"]:
            load_state(page, state)
            page.wait_for_timeout(80)
            tablet_results.append(state_metrics(page, state))
            responsive_captures.append(capture(page, f"tablet-{state}-768"))
        report["viewports"]["768x1024"] = tablet_results

        # Mobile evidence and metrics.
        page.set_viewport_size({"width": 390, "height": 844})
        mobile_results = []
        for state in ["cover", "suite", "mobile"]:
            load_state(page, state)
            page.wait_for_timeout(80)
            mobile_results.append(state_metrics(page, state))
            responsive_captures.append(capture(page, f"mobile-{state}-390"))
        report["viewports"]["390x844"] = mobile_results

        # Motion stability and deterministic frame evidence at desktop.
        page.set_viewport_size({"width": 1440, "height": 1100})
        load_state(page, "adaptation", skip_relay=False)
        replay = page.locator('[data-action="replay"]')
        replay.focus()
        page.evaluate("window.scrollTo(0, 20)")
        page.wait_for_timeout(20)
        page.evaluate("document.querySelector('[data-action=\"replay\"]').addEventListener('click', () => { window.__relayTriggerScrollY = window.scrollY; }, {capture: true, once: true})")
        before = page.evaluate("({focus: document.activeElement?.getAttribute('data-action'), x: scrollX, y: scrollY, h: document.documentElement.scrollHeight})")
        motion_captures.append(capture(page, "motion-frame-00-before", full_page=False))
        page.keyboard.press("Enter")
        page.wait_for_timeout(170)
        motion_captures.append(capture(page, "motion-frame-01-annotation", full_page=False))
        page.wait_for_timeout(170)
        motion_captures.append(capture(page, "motion-frame-02-article", full_page=False))
        page.wait_for_timeout(200)
        motion_captures.append(capture(page, "motion-frame-03-formats", full_page=False))
        page.wait_for_timeout(280)
        motion_captures.append(capture(page, "motion-frame-04-review", full_page=False))
        after = page.evaluate("({focus: document.activeElement?.getAttribute('data-action'), x: scrollX, y: scrollY, h: document.documentElement.scrollHeight, state: document.querySelector('[data-relay]').dataset.motionState, triggerY: window.__relayTriggerScrollY})")
        report["motion"] = {
            "before": before,
            "after": after,
            "passed": before["focus"] == "replay" and after["focus"] == "replay" and before["x"] == after["x"] and after["triggerY"] == after["y"] and before["h"] == after["h"] and after["state"] == "complete",
            "nominalDurationMs": 720,
            "evidenceFrames": [
                "motion-relay-frames.svg / panel motion-frame-00-before",
                "motion-relay-frames.svg / panel motion-frame-01-annotation",
                "motion-relay-frames.svg / panel motion-frame-02-article",
                "motion-relay-frames.svg / panel motion-frame-03-formats",
                "motion-relay-frames.svg / panel motion-frame-04-review",
            ],
        }

        context.close()

        # Reduced-motion equivalence.
        reduced_context = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
        reduced_page = reduced_context.new_page()
        load_state(reduced_page, "adaptation", skip_relay=False)
        reduced_page.locator('[data-action="replay"]').focus()
        reduced_page.keyboard.press("Enter")
        reduced_page.wait_for_timeout(30)
        visible_steps = reduced_page.evaluate("[...document.querySelectorAll('.relay-step')].every(el => getComputedStyle(el).opacity === '1')")
        reduced_focus = reduced_page.evaluate("document.activeElement?.getAttribute('data-action')")
        report["reducedMotion"] = {
            "allFinalStepsVisible": visible_steps,
            "focus": reduced_focus,
            "passed": bool(visible_steps and reduced_focus == "replay"),
        }
        reduced_context.close()
        browser.close()

    report["screenshots"] = [
        write_atlas("desktop-states-a-1440.svg", desktop_captures[:4], columns=2, cell_width=280),
        write_atlas("desktop-states-b-1440.svg", desktop_captures[4:], columns=2, cell_width=280),
        *[write_atlas(f"{name}.svg", [(name, image)], columns=1, cell_width=260) for name, image in responsive_captures[:3]],
        *[write_atlas(f"{name}.svg", [(name, image)], columns=1, cell_width=160) for name, image in responsive_captures[3:]],
        write_atlas("motion-relay-frames.svg", motion_captures, columns=2, cell_width=300),
    ]
    report["capturePanels"] = {
        "desktop-states-a-1440.svg": [name for name, _ in desktop_captures[:4]],
        "desktop-states-b-1440.svg": [name for name, _ in desktop_captures[4:]],
        **{f"{name}.svg": [name] for name, _ in responsive_captures},
        "motion-relay-frames.svg": [name for name, _ in motion_captures],
    }

    all_metrics = [m for group in report["viewports"].values() for m in group]
    report["summary"] = {
        "allQueriesResolve": all(m["active"] == m["state"] and m["visible"] for m in all_metrics),
        "zeroHorizontalOverflow": all(m["horizontalOverflow"] <= 0 for m in all_metrics),
        "zeroBrokenImages": all(not m["brokenImages"] for m in all_metrics),
        "zeroConsoleErrors": not report["consoleErrors"],
        "zeroPageErrors": not report["pageErrors"],
        "zeroFailedRequests": not report["failedRequests"],
        "zeroExternalRequests": not report["externalRequests"],
        "keyboardPassed": report["keyboard"].get("passed", False),
        "motionPassed": report["motion"].get("passed", False),
        "reducedMotionPassed": report["reducedMotion"].get("passed", False),
    }
    report["passed"] = all(report["summary"].values())
    (EVIDENCE / "validation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVIDENCE / "motion-frames.json").write_text(json.dumps(report["motion"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1
if __name__ == "__main__":
    raise SystemExit(main())
