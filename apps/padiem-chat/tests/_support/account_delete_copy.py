"""Parsed views of the shipped account-deletion help, index and legal copy.

The raw ``read_text`` calls live here (#8060 7차) so the contract test can assert
on parsed values instead of pinning source spelling. No runtime file changes.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATIC = ROOT / "apps" / "padiem-chat" / "static"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def help_account_section() -> str:
    """Visible text of the help page's account section, whitespace normalised."""

    text = (STATIC / "help.html").read_text(encoding="utf-8")
    section = text.split('id="account"', 1)[1].split('id="faq"', 1)[0]
    parser = _Text()
    parser.feed(section)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def help_has_brand() -> bool:
    return "PADIEM" in (STATIC / "help.html").read_text(encoding="utf-8")


def index_element_ids() -> list[str]:
    from _support.html_tags import tags_for_page

    return [attrs.get("id") for _tag, attrs in tags_for_page("index.html")
            if attrs.get("id")]


def js_string_literals(*names: str) -> list[str]:
    """Every simple quoted string literal in the named static JS files."""

    literals: list[str] = []
    for name in names:
        text = (STATIC / name).read_text(encoding="utf-8")
        literals.extend(re.findall(r"""["']([^"'\n\\]+)["']""", text))
    return literals


def legal_text(relative: str) -> str:
    """The shipped legal draft as text, whitespace normalised."""

    text = (ROOT / relative).read_text(encoding="utf-8")
    return " ".join(text.split())
