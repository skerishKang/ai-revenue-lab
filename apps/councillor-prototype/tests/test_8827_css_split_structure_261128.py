# -*- coding: utf-8 -*-
"""#8827 no extra cascade sheets, tokens only in base, each page gets three CSS links."""
from pathlib import Path
import re
import sys
import pytest
from css_source import css_paths, read_site_css

ROOT=Path(__file__).resolve().parents[1]
CSS=ROOT/"static/css"
PAGES={
    "index.html":"home","about.html":"about","activity.html":"activity",
    "policy.html":"policy","media.html":"media","news.html":"news",
    "404.html":"notfound",
}
def test_css_structure_and_single_source_of_tokens():
    assert not (ROOT/"static/styles.css").exists()
    assert (CSS/"base.css").is_file()
    assert (CSS/"components.css").is_file()
    paths=css_paths()
    assert len(paths)==9 and len(set(paths))==9
    assert all(p.is_file() for p in paths)
    assert sum(p.read_text(encoding="utf-8").count("!important") for p in paths)==5
    assert "/* News reserves the common eyebrow line" not in read_site_css()
    decl=re.compile(r"--[a-z][\w-]*\s*:")
    for p in paths[1:]:
        non_comments=re.sub(r"/\*.*?\*/","",p.read_text(encoding="utf-8"),flags=re.S)
        assert not decl.findall(non_comments),(p.name,decl.findall(non_comments))
    base=(CSS/"base.css").read_text(encoding="utf-8")
    assert "--accent:" in base and "--fs-body:" in base and "--hero-image:" in base
    assert ':root {' in base


@pytest.mark.parametrize("name,page",list(PAGES.items()))
def test_each_generated_page_reads_only_its_own_sheet_in_exact_order(name,page):
    sys.path.insert(0,str(ROOT/"scripts"))
    import assemble
    html=assemble.render(name)
    links=re.findall(r'<link rel="stylesheet" href="([^"]+\.css)"',html)
    ours=[link for link in links if link.startswith("./static/css/")]
    assert ours==[
        "./static/css/base.css",
        "./static/css/components.css",
        "./static/css/pages/"+page+".css",
    ],(name,ours)
    assert "./static/styles.css" not in html
    assert read_site_css(name)==read_site_css(page)
    assert len(css_paths(name))==3


def test_page_specific_selectors_do_not_cross_into_other_pages():
    forbidden={
       "home":(".activity-", ".intro-", ".bill-", ".site-change", ".not-found"),
       "about":(".activity-", ".hero-", ".bill-", ".media-grid", ".site-change"),
       "activity":(".intro-", ".hero-", ".bill-", ".site-change", ".not-found"),
       "policy":(".hero-", ".intro-", ".activity-", ".site-change", ".not-found"),
       "media":(".hero-", ".intro-", ".activity-", ".bill-", ".site-change"),
       "news":(".hero-", ".intro-", ".activity-", ".bill-", ".not-found"),
       "notfound":(".hero-", ".intro-", ".activity-", ".bill-", ".site-change"),
    }
    for page,other in forbidden.items():
        raw=(CSS/"pages"/(page+".css")).read_text(encoding="utf-8")
        raw=re.sub(r"/\*.*?\*/","",raw,flags=re.S)
        for marker in other:
            assert marker not in raw,(page,marker)


def test_no_cross_file_duplicate_identical_rules():
    # Compare identical selector/declaration text; all wrappers are per-sheet.
    by_content={}
    for path in css_paths():
        raw=re.sub(r"/\*.*?\*/","",path.read_text(encoding="utf-8"),flags=re.S)
        for selector,body in re.findall(r"([^{}]+)\{([^{}]*)\}",raw):
            if not body.strip() or selector.strip().startswith("@"):continue
            normalized=re.sub(r"\s+"," ",selector.strip()+"{"+body.strip()+"}")
            previous=by_content.get(normalized)
            assert previous is None or previous==path,(path,previous,normalized)
            by_content[normalized]=path
