import json
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("news_prerender", ROOT / "scripts/prerender.py")
prerender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prerender)
sys.path.insert(0, str(ROOT / "scripts"))
import assemble  # noqa: E402


def test_news_is_static_latest_first(tmp_path):
    data = json.loads((ROOT / "static/miraen.json").read_text(encoding="utf8"))
    news = data["news"]
    assert len(news) >= 5
    assert [n["date"] for n in news] == sorted((n["date"] for n in news), reverse=True)
    # #8968: 승인된 11-28 소식 한 줄만 늘고, 이전 소식 길이 계약은 유지한다.
    assert len(news[0]["changes"]) == 5
    assert all(2 <= len(n["changes"]) <= 4 for n in news[1:])
    path = tmp_path / "news.html"
    path.write_text(assemble.render("news.html"), encoding="utf8")
    prerender.inject(tmp_path, data)
    html = path.read_text(encoding="utf8")
    assert html.count('class="info-card site-change"') == len(news)
    assert all(n["title"] in html for n in news)
    assert all(word not in prerender.prerender_news(data) for word in ("AI 명예회원", "PR #", "#8673", "#8668"))
    assert html.count('aria-label="모바일 메뉴"') == 1


def test_the_change_list_is_not_the_home_news_mount():
    """app.js fills #newsList with activity news on every page; the change history
    must use its own mount or the script overwrites it."""
    html = assemble.render("news.html")
    assert 'id="newsList"' not in html and 'id="siteChangeList"' in html
    assert "siteChangeList" not in (ROOT / "static/app.js").read_text(encoding="utf8")


def test_approved_news_1128_is_first_with_exact_copy():
    data = json.loads((ROOT / "static/miraen.json").read_text(encoding="utf-8"))
    item = data["news"][0]
    assert item == {
        "date": "2026-11-28",
        "title": "더 읽기 편하게",
        "changes": [
            "어두운 화면에서 파란 글자와 조례안 검색칸 글자가 잘 보이도록 바꿨습니다.",
            "휴대폰에서 의정활동과 미디어를 한 줄에 하나씩 크게 볼 수 있습니다.",
            "의원 소개 사진과 소개 글을 나란히 놓아 한눈에 읽을 수 있습니다.",
            "낱말이 줄 끝에서 끊기지 않고, 오류·불편을 보낼 때 빠뜨린 곳을 바로 알려 드립니다.",
            "정책자료 조례안 말에 쉬운 풀이를 붙이고, '조례안 찾기'로 바로 검색할 수 있습니다.",
        ],
    }
    rendered = prerender.prerender_news(data)
    assert rendered.index("2026-11-28") < rendered.index("2026-11-25")


def test_news_eyebrow_is_approved_word_without_spacer():
    html = assemble.render("news.html")
    assert '<p class="section-eyebrow">알림</p>' in html
    assert "news-eyebrow-spacer" not in html
    assert 'aria-hidden="true">알림' not in html
