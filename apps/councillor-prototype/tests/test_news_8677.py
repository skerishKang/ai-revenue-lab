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
    assert all(2 <= len(n["changes"]) <= 4 for n in news)
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
