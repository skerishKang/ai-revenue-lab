from pathlib import Path

from scripts import build_static_production


def test_production_review_keeps_guide_and_hides_preview_chrome(tmp_path: Path) -> None:
    out = build_static_production.main(tmp_path / "production")

    root = (out / "index.html").read_text(encoding="utf-8")
    guide = (out / "guide.html").read_text(encoding="utf-8")

    assert 'class="top-note"' not in root
    assert 'href="/guide.html"' in root
    assert "GUIDE · 30 SECONDS" in guide
    assert "관심 주제를 만듭니다" in guide
    assert (out / "topics" / "new" / "index.html").exists()
    assert (out / "records" / "index.html").exists()


def test_production_review_preserves_static_safety_headers(tmp_path: Path) -> None:
    out = build_static_production.main(tmp_path / "production")
    headers = (out / "_headers").read_text(encoding="utf-8")
    robots = (out / "robots.txt").read_text(encoding="utf-8")

    assert "form-action 'none'" in headers
    assert "connect-src 'none'" in headers
    assert "X-Robots-Tag: noindex, nofollow" in headers
    assert "Disallow: /" in robots
