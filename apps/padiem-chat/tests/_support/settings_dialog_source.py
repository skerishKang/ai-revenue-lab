"""Parsed views for the settings-dialog contracts (#8060 51차).

Raw file reads live here. Tests receive parsed HTML elements, CSS rules,
token values, locale maps and JS string literals, and assert on those. The
shared ``claw_static`` / ``css_rules`` / ``locale_bundle`` helpers are reused
wherever they already own the read path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import locale_bundle
from css_rules import declaration, parse_rules, rules_for_sheet

from _support.claw_static import sheet

_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input",
     "link", "meta", "param", "source", "track", "wbr"}
)


@dataclass
class Element:
    """One parsed HTML element: tag, attribute map, own text and document order."""

    tag: str
    attrs: dict[str, str | None]
    text: str = ""
    order: int = 0
    depth: int = 0
    children: list["Element"] = field(default_factory=list)

    def has_class(self, name: str) -> bool:
        return name in (self.attrs.get("class") or "").split()


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self._stack: list[Element] = []

    def handle_starttag(self, tag, attrs) -> None:
        el = Element(tag, dict(attrs), order=len(self.elements), depth=len(self._stack))
        self.elements.append(el)
        if self._stack:
            self._stack[-1].children.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data) -> None:
        if self._stack:
            self._stack[-1].text += data


def _parse(text: str) -> list[Element]:
    parser = _Parser()
    parser.feed(text)
    parser.close()
    return parser.elements


def index_elements() -> list[Element]:
    """Every element of the shipped index page, in document order."""
    return _parse(sheet("index.html"))


def dialog_elements() -> list[Element]:
    """Every element inside the settings dialog, in document order."""
    source = sheet("index.html")
    start = source.index('<dialog class="settings-dialog"')
    end = source.index("</dialog>", start)
    return _parse(source[start:end])


def settings_rules():
    """Parsed rules of the shipped settings sheet."""
    return rules_for_sheet("padiem-settings.css")


def token_value(name: str) -> str:
    """A custom-property value from the token sheet, parsed as a declaration."""
    for rule in parse_rules(sheet("padiem-tokens.css")):
        value = declaration(rule, name)
        if value is not None:
            return value
    raise AssertionError(f"token {name} is not declared in padiem-tokens.css")


def locale_map(lang: str) -> dict[str, str]:
    """The merged locale group for ``lang`` as a parsed key/value map."""
    return dict(locale_bundle.keys(lang))


def theme_strings() -> list[str]:
    """Quoted string literals in the shipped theme script."""
    source = sheet("theme.js")
    pairs = re.findall(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'', source)
    return [double or single for double, single in pairs]


def theme_class_assignments() -> list[str]:
    """className values assigned in the shipped theme script, in source order."""
    return re.findall(r'\.className\s*=\s*"([^"]*)"', sheet("theme.js"))


def by_id(elements: list[Element], element_id: str) -> list[Element]:
    return [el for el in elements if el.attrs.get("id") == element_id]


def by_locale_key(elements: list[Element], key: str) -> list[Element]:
    return [el for el in elements if el.attrs.get("data-locale-key") == key]
