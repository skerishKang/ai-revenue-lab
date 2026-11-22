"""#8060 parsed facts for the owner sidebar history-scroll contract.

Raw reads of the shipped CSS, markup and modules stay here; the contract
asserts parsed declarations, selectors, markup order and token presence.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

MEDIA_DESKTOP = "min-width: 921px"
MEDIA_MOBILE = "max-width: 920px"
STORAGE_TOKENS = ("localStorage", "sessionStorage")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _present(tokens, source: str) -> tuple[str, ...]:
    return tuple(token for token in tokens if token in source)


class _Markup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stylesheets: list[str] = []
        self.ids: set[str] = set()
        self.classes: set[str] = set()
        self.aria_controls: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "stylesheet":
            href = values.get("href")
            if href:
                self.stylesheets.append(href)
        if "id" in values:
            self.ids.add(values["id"])
        self.classes.update(values.get("class", "").split())
        if "aria-controls" in values:
            self.aria_controls.append(values["aria-controls"])


def markup_facts() -> dict:
    parser = _Markup()
    parser.feed(_read("index.html"))
    parser.close()
    return {
        "stylesheets": tuple(parser.stylesheets),
        "ids": frozenset(parser.ids),
        "classes": frozenset(parser.classes),
        "aria_controls": tuple(parser.aria_controls),
    }


def css_facts() -> dict:
    css = re.sub(r"/\*.*?\*/", "", _read("sidebar-history-scroll.css"), flags=re.DOTALL)
    return {
        "selectors": tuple(selector.strip() for selector in re.findall(r"([^{}]+)\{", css)),
        "declarations": frozenset((prop.strip(), value.strip()) for prop, value in
                                  re.findall(r"([a-z-]+)\s*:\s*([^;{}]+);", css)),
        "media": tuple(re.findall(r"@media\s*\(([^)]+)\)", css)),
        "storage_tokens": _present(STORAGE_TOKENS, css),
    }


def app_facts() -> dict:
    source = _read("app.js") + _read("chat-history-module.js")
    return {
        "tokens": _present((
            'className = "history-actions-menu"',
            "row.append(button, actions)",
            "row.append(button, manage)",
        ), source),
    }
