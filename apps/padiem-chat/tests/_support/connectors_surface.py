"""Parsed views of the shipped connectors surface (#8060 24차).

Keeps the raw ``read_text`` calls out of the truthfulness contract tests: the
tests receive the dialog element, the structured capability cards, the locale
table and the shipped connector constants instead of sheet text. The sheet
paths stay here.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
import re

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[2] / "tests"

NAV_ID = "connectorsNavButton"
DIALOG_ID = "connectorsDialog"

CARD_RE = re.compile(r'<div class="capability-card"([^>]*)>(.*?)</div>', re.DOTALL)


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js_text() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def connectors_module_text() -> str:
    return (_STATIC / "chat-connectors-module.js").read_text(encoding="utf-8")


def calendar_module_text() -> str:
    return (_STATIC / "chat-calendar-module.js").read_text(encoding="utf-8")


def capability_css_text() -> str:
    return (_STATIC / "capability-nav.css").read_text(encoding="utf-8")


def strict_deps_text() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def dialog_element() -> str:
    """The shipped connectors <dialog> element, tags included."""
    index = index_html()
    before, _ = index.split(f'id="{DIALOG_ID}"', 1)
    start = before.rindex("<dialog")
    return index[start:].split("</dialog>", 1)[0] + "</dialog>"


def nav_markup() -> str:
    """The shipped connectors nav <button> element, tags included."""
    index = index_html()
    marker = f'id="{NAV_ID}"'
    assert marker in index
    before, after = index.split(marker, 1)
    return "<button" + before.rsplit("<button", 1)[1] + marker + after.split("</button>", 1)[0] + "</button>"


def dialog_cards() -> dict[str, dict]:
    """The capability cards parsed from the dialog: ids, states, actions.

    ``connect_actions`` collects the ``data-google-connector-connect`` values
    the card offers, and ``has_support``/``has_workspace`` say whether the two
    state sinks are wired — the former raw substrings of the card markup.
    """
    cards: dict[str, dict] = {}
    for attrs, inner in CARD_RE.findall(dialog_element()):
        slug = re.search(r'data-connector="([^"]+)"', attrs)
        if not slug:
            continue
        connector_id = re.search(r'data-connector-id="([^"]+)"', attrs)
        status = re.search(r'data-connector-status="([^"]+)"', attrs)
        cards[slug.group(1)] = {
            "connector_id": connector_id.group(1) if connector_id else "",
            "status": status.group(1) if status else "",
            # Attribute presence, not substring: a renamed sink attribute must
            # not read as the reviewed state sink (#8060 24차).
            "has_support": re.search(r'data-connector-support(?=[\s>]|$)', inner) is not None,
            "has_workspace": re.search(r'data-connector-workspace(?=[\s>]|$)', inner) is not None,
            "connect_actions": set(re.findall(r'data-google-connector-connect="([^"]+)"', inner)),
        }
    return cards


def dialog_element_attrs(element_id: str) -> dict[str, str]:
    """The attribute map of one element inside the dialog, by id."""
    dialog = dialog_element()
    match = re.search(rf'<[a-z]+[^>]*\bid="{element_id}"([^>]*)>', dialog)
    assert match, element_id
    return dict(re.findall(r'([A-Za-z-]+)="([^"]*)"', match.group(1)))


def nav_attributes() -> dict[str, str]:
    """The attribute map of the shipped connectors nav button."""
    markup = nav_markup()
    match = re.search(r"<button([^>]*)>", markup)
    assert match
    return dict(re.findall(r'([A-Za-z-]+)="([^"]*)"', match.group(1)))


def locale_table() -> dict[str, dict[str, str]]:
    """The shipped locale keys and phrases per language, parsed."""
    source = locale_bundle.SOURCE.read_text(encoding="utf-8")
    pattern = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    assert "en: {" in source
    ko_part, en_part = source.split("en: {", 1)
    return {
        "ko": {key: unescape(value) for key, value in pattern.findall(ko_part)},
        "en": {key: unescape(value) for key, value in pattern.findall(en_part)},
    }


def shipped_connector_constants() -> dict[str, str]:
    """Read the connector route constants from the shipped sources.

    R5 2부 B2: the Drive/Gmail constants moved into chat-connectors-module.js;
    the Calendar constants stay in app.js.
    """
    app = app_js_text() + connectors_module_text() + calendar_module_text()
    constants: dict[str, str] = {}
    for name in (
        "GOOGLE_CALENDAR_CONNECTOR",
        "GOOGLE_CALENDAR_TICKET_ENDPOINT",
        "GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT",
        "GOOGLE_DRIVE_CONNECTOR",
        "GOOGLE_DRIVE_TICKET_ENDPOINT",
        "GOOGLE_GMAIL_CONNECTOR",
        "GOOGLE_GMAIL_TICKET_ENDPOINT",
    ):
        match = re.search(rf'\bconst {name} = "([^"]+)";', app)
        assert match, name
        constants[name] = match.group(1)
    return constants
