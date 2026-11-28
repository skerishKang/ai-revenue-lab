# -*- coding: utf-8 -*-
"""A single, location-independent view of the site's stylesheet sources for tests.

Actual pages load base.css -> components.css -> their own pages/<page>.css.
When callers omit page, include each unique stylesheet once for source audits.
"""
from pathlib import Path

_APP = Path(__file__).resolve().parents[1]
_CSS = _APP / "static" / "css"
_PAGES = ("home", "about", "activity", "policy", "media", "news", "notfound")


def css_paths(page=None):
    base = (_CSS / "base.css", _CSS / "components.css")
    if page is None:
        return base + tuple(_CSS / "pages" / (name + ".css") for name in _PAGES)
    if page.endswith(".html"):
        page = page[:-5]
    if page == "index":
        page = "home"
    if page == "404":
        page = "notfound"
    if page not in _PAGES:
        raise ValueError("Unknown stylesheet page: " + str(page))
    return base + (_CSS / "pages" / (page + ".css"),)


def read_site_css(page=None):
    """Read each CSS source precisely once, in its actual link order."""
    return "\n".join(path.read_text(encoding="utf-8") for path in css_paths(page))
