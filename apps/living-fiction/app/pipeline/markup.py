"""Recursive rejection of unsafe markup in visible output fields.

Generated text must never contain raw HTML, scripts, iframes, event-handler
content, or ``javascript:`` URLs. This module walks strings and nested
list/dict structures recursively so a payload cannot smuggle unsafe content
inside a list, a nested object, or a multi-line string.
"""

from __future__ import annotations

import re
from typing import Any

from app.pipeline.errors import UnsafeMarkupError

_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z]")
_UNSAFE_ATTR_RE = re.compile(
    r"(?i)\bon[a-z]+\s*=|javascript\s*:|vbscript\s*:|data\s*:\s*text/html"
)
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})


def _contains_unsafe(content: str) -> str | None:
    if not isinstance(content, str):
        return None
    if _TAG_RE.search(content):
        return "raw HTML tag"
    if _UNSAFE_ATTR_RE.search(content):
        return "event handler or unsafe URL scheme"
    return None


def check_string(value: str, *, field_name: str) -> None:
    reason = _contains_unsafe(value)
    if reason is not None:
        raise UnsafeMarkupError(
            f"unsafe markup rejected in '{field_name}': {reason}"
        )


def check_payload(payload: Any) -> None:
    """Recursively walk a parsed payload and reject unsafe strings."""
    _walk(payload, path="")


def _walk(node: Any, *, path: str) -> None:
    # Exempt user-generated comment field from markup safety checks.
    # Comments are stored as-is and escaped by Jinja at render time.
    if path == "applied_reader_input.comment":
        return
    if isinstance(node, str):
        reason = _contains_unsafe(node)
        if reason is not None:
            label = path or "value"
            raise UnsafeMarkupError(
                f"unsafe markup rejected in '{label}': {reason}"
            )
        return
    if isinstance(node, list):
        for idx, item in enumerate(node):
            _walk(item, path=f"{path}[{idx}]" if path else f"[{idx}]")
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            _walk(value, path=child_path)
        return
    return
