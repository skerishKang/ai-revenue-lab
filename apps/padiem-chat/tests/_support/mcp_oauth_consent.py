"""Parsed views of the shipped MCP OAuth consent page and its locale (#8060 22차).

Keeps the raw ``read_text`` calls out of the MCP OAuth contract tests: the
tests receive the parsed tag list, the wired locale keys, the script list and
the localized phrases instead of raw sheet text. The sheet paths stay here.
"""
from __future__ import annotations

import re

import locale_bundle

from _support.claw_static import sheet
from _support.html_tags import tags_for_page

CONSENT_PAGE_SHEET = "mcp-oauth-consent.html"
CONSENT_SCRIPT_SHEET = "mcp-oauth-consent.js"


def consent_page_tags() -> list[tuple[str, dict[str, str]]]:
    """The consent page as an ordered (tag, attributes) list."""
    return tags_for_page(CONSENT_PAGE_SHEET)


def consent_page_scripts() -> list[str]:
    """The ``src`` of every script the consent page loads, in order."""
    return [
        attrs["src"] for _tag, attrs in consent_page_tags()
        if attrs.get("src")
    ]


def consent_page_locale_keys() -> list[str]:
    """Every ``data-locale-key`` the consent page wires, in order."""
    return [
        attrs["data-locale-key"] for _tag, attrs in consent_page_tags()
        if attrs.get("data-locale-key")
    ]


def consent_script_oauth_urls() -> set[str]:
    """OAuth endpoints the consent script names in its own string literals."""
    source = sheet(CONSENT_SCRIPT_SHEET)
    return set(re.findall(r'["\'](/oauth/[^"\']*)["\']', source))


def locale_phrases(key: str) -> dict[str, str]:
    """One locale key's shipped phrase per language (ko, en)."""
    return {lang: locale_bundle.keys(lang).get(key) for lang in ("ko", "en")}
