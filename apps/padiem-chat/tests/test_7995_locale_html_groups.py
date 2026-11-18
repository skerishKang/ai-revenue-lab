"""#7995 — every HTML that loads locale.js must load the groups its keys need."""
from __future__ import annotations

import re
from pathlib import Path

import locale_bundle
import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
SCRIPTS = re.compile(r'<script[^>]*\bsrc="([^"]+)"')
KEYS = re.compile(r'data-locale-(?:key|aria-label|title)="([^"]+)"')
GROUP_NAMES = set(locale_bundle.GROUP_NAMES)


def locale_html() -> list[Path]:
    return sorted(p for p in STATIC.glob("*.html")
                  if re.search(r'<script[^>]*\bsrc="[^"]*locale\.js"', p.read_text(encoding="utf-8")))


def check_page(html: str, name: str) -> list[str]:
    scripts = SCRIPTS.findall(html)
    locale_at = next((i for i, src in enumerate(scripts)
                      if src.rstrip("/").endswith("locale.js")), None)
    assert locale_at is not None, name
    loaded = {Path(src.rstrip("/")).stem for src in scripts[:locale_at]}
    problems = []
    for key in sorted(set(KEYS.findall(html))):
        owner = locale_bundle.key_owner(key)
        if owner is not None and owner not in loaded:
            problems.append("%s needs %s for key %s" % (name, owner, key))
    return problems


def test_every_locale_html_loads_the_groups_its_keys_need():
    pages = locale_html()
    assert {p.name for p in pages} >= {"index.html", "mcp-oauth-consent.html"}
    for page in pages:
        assert not check_page(page.read_text(encoding="utf-8"), page.name), page.name


def test_consent_page_loads_common_then_pc_connect_before_bootstrap():
    html = (STATIC / "mcp-oauth-consent.html").read_text(encoding="utf-8")
    scripts = SCRIPTS.findall(html)
    order = [Path(src).name for src in scripts]
    assert order.index("locale-common.js") < order.index("locale-pc-connect.js") < order.index("locale.js")


def test_all_consent_keys_are_declared_in_a_loaded_group():
    html = (STATIC / "mcp-oauth-consent.html").read_text(encoding="utf-8")
    missing = [key for key in set(KEYS.findall(html))
               if locale_bundle.key_owner(key) is None]
    assert not missing, missing


def test_removing_a_required_group_fails_the_check():
    """Mutation: drop the PC-connect group from the consent page."""
    html = (STATIC / "mcp-oauth-consent.html").read_text(encoding="utf-8")
    mutated = html.replace('<script src="/locale-pc-connect.js"></script>\n', "")
    assert mutated != html
    assert check_page(mutated, "mcp-oauth-consent.html")
