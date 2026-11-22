"""#8241: responsive news cards and scroll behavior, with isolated fixture data."""
from __future__ import annotations

import re

import pytest
from _support.chat_news_browser import THEMES, WIDTHS, open_news

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(ignore_default_args=["--hide-scrollbars"])
        yield browser
        browser.close()


def luminance(rgb):
    channels = [c / 255 for c in rgb]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def scrollbar_contrast(value):
    thumb, track = [list(map(float, re.findall(r"[\d.]+", color)))
                    for color in re.findall(r"rgba?\([^)]+\)", value)]
    assert len(track) == 3 or track[3] == 1
    alpha = thumb[3] if len(thumb) == 4 else 1
    thumb_rgb = [a * alpha + b * (1 - alpha) for a, b in zip(thumb, track)]
    a, b = sorted((luminance(thumb_rgb), luminance(track[:3])))
    return (b + 0.05) / (a + 0.05)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", WIDTHS)
def test_news_dialog_cards_and_body_scroll(browser, theme, width):
    page = open_news(browser, theme, width)
    try:
        dialog = page.locator("#newsDialog")
        body = page.locator("#newsBody")
        header = dialog.locator(".news-panel > .news-header")
        close = page.locator("#newsClose")
        metrics = body.evaluate("""body => ({
          overflow: getComputedStyle(body).overflowY,
          scrollbar: getComputedStyle(body).scrollbarColor,
          gutter: body.offsetWidth - body.clientWidth,
          scrollHeight: body.scrollHeight, clientHeight: body.clientHeight,
          scrollWidth: body.scrollWidth, clientWidth: body.clientWidth
        })""")
        assert metrics["overflow"] == "scroll"
        assert metrics["scrollHeight"] > metrics["clientHeight"]
        assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1
        assert metrics["gutter"] >= 8
        assert scrollbar_contrast(metrics["scrollbar"]) >= 3
        assert header.evaluate("el => getComputedStyle(el).position") == "sticky"
        assert dialog.evaluate("el => getComputedStyle(el).overflowY") == "hidden"
        assert dialog.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        cards = page.locator("#newsList > li")
        assert cards.count() == 4
        assert cards.locator("h3").all_text_contents() == [
            "Version 2026.11.16", "Version 2026.11.12", "Other news", "Other news"]
        assert cards.locator("time").evaluate_all("els => els.map(el => el.dateTime)") == [
            "2026-11-16", "2026-11-12", "2026-11-15", "2026-11-13"]
        assert cards.first.locator("h4").count() == 2
        assert cards.first.locator("ul").evaluate_all(
            "els => els.map(el => [...el.children].map(li => li.dataset.newsNumber))"
        ) == [["9"], ["8", "7"]]
        assert page.locator("#newsList .news-source").count() == 4
        for number in (9, 8, 7, 4):
            assert page.locator(f'[data-news-number="{number}"] .news-source').count() == 1
        for number in (6, 5, 3):
            assert page.locator(f'[data-news-number="{number}"] .news-source').count() == 0
        before_header, before_close = header.bounding_box(), close.bounding_box()
        assert before_close["height"] >= 44 and before_close["width"] >= 44
        assert 0 <= before_close["x"] < width - before_close["width"] + 1
        body.evaluate("el => el.scrollTop = el.scrollHeight")
        assert body.evaluate("el => el.scrollTop") > 0
        assert header.bounding_box() == before_header
        assert close.bounding_box() == before_close
        close.click()
        assert not dialog.is_visible()
        page.evaluate("() => window.PadiemNews.open(3)")
        target = page.locator('[data-news-number="3"][data-active="true"]')
        target.wait_for()
        page.wait_for_function("""() => {
          const el = document.querySelector('[data-news-number="3"][data-active="true"]');
          if (!el || !el.isConnected) return false;
          const body = el.closest('#newsBody').getBoundingClientRect();
          const row = el.getBoundingClientRect();
          return row.top >= body.top - 1 && row.bottom <= body.bottom + 1;
        }""")
    finally:
        page.close()

