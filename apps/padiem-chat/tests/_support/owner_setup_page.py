"""Parsed views for the #4139 owner setup page contracts (#8060 61차).

Raw served sheets and packaged page/script markup stay behind this helper (via
the shared ``claw_static`` sheet reader and the conversation-search JS parser).
Contract tests receive parsed HTML/JS facts and assert on those instead of
pinning shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from _support.claw_static import sheet
from _support.conversation_search_4471 import _facts, _strip_js_comments, _string_literals


_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_PROPERTY_RX = re.compile(rf'"?({_IDENT})"?\s*:\s*"([^"]+)"')
_STATE_CMP_RX = re.compile(rf"({_CHAIN})\s*===\s*\"([^\"]+)\"")
_NUM_CMP_RX = re.compile(rf"({_CHAIN})\s*===\s*(\d+)")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict]] = []
        self.texts: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        if data.strip():
            self.texts.append(data.strip())


def html_facts(markup: str) -> dict:
    """Parsed element/id/text facts for one HTML document."""
    parser = _Markup()
    parser.feed(markup)
    parser.close()
    elements = parser.elements
    return {
        "elements": elements,
        "ids": [attrs["id"] for _tag, attrs in elements if attrs.get("id")],
        "tags": {tag for tag, _attrs in elements},
        "texts": set(parser.texts),
        "attrs_by_id": {attrs["id"]: dict(attrs) for _tag, attrs in elements if attrs.get("id")},
        "script_srcs": [
            attrs.get("src") for tag, attrs in elements
            if tag == "script" and attrs.get("src")
        ],
        "links": [(tag, dict(attrs)) for tag, attrs in elements if tag == "a"],
    }


def js_facts(text: str) -> dict:
    """Parsed facts for executable JS supplied as text (comments stripped)."""
    executable = _strip_js_comments(text)
    facts = _facts(executable)
    facts["string_literals"] = set(_string_literals(executable))
    facts["property_pairs"] = set(_PROPERTY_RX.findall(executable))
    facts["state_comparisons"] = set(_STATE_CMP_RX.findall(executable))
    facts["number_comparisons"] = set(_NUM_CMP_RX.findall(executable))
    return facts


def setup_html() -> dict:
    from app import connector_owner_setup_page as setup

    return html_facts(setup._HTML)


def setup_script() -> dict:
    from app import connector_owner_setup_page as setup

    return js_facts(setup._SCRIPT)


def claw_choices_source() -> str:
    """The shipped claw-home-choices.js source, read only inside this helper."""
    return sheet("claw-home-choices.js")


def claw_choices_facts() -> dict:
    return js_facts(claw_choices_source())
