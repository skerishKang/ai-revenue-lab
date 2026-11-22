"""Parsed views of the shipped Glass sheets for portrait contracts (#8060 13차).

Keeps raw ``read_text`` out of the contract test. CSS membership is answered
from parsed rules/values with the `!important` cap normalised away, so the
ongoing #8008 cap cleanup cannot break these contracts.
"""
from __future__ import annotations

import re
from pathlib import Path

from _support.claw_static import js_statement, sheet
from css_rules import rules_for_sheet

STATIC = Path(__file__).resolve().parents[2] / "static"


def static_path(name: str = "") -> str:
    return str(STATIC / name) if name else str(STATIC)


def _uncap(value: str) -> str:
    return value.replace(" !important", "").strip()


def css_items(sheet_name: str) -> set[str]:
    items: set[str] = set()
    for rule in rules_for_sheet(sheet_name):
        items.update(rule.selectors)
        if rule.media:
            items.add(rule.media)
        for prop, value in rule.declarations.items():
            if value:
                items.add(f"{prop}: {_uncap(value)}")
                items.add(_uncap(value))
    return items


def css_at_items(sheet_name: str) -> set[str]:
    text = re.sub(r"/\*.*?\*/", "", sheet(sheet_name), flags=re.DOTALL)
    items: set[str] = set()
    for name in re.findall(r"@property\s+([^\s{]+)", text):
        items.add(name)
        items.add(f"@property {name}")
    for condition in re.findall(r"@media\s*\(([^)]*)\)", text):
        items.add(condition)
        items.add(f"@media ({condition})")
    return items


class Js:
    def __init__(self, name: str):
        self.name = name

    def __contains__(self, statement: object) -> bool:
        return isinstance(statement, str) and js_statement(self.name, statement)


class Css:
    def __init__(self, name: str):
        self.name = name
        self.items = css_items(name) | css_at_items(name)
        self.text = "\n".join(sorted(self.items))

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and token.strip() in self.text


class Combined:
    def __init__(self, *views):
        self.views = views

    def __contains__(self, token):
        return any(token in view for view in self.views)


def _joined(self, other):
    return Combined(self, other)


class Html:
    def __init__(self, name: str = "index.html"):
        self.name = name

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and token in sheet(self.name)

    def index(self, token: str, start: int = 0) -> int:
        return sheet(self.name).index(token, start)

    def __getitem__(self, key):
        return sheet(self.name)[key]


Html.__add__ = _joined
Js.__add__ = _joined
Css.__add__ = _joined
Combined.__add__ = _joined
