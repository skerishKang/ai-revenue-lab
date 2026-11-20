"""Shipped voice assets as parsed facts, not raw text in contract tests (#8060).

The helper owns the file reads. Tests assert on comment-stripped code, UMD
exports, parsed HTML tags and declared JS constants, so renaming or reflowing
the source cannot silently weaken a contract.
"""
from __future__ import annotations

import re
from pathlib import Path

from .html_tags import tags_for_page

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"


def source(name: str) -> str:
    """Exact text of a shipped static sheet or a repository source file."""
    path = STATIC / name if not name.endswith((".py", ".toml")) else ROOT / name
    return text(path)


def text(path) -> str:
    """Exact text of an explicit test fixture path."""
    return Path(path).read_text(encoding="utf-8")


def code(name: str) -> str:
    """Executable JS only: block and line comments removed, prose ignored."""
    text = source(name)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def script_order(page: str = "index.html") -> list[str]:
    """Script ``src`` values in document order."""
    return [attrs.get("src", "") for tag, attrs in tags_for_page(page) if tag == "script"]


def element_ids(page: str = "index.html") -> set[str]:
    """Ids present in a shipped page, from parsed tags."""
    return {attrs["id"] for _tag, attrs in tags_for_page(page) if "id" in attrs}


def umd_exports(name: str) -> list[str]:
    """Globals a shipped module publishes through its UMD ``root.X = api`` line."""
    return re.findall(r"root\.([A-Za-z0-9_$]+)\s*=\s*api\s*;", source(name))


def has_exact_line(name: str, line: str) -> bool:
    """Whether one exact code line is present, independent of its file offset."""
    return any(actual.strip() == line.strip() for actual in source(name).splitlines())
