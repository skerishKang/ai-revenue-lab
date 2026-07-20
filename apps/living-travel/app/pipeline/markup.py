"""Markup rejection utilities for Living Travel."""

from __future__ import annotations

import re

_UNSAFE_PATTERNS = [
    re.compile(r"<script\b", re.IGNORECASE),
    re.compile(r"</script>", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"\bon\w+\s*=", re.IGNORECASE),
    re.compile(r"<iframe\b", re.IGNORECASE),
    re.compile(r"<object\b", re.IGNORECASE),
    re.compile(r"<embed\b", re.IGNORECASE),
    re.compile(r"<link\b", re.IGNORECASE),
    re.compile(r"<meta\b", re.IGNORECASE),
    re.compile(r"<style\b", re.IGNORECASE),
    re.compile(r"<form\b", re.IGNORECASE),
    re.compile(r"<input\b", re.IGNORECASE),
    re.compile(r"<svg\b", re.IGNORECASE),
    re.compile(r"expression\s*\(", re.IGNORECASE),
    re.compile(r"url\s*\(", re.IGNORECASE),
]

_UNSAFE_URL_SCHEMES = ["javascript:", "data:", "vbscript:"]


def check_unsafe_markup(text: str) -> list[str]:
    violations: list[str] = []
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(text):
            violations.append(f"unsafe pattern: {pattern.pattern}")

    lower = text.lower()
    for scheme in _UNSAFE_URL_SCHEMES:
        if scheme in lower:
            violations.append(f"unsafe URL scheme: {scheme}")

    return violations


def reject_if_unsafe(text: str) -> None:
    from app.pipeline.errors import MarkupError

    violations = check_unsafe_markup(text)
    if violations:
        raise MarkupError(
            "Unsafe markup detected: " + "; ".join(violations)
        )
