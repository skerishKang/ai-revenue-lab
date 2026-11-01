"""Launch contract for the councillor prototype (apps/councillor-prototype).

The file started as #6063's mobile-navigation contract: ``.top-nav`` is
``display:none`` from 900px down, so every page has to offer the page set
somewhere else. That still holds, and it is now a fixed bottom tab bar.

#6063 also accepted footer links as the only phone navigation. This launch pass
replaces that allowance: every page — including 404 — must carry the tab bar,
because a visitor who lands on one inner page has to be able to move without
scrolling to the footer first.

Everything here is static on purpose: no browser, no network, no provider. When
a rule lives in CSS the test reads the CSS; when a rule lives in rendered JS it
checks the single data source (``static/miraen.json``) and proves the scripts
copy nothing out of it. Deployment rules are checked against a real
``scripts/build-dist`` run into a temporary folder, not against a declaration.
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
# The deployment origin lives in one place; the source tree carries a token.
BASE_URL = json.loads((APP_ROOT / "site.config.json").read_text(encoding="utf-8"))["baseUrl"].rstrip("/")
PLACEHOLDER = "__BASE_URL__"
BUILD_SCRIPT = APP_ROOT / "scripts" / "build-dist"

PAGES = ["index.html", "about.html", "activity.html", "policy.html", "media.html"]
SITE_PAGES = PAGES + ["404.html"]
# The one menu order the whole site shares: header, footer and phone tab bar.
MENU = ["index.html", "about.html", "activity.html", "policy.html", "media.html"]
REQUIRED_HTML = tuple(SITE_PAGES)
ROOT_ASSETS = ("robots.txt", "sitemap.xml", "favicon.ico", "favicon-32.png", "favicon.svg", "apple-touch-icon.png")
TEXT_SUFFIXES = {".html", ".xml", ".txt", ".json", ".js", ".css", ".svg"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STYLES = (APP_ROOT / "static" / "styles.css").read_text(encoding="utf-8")
# Selector matching below is textual, so comments would glue onto the next selector.
CSS_RULES = re.sub(r"/\*.*?\*/", "", STYLES, flags=re.S)
APP_JS = (APP_ROOT / "static" / "app.js").read_text(encoding="utf-8")
HOME_JS = (APP_ROOT / "static" / "home.js").read_text(encoding="utf-8")
DATA = json.loads((APP_ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))


# ── helpers ────────────────────────────────────────────────────────────────
def page(name: str) -> str:
    return (APP_ROOT / name).read_text(encoding="utf-8")


def nav_targets(html: str, cls: str) -> list[str]:
    """hrefs of the <nav class="..."> block, reduced to the file name."""
    m = re.search(rf'<nav class="{cls}"[^>]*>(.*?)</nav>', html, flags=re.S)
    assert m, f"no <nav class={cls}> block"
    return [href.split("?")[0].lstrip("./") for href in re.findall(r'href="([^"]+)"', m.group(1))]


def meta_content(html: str, key: str, attr: str = "name") -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)"', html)
    return m.group(1) if m else None


def rules(css: str, selector: str) -> list[str]:
    """Every declaration block whose selector list contains ``selector`` verbatim."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sels = [s.strip() for s in m.group(1).split(",")]
        if selector in sels:
            out.append(m.group(2))
    return out


def media_blocks(css: str) -> list[tuple[str, str]]:
    """(condition, body) for every top-level @media block, braces balanced."""
    out = []
    for m in re.finditer(r"@media\s*\(([^)]*)\)\s*\{", css):
        depth, i = 1, m.end()
        while i < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append((m.group(1), css[m.end(): i - 1]))
    return out


def block_at(condition: str) -> str:
    hits = [body for cond, body in media_blocks(STYLES) if cond.replace(" ", "") == condition]
    assert hits, f"no @media ({condition}) block"
    # Two queries can share a breakpoint (the tab bar sits in its own 900px block).
    return "\n".join(hits)


def strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def image_size(path: Path) -> tuple[int, int]:
    """Width/height for PNG, JPEG or WebP without third-party packages."""
    head = path.read_bytes()[:64]
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
    if head[:2] == b"\xff\xd8":
        data = path.read_bytes()
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        raise AssertionError(f"no SOF marker in {path}")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        chunk = head[12:16]
        if chunk == b"VP8X":
            width = int.from_bytes(head[24:27], "little") + 1
            height = int.from_bytes(head[27:30], "little") + 1
            return width, height
        if chunk == b"VP8 ":
            width = int.from_bytes(head[26:28], "little") & 0x3FFF
            height = int.from_bytes(head[28:30], "little") & 0x3FFF
            return width, height
        if chunk == b"VP8L":
            bits = int.from_bytes(head[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise AssertionError(f"unrecognised image header in {path}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def news_items() -> list[dict]:
    """The news list is the featured subset of the one activity list."""
    return [item for item in DATA["activity"]["items"] if item.get("featured") is True]


def array_literals(js: str, name: str) -> list[str]:
    """Bodies of every array literal assigned to ``name`` (const/let/var)."""
    return [m.group(1) for m in re.finditer(rf"(?:const|let|var)\s+{name}\s*=\s*\[(.*?)\];", js, re.S)]


@pytest.fixture(scope="module")
def built_dist(tmp_path_factory) -> Path:
    """Build the upload folder exactly as the README tells the deployer to."""
    out = tmp_path_factory.mktemp("build") / "dist"
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--out", str(out)],
        cwd=str(APP_ROOT), capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


# ── 1. navigation ──────────────────────────────────────────────────────────
def test_the_header_nav_is_hidden_on_phones():
    """The premise of the tab bar. If the breakpoint moves, revisit the rest."""
    hidden_at = [int(cond.split(":")[1].strip().rstrip("px"))
                 for cond, body in media_blocks(STYLES)
                 if "max-width" in cond and re.search(r"\.top-nav\s*\{[^}]*display:\s*none", body)]
    assert hidden_at, "no media query hides .top-nav any more — re-check this contract"
    assert max(hidden_at) >= 760, f".top-nav only hidden below {max(hidden_at)}px"


def test_every_page_carries_the_phone_tab_bar():
    """Supersedes the old allowance of footer-only navigation on phones."""
    for name in SITE_PAGES:
        html = page(name)
        assert 'class="mobile-tabbar"' in html, f"{name} has no phone tab bar"
        assert nav_targets(html, "mobile-tabbar") == MENU, f"{name} tab bar order drifted"


def test_the_tab_bar_is_a_fixed_bar_below_the_header_breakpoint():
    base = rules(CSS_RULES, ".mobile-tabbar")
    assert base and "display: none" in base[0], "the tab bar must be off above the breakpoint"
    block = block_at("max-width:900px")
    assert re.search(r"\.mobile-tabbar\s*\{[^}]*position:\s*fixed", block), "the phone menu must stay on screen"
    assert re.search(r"\.mobile-tabbar\s*\{[^}]*grid-template-columns:\s*repeat\(5", block), "one tab per page"
    assert re.search(r"\.mobile-tabbar a\s*\{[^}]*min-height:\s*var\(--tap\)", block), "tabs must be 44px tall"
    assert re.search(r"body\s*\{[^}]*padding-bottom", block), "the fixed bar needs room under the footer"


def test_the_header_name_links_home_on_every_page():
    for name in SITE_PAGES:
        html = page(name)
        m = re.search(r'<a class="brand" href="([^"]+)"', html)
        assert m, f"{name}: the brand block is not a link"
        assert m.group(1).lstrip("./") == "index.html", f"{name}: brand links {m.group(1)}"


def test_every_page_uses_one_menu_order():
    for name in SITE_PAGES:
        html = page(name)
        assert nav_targets(html, "top-nav") == MENU, f"{name}: header order drifted"
        footer = nav_targets(html, "footer-nav")
        assert footer[:5] == MENU, f"{name}: footer order drifted"
    # Active states are per page, the targets are not.
    for name in PAGES:
        html = page(name)
        for nav_cls in ("top-nav", "mobile-tabbar"):
            block = re.search(rf'<nav class="{nav_cls}"[^>]*>(.*?)</nav>', html, re.S).group(1)
            active = re.findall(r'<a href="([^"]+)" class="active"', block)
            assert active == [f"./{name}"], f"{name}: {nav_cls} marks {active} active"


# ── 2. the prototype disclaimer is gone ────────────────────────────────────
def test_no_page_calls_itself_a_prototype_site():
    banned = ["시제품이며", "공식 웹사이트가 아닙니다", "시제품"]
    for name in SITE_PAGES:
        html = page(name)
        for phrase in banned:
            assert phrase not in html, f"{name} still says {phrase!r}"
    for asset in (APP_ROOT / "static" / "app.js", APP_ROOT / "static" / "home.js",
                  APP_ROOT / "static" / "miraen.json"):
        assert "시제품" not in asset.read_text(encoding="utf-8"), f"{asset.name} still carries the disclaimer"
    assert "prototypeNotice" not in DATA, "miraen.json still declares a prototype notice"
    assert DATA.get("notes") == [], "miraen.json still lists notice items"


# ── 3. first-screen contact ────────────────────────────────────────────────
def test_the_first_screen_offers_a_call_and_the_council_minwon_page():
    html = page("index.html")
    actions = re.search(r'<div class="hero-actions">(.*?)</div>', html, re.S).group(1)
    call = re.search(r'<a class="btn primary" href="tel:([0-9-]+)"', actions)
    assert call, "the hero has no immediate-call button"
    assert call.group(1) == DATA["profile"][-1]["value"], "the number must be the office number in miraen.json"
    assert "062-613-5133" in call.group(0), "the number must be visible on the button"
    minwon = re.search(r'href="(https://council\.gwangju\.go\.kr/[^"]+)"[^>]*target="_blank" rel="noopener"', actions)
    assert minwon, "the hero has no council 민원 link"
    assert "PID=133" in minwon.group(1), "민원 means 의회에바란다 (PID=133), not the photo board"


def test_the_office_number_is_dialable_from_the_profile():
    html = page("about.html")
    assert '<a href="tel:062-613-5133">062-613-5133</a>' in html


# ── 4. metadata, robots, sitemap, 404 ──────────────────────────────────────
def test_every_page_declares_lang_description_canonical_og_and_icons():
    for name in SITE_PAGES:
        html = page(name)
        assert '<html lang="ko"' in html, f"{name}: lang is not ko"
        assert meta_content(html, "description"), f"{name}: no description"
        assert meta_content(html, "og:title", "property"), f"{name}: no og:title"
        assert meta_content(html, "og:description", "property"), f"{name}: no og:description"
        assert meta_content(html, "og:image", "property"), f"{name}: no og:image"
        assert meta_content(html, "og:image:width", "property") == "1200", name
        assert meta_content(html, "og:image:height", "property") == "630", name
        assert meta_content(html, "twitter:card") == "summary_large_image", name
        assert 'rel="icon"' in html and 'rel="apple-touch-icon"' in html, f"{name}: no favicons"
        if name != "404.html":
            assert meta_content(html, "robots") is None or "noindex" not in meta_content(html, "robots")
            canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html)
            assert canonical, f"{name}: no canonical"
            expected = PLACEHOLDER + "/" if name == "index.html" else f"{PLACEHOLDER}/{name}"
            assert canonical.group(1) == expected, f"{name}: canonical {canonical.group(1)} != {expected}"


def test_the_social_card_shows_a_face_and_a_name_at_1200x630():
    card = APP_ROOT / "static" / "images" / "og-card.jpg"
    assert card.exists(), "og-card.jpg is missing"
    assert image_size(card) == (1200, 630), f"og card is {image_size(card)}"
    for name in PAGES:
        html = page(name)
        assert meta_content(html, "og:image", "property") == f"{PLACEHOLDER}/static/images/og-card.jpg"
        assert meta_content(html, "og:image:alt", "property"), f"{name}: og:image needs alt text"
    assert card.stat().st_size < 150_000, "the social card should not be a 5MB upload"


def test_robots_and_sitemap_agree_with_the_pages():
    robots = (APP_ROOT / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots and "Allow: /" in robots
    assert f"Sitemap: {PLACEHOLDER}/sitemap.xml" in robots
    sitemap = (APP_ROOT / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    assert locs == [PLACEHOLDER + "/"] + [f"{PLACEHOLDER}/{name}" for name in PAGES if name != "index.html"], locs
    assert "404.html" not in sitemap, "a 404 page must not be indexed"
    assert sitemap.count("<lastmod>2026-11-01</lastmod>") == len(locs)


def test_the_deployment_origin_lives_only_in_site_config():
    """A dedicated domain later must be a one-line change, not a 20-file sweep."""
    for name in SITE_PAGES + ["robots.txt", "sitemap.xml"]:
        text = read_text(APP_ROOT / name)
        assert BASE_URL not in text, f"{name} hard-codes the deployment origin"
        assert PLACEHOLDER in text, f"{name} carries no base-URL token"
    for name in ("app.js", "home.js", "miraen.json"):
        assert BASE_URL not in read_text(APP_ROOT / "static" / name), f"{name} hard-codes the deployment origin"


def test_the_404_page_is_noindex_and_leads_home():
    html = page("404.html")
    assert meta_content(html, "robots") == "noindex"
    assert 'rel="canonical"' not in html, "an error page has no canonical URL"
    assert 'href="./index.html"' in html and 'href="./activity.html"' in html
    assert "페이지를 찾을 수 없습니다" in html


# ── 5. Korean labels and the type/tap floor ────────────────────────────────
def test_no_english_section_titles_remain():
    for name in SITE_PAGES:
        html = page(name)
        for cls in ("hero-eyebrow", "section-eyebrow"):
            for text in re.findall(rf'<p class="{cls}">(.*?)</p>', html, re.S):
                assert re.search(r"[가-힣]", text), f"{name}: {cls} {text!r} is not Korean"
        for banned in (">ABOUT<", ">POLICY<", ">ACTIVITY<", ">MEDIA<", ">RECENT ACTIVITY<"):
            assert banned not in html, f"{name} still shows {banned}"


def test_type_floor_is_16_body_14_label():
    assert "--fs-body: 16px" in STYLES
    assert "--fs-label: 14px" in STYLES
    assert re.search(r"body\s*\{[^}]*font-size:\s*var\(--fs-body\)", STYLES), "body copy must use the floor"
    too_small = [float(size) for size in re.findall(r"font-size:\s*([0-9.]+)px", STYLES) if float(size) < 14]
    assert not too_small, f"font sizes below 14px: {sorted(set(too_small))}"
    clamped = [float(m) for m in re.findall(r"font-size:\s*clamp\(\s*([0-9.]+)px", STYLES)]
    assert clamped and min(clamped) >= 14, f"a clamp starts below 14px: {clamped}"


def test_every_tappable_control_is_at_least_44px():
    assert "--tap: 44px" in STYLES
    controls = [".btn", ".brand", ".skip-link", ".top-nav a", ".ghost", ".top-cta", ".strip-link", ".section-more",
                ".col-item", ".col-tile", ".footer-nav a", ".mobile-tabbar a", ".card-link",
                ".back-btn", ".detail-link", ".profile-list dd a", ".activity-toolbar input", ".activity-toolbar select"]
    for selector in controls:
        bodies = rules(CSS_RULES, selector)
        assert bodies, f"{selector} has no rule"
        assert any("min-height: var(--tap)" in body for body in bodies), \
            f"{selector} is not pinned to the 44px tap target"


# ── 6. one content source ──────────────────────────────────────────────────
def test_the_screens_render_miraen_json_without_copying_its_content():
    """Content lives once. A pasted array in a script is the defect this blocks."""
    assert 'const DATA_URL = "./static/miraen.json";' in APP_JS
    assert "fetch(DATA_URL" in APP_JS
    assert "window.COUNCILLOR_DATA_READY = loadSiteData();" in APP_JS
    assert "window.COUNCILLOR_DATA_READY" in HOME_JS, "home.js must wait on the shared load"
    assert "fetch(" not in HOME_JS, "home.js must not load the data a second time"
    for name, js in (("app.js", APP_JS), ("home.js", HOME_JS)):
        for array in ("ACTIVITIES", "MEDIA", "NEWS"):
            for body in array_literals(js, array):
                assert not body.strip(), f"{name} copies content into {array}"
        assert re.search(r"NEWS\s*=\s*\w+\.filter\(.*?featured\s*===\s*true", js), \
            f"{name} must derive news from the featured activity items"
    assert re.search(r"renderNewsColumn\(NEWS\)", HOME_JS)
    assert re.search(r"renderStats\(activities,\s*mediaTiles,\s*NEWS\)", HOME_JS)


def test_activity_records_are_verified_sorted_and_uniquely_keyed():
    items = DATA["activity"]["items"]
    assert items, "miraen.json lists no activity"
    dates = [item["date"] for item in items]
    assert all(ISO_DATE.match(date) for date in dates), dates
    assert dates == sorted(dates, reverse=True), "records must be newest first"
    keys = [(item["date"], item["title"]) for item in items]
    assert len(keys) == len(set(keys)), "two records share a date and title"
    for item in items:
        assert item["tag"].strip(), item
        assert item["title"].strip(), item
        assert item["url"].startswith(("http://", "https://")), item["url"]
        if item.get("thumb"):
            assert item["thumb"].startswith("./static/images/"), item["thumb"]
            assert (APP_ROOT / item["thumb"][2:]).is_file(), item["thumb"]


def test_every_activity_tag_is_a_filter_option():
    filters = re.findall(r'<option value="([^"]+)"', page("activity.html"))
    tags = {item["tag"] for item in DATA["activity"]["items"]}
    assert tags <= set(filters), f"tags without a filter: {sorted(tags - set(filters))}"


def test_every_content_link_is_an_absolute_web_url():
    urls = [item["url"] for item in DATA["activity"]["items"]]
    urls += [tile["url"] for tile in DATA["media"]["tiles"]]
    urls += [channel["url"] for channel in DATA["sns"]["channels"]]
    for url in urls:
        assert re.fullmatch(r"https?://[^\s\"'<>]+", url), f"not an absolute web link: {url!r}"


def test_the_about_page_renders_the_same_bio_and_profile():
    html = page("about.html")
    bio = re.search(r'<div class="intro-bio">(.*?)</div>', html, re.S).group(1)
    paragraphs = [strip_tags(p) for p in re.findall(r"<p>(.*?)</p>", bio, re.S)]
    assert paragraphs == [strip_tags(p) for p in DATA["bio"].split("\n\n")]
    dl = re.search(r'<dl class="profile-list"[^>]*>(.*?)</dl>', html, re.S).group(1)
    pairs = [(strip_tags(label), strip_tags(value))
             for label, value in re.findall(r"<div><dt>(.*?)</dt><dd>(.*?)</dd></div>", dl, re.S)]
    assert pairs == [(row["label"], row["value"]) for row in DATA["profile"]]
    assert "(3인 선거구)" in html, "남구 제1선거구 must say it is a 3-seat district"
    assert "박사과정" in html, "the PhD course must be in the education line"


def test_news_is_the_featured_subset_with_a_date_title_summary_and_source():
    """News is not a second list: it is the featured records, so it cannot drift."""
    assert DATA["notes"] == [], "a notice list must stay empty; news is the featured activity list"
    news = news_items()
    assert news, "no featured record — the home news column would be empty"
    for item in news:
        assert ISO_DATE.match(item["date"]), item
        assert item["title"].strip(), item
        assert item.get("body", "").strip(), f"{item['title']} has no summary"
        assert item.get("source", "").strip(), f"{item['title']} has no source"
        assert item["url"].startswith(("http://", "https://")), item["url"]


def test_news_reaches_past_the_new_council_opening():
    news = news_items()
    assert news[0]["date"] >= "2026-07-01", "the newest news predates the 2026-07-01 opening"
    dates = [item["date"] for item in news]
    assert dates == sorted(dates, reverse=True), "the news column must start with the newest record"


# ── 7. policy links and the media gallery ──────────────────────────────────
def test_policy_cards_do_not_share_one_photo_board():
    html = page("policy.html")
    hrefs = re.findall(r'<a class="card-link" href="([^"]+)"', html)
    assert hrefs, "the policy page has no cards"
    assert len(hrefs) == len(set(hrefs)), f"two cards share a link: {hrefs}"
    for href in hrefs:
        assert "PID=014" not in href, "PID=014 is the photo gallery, not a policy page"
    for hidden in ("의정 보고서", "예산·결산"):
        assert hidden not in html, f"{hidden} has no correct page and must stay hidden"


def test_the_media_gallery_does_not_repeat_one_poster():
    posters = [tile["thumb"] for tile in DATA["media"]["tiles"] if tile.get("thumb")]
    assert len(posters) == len(set(posters)), "two tiles share a thumbnail"
    for thumb in posters:
        assert thumb.startswith("./static/images/"), f"{thumb} is not a local gallery image"
    assert not [t for t in posters if "poster" in t or "media.padiem.net" in t], \
        "the hero video poster must not be reused as a tile image"
    media_html = page("media.html")
    assert media_html.count('poster="https://media.padiem.net/') == 1, "one hero video, one poster"
    for name in SITE_PAGES:
        assert "첫 화면 영상" not in page(name), f"{name} still says 첫 화면 영상"


def test_the_phone_gallery_is_two_columns():
    block = block_at("max-width:760px")
    assert re.search(r"\.media-grid\s*\{[^}]*grid-template-columns:\s*1fr\s+1fr", block), \
        "phones must see a 2-column gallery"
    narrow = block_at("max-width:420px")
    assert ".media-grid" not in narrow, "no rule may collapse the gallery back to one column"


# ── 8. weight ──────────────────────────────────────────────────────────────
def test_hero_and_portrait_are_webp_with_a_smaller_phone_copy():
    images = APP_ROOT / "static" / "images"
    hero, hero_phone = images / "hero-panorama.webp", images / "hero-panorama-mobile.webp"
    portrait, portrait_phone = images / "profile-portrait.webp", images / "profile-portrait-390.webp"
    for path in (hero, hero_phone, portrait, portrait_phone):
        assert path.exists(), f"{path.name} is missing"
    assert image_size(hero)[0] > image_size(hero_phone)[0], "the phone panorama must be smaller"
    assert hero_phone.stat().st_size < hero.stat().st_size
    assert portrait_phone.stat().st_size < portrait.stat().st_size
    assert not (images / "hero-panorama.jpg").exists(), "the JPG panorama was replaced, not kept"
    assert not (images / "profile-portrait.png").exists(), "the PNG portrait was replaced, not kept"
    assert '--hero-image: url("./images/hero-panorama.webp")' in STYLES
    assert '--hero-image: url("./images/hero-panorama-mobile.webp")' in block_at("max-width:760px")
    html = page("index.html")
    assert "profile-portrait.webp" in html and "profile-portrait-390.webp" in html
    assert "srcset=" in html and "sizes=" in html, "the portrait needs responsive sources"


def test_the_serif_face_ships_only_the_glyphs_in_use():
    font = APP_ROOT / "static" / "fonts" / "maruburi" / "MaruBuri-Bold.woff2"
    assert font.exists()
    assert font.stat().st_size < 60_000, f"{font.stat().st_size} bytes means the full face is back"
    css = (APP_ROOT / "static" / "fonts" / "maruburi.css").read_text(encoding="utf-8")
    assert "subset" in css.lower(), "record that the shipped file is a subset"


def test_the_dist_build_contains_only_site_assets(built_dist):
    """`.assetsignore` never worked on Pages; the build folder is the contract now."""
    files = {path.relative_to(built_dist).as_posix() for path in built_dist.rglob("*") if path.is_file()}
    assert set(REQUIRED_HTML) <= files, set(REQUIRED_HTML) - files
    assert set(ROOT_ASSETS) <= files, set(ROOT_ASSETS) - files
    assert "static/miraen.json" in files, "the data source must ship"
    for name in files:
        assert not name.startswith(("docs/", "tests/", "scripts/")), f"{name} is not a site asset"
        assert name not in {"README.md", "site.config.json", ".gitignore", ".assetsignore"}, name
        assert not name.endswith((".md", ".py")), f"{name} is documentation or tooling"
        assert "__pycache__" not in name, name
    top = {name.split("/")[0] for name in files}
    assert top == set(REQUIRED_HTML) | set(ROOT_ASSETS) | {"static"}, f"unexpected top-level entry: {top}"


def test_the_dist_build_resolves_the_configured_base_url(built_dist):
    for path in built_dist.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            assert PLACEHOLDER not in read_text(path), f"token left in {path.name}"
    for name in SITE_PAGES:
        html = read_text(built_dist / name)
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        if name != "404.html":
            expected = BASE_URL + "/" if name == "index.html" else f"{BASE_URL}/{name}"
            assert canonical and canonical.group(1) == expected, f"{name}: canonical not built"
        assert meta_content(html, "og:image", "property") == f"{BASE_URL}/static/images/og-card.jpg", name
    robots = read_text(built_dist / "robots.txt")
    assert f"Sitemap: {BASE_URL}/sitemap.xml" in robots
    locs = re.findall(r"<loc>([^<]+)</loc>", read_text(built_dist / "sitemap.xml"))
    assert locs == [BASE_URL + "/"] + [f"{BASE_URL}/{name}" for name in PAGES if name != "index.html"], locs
    assert (built_dist / "static" / "miraen.json").is_file()


def test_every_local_asset_reference_resolves():
    refs: set[str] = set()
    for name in SITE_PAGES:
        html = page(name)
        refs.update(re.findall(r'(?:src|href)="(\./[^"]+\.(?:png|jpe?g|webp|svg|ico|css|js))"', html))
        for srcset in re.findall(r'srcset="([^"]+)"', html):
            refs.update(candidate.strip().split(" ")[0] for candidate in srcset.split(","))
    refs.update(re.findall(r'url\("(\./images/[^"]+)"\)', STYLES))
    refs.update(item["thumb"] for item in DATA["activity"]["items"] if item.get("thumb"))
    refs.update(tile["thumb"] for tile in DATA["media"]["tiles"] if tile.get("thumb"))
    for ref in sorted(refs):
        target = (APP_ROOT / "static" / ref[2:]) if ref.startswith("./images/") else (APP_ROOT / ref[2:])
        assert target.exists(), f"{ref} is referenced but not shipped"


# ── 9. footer, theme, motion ───────────────────────────────────────────────
def test_the_footer_links_the_office_login_tool():
    for name in SITE_PAGES:
        html = page(name)
        m = re.search(r'<a class="footer-login" href="([^"]+)"[^>]*>(.*?)</a>', html)
        assert m, f"{name}: no office login link"
        assert m.group(1) == "https://chat.padiem.net/apps/council/"
        assert "의원실 로그인" in m.group(2)
        assert 'target="_blank"' in m.group(0) and 'rel="noopener"' in m.group(0)


def test_theme_is_applied_before_paint_and_storage_is_guarded():
    for name in SITE_PAGES:
        html = page(name)
        head = html.split("</head>")[0]
        script = re.search(r"<script>(.*?)</script>", head, re.S)
        assert script, f"{name}: no inline theme script"
        body = script.group(1)
        assert "localStorage.getItem" in body, f"{name}: the saved theme is never read"
        assert re.search(r"try\s*\{[^}]*localStorage", body, re.S), f"{name}: storage read is unguarded"
        assert 'data-theme="light"' in html, f"{name}: no default theme attribute"
    assert re.search(r"try\s*\{[^}]*localStorage\.setItem[^}]*\}\s*catch", APP_JS, re.S), \
        "app.js must guard the theme write"


def test_reduced_motion_turns_off_smooth_scrolling_and_transitions():
    assert "prefers-reduced-motion" in APP_JS
    assert re.search(r'behavior:\s*prefersReducedMotion\(\)\s*\?\s*"auto"\s*:\s*"smooth"', APP_JS)
    assert "scrollIntoView" in APP_JS
    reduced = block_at("prefers-reduced-motion:reduce")
    assert "transition: none" in reduced and "animation: none" in reduced


# ── 10. the measured-not-broken portrait state from #6063 ──────────────────
def test_the_hero_portrait_is_styled_to_avoid_cropping_on_phones():
    block = block_at("max-width:760px")
    rule = re.search(r"\.hero-portrait\s*\{(.*?)\}", block, re.S)
    assert rule, "no .hero-portrait rule inside the phone media query any more"
    assert "object-fit: contain" in rule.group(1), "the phone portrait must not crop the cut-out"
    assert "max-width" in rule.group(1), "the phone portrait needs a width cap to stay inside the gutter"
