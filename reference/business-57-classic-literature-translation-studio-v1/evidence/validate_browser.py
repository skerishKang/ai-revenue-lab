#!/usr/bin/env python3
"""Chromium validation and visual evidence for Business 57."""
from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/screenshots"
REPORT = ROOT / "evidence/browser-validation.json"
VERSION = "classic-literature-translation-20260728-2"
STATES = ["library", "source-fidelity", "comparison", "ledger", "poetry", "mobile", "weave"]
VIEWPORTS = [(1440, 1100), (768, 1024), (390, 844)]
CHROMIUM = "/usr/bin/chromium"


def inline_document() -> str:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
    js = (ROOT / "scripts/review.js").read_text(encoding="utf-8")
    svg = base64.b64encode((ROOT / "assets/rose-mark.svg").read_bytes()).decode("ascii")
    html = html.replace(
        f'<link rel="stylesheet" href="./styles/main.css?v={VERSION}">',
        f"<style>{css}</style>",
    )
    html = html.replace(
        f'<script src="./scripts/review.js?v={VERSION}" defer></script>', ""
    )
    html = html.replace("./assets/rose-mark.svg", f"data:image/svg+xml;base64,{svg}")
    monitor = """<script>
window.__unhandledRejections = [];
window.addEventListener('unhandledrejection', event => {
  window.__unhandledRejections.push(String(event.reason));
});
</script>"""
    html = html.replace("</head>", monitor + "</head>")
    html = html.replace("</body>", f"<script>{js}</script></body>")
    return html


def ms_list(value: str) -> list[float]:
    values: list[float] = []
    for part in value.split(","):
        token = part.strip()
        if token.endswith("ms"):
            values.append(float(token[:-2]))
        elif token.endswith("s"):
            values.append(float(token[:-1]) * 1000)
        else:
            values.append(0.0)
    return values or [0.0]


def computed_motion(page: Page) -> tuple[list[dict[str, str]], float]:
    rows = page.locator(".thread, .rendering").evaluate_all(
        """els => els.map(el => {
          const s = getComputedStyle(el);
          return {
            className: el.className.baseVal || el.className,
            animationName: s.animationName,
            duration: s.animationDuration,
            delay: s.animationDelay
          };
        })"""
    )
    maximum = 0.0
    for row in rows:
        durations = ms_list(row["duration"])
        delays = ms_list(row["delay"])
        for index in range(max(len(durations), len(delays))):
            maximum = max(
                maximum,
                durations[index % len(durations)] + delays[index % len(delays)],
            )
    return rows, round(maximum, 3)


def rect(page: Page, selector: str) -> dict[str, float]:
    return page.locator(selector).evaluate(
        """el => {
          const r = el.getBoundingClientRect();
          return {x:r.x, y:r.y, width:r.width, height:r.height};
        }"""
    )


def geometry(page: Page) -> dict[str, Any]:
    return {
        "source": rect(page, ".weave-source"),
        "target": rect(page, ".weave-target"),
        "paragraph": rect(page, ".settled-paragraph"),
        "button": rect(page, "#replay-weave"),
        "rail": rect(page, ".review-rail"),
        "documentHeight": page.evaluate("document.documentElement.scrollHeight"),
    }


def close_geometry(first: dict[str, Any], second: dict[str, Any], tolerance: float = 0.25) -> bool:
    for key, value in first.items():
        if key == "documentHeight":
            if value != second[key]:
                return False
            continue
        for dimension in ("x", "y", "width", "height"):
            if abs(float(value[dimension]) - float(second[key][dimension])) > tolerance:
                return False
    return True


def final_styles(page: Page) -> list[dict[str, str]]:
    return page.locator(".thread, .rendering").evaluate_all(
        """els => els.map(el => {
          const s = getComputedStyle(el);
          return {
            className: el.className.baseVal || el.className,
            dash: s.strokeDashoffset,
            opacity: s.opacity,
            boxShadow: s.boxShadow
          };
        })"""
    )


def runtime_snapshot(page: Page) -> dict[str, Any]:
    return {
        "geometry": geometry(page),
        "scroll": page.evaluate("window.scrollY"),
        "focus": page.evaluate("document.activeElement?.id || ''"),
        "motionState": page.locator("#weave-board").get_attribute("data-motion-state"),
        "styles": final_styles(page),
    }


def state_metrics(page: Page, state: str) -> dict[str, Any]:
    tab = page.locator(f'[data-state-target="{state}"]')
    tab.click()
    page.wait_for_timeout(720 if state == "weave" else 30)
    overflow = page.evaluate(
        "Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)"
    )
    return {
        "activeState": page.locator(".visual-state:not([hidden])").get_attribute("data-state"),
        "horizontalOverflow": overflow,
        "ariaSelected": tab.get_attribute("aria-selected"),
        "ariaCurrent": tab.get_attribute("aria-current"),
        "accessibleName": tab.inner_text().strip(),
        "panelVisible": page.locator(f'[data-state="{state}"]').is_visible(),
        "imagesLoaded": page.locator("img").evaluate_all(
            "els => els.every(el => el.complete && el.naturalWidth > 0)"
        ),
    }


def screenshot(page: Page, name: str, *, full_page: bool = True) -> None:
    page.screenshot(path=str(OUT / name), full_page=full_page)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.iterdir():
        if old.is_file():
            old.unlink()

    document = inline_document()
    report: dict[str, Any] = {
        "business": 57,
        "version": VERSION,
        "browser": CHROMIUM,
        "harness": "actual source bytes inlined with page.set_content because localhost/file navigation is blocked",
        "viewports": {},
        "motion": {},
        "reducedMotion": {},
        "checks": [],
    }

    def check(name: str, passed: bool, detail: str) -> None:
        report["checks"].append({"name": name, "passed": bool(passed), "detail": detail})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=CHROMIUM, args=["--no-sandbox"]
        )

        all_state_ok = True
        all_overflow_zero = True
        all_errors_zero = True
        all_assets_ok = True
        all_requests_zero = True
        keyboard_ok = True
        focus_visible_ok = True

        for width, height in VIEWPORTS:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[str] = []
            requests: list[str] = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("requestfailed", lambda request: failed_requests.append(request.url))
            page.on("request", lambda request: requests.append(request.url))
            page.set_content(document, wait_until="load")

            state_results: dict[str, Any] = {}
            for state in STATES:
                state_results[state] = state_metrics(page, state)
                row = state_results[state]
                all_state_ok &= row["activeState"] == state and row["panelVisible"] and row["ariaSelected"] == "true" and bool(row["accessibleName"])
                all_overflow_zero &= row["horizontalOverflow"] == 0
                all_assets_ok &= row["imagesLoaded"]
                if width == 1440:
                    screenshot(page, f"desktop-1440-{state}.png")

            if width == 768:
                page.locator('[data-state-target="source-fidelity"]').click()
                screenshot(page, "tablet-768-source-fidelity.png")
            if width == 390:
                page.locator('[data-state-target="mobile"]').click()
                page.wait_for_timeout(30)
                screenshot(page, "mobile-390-reading.png", full_page=False)
                reveal = page.locator(".source-reveal")
                reveal.click()
                reveal_open = reveal.get_attribute("aria-expanded") == "true" and page.locator(".phone-source").is_visible()
                reveal.click()
                reveal_closed = reveal.get_attribute("aria-expanded") == "false" and page.locator(".phone-source").is_hidden()
            else:
                reveal_open = reveal_closed = True

            page.locator("#tab-library").focus()
            page.keyboard.press("ArrowRight")
            focused = page.evaluate("document.activeElement?.id")
            style = page.locator("#tab-source-fidelity").evaluate(
                "el => { const s=getComputedStyle(el); return {style:s.outlineStyle, width:s.outlineWidth}; }"
            )
            keyboard_here = focused == "tab-source-fidelity"
            focus_here = style["style"] not in ("none", "") and float(style["width"].replace("px", "") or 0) >= 2
            keyboard_ok &= keyboard_here
            focus_visible_ok &= focus_here

            unhandled = page.evaluate("window.__unhandledRejections")
            external_requests = [url for url in requests if url.startswith(("http://", "https://"))]
            all_errors_zero &= not console_errors and not page_errors and not unhandled
            all_requests_zero &= not external_requests and not failed_requests
            report["viewports"][f"{width}x{height}"] = {
                "states": state_results,
                "consoleErrors": console_errors,
                "pageErrors": page_errors,
                "unhandledRejections": unhandled,
                "failedRequests": failed_requests,
                "externalRuntimeRequests": external_requests,
                "keyboard": {"focused": focused, "passed": keyboard_here},
                "visibleFocus": {"style": style, "passed": focus_here},
                "mobileSourceReveal": {"open": reveal_open, "closed": reveal_closed},
            }
            context.close()

        check("seven_states_all_viewports", all_state_ok, "all state controls activate named panels")
        check("horizontal_overflow_zero", all_overflow_zero, "all states at 1440/768/390")
        check("local_assets_loaded", all_assets_ok, "rose SVG naturalWidth > 0")
        check("console_page_unhandled_zero", all_errors_zero, "no console/page/unhandled rejection errors")
        check("network_runtime_zero", all_requests_zero, "no external or failed runtime requests")
        check("keyboard_navigation", keyboard_ok, "ArrowRight moves focus and active panel")
        check("visible_focus", focus_visible_ok, "computed outline >= 2px")

        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        page.set_content(document, wait_until="load")
        page.locator('[data-state-target="weave"]').click()
        page.wait_for_timeout(720)
        page.locator("#replay-weave").focus()
        page.evaluate("window.scrollTo(0, 120)")
        page.wait_for_timeout(20)
        before = runtime_snapshot(page)
        screenshot(page, "weave-before.png", full_page=False)

        replay = page.locator("#replay-weave")
        replay.click()
        page.wait_for_timeout(10)
        running_state = page.locator("#weave-board").get_attribute("data-motion-state")
        timing, computed_end = computed_motion(page)
        gif_frames: list[Path] = []
        for index, wait in enumerate([0, 160, 170, 170, 210]):
            if wait:
                page.wait_for_timeout(wait)
            frame = OUT / f".weave-frame-{index}.png"
            page.screenshot(path=str(frame), full_page=False)
            gif_frames.append(frame)
            if index == 2:
                page.screenshot(path=str(OUT / "weave-midpoint.png"), full_page=False)
        page.wait_for_timeout(40)
        after_first = runtime_snapshot(page)
        screenshot(page, "weave-complete.png", full_page=False)

        replay.click()
        page.wait_for_timeout(720)
        after_second = runtime_snapshot(page)

        images = [Image.open(path).convert("P", palette=Image.Palette.ADAPTIVE) for path in gif_frames]
        images[0].save(
            OUT / "translation-weave-680ms.gif",
            save_all=True,
            append_images=images[1:],
            duration=[120, 160, 170, 170, 180],
            loop=0,
            optimize=False,
        )
        for image in images:
            image.close()
        for path in gif_frames:
            path.unlink()

        geometry_stable = close_geometry(before["geometry"], after_first["geometry"]) and close_geometry(after_first["geometry"], after_second["geometry"])
        final_same = after_first["styles"] == after_second["styles"] == before["styles"]
        focus_stable = all(item["focus"] == "replay-weave" for item in [before, after_first, after_second])
        scroll_stable = len({item["scroll"] for item in [before, after_first, after_second]}) == 1
        state_complete = after_first["motionState"] == after_second["motionState"] == "complete"

        report["motion"] = {
            "computedStyles": timing,
            "computedMaximumEndMs": computed_end,
            "runningStateObserved": running_state,
            "before": before,
            "afterFirst": after_first,
            "afterSecond": after_second,
            "geometryStable": geometry_stable,
            "firstSecondFinalEquivalent": final_same,
            "focusStable": focus_stable,
            "scrollStable": scroll_stable,
            "completionState": state_complete,
        }
        check("motion_computed_680ms", math.isclose(computed_end, 680.0, abs_tol=0.1), f"computed={computed_end}")
        check("motion_running_complete_transition", running_state == "running" and state_complete, f"running={running_state}, final={after_first['motionState']}")
        check("motion_geometry_stable", geometry_stable, "source/target/paragraph/button/rail/document height")
        check("motion_replay_equivalent", final_same, "complete styles before/after replay 1/replay 2")
        check("motion_focus_scroll_stable", focus_stable and scroll_stable, f"focus={focus_stable}, scroll={scroll_stable}")
        context.close()

        context = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
        page = context.new_page()
        page.set_content(document, wait_until="load")
        page.locator('[data-state-target="weave"]').click()
        page.wait_for_timeout(30)
        page.locator("#replay-weave").focus()
        page.evaluate("window.scrollTo(0, 120)")
        reduced_before = runtime_snapshot(page)
        page.locator("#replay-weave").click()
        page.wait_for_timeout(30)
        reduced_after = runtime_snapshot(page)
        screenshot(page, "reduced-motion-weave-final.png", full_page=False)

        reduced_equivalent = reduced_after["styles"] == after_first["styles"]
        reduced_geometry = close_geometry(reduced_before["geometry"], reduced_after["geometry"])
        reduced_focus = reduced_before["focus"] == reduced_after["focus"] == "replay-weave"
        reduced_scroll = reduced_before["scroll"] == reduced_after["scroll"]
        reduced_complete = reduced_before["motionState"] == reduced_after["motionState"] == "complete"
        report["reducedMotion"] = {
            "before": reduced_before,
            "after": reduced_after,
            "normalFinalInformationEquivalent": reduced_equivalent,
            "geometryStable": reduced_geometry,
            "focusStable": reduced_focus,
            "scrollStable": reduced_scroll,
            "completeImmediately": reduced_complete,
        }
        check("reduced_motion_information_equivalent", reduced_equivalent and reduced_complete, "normal and reduced final path/emphasis styles match")
        check("reduced_motion_stability", reduced_geometry and reduced_focus and reduced_scroll, "geometry/focus/scroll stable")
        context.close()
        browser.close()

    report["status"] = "BROWSER_VALIDATION_PASS" if all(row["passed"] for row in report["checks"]) else "BROWSER_VALIDATION_FAIL"
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "BROWSER_VALIDATION_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
