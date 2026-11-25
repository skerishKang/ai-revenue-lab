"""Activity build contracts that run without browser or image dependencies."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))["activity"]["items"]
SPEC = importlib.util.spec_from_file_location("prerender", ROOT / "scripts" / "prerender.py")
prerender = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prerender)


def test_dist_activity_contains_every_record_and_stable_id(tmp_path):
    out = tmp_path / "dist"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build-dist"), "--out", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    html = (out / "activity.html").read_text(encoding="utf-8")
    rows = re.findall(r'<li class="activity-item" id="([^"]+)">(.*?)</li>', html, re.S)
    ids = [activity_id for activity_id, _ in rows]
    assert ids == [item["id"] for item in ITEMS]
    assert len(ids) == len(set(ids))
    for item, (_, row) in zip(ITEMS, rows):
        for field in ("date", "tag", "title"):
            assert escape(item.get(field, ""), quote=True) in row
        paragraphs = [part for part in item.get("body", "").split("\n\n") if part]
        for paragraph in paragraphs:
            assert escape(paragraph, quote=True) in row
        body_match = re.search(r'<div class="detail-body">(.*?)</div>', row, re.S)
        if paragraphs:
            assert body_match is not None
            assert body_match.group(1).count("<p>") == len(paragraphs)
        else:
            assert body_match is None
        sentences = re.split(r"(?<=[.!?])\s+", item.get("body", "").strip()) if paragraphs else []
        if len(sentences) >= 3:
            assert len(paragraphs) >= 2, item["id"]
        assert '<noscript>' in row


def test_activity_prerender_only_links_allowed_sources():
    for url in ("https://example.com", "http://example.com", "./about", "mailto:test@example.com", "#", "javascript:alert(1)", "//example.com"):
        item = dict(ITEMS[0], url=url, title="<unsafe>")
        markup = prerender.prerender_activity({"activity": {"items": [item]}})
        assert "&lt;unsafe&gt;" in markup
        assert ("href=" in markup) == url.startswith(("https://", "http://", "./"))


def test_activity_glossary_covers_all_categories_and_prerenders():
    data = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
    glossary = data["activity"]["glossary"]
    assert set(glossary["categories"]) == {a["tag"] for a in ITEMS}
    legend = prerender.activity_legend(data)
    assert legend.count("<span>") == 7
    for term, meaning in glossary["categories"].items():
        assert escape(term) in legend and escape(meaning) in legend
    terms = prerender.activity_terms(data, ITEMS[0])
    assert escape(glossary["terms"]["행정사무감사"]) in terms


def test_home_search_and_shared_photo_dialog_contract():
    sys.path.insert(0, str(ROOT / "scripts"))
    import assemble
    home = assemble.render("index.html")
    media = assemble.render("media.html")
    form = re.search(r'<form class="home-search".*?</form>', home, re.S).group()
    assert form.count("<button") == 1 and 'name="scope" value="all"' in form
    assert 'id="mediaLightbox"' in home and 'id="mediaLightbox"' in media
    data = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))
    for html, count in ((prerender.prerender_home(data)["homeMedia"], 3),
                        (prerender.prerender_media(data), sum(bool(m.get("thumb")) for m in data["media"]["tiles"]))):
        assert html.count("data-media-thumb=") == count
        assert html.count('class="media-source"') == count
