"""Parsed views for the answer-view contracts (#8060 34차).

The raw sheet reads live here (via claw_static); the contract tests receive
parsed tag/rule/icon/locale values and assert on those, never on source text
directly. Template scoping is by document order: a template's tags run from
its ``<template>`` tag up to the next ``<template>`` tag.
"""
from __future__ import annotations

import re

import locale_bundle
from _support.claw_static import sheet as _sheet
from _support.html_tags import tags_for_page


def sheet(name: str) -> str:
    """One shipped static sheet as text; the read lives here, not in tests."""
    return _sheet(name)


def index_tags() -> list:
    return tags_for_page("index.html")


def element_attrs(element_id: str):
    """Attribute map of the element with this id, or None."""
    for _tag, attrs in index_tags():
        if attrs.get("id") == element_id:
            return attrs
    return None


def script_sources() -> list[str]:
    """Script src basenames in load order."""
    sources: list[str] = []
    for tag, attrs in index_tags():
        if tag == "script" and attrs.get("src"):
            sources.append(attrs["src"].rsplit("/", 1)[-1])
    return sources


def template_tags(template_id: str) -> list:
    """Tags inside one ``<template>`` (document-order slice, next template ends it)."""
    tags = index_tags()
    start = None
    for idx, (tag, attrs) in enumerate(tags):
        if tag == "template" and attrs.get("id") == template_id:
            start = idx
            break
    assert start is not None, f"template {template_id} missing"
    end = len(tags)
    for idx in range(start + 1, len(tags)):
        if tags[idx][0] == "template":
            end = idx
            break
    return tags[start + 1:end]


def answer_icon_actions() -> list[str]:
    """The icon-button class strings the answer bar creates, in order."""
    src = sheet("outputs.js")
    return re.findall(r'iconButton\("(answer-action answer-[a-z-]+)"', src)


def assistant_product_text() -> str:
    """The text the assistant template shows as the product name."""
    match = re.search(r"<span[^>]*data-assistant-product[^>]*>([^<]+)</span>", sheet("index.html"))
    assert match, "assistant product span missing"
    return match.group(1).strip()


def locale_keys(lang: str) -> dict[str, str]:
    return locale_bundle.keys(lang)
