"""#6063 mobile navigation contract for the councillor prototype.

The reported symptom was a cropped hero portrait at 390px. Measured in a real
browser at 240 to 1440px the portrait never leaves the viewport, so nothing was
changed about it. What did reproduce is worse: ``.top-nav`` is ``display:none``
from 900px down and the four inner pages carried no other navigation, so a
phone visitor who landed on 의원 소개·의정활동·정책자료·미디어 could not reach
any page at all.

These tests pin that failure shut without needing a browser: they assert the
CSS premise (the header nav really is hidden on phones) and then require every
page to offer the full page set somewhere that survives that rule.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
STYLES = (APP_ROOT / "static" / "styles.css").read_text(encoding="utf-8")
PAGES = ["index.html", "about.html", "activity.html", "policy.html", "media.html"]


class LinkParser(HTMLParser):
    """Collects ``a href`` values, tagged with the nearest enclosing element ids."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.links: list[tuple[str, tuple[str, ...]]] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"nav", "header", "footer", "div", "section", "main"}:
            a = dict(attrs)
            ident = a.get("class") or a.get("id") or tag
            self.stack.append(f"{tag}.{ident}")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self.links.append((href, tuple(self.stack)))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1].startswith(f"{tag}."):
            self.stack.pop()


def _links(page: str) -> list[tuple[str, tuple[str, ...]]]:
    parser = LinkParser()
    parser.feed((APP_ROOT / page).read_text(encoding="utf-8"))
    return parser.links


def _page_targets(links) -> set[str]:
    return {Path(href.split("?")[0]).name for href, _ in links if href.endswith(".html")}


def _in_hidden_header(href: str, chain: tuple[str, ...]) -> bool:
    return any("nav.top-nav" in part for part in chain)


def test_the_header_nav_is_hidden_on_phones():
    """The premise of this whole file. If the design changes, revisit the rest."""
    blocks = re.findall(
        r"@media\s*\(max-width:\s*(\d+)px\)\s*\{(.*?)\n\}", STYLES, flags=re.S
    )
    hidden_at = [int(w) for w, body in blocks
                 if re.search(r"\.top-nav\s*\{[^}]*display:\s*none", body)]
    assert hidden_at, "no media query hides .top-nav any more — re-check this contract"
    assert max(hidden_at) >= 760, f".top-nav only hidden below {max(hidden_at)}px"


def test_every_page_can_reach_every_page_without_the_header_nav():
    for page in PAGES:
        outside_header = [(href, chain) for href, chain in _links(page)
                          if not _in_hidden_header(href, chain)]
        targets = _page_targets(outside_header)
        missing = [p for p in PAGES if p != page and p not in targets]
        assert not missing, f"{page} loses navigation on phones: {missing} only live in .top-nav"
        assert outside_header, f"{page} has no visible link outside the header at all"


def test_inner_pages_keep_a_footer_navigation_block():
    for page in PAGES[1:]:
        links = _links(page)
        footer = [href for href, chain in links if any("footer" in c for c in chain)]
        assert len(footer) >= 5, f"{page} footer exposes {len(footer)} links, expected the page set"
        assert any("index.html" in h for h in footer), f"{page} footer cannot get home"


def test_the_disclaimer_and_source_note_survive_the_footer_rewrite():
    for page in PAGES:
        text = (APP_ROOT / page).read_text(encoding="utf-8")
        assert "이 페이지는 시제품이며 의원실 공식 웹사이트가 아닙니다." in text, page
        assert "2026-10-25 확인" in text, page


def test_no_page_links_the_portrait_from_a_different_source():
    """The real person's photo must stay the one file the design already uses."""
    for page in PAGES:
        html = (APP_ROOT / page).read_text(encoding="utf-8")
        for src in re.findall(r'src="\./static/images/([^"]+)"', html):
            assert src in {"profile-portrait.png", "hero-panorama.jpg", "activity-01.jpg",
                           "activity-02.jpg"} or src.startswith("media-"), f"{page}: {src}"


def test_the_hero_portrait_is_styled_to_avoid_cropping_on_phones():
    """Guards the measured-not-broken state of the reported symptom.

    ``object-fit: contain`` plus a bounded width is what keeps the face inside
    the safe area at 240 to 430px. A future ``cover`` here would crop the head
    again, which is the bug this issue was opened for.
    """
    mobile = STYLES[STYLES.index("@media (max-width: 760px)"):]
    block = re.search(r"\.hero-portrait\s*\{(.*?)\}", mobile, flags=re.S)
    assert block, "no .hero-portrait rule inside the phone media query any more"
    body = block.group(1)
    assert "object-fit: contain" in body, "the phone portrait must not crop the cut-out"
    assert "max-width" in body, "the phone portrait needs a width cap to stay inside the gutter"
