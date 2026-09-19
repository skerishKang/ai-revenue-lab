from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

TARGET = "https://storymemory-padiem-567.pages.dev/"
OUT = Path(".tmp/b61-public-product-film")
RAW = OUT / "raw"
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

console_errors: list[str] = []
page_errors: list[str] = []
interactions: list[str] = []


def click(
    page,
    selector: str,
    label: str,
    *,
    pause_ms: int = 1200,
    force: bool = False,
) -> None:
    loc = page.locator(selector)
    loc.wait_for(state="visible", timeout=8000)
    loc.click(timeout=5000, force=force)
    interactions.append(label)
    page.wait_for_timeout(pause_ms)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=1,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        record_video_dir=str(RAW),
        record_video_size={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    response = page.goto(TARGET, wait_until="domcontentloaded", timeout=45000)
    if response is None or response.status >= 400:
        raise RuntimeError(
            f"StoryMemory load failed: {response.status if response else 'NO_RESPONSE'}"
        )
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    page.wait_for_timeout(3200)
    if not page.url.startswith(TARGET):
        raise RuntimeError(f"Capture left approved latest host: {page.url}")

    body = page.locator("body")
    if not body.is_visible():
        raise RuntimeError("StoryMemory body is not visible")
    initial_text = body.inner_text()
    if len(initial_text.strip()) < 40:
        raise RuntimeError("StoryMemory public UI has insufficient visible content")

    library = page.locator("#library")
    if "active" not in (library.get_attribute("class") or ""):
        raise RuntimeError("StoryMemory did not open on the Library screen")

    initial_book = page.locator("#libTitle").inner_text().strip()
    if initial_book != "성경":
        raise RuntimeError(f"Unexpected initial Library selection: {initial_book!r}")

    # The Album still is the clean real public Library frame. It is captured before
    # any interaction, and the same frame is also present at the start of the film.
    page.screenshot(
        path=str(OUT / "storymemory-product-still-v1.png"),
        full_page=False,
    )
    page.wait_for_timeout(1800)

    # Real UI path: the public shelf starts on Bible (index 3). Three actual Previous
    # clicks retarget the carousel to Iliad; no internal JS function or synthetic state.
    for step in range(3):
        click(
            page,
            "#prevBook",
            f"library_prev_{step + 1}",
            pause_ms=850,
        )

    selected_book = page.locator("#libTitle").inner_text().strip()
    if selected_book != "일리아드":
        raise RuntimeError(
            f"Expected real Library navigation to select 일리아드, got {selected_book!r}"
        )
    page.wait_for_timeout(1400)

    click(page, "#openBook", "open_iliad_reader", pause_ms=500)
    page.locator("#reader.active").wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(1800)

    reader_title = page.locator("#readerVolumeTitle").inner_text().strip()
    if reader_title != "일리아드":
        raise RuntimeError(f"Expected Iliad Reader, got {reader_title!r}")

    reader_body = page.locator("#readerPageBody")
    reader_body.wait_for(state="visible", timeout=8000)
    if len(reader_body.inner_text().strip()) < 40:
        raise RuntimeError("Reader entered but visible reading content is empty")

    # Demonstrate real reading progression.
    # The page-turn control has intentional continuous motion. Playwright's normal
    # stability gate never settles, so force only bypasses the automation
    # stability check; the real button click handler still receives the event.
    click(page, "#pageTurnNext", "reader_next_page", pause_ms=1800, force=True)

    # Demonstrate Memory UI without persisting a note.
    click(page, "#newFreeNote", "memory_note_open", pause_ms=1200)
    note_input = page.locator("#memoryNoteInput")
    note_input.wait_for(state="visible", timeout=5000)
    note_input.fill("이 장면을 기억해 두기")
    interactions.append("memory_note_draft")
    page.wait_for_timeout(1100)
    click(page, "#cancelMemoryNote", "memory_note_cancel", pause_ms=1000)

    # Open the real AI Companion context surface, but do not submit any request.
    ai_tab = page.locator("#aiRailTab")
    ai_tab.wait_for(state="visible", timeout=5000)
    if ai_tab.get_attribute("aria-expanded") != "true":
        click(page, "#aiRailTab", "ai_companion_open", pause_ms=1300)
    else:
        interactions.append("ai_companion_already_open")
        page.wait_for_timeout(1300)

    ask = page.locator("#askInput")
    ask.wait_for(state="visible", timeout=5000)
    ask.fill("이 장면의 맥락은?")
    interactions.append("ai_prompt_draft_no_submit")
    page.wait_for_timeout(1400)
    ask.fill("")
    page.wait_for_timeout(900)

    visible_text = body.inner_text()
    visible_email = bool(
        re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", visible_text, re.I)
    )
    if visible_email:
        raise RuntimeError("Privacy guard found a visible email")

    final_screen = "reader" if page.locator("#reader.active").count() else "unknown"
    if final_screen != "reader":
        raise RuntimeError(f"Capture did not remain in Reader: {final_screen}")

    if len(interactions) < 9:
        raise RuntimeError(f"Insufficient real UI interactions: {interactions!r}")

    evidence = {
        "target": TARGET,
        "final_url": page.url,
        "title": page.title(),
        "viewport": {"width": 1440, "height": 900},
        "initial_screen": "library",
        "initial_book": initial_book,
        "selected_book": selected_book,
        "final_screen": final_screen,
        "reader_title": reader_title,
        "interactions": interactions,
        "interaction_count": len(interactions),
        "visible_email": visible_email,
        "login_performed": False,
        "note_saved": False,
        "ai_prompt_submitted": False,
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    (OUT / "capture-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    video = page.video
    context.close()
    if video is None:
        raise RuntimeError("Playwright did not create capture video")
    video.save_as(str(OUT / "storymemory-product-film-v1.webm"))
    browser.close()
