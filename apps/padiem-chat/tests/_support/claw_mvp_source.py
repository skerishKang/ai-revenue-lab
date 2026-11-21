"""Parsed-source boundary for the #2299 Claw usability contracts.

Raw ``read_text`` stays here; tests receive named views and assert on parsed
values. No runtime file is changed.
"""
from __future__ import annotations

from _support.claw_static import locale_source, sheet
from css_rules import rules_for_sheet


class Static:
    def __init__(self, name: str):
        self.name = name

    @property
    def text(self) -> str:
        return sheet(self.name)

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and token in self.text

    def count(self, token: str) -> int:
        return self.text.count(token)

    def lower(self) -> str:
        return self.text.lower()

    def __add__(self, other):
        if isinstance(other, Static):
            return StaticPair(self, other)
        if isinstance(other, str):
            return StringPair(self.text + other)
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, str):
            return StringPair(other + self.text)
        return NotImplemented


class StaticPair:
    def __init__(self, left, right):
        self.parts = [left, right]

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and any(token in part.text for part in self.parts)

    def __add__(self, other):
        if isinstance(other, Static):
            return StaticPair(*self.parts, other)
        if isinstance(other, str):
            return StringPair(self.text + other)
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, str):
            return StringPair(other + self.text)
        return NotImplemented


class Css:
    def __init__(self, name: str):
        self.name = name
        rules = rules_for_sheet(name)
        self.items = {selector for rule in rules for selector in rule.selectors}
        for rule in rules:
            for prop, value in rule.declarations.items():
                if not value:
                    continue
                self.items.add(value)
                self.items.add(f"{prop}: {value}")
        for media in (rule.media for rule in rules if rule.media):
            self.items.add(media)
            self.items.add("@media " + media)

    def __contains__(self, token: object) -> bool:
        return isinstance(token, str) and any(token in item for item in self.items)


class StringPair:
    def __init__(self, text):
        self.text = text

    def __contains__(self, token):
        return isinstance(token, str) and token in self.text

    def __add__(self, other):
        if isinstance(other, str) or isinstance(other, Static):
            return StringPair(self.text + (other.text if isinstance(other, Static) else other))
        return NotImplemented


def locale() -> str:
    return locale_source()
