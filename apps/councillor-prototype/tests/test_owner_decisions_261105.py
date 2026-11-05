# -*- coding: utf-8 -*-
"""대표 결정 11-05 — 새 의정활동 3건, 이메일 공개, 항목 수 띠 삭제, 정책자료·미디어 정리.

되살아나면 안 되는 것: 첫 화면의 "이 페이지에 정리한 자료" 띠와 그 숫자, 옛 의회
민원 링크(council.gwangju.go.kr/index.do?PID=133), 확인 날짜 2026-11-01.

남아야 하는 것: 의회 공식 명단의 이메일, 보도자료로 확인한 의정활동 3건, 출처가
있는 정책자료, 빈 타일 없는 미디어 갤러리, 소개 영상, 깨끗한 주소.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PAGES = ["index.html", "about.html", "activity.html", "policy.html", "media.html", "404.html"]
DATA = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))

REMOVED_PHRASES = ("이 페이지에 정리한 자료", "성과나 평가 지표가 아닙니다")


def page(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_the_material_count_band_is_gone_and_guarded() -> None:
    for name in PAGES:
        html = page(name)
        for phrase in REMOVED_PHRASES:
            assert phrase not in html, f"{name} still carries {phrase!r}"
    index = page("index.html")
    assert 'id="statList"' not in index and 'class="stat-band"' not in index
    home_js = (ROOT / "static" / "home.js").read_text(encoding="utf-8")
    assert "renderStats" not in home_js and "statList" not in home_js
    if DIST.is_dir():
        for name in PAGES:
            text = (DIST / name).read_text(encoding="utf-8")
            for phrase in REMOVED_PHRASES:
                assert phrase not in text, f"dist/{name} still carries {phrase!r}"


def test_every_checked_date_is_2026_11_05() -> None:
    for name in PAGES:
        html = page(name)
        assert "2026-11-01 확인" not in html, f"{name} still says 2026-11-01"
    assert "2026-11-01 확인" not in DATA["sourceNotice"]
    assert DATA["sourceNotice"].endswith("(2026-11-05 확인)")
    for name in ("index.html", "about.html", "activity.html", "policy.html", "media.html"):
        assert "2026-11-05 확인" in page(name), f"{name} has no verification date"
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.count("<lastmod>2026-11-05</lastmod>") == 5


def test_the_office_email_is_published_on_the_first_screen_and_profile() -> None:
    email = DATA["contact"]["email"]
    assert email == "miran2640@naver.com"
    index = page("index.html")
    actions = re.search(r'<div class="hero-actions">(.*?)</div>', index, re.S).group(1)
    assert f'href="mailto:{email}"' in actions
    about = page("about.html")
    assert f'href="mailto:{email}"' in about
    assert "data-contact-email" in about
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "data.contact" in app_js and "mailto:" in app_js


def test_the_new_council_opinion_page_replaced_the_old_minwon_link() -> None:
    index = page("index.html")
    assert "council.gwangju.go.kr/index.do?PID=133" not in index
    assert "https://council.jeonnam-gwangju.go.kr/jngjassem/board/16" in index
    actions = re.search(r'<div class="hero-actions">(.*?)</div>', index, re.S).group(1)
    assert "광주시의회 민원" not in actions


def test_the_three_new_activity_records_are_grounded_in_press_releases() -> None:
    items = DATA["activity"]["items"]
    by_date = {item["date"]: item for item in items}
    expected = {
        "2026-10-29": ("토론회", "https://council.jeonnam-gwangju.go.kr/jngjassem/board/7/1/read/2115"),
        "2026-11-02": ("토론회", "https://council.jeonnam-gwangju.go.kr/jngjassem/board/7/1/read/2134"),
        "2026-11-04": ("위원회", "https://council.jeonnam-gwangju.go.kr/jngjassem/board/7/1/read/2258"),
    }
    for date, (tag, url) in expected.items():
        item = by_date.get(date)
        assert item, f"missing activity for {date}"
        assert item["tag"] == tag and item["url"] == url
        assert item["featured"] is True
        assert item.get("body", "").strip(), f"{date} has no summary"
        assert re.search(r"\(2026-11-0[25] 게시\)", item["source"]), item["source"]
    dates = [item["date"] for item in items]
    assert dates == sorted(dates, reverse=True)


def test_policy_material_has_a_source_link_for_every_card() -> None:
    policy = DATA["policy"]
    assert len(policy["forums"]) == 3
    assert len(policy["videos"]) == 4
    for group in ("forums", "videos", "bills"):
        for item in policy[group]:
            assert item["title"].strip()
            assert item["url"].startswith("https://"), item["url"]
            assert item.get("summary", "").strip(), item["title"]
    videos = policy["videos"]
    assert sum("제9대 광주광역시의회" in (item.get("note") or "") for item in videos) == 3
    assert "제9대 광주광역시의회" not in (videos[0].get("note") or "")


def test_the_gallery_has_no_empty_tile_and_the_rest_is_a_link_list() -> None:
    thumbs = [tile for tile in DATA["media"]["tiles"] if tile.get("thumb")]
    rest = [tile for tile in DATA["media"]["tiles"] if not tile.get("thumb")]
    assert len(thumbs) == 13, f"expected 9 photos + 4 video stills, got {len(thumbs)}"
    assert len(rest) == 5, f"expected the five link-only entries, got {len(rest)}"
    for tile in thumbs:
        assert tile["thumb"].startswith("./static/images/")
        assert (ROOT / tile["thumb"][2:]).is_file(), tile["thumb"]
    stills = [tile for tile in thumbs if "youtube.com" in tile["url"]]
    assert len(stills) == 4 and all(tile["thumb"].endswith(".webp") for tile in stills)
    media = page("media.html")
    assert 'id="mediaMore"' in media
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "MEDIA.filter((m) => m.thumb)" in app_js
    assert "renderMediaMore" in app_js


def test_the_introduction_video_reaches_a_screen_without_autoplay() -> None:
    feature = DATA["feature"]
    assert feature["sources"] and feature["sources"][0].endswith("introduction-2025.mp4")
    about = page("about.html")
    assert 'id="introVideo"' in about
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "renderIntroVideo" in app_js
    assert 'controls preload="metadata"' in app_js
    assert "autoplay" not in app_js.lower()
    assert DATA["hero"]["poster"] in app_js or "data.hero.poster" in app_js
    assert "영상: 의원실 제공 자료" in DATA["hero"]["credit"]


def test_old_council_records_say_which_council_they_came_from() -> None:
    old = "https://council.gwangju.go.kr"
    for item in DATA["activity"]["items"]:
        if item["url"].startswith(old):
            assert "제9대 광주광역시의회" in (item.get("source") or ""), item["title"]
    for tile in DATA["media"]["tiles"]:
        if tile["url"].startswith(old):
            notes = " ".join(tile.get("notes") or [])
            assert "제9대 광주광역시의회" in notes, tile["title"]


def test_the_link_check_runs_weekly_and_not_on_pull_requests() -> None:
    workflow = (ROOT.parents[1] / ".github/workflows/padiem-councillor-prototype-ci.yml").read_text(encoding="utf-8")
    assert "0 0 * * 1" in workflow, "the weekly link check lost its schedule"
    assert "external-links" in workflow and "scripts/check-links" in workflow
    job = workflow.split("external-links:", 1)[1]
    assert "github.event_name == 'schedule'" in job, "the link check must stay out of the PR lane"


def test_the_build_rewrites_internal_links_to_clean_urls() -> None:
    script = (ROOT / "scripts" / "build-dist").read_text(encoding="utf-8")
    assert 'CLEAN_LINKS' in script and '"about.html": "./about"' in script
    # The source keeps .html so a plain http.server preview still works.
    assert 'href="./about.html"' in page("about.html")
