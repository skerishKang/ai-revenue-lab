"""Read the streaming lane's shipped sheets for the R5 step5b contracts
(#8060 23차).

Keeps raw ``read_text`` out of the test module: the contracts receive parsed
script order, whole-word definition counts, the exposed-name set and the
extracted registration blocks. The forbidden-API boundary stays a sheet-level
check here, with its reason recorded in the test (README §3).
"""
from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def module_source() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def index_script_srcs() -> list[str]:
    """Every ``<script src>`` of index.html, in document order."""
    from _support.html_tags import tags_for_page

    return [attrs["src"] for _tag, attrs in tags_for_page("index.html")
            if attrs.get("src")]


def _balanced_block(source: str, start: int) -> str:
    i = source.index("{", start)
    depth = 0
    for k in range(i, len(source)):
        if source[k] == "{":
            depth += 1
        elif source[k] == "}":
            depth -= 1
            if depth == 0:
                return source[i:k + 1]
    raise AssertionError("unbalanced block")


def function_definitions(source: str, name: str) -> int:
    """Whole-word count of ``function <name>(`` definitions in one sheet."""
    return len(re.findall(r"\bfunction %s\(" % re.escape(name), source))


def exposed_names(module: str) -> set[str]:
    """The names the streaming factory's object returns (shorthand entries)."""
    start = module.rindex("return {")
    block = _balanced_block(module, start)
    return {part.strip() for part in block[1:-1].split(",") if part.strip()}


def factory_globals(sheet: str) -> int:
    """Count of ``window.PadiemChatStreamingModule = {`` factory definitions."""
    return len(re.findall(r"window\.PadiemChatStreamingModule\s*=\s*\{", sheet))


def deps_assignment_targets(sheet: str) -> set[str]:
    """The state names a sheet writes on the shared deps surface."""
    return set(re.findall(r"\bdeps\.(\w+)\s*=", sheet))
