"""Parsed views of the shipped Chat conversation module and its index wiring.

The raw ``read_text`` calls live here (#8060 10차) so the contract tests assert
on parsed values instead of pinning source spelling.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
STATIC = TESTS.parent / "static"


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            if attrs.get("src"):
                self.sources.append(attrs["src"])


def static_path(name: str = "") -> str:
    return str(STATIC / name) if name else str(STATIC)


def index_script_sources() -> list[str]:
    parser = _Scripts()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    parser.close()
    return parser.sources


def _source(sheet: str) -> str:
    return (STATIC / sheet).read_text(encoding="utf-8")


def function_counts(sheet: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", _source(sheet)):
        counts[name] = counts.get(name, 0) + 1
    return counts


def contains(sheet: str, marker: str) -> bool:
    return marker in _source(sheet)


def function_block(sheet: str, name: str) -> str:
    """One function declaration, braces balanced, without pinning whitespace."""

    source = _source(sheet)
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", source)
    if match is None:
        raise AssertionError(f"{name} function not found in {sheet}")
    index = source.index("{", match.end())
    depth = 0
    quote = ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
        index += 1
    raise AssertionError(f"{name} function has no closing brace in {sheet}")


def strict_deps_harness() -> str:
    return (TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")
