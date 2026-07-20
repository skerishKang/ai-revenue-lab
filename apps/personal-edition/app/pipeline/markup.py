"""Recursive rejection of unsafe markup in visible output fields.

Contract (PERSONAL_EDITION_MVP_CONTRACT.md section 9, PERSONAL_EDITION_MVP_ARCHITECTURE.md
section 10): generated text must never contain raw HTML, scripts, iframes,
event-handler content, or ``javascript:`` URLs. The model never produces
complete HTML; EditionContent is rendered through trusted templates that escape
by default.

This module is a deterministic backstop. It walks strings and nested
list/dict structures recursively so a payload cannot smuggle unsafe content
inside a list, a nested object, or a multi-line string.
"""

from __future__ import annotations

import re
from typing import Any

from app.pipeline.errors import UnsafeMarkupError

# Visible output fields that are checked with extra scrutiny. These are the
# fields a reader actually sees; their values must be plain text.
VISIBLE_STRING_FIELDS = frozenset(
    {
        "publication_title",
        "edition_title",
        "deck",
        "opening",
        "title",
        "highlighted_insight",
        "continuity_note",
        "provenance_note",
        "question",
        "action",
        "evidence",
        "working_title",
        "purpose",
        "central_theme",
        "reader_value",
        "opening_intent",
        "next_edition_prompt",
    }
)

# Raw tag detection: a "<" followed by an optional slash and a letter, which
# covers <script>, <iframe>, <b>, </div>, etc. We do not attempt to parse HTML;
# any such sequence in a visible string field is rejected.
_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z]")

# Event-handler attribute patterns and javascript: URLs. These catch both
# inline handlers and dangerous URL schemes regardless of surrounding markup.
_UNSAFE_ATTR_RE = re.compile(
    r"(?i)\bon[a-z]+\s*=|javascript\s*:|vbscript\s*:|data\s*:\s*text/html"
)

# A short allow-list of URL schemes that may legitimately appear in
# free-text reader copy (plain http(s) links are fine; everything else in a
# URL position is suspect, but we only hard-reject the schemes above plus raw
# tags). This constant is exported so tests can assert the policy surface.
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})


def _contains_unsafe(content: str) -> str | None:
    """Return a short reason string if content is unsafe, else None."""
    if not isinstance(content, str):
        return None
    if _TAG_RE.search(content):
        return "raw HTML tag"
    if _UNSAFE_ATTR_RE.search(content):
        return "event handler or unsafe URL scheme"
    return None


def check_string(value: str, *, field_name: str) -> None:
    """Raise UnsafeMarkupError if a visible string contains unsafe markup."""
    reason = _contains_unsafe(value)
    if reason is not None:
        raise UnsafeMarkupError(
            f"unsafe markup rejected in '{field_name}': {reason}"
        )


def check_payload(payload: Any) -> None:
    """Recursively walk a parsed payload and reject unsafe strings.

    All string values are checked, not just the ones in VISIBLE_STRING_FIELDS,
    so that unsafe content cannot hide in a nested list, a metadata object, or
    a choice string. Field names are included in error messages only when the
    string is a dict value (so a reviewer knows where to look) but never
    include the offending text itself.
    """
    _walk(payload, path="")


def _walk(node: Any, *, path: str) -> None:
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
    # Numbers, bools, None: no markup risk.
    return
