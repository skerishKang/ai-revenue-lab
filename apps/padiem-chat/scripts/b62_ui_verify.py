"""B62 Chat UI split-search lightweight visual verification.

Run against a locally served padiem-chat instance:

    PADIEM_CHAT_RUNTIME_MODE=mock PADIEM_CHAT_WEB_PROVIDER=mock \
      python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
    python scripts/b62_ui_verify.py http://127.0.0.1:8080 <output-dir>

Checks (maps to the B62 split-search task tests 1-5):
  1. Collapse button sits at the right end of the brand row; collapse/expand works.
  2. New Chat + Search share the second row; no redundant mode hint text.
  3. A left search click does NOT change the center web card's status text.
  4. The composer web-search button still toggles the center card; card still exists.
  5. Narrow viewport keeps the layout intact (no overlap / horizontal scroll).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "."
CHROME = os.environ.get("B62_CHROME_PATH")  # optional explicit chromium path


async def main() -> None:
    results: dict[str, object] = {}
    async with async_playwright() as pw:
        launch_kwargs: dict[str, object] = {"args": ["--no-sandbox"]}
        if CHROME:
            launch_kwargs["executable_path"] = CHROME
        browser = await pw.chromium.launch(**launch_kwargs)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(BASE, wait_until="load")
        await page.wait_for_timeout(1200)

        # ---- Fix 1: brand row collapse placement --------------------------
        collapse = page.locator("#sidebarCollapseButton")
        brand_row = page.locator(".brand-row")
        collapse_box = await collapse.bounding_box()
        brand_box = await brand_row.bounding_box()
        results["collapse_in_brand_row"] = bool(
            collapse_box
            and brand_box
            and collapse_box["y"] >= brand_box["y"] - 1
            and collapse_box["y"] + collapse_box["height"] <= brand_box["y"] + brand_box["height"] + 1
        )
        # right end: within a few px of the brand row's right edge
        results["collapse_at_right_end"] = bool(
            collapse_box
            and brand_box
            and abs((collapse_box["x"] + collapse_box["width"]) - (brand_box["x"] + brand_box["width"])) <= 20
        )

        # ---- Fix 1: new chat + search on one row --------------------------
        new_chat = page.locator("#newChatButton")
        search = page.locator("#sidebarSearchButton")
        nc_box = await new_chat.bounding_box()
        s_box = await search.bounding_box()
        results["actions_same_row"] = bool(
            nc_box and s_box and abs(nc_box["y"] - s_box["y"]) <= 2
        )
        results["search_visible"] = await search.is_visible()
        results["search_disabled"] = await search.is_disabled()
        results["search_hold_title"] = await search.get_attribute("title")

        # ---- Fix 1: no "일반 대화" --------------------------------------
        body_text = await page.locator("body").inner_text()
        results["no_general_conversation_text"] = "일반 대화" not in body_text
        results["no_mode_hint_attr"] = (
            await new_chat.get_attribute("data-mode-hint")
        ) is None

        # ---- Fix 1/keep: collapse & expand --------------------------------
        await collapse.click()
        await page.wait_for_timeout(350)
        results["collapse_hides_sidebar"] = not await page.locator("#sidebar").is_visible()
        results["restore_button_appears"] = await page.locator("#sidebarRestoreButton").is_visible()
        await page.locator("#sidebarRestoreButton").click()
        await page.wait_for_timeout(350)
        results["expand_restores_sidebar"] = await page.locator("#sidebar").is_visible()

        # ---- Fix 3/4: center web card decoupling --------------------------
        starter = page.locator("#webSearchStarterButton")
        results["center_card_exists"] = await starter.count() == 1
        card_visible = await starter.is_visible()
        results["center_card_visible"] = card_visible
        card_status = starter.locator("small")
        if card_visible:
            before = (await card_status.inner_text()).strip()
            # The button is disabled by design; dispatch a synthetic click to
            # prove no handler changes the card either.
            await search.dispatch_event("click")
            await page.wait_for_timeout(300)
            after_search_click = (await card_status.inner_text()).strip()
            results["card_text_unchanged_after_search_click"] = before == after_search_click
            results["card_text_before"] = before
            # composer web search still toggles it
            web_toggle = page.locator("#webSearchButton")
            await web_toggle.click()
            await page.wait_for_timeout(300)
            after_web_click = (await card_status.inner_text()).strip()
            results["card_text_after_web_toggle"] = after_web_click
            results["web_toggle_still_works"] = after_web_click != before
            # left search click again still inert while web mode active
            await search.dispatch_event("click")
            await page.wait_for_timeout(300)
            results["card_text_stable_second_search_click"] = (
                (await card_status.inner_text()).strip() == after_web_click
            )
            # toggle web mode back off for a clean final state
            await web_toggle.click()
            await page.wait_for_timeout(200)

        # ---- Screenshot 1: desktop, sidebar + center card ------------------
        await page.screenshot(path=f"{OUT_DIR}/b62_desktop_sidebar.png", full_page=False)

        # ---- Fix 1/5: narrow viewport --------------------------------------
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(400)
        overflow = await page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        results["narrow_no_horizontal_overflow"] = overflow <= 0
        # open the mobile drawer to capture the actions row on narrow screens
        await page.locator("#mobileMenu").click()
        await page.wait_for_timeout(400)
        nc_box = await new_chat.bounding_box()
        s_box = await search.bounding_box()
        results["narrow_actions_same_row"] = bool(
            nc_box and s_box and abs(nc_box["y"] - s_box["y"]) <= 2
        )
        await page.screenshot(path=f"{OUT_DIR}/b62_mobile_sidebar.png", full_page=False)

        results["page_errors"] = errors
        await browser.close()

    report = json.dumps(results, ensure_ascii=False, indent=2)
    print(report)
    with open(f"{OUT_DIR}/b62_ui_verify_result.json", "w", encoding="utf-8") as handle:
        handle.write(report + "\n")
    failed = [key for key, value in results.items() if value is False]
    if failed:
        print(f"FAILED CHECKS: {failed}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


asyncio.run(main())
