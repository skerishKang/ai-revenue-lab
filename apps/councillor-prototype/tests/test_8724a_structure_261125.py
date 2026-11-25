# -*- coding: utf-8 -*-
"""#8724 step 1·2 — one renderer, one shared shell.

The source pages hold only their body; scripts/assemble.py puts the partials back.
app.js may attach behavior to existing DOM but must not draw list/card markup.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assemble  # noqa: E402

PAGES = ["index.html", "about.html", "activity.html", "policy.html", "media.html", "news.html", "404.html"]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HOME_JS = (ROOT / "static" / "home.js").read_text(encoding="utf-8")
PRERENDER = (ROOT / "scripts" / "prerender.py").read_text(encoding="utf-8")


def test_app_js_does_not_draw_lists_or_cards():
    """Search/detail states may add a message row, but records come from prerender."""
    forbidden = (
        '<span class="item-date"', '<span class="bill-number"',
        '<div class="tile-kind"', '<article class="info-card"',
        '<a class="key-activity-card"', '<div class="news-date"',
        '<span class="link-title"', '<span class="item-more"',
    )
    hits = [token for token in forbidden if token in APP_JS]
    assert not hits, f"app.js still draws records: {hits}"


def test_every_page_uses_the_same_partials():
    for page in PAGES:
        html = assemble.render(page)
        assert html.startswith('<!doctype html>\n<html lang="ko" data-theme="light">\n<head>'), page
        for marker in ('<header class="topbar">', '<footer class="site-footer">',
                       '<nav class="mobile-tabbar"', 'class="skip-link"'):
            assert html.count(marker) == 1, f"{page}: {marker} count drifted"
        body = (ROOT / page).read_text(encoding="utf-8")
        assert "<head>" not in body and "<header" not in body, f"{page} is not body-only"
        assert "<footer" not in body and "mobile-tabbar" not in body, f"{page} is not body-only"


def test_prerender_is_the_only_list_drawer():
    for token in ("prerender_home", "prerender_activity", "prerender_policy",
                  "prerender_media", "prerender_media_more", "prerender_news"):
        assert token in PRERENDER, token
    for token in ("activity-item", "bill-row", "media-tile", "info-card",
                  "key-activity-card", "site-change"):
        assert token in PRERENDER, token
    assert 'label: "정책자료"' not in HOME_JS and "renderKeyActivities" not in HOME_JS
