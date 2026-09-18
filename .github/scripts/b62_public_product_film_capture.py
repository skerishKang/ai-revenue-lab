from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


TARGET = "https://chat.padiem.net/"
OUT = Path(".tmp/b62-public-product-film")
RAW = OUT / "raw"
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

console_errors: list[str] = []
page_errors: list[str] = []

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
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    response = page.goto(TARGET, wait_until="domcontentloaded", timeout=45_000)
    if response is None or response.status >= 400:
        raise RuntimeError(f"Public Padiem Chat failed to load: HTTP {response.status if response else 'NO_RESPONSE'}")

    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(4_000)

    if not page.url.startswith("https://chat.padiem.net/"):
        raise RuntimeError(f"Capture left canonical public host: {page.url}")
    if "Padiem Chat" not in page.title():
        raise RuntimeError(f"Unexpected public title: {page.title()}")

    composer = page.locator("#messageInput")
    tier = page.locator(".model-pill")
    settings = page.locator("#settingsButton")

    composer.wait_for(state="visible", timeout=20_000)
    tier.wait_for(state="visible", timeout=20_000)
    settings.wait_for(state="visible", timeout=20_000)

    tier_text = tier.inner_text().strip()
    if "padiem plus" not in tier_text.lower():
        raise RuntimeError(f"Unexpected public tier presentation: {tier_text}")

    # Scene 1: real public front door.
    page.wait_for_timeout(3_000)

    # Scene 2: actual public tier presentation. Do not select another tier.
    tier.click()
    panel = page.locator("#modePresentationPanel")
    panel.wait_for(state="visible", timeout=10_000)
    page.wait_for_timeout(3_500)
    page.keyboard.press("Escape")
    page.wait_for_timeout(1_500)

    # Scene 3: actual Settings surface. Do not alter theme or language.
    settings.click()
    settings_dialog = page.locator("#settingsDialog")
    settings_dialog.wait_for(state="visible", timeout=10_000)
    page.wait_for_timeout(5_000)
    close_button = page.locator("#settingsCloseButton")
    if close_button.is_visible():
        close_button.click()
    else:
        page.keyboard.press("Escape")
    page.wait_for_timeout(2_000)

    # Scene 4: actual composer interaction, deliberately no submit/model call.
    composer.fill("실제 공개 화면에서 작성 중인 제품 데모입니다.")
    page.wait_for_timeout(4_000)
    composer.fill("")
    page.wait_for_timeout(3_000)

    # Finish on a clean public product frame for Album cover.
    page.screenshot(path=str(OUT / "padiem-chat-product-still-v1.png"), full_page=False)

    visible_text = page.locator("body").inner_text()
    visible_email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", visible_text, re.I)
    if visible_email:
        raise RuntimeError(f"Privacy guard found an unexpected visible email: {visible_email.group(0)}")

    evidence = {
        "target": TARGET,
        "final_url": page.url,
        "title": page.title(),
        "viewport": {"width": 1440, "height": 900},
        "tier_text": tier_text,
        "composer_visible": composer.is_visible(),
        "settings_proven_visible": True,
        "prompt_submitted": False,
        "login_performed": False,
        "file_picker_opened": False,
        "claw_opened": False,
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
        raise RuntimeError("Playwright did not create a capture video")
    video.save_as(str(OUT / "padiem-chat-product-film-v1.webm"))
    browser.close()
