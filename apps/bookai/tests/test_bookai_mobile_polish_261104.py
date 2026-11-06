"""Focused browser checks for B61 mobile touch targets and reader themes."""

from __future__ import annotations

import http.server
import os
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

PUBLIC = Path(__file__).resolve().parents[1] / "public"
CHROME = os.environ.get("B61_CHROME_PATH")


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, *_args):
        pass


@pytest.fixture
def base_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(value) / 255 for value in re.findall(r"\d+", color)[:3]]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _assert_minimum_target(locator, minimum: float = 44):
    box = locator.bounding_box()
    assert box is not None
    rounded = _rounded_target_box(box)
    assert rounded["width"] >= minimum, (locator, rounded)
    assert rounded["height"] >= minimum, (locator, rounded)
    return box


def _rounded_target_box(box):
    return {
        **box,
        "width": round(box["width"], 2),
        "height": round(box["height"], 2),
    }


def _touch_target_is_undersized(box, minimum: float = 44):
    rounded = _rounded_target_box(box)
    return rounded["width"] < minimum or rounded["height"] < minimum


def test_touch_target_rounding_accepts_subpixel_noise_and_rejects_43_5px():
    assert not _touch_target_is_undersized({"width": 43.99997, "height": 44.0})
    assert _touch_target_is_undersized({"width": 43.5, "height": 44.0})
    assert _touch_target_is_undersized({"width": 44.0, "height": 43.5})


def _wait_for_layout_stable(page, selector: str):
    page.evaluate(
        """async selector => {
          await document.fonts.ready;
          const root = document.querySelector("#library");
          const boxes = () => Array.from(document.querySelectorAll(selector)).map(element => {
            const rect = element.getBoundingClientRect();
            return [rect.x, rect.y, rect.width, rect.height];
          });
          const deadline = performance.now() + 10000;
          let previous = JSON.stringify(boxes());
          let stableFrames = 0;
          while (performance.now() < deadline) {
            const transitions = root.getAnimations({subtree: true}).filter(animation =>
              animation.playState === "running" &&
              animation.effect?.getComputedTiming().iterations !== Infinity
            );
            if (transitions.length) {
              await Promise.all(transitions.map(animation => animation.finished.catch(() => null)));
              previous = JSON.stringify(boxes());
              stableFrames = 0;
              continue;
            }
            await new Promise(requestAnimationFrame);
            const current = JSON.stringify(boxes());
            if (current === previous) {
              stableFrames += 1;
              if (stableFrames >= 2) return;
            } else {
              previous = current;
              stableFrames = 0;
            }
          }
          throw new Error(`Layout did not stabilize for ${selector}: ${JSON.stringify(boxes())}`);
        }""",
        selector,
    )


def _overlaps(boxes):
    overlaps = []
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            width = min(first["x"] + first["width"], second["x"] + second["width"]) - max(first["x"], second["x"])
            height = min(first["y"] + first["height"], second["y"] + second["height"]) - max(first["y"], second["y"])
            if width > 1 and height > 1:
                overlaps.append((first, second, width, height))
    return overlaps


def _visible_button_boxes(page, selector: str):
    return page.locator(selector).evaluate_all(
        """elements => elements.map(element => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {element, rect, style, visible: rect.width > 0 && rect.height > 0 &&
            style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight};
        }).filter(item => item.visible).map(item => ({
          selector: (() => {
            const parts = [];
            for (let node = item.element; node; node = node.parentElement) {
              const classes = Array.from(node.classList || []).map(value => "." + value).join("");
              parts.unshift(node.id ? "#" + node.id : node.tagName.toLowerCase() + classes);
              if (node.id) break;
            }
            return parts.join(" > ");
          })(),
          x: item.rect.x, y: item.rect.y, width: item.rect.width, height: item.rect.height
        }))"""
    )


def test_mobile_theme_touch_targets_and_dark_memory_contrast(base_url):
    if CHROME and not Path(CHROME).is_file():
        pytest.skip("Chrome executable is unavailable")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=CHROME) if CHROME else playwright.chromium.launch(headless=True)
        page_errors = []

        # Existing users with no explicit preference retain the original default.
        page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        page.add_init_script("""
window.__bookaiErrors=[];
window.addEventListener('error', e => {
  var where = e.filename || '';
  window.__bookaiErrors.push(e.message + ' @ ' + where + ':' + e.lineno + ':' + e.colno);
});
""")
        page.goto(base_url, wait_until="load")
        page.wait_for_function("() => window.__smReaderSettingsV1 && typeof window.__smReaderSettingsV1.get === 'function'")
        assert page.evaluate("window.__smReaderSettingsV1.get().theme") == "default"
        assert not page.locator("body").evaluate("element => element.classList.contains('smr-theme-light') || element.classList.contains('smr-theme-dark')")
        page_errors.extend(page.evaluate("window.__bookaiErrors || []"))
        page.close()

        for theme in ("light", "dark"):
            context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
            context.add_init_script(
                "localStorage.setItem('storymemory.readerSettings.v1', JSON.stringify({"
                "version:1,font:'noto-sans-kr',fontSize:'base',lineHeight:'relaxed',"
                f"theme:{theme!r},englishMode:'show',verseNumbers:true}}));"
            )
            context.add_init_script("""
window.__bookaiErrors=[];
window.addEventListener('error', e => {
  var where = e.filename || '';
  window.__bookaiErrors.push(e.message + ' @ ' + where + ':' + e.lineno + ':' + e.colno);
});
""")
            page = context.new_page()
            page.goto(base_url, wait_until="load")
            page.wait_for_function("() => window.__smReaderSettingsV1 && typeof window.__smReaderSettingsV1.get === 'function'")
            page_errors.extend(page.evaluate("window.__bookaiErrors || []"))
            assert page.locator("body").evaluate(f"element => element.classList.contains('smr-theme-{theme}')")
            _wait_for_layout_stable(page, "#library button")
            library_boxes = _visible_button_boxes(page, "#library button")
            undersized = [
                _rounded_target_box(box)
                for box in library_boxes
                if _touch_target_is_undersized(box)
            ]
            assert not undersized, f"Visible #library buttons below 44px after layout stabilized: {undersized}"
            assert not _overlaps(library_boxes)

            library = page.evaluate(
                """() => ({background:getComputedStyle(document.body).backgroundColor,
                  image:getComputedStyle(document.querySelector('#library')).backgroundImage})"""
            )
            if theme == "light":
                assert library["background"] == "rgb(238, 232, 223)"
                assert "rgb(244, 240, 233)" in library["image"]
            else:
                assert "rgb(24, 27, 37)" in library["image"]

            page.locator("#openBook").click()
            page.locator("#index.active").wait_for()
            entry_targets = _visible_button_boxes(
                page,
                "#index .back-btn, #index #resume, #index .testament-tab, #chapterDots button, "
                "#prevChapter, #openChapter, #nextChapter",
            )
            assert all(not _touch_target_is_undersized(box) for box in entry_targets)
            page.locator("#index .volume").filter(has_text="사도행전").click()
            page.wait_for_function("!document.querySelector('#index').classList.contains('volume-transitioning')")
            for _ in range(8):
                page.locator("#nextChapter").click()
            # Exercise real dot selection after the volume transition has reset
            # the chapter state: chapter 9 -> 10 by dot, then back to 9 by dot.
            page.locator("#chapterDots button").nth(6).click()
            page.locator("#chapterDots button").nth(4).click()
            page.wait_for_function("document.querySelector('#index .chapter-stack.on')?.dataset.chapter === '9'")
            page.wait_for_timeout(1300)  # let the existing book transition settle before measuring
            index_button_boxes = _visible_button_boxes(page, "#index button")
            assert all(not _touch_target_is_undersized(box) for box in index_button_boxes)

            for selector in ("#index .back-btn", "#index #resume", "#index .testament-tab"):
                for index in range(page.locator(selector).count()):
                    _assert_minimum_target(page.locator(selector).nth(index))

            dot_boxes = [_assert_minimum_target(page.locator("#chapterDots button").nth(index)) for index in range(page.locator("#chapterDots button").count())]
            assert not _overlaps(dot_boxes)
            for index in range(page.locator("#chapterTrack .chapter-stack").count()):
                stack = page.locator("#chapterTrack .chapter-stack").nth(index)
                box = stack.bounding_box()
                if box and box["x"] < 390 and box["x"] + box["width"] > 0 and box["y"] < 844 and box["y"] + box["height"] > 0:
                    assert not _touch_target_is_undersized(box), _rounded_target_box(box)
            nav_boxes = [_assert_minimum_target(page.locator(selector)) for selector in ("#prevChapter", "#openChapter", "#nextChapter")]
            assert not _overlaps(nav_boxes)

            index_surfaces = page.evaluate(
                """() => ({shell:getComputedStyle(document.querySelector('.index-shell')).backgroundColor,
                  hero:getComputedStyle(document.querySelector('.index-hero')).backgroundImage,
                  body:getComputedStyle(document.querySelector('.index-body')).backgroundColor})"""
            )
            if theme == "dark":
                assert index_surfaces["shell"] == "rgb(38, 33, 26)"
                assert "rgb(38, 33, 26)" in index_surfaces["hero"]
                assert index_surfaces["body"] == "rgb(33, 28, 22)"

            page.locator("#openChapter").click()
            page.locator("#reader.active").wait_for()
            page.locator("#mobileDock [data-mobile='memory']").click()
            page.wait_for_function("document.body.classList.contains('memory-open')")
            memory = page.locator(".memory-rail")
            memory_initial_boxes = _visible_button_boxes(page, ".memory-rail button")
            assert all(not _touch_target_is_undersized(box) for box in memory_initial_boxes)
            assert not _overlaps(memory_initial_boxes)
            _assert_minimum_target(memory.locator(".sheet-close"))
            _assert_minimum_target(memory.locator("#memorySearchClear"))
            for index in range(memory.locator(".memory-scope-toggle button").count()):
                _assert_minimum_target(memory.locator(".memory-scope-toggle button").nth(index))

            page.locator("#newFreeNote").scroll_into_view_if_needed()
            new_note_box = _assert_minimum_target(memory.locator("#newFreeNote"))
            page.locator("#newFreeNote").click()
            page.locator("#memoryNoteInput").fill("touch target check")
            page.locator("#saveMemoryNote").scroll_into_view_if_needed()
            save_box = _assert_minimum_target(memory.locator("#saveMemoryNote"))
            cancel_box = _assert_minimum_target(memory.locator("#cancelMemoryNote"))

            memory_button_boxes = _visible_button_boxes(page, ".memory-rail button")
            assert all(not _touch_target_is_undersized(box) for box in memory_button_boxes)
            assert not _overlaps(memory_button_boxes)
            assert _rounded_target_box(new_note_box)["width"] == 44.00
            assert _rounded_target_box(new_note_box)["height"] == 44.00
            assert not _touch_target_is_undersized(save_box)
            assert _rounded_target_box(cancel_box)["width"] == 44.00
            assert _rounded_target_box(cancel_box)["height"] == 44.00

            if theme == "dark":
                colors = page.evaluate(
                    """() => {
                      const rail = document.querySelector('.memory-rail');
                      const title = rail.querySelector('.side-head strong');
                      const close = rail.querySelector('.sheet-close');
                      return {background:getComputedStyle(rail).backgroundColor,
                        title:getComputedStyle(title).color,close:getComputedStyle(close).color};
                    }"""
                )
                assert _contrast(colors["title"], colors["background"]) >= 4.5
                assert _contrast(colors["close"], colors["background"]) >= 3

            assert not page_errors
            context.close()

        browser.close()
