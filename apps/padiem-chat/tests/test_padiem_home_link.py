from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_sidebar_padiem_home_link_exists() -> None:
    assert 'class="home-link"' in HTML


def test_sidebar_padiem_home_link_label() -> None:
    assert 'data-locale-key="home-link"' in HTML
    assert "Padiem Home" in HTML


def test_sidebar_padiem_home_link_targets_padiem_net() -> None:
    assert 'href="https://padiem.net/"' in HTML


def test_sidebar_padiem_home_link_opens_safely() -> None:
    assert 'target="_blank"' in HTML
    assert 'rel="noopener"' in HTML
    link = [line for line in HTML.splitlines() if "home-link" in line and "href" in line][0]
    assert 'target="_blank"' in link
    assert 'rel="noopener"' in link
    assert 'href="https://padiem.net/"' in link


def test_sidebar_padiem_home_link_is_not_a_dead_button() -> None:
    assert "<a " in HTML and 'class="home-link"' in HTML
    link_line = [line for line in HTML.splitlines() if 'class="home-link"' in line][0]
    assert link_line.strip().startswith("<a ")
