"""Capture-only evidence runner for the public StoryMemory surface.

This script never logs in, saves a note, submits an AI prompt, or calls a
provider. It records a private review artifact for the branch-bounded CI job.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


TARGET = "https://storymemory-padiem-567.pages.dev/"
OUT = Path(".tmp/b61-public-product-film")
RAW = OUT / "raw"


def click(page: Page, selector: str, label: str, interactions: list[str], *, force: bool = False) -> None:
    locator = page.locator(selector)
    locator.wait_for(state="visible", timeout=8_000)
    locator.click(timeout=5_000, force=force)
    interactions.append(label)
    page.wait_for_timeout(900)


def capture() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    interactions: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            record_video_dir=str(RAW),
            record_video_size={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        response = page.goto(TARGET, wait_until="domcontentloaded", timeout=45_000)
        if response is None or response.status >= 400:
            raise RuntimeError(f"public StoryMemory load failed: {response.status if response else 'NO_RESPONSE'}")
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        page.wait_for_timeout(2_500)

        if not page.url.startswith(TARGET):
            raise RuntimeError("capture left the approved public StoryMemory host")
        body = page.locator("body")
        if not body.is_visible() or len(body.inner_text().strip()) < 40:
            raise RuntimeError("public StoryMemory UI is not visibly usable")
        if "active" not in (page.locator("#library").get_attribute("class") or ""):
            raise RuntimeError("capture did not start on the public Library screen")

        initial_book = page.locator("#libTitle").inner_text().strip()
        if initial_book != "성경":
            raise RuntimeError(f"unexpected initial public Library selection: {initial_book!r}")
        page.screenshot(path=str(OUT / "storymemory-product-still-v1.png"))

        for index in range(3):
            click(page, "#prevBook", f"library_previous_{index + 1}", interactions)
        selected_book = page.locator("#libTitle").inner_text().strip()
        if selected_book != "일리아드":
            raise RuntimeError(f"expected public Library selection 일리아드, got {selected_book!r}")

        click(page, "#openBook", "open_iliad_reader", interactions)
        page.locator("#reader.active").wait_for(state="visible", timeout=10_000)
        reader_title = page.locator("#readerVolumeTitle").inner_text().strip()
        if reader_title != "일리아드":
            raise RuntimeError(f"expected public Reader title 일리아드, got {reader_title!r}")
        if len(page.locator("#readerPageBody").inner_text().strip()) < 40:
            raise RuntimeError("public Reader content is empty")

        click(page, "#pageTurnNext", "reader_next_page", interactions, force=True)

        # Open and cancel the memory dialog without persisting a note.
        click(page, "#newFreeNote", "memory_note_open", interactions)
        note_input = page.locator("#memoryNoteInput")
        note_input.wait_for(state="visible", timeout=5_000)
        note_input.fill("capture-only draft")
        interactions.append("memory_note_draft_no_save")
        click(page, "#cancelMemoryNote", "memory_note_cancel", interactions)

        # Draft text in the visible companion UI only; never submit it.
        ask = page.locator("#askInput")
        if not ask.is_visible():
            ai_tab = page.locator("#aiRailTab")
            if ai_tab.is_visible():
                click(page, "#aiRailTab", "ai_companion_open", interactions)
            else:
                mobile_ai = page.locator('#mobileDock [data-mobile="ai"]')
                if mobile_ai.is_visible():
                    click(page, '#mobileDock [data-mobile="ai"]', "ai_companion_open_mobile", interactions)
        ask.wait_for(state="visible", timeout=5_000)
        ask.fill("capture-only draft")
        interactions.append("ai_prompt_draft_no_submit")
        ask.fill("")

        visible_text = body.inner_text()
        if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", visible_text, re.IGNORECASE):
            raise RuntimeError("privacy guard found a visible email")
        if not page.locator("#reader.active").count():
            raise RuntimeError("capture did not finish in the public Reader")
        if len(interactions) < 9:
            raise RuntimeError(f"insufficient public UI interactions: {interactions!r}")

        evidence = {
            "target_host": "storymemory-padiem-567.pages.dev",
            "viewport": {"width": 1440, "height": 900},
            "initial_screen": "library",
            "initial_book": initial_book,
            "selected_book": selected_book,
            "final_screen": "reader",
            "reader_title": reader_title,
            "interactions": interactions,
            "interaction_count": len(interactions),
            "login_performed": False,
            "note_saved": False,
            "ai_prompt_submitted": False,
            "visible_email": False,
            "console_error_count": len(console_errors),
            "page_error_count": len(page_errors),
        }
        (OUT / "capture-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        video = page.video
        context.close()
        if video is None:
            raise RuntimeError("capture video was not produced")
        video.save_as(str(OUT / "storymemory-product-film-v1.webm"))
        browser.close()


if __name__ == "__main__":
    capture()
