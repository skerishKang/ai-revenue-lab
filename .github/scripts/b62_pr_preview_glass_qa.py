from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ["B62_QA_BASE_URL"].rstrip("/")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-preview-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def shell_state(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const style = getComputedStyle(root);
          const shell = window.__padiemGlassShell || {};
          const frags = [...document.querySelectorAll('.glass-shell-frag')];
          const opacities = frags.map((el) => parseFloat(getComputedStyle(el).opacity) || 0);
          const rects = frags.map((el) => el.getBoundingClientRect());
          const imageRect = shell.imageRect ? shell.imageRect() : null;
          const visibleRects = rects.filter((_, i) => opacities[i] > .08);
          const imageArea = imageRect ? imageRect.width * imageRect.height : 0;
          const portal = document.querySelector('.glass-shell-portrait');
          const portalStyle = portal ? getComputedStyle(portal) : null;
          return {
            progress: shell.progress ? shell.progress() : -1,
            target: shell.target ? shell.target() : -1,
            pointer: parseFloat(style.getPropertyValue('--glass-pointer-reveal')) || 0,
            pointerX: style.getPropertyValue('--glass-pointer-x').trim(),
            pointerY: style.getPropertyValue('--glass-pointer-y').trim(),
            portalOpacity: portalStyle ? parseFloat(portalStyle.opacity) || 0 : 0,
            visibleFragments: opacities.filter((o) => o > .08).length,
            maxFragmentOpacity: opacities.length ? Math.max(...opacities) : 0,
            maxFragmentHeightRatio: imageRect && visibleRects.length
              ? Math.max(...visibleRects.map((r) => r.height / imageRect.height))
              : 0,
            maxFragmentAreaRatio: imageArea > 0 && visibleRects.length
              ? Math.max(...visibleRects.map((r) => (r.width * r.height) / imageArea))
              : 0,
            imageRect,
          };
        }
        """
    )


async def wait_clean(page: Page) -> None:
    await page.wait_for_function(
        """() => {
          const shell = window.__padiemGlassShell;
          if (!shell || shell.progress() > .05) return false;
          const frags = [...document.querySelectorAll('.glass-shell-frag')];
          const maxFrag = frags.length
            ? Math.max(...frags.map((el) => parseFloat(getComputedStyle(el).opacity) || 0))
            : 0;
          const portal = document.querySelector('.glass-shell-portrait');
          const portalOpacity = portal ? (parseFloat(getComputedStyle(portal).opacity) || 0) : 0;
          return maxFrag <= .05 && portalOpacity <= .05;
        }""",
        timeout=12_000,
        polling=100,
    )


async def wait_recovered(page: Page) -> None:
    await page.wait_for_function(
        """() => {
          const shell = window.__padiemGlassShell;
          if (!shell || shell.progress() < .99) return false;
          const frags = [...document.querySelectorAll('.glass-shell-frag')];
          const maxFrag = frags.length
            ? Math.max(...frags.map((el) => parseFloat(getComputedStyle(el).opacity) || 0))
            : 0;
          const portal = document.querySelector('.glass-shell-portrait');
          const portalOpacity = portal ? (parseFloat(getComputedStyle(portal).opacity) || 0) : 0;
          return maxFrag <= .05 && portalOpacity >= .80;
        }""",
        timeout=12_000,
        polling=100,
    )


async def hover_at(page: Page, frac: float) -> None:
    rect = await page.evaluate(
        "() => window.__padiemGlassShell && window.__padiemGlassShell.imageRect && window.__padiemGlassShell.imageRect()"
    )
    if not rect:
        raise AssertionError("Preview shell imageRect is unavailable")
    await page.mouse.move(
        rect["left"] + rect["width"] * frac,
        rect["top"] + rect["height"] * .44,
    )


async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(
            f"{BASE_URL}/?theme=padiem-glass&glass=female&mask=auto",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        await page.locator("#messageInput").wait_for(state="visible", timeout=15_000)
        await wait_recovered(page)
        report["idle"] = await shell_state(page)
        await page.screenshot(path=str(OUT_DIR / "preview-female-idle.png"), full_page=False)

        tier = page.locator(".composer .model-pill[data-mode-control='true']")
        await tier.wait_for(state="visible", timeout=5_000)
        spark = tier.locator(".status-spark")
        spark_color = await spark.evaluate("el => getComputedStyle(el).color")
        spark_opacity = float(await spark.evaluate("el => getComputedStyle(el).opacity"))
        if spark_color != "rgb(79, 134, 173)" or spark_opacity < .99:
            raise AssertionError(f"Preview Plus spark regression: {spark_color=} {spark_opacity=}")
        report["plus_spark"] = {"color": spark_color, "opacity": spark_opacity}

        attachment = page.locator("#attachmentButton")
        rest_bg = await attachment.evaluate("el => getComputedStyle(el).backgroundColor")
        await attachment.hover()
        await page.wait_for_timeout(220)
        hover_style = {
            "color": await attachment.evaluate("el => getComputedStyle(el).color"),
            "background": await attachment.evaluate("el => getComputedStyle(el).backgroundColor"),
            "border": await attachment.evaluate("el => getComputedStyle(el).borderTopWidth"),
            "shadow": await attachment.evaluate("el => getComputedStyle(el).boxShadow"),
        }
        if hover_style["color"] != "rgb(23, 33, 42)":
            raise AssertionError(f"Preview + file foreground regression: {hover_style}")
        if hover_style["background"] == rest_bg or hover_style["border"] != "1px" or hover_style["shadow"] == "none":
            raise AssertionError(f"Preview + file hover is not distinct: rest={rest_bg}, hover={hover_style}")
        report["attachment_hover"] = {"rest_background": rest_bg, **hover_style}
        await page.screenshot(path=str(OUT_DIR / "preview-attachment-hover.png"), full_page=False)
        await page.mouse.move(70, 90)
        await wait_recovered(page)

        started = await page.evaluate("performance.now()")
        await hover_at(page, .18)
        await page.wait_for_timeout(260)
        early = await shell_state(page)
        if early["pointer"] < .99 or early["target"] > .01:
            raise AssertionError(f"Preview left hover did not latch binary target: {early}")
        if early["progress"] < .68 or early["portalOpacity"] < .55:
            raise AssertionError(f"Preview shell faded too early at 260ms: {early}")
        if early["maxFragmentHeightRatio"] > .075 or early["maxFragmentAreaRatio"] > .075:
            raise AssertionError(f"Preview contains oversized mosaic fragments: {early}")
        if early["pointerX"] not in {"", "0px", "0.0px"} or early["pointerY"] not in {"", "0px", "0.0px"}:
            raise AssertionError(f"Preview portrait parallax regression: {early}")

        await hover_at(page, .82)
        elapsed = float(await page.evaluate("s => performance.now() - s", started))
        if elapsed < 900:
            await page.wait_for_timeout(int(900 - elapsed))
        mid_elapsed = float(await page.evaluate("s => performance.now() - s", started))
        mid = await shell_state(page)
        if not 800 <= mid_elapsed <= 1300:
            raise AssertionError(f"Preview mid sample missed timing window: {mid_elapsed:.0f}ms")
        if mid["pointer"] < .99 or mid["target"] > .01:
            raise AssertionError(f"Preview right hover changed binary target: {mid}")
        if mid["progress"] > early["progress"] + .02 or mid["progress"] >= early["progress"] - .10:
            raise AssertionError(f"Preview X motion scrubbed/reversed progress: early={early}, mid={mid}")
        if not .15 <= mid["progress"] <= .65 or mid["portalOpacity"] <= .18 or mid["visibleFragments"] <= 0:
            raise AssertionError(f"Preview ~900ms frame is not visibly mid-transition: {mid}")
        if mid["maxFragmentHeightRatio"] > .075 or mid["maxFragmentAreaRatio"] > .075:
            raise AssertionError(f"Preview mid-transition mosaic regression: {mid}")

        await wait_clean(page)
        peel_elapsed = float(await page.evaluate("s => performance.now() - s", started))
        if not 1800 <= peel_elapsed <= 3600:
            raise AssertionError(f"Preview peel timing regression: {peel_elapsed:.0f}ms")
        clean = await shell_state(page)
        if clean["visibleFragments"] or clean["maxFragmentOpacity"] > .05 or clean["portalOpacity"] > .05:
            raise AssertionError(f"Preview clean end-state is obstructed: {clean}")
        await page.screenshot(path=str(OUT_DIR / "preview-female-clean.png"), full_page=False)

        recover_started = await page.evaluate("performance.now()")
        await page.mouse.move(70, 90)
        await page.wait_for_timeout(250)
        recovering = await shell_state(page)
        if recovering["progress"] <= clean["progress"]:
            raise AssertionError(f"Preview pointer leave did not start reassembly: {recovering}")
        await wait_recovered(page)
        recover_elapsed = float(await page.evaluate("s => performance.now() - s", recover_started))
        if not 1600 <= recover_elapsed <= 3600:
            raise AssertionError(f"Preview recovery timing regression: {recover_elapsed:.0f}ms")
        recovered = await shell_state(page)
        await page.screenshot(path=str(OUT_DIR / "preview-female-recovered.png"), full_page=False)

        # Capture deployed early and mid visual evidence in separate cycles so
        # screenshot I/O cannot distort the timing assertions above.
        await hover_at(page, .18)
        await page.wait_for_timeout(260)
        await page.screenshot(path=str(OUT_DIR / "preview-female-transition-early.png"), full_page=False)
        await page.mouse.move(70, 90)
        await wait_recovered(page)

        await hover_at(page, .82)
        await page.wait_for_timeout(900)
        deployed_mid = await shell_state(page)
        if not .15 <= deployed_mid["progress"] <= .65 or deployed_mid["visibleFragments"] <= 0:
            raise AssertionError(f"Preview deployed mid evidence is not transitional: {deployed_mid}")
        await page.screenshot(path=str(OUT_DIR / "preview-female-transition-mid.png"), full_page=False)
        await page.mouse.move(70, 90)
        await wait_recovered(page)

        report.update(
            {
                "early_260ms": early,
                "mid_900ms": mid,
                "mid_elapsed_ms": mid_elapsed,
                "peel_elapsed_ms": peel_elapsed,
                "clean": clean,
                "recovering_250ms": recovering,
                "recover_elapsed_ms": recover_elapsed,
                "recovered": recovered,
                "deployed_mid_evidence": deployed_mid,
            }
        )
        await browser.close()

    (OUT_DIR / "preview-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"B62 immutable Preview Glass browser smoke: PASS -> {OUT_DIR / 'preview-report.json'}")


if __name__ == "__main__":
    asyncio.run(main())
