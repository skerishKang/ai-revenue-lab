"""Raw reads and parsed views for the Glass theme contracts.

The shipped CSS/JS/HTML text is opened here (through claw_static); the test
module receives selectors, declarations, token values, tag attributes and JS
literal/identifier sets instead of raw source text.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from _support import theme_sheets


_JS_STRING = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`")
_JS_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_JS_MEMBER = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)\s*(?=\(|\b)")
_CSS_AT_RULE = re.compile(r"@(media|supports)\s+([^{;]+)\{")


def js(name: str) -> str:
    return theme_sheets.theme_js() if name == "theme.js" else theme_sheets.theme_init_js()


def raw_glass_css() -> str:
    from _support.claw_static import sheet

    return sheet("padiem-glass.css")


def js_strings(name: str) -> set[str]:
    """Quoted literals in one shipped JS file, without their quotes."""
    return {token[1:-1] for token in _JS_STRING.findall(js(name))}


def js_identifiers(name: str) -> set[str]:
    return set(_JS_IDENT.findall(js(name)))


def js_members(name: str) -> set[str]:
    return set(_JS_MEMBER.findall(js(name)))


def css_at_rules() -> set[str]:
    """At-rule preludes (e.g. `prefers-reduced-transparency: reduce`)."""
    return {match.group(2).strip() for match in _CSS_AT_RULE.finditer(raw_glass_css())}


def index_attrs() -> list[tuple[str, dict[str, str]]]:
    return theme_sheets.index_tags()


def index_hrefs() -> set[str]:
    return {attrs["href"] for tag, attrs in index_attrs() if attrs.get("href")}


def theme_picker_values() -> set[str]:
    return {attrs["data-theme-value"] for _tag, attrs in index_attrs() if attrs.get("data-theme-value")}


class _Dom(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str], list[str]]] = []
        self.markers: set[str] = set()

    def handle_starttag(self, tag, attrs):
        self.stack.append((tag, dict(attrs), []))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] != tag:
                continue
            subtree = self.stack[i:]
            self.stack = self.stack[:i]
            text = "".join("".join(node[2]) for node in subtree).strip()
            if tag == "span" and text == "Padiem Chat":
                self.markers.add("Padiem Chat</span>")
            if tag == "header" and "topbar" in subtree[0][1].get("class", ""):
                ids = {node[1].get("id") for node in subtree}
                if "settingsButton" in ids:
                    self.markers.add("topbar:settingsButton")
                if "loginButton" in ids:
                    self.markers.add("topbar:loginButton")
            break

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2].append(data)


def dom_markers() -> set[str]:
    parser = _Dom()
    parser.feed(theme_sheets.page_html())
    parser.close()
    return parser.markers


def html_text() -> str:
    """All visible text nodes joined — for the page-title contract."""
    parts: list[str] = []

    class Collector(HTMLParser):
        def handle_data(self, data):
            parts.append(data)

    parser = Collector(convert_charrefs=True)
    parser.feed(theme_sheets.page_html())
    parser.close()
    return " ".join(parts)
