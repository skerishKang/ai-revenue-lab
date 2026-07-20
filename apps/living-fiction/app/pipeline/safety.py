"""Prohibited identifier checking — real persons, brands, franchises, characters.

Deterministic check against an explicit prohibited set. Does not prove
universal originality — only that configured prohibited names are absent.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from app.pipeline.errors import ProhibitedContentError

# Default prohibited identifiers — well-known franchises, characters, brands,
# and real-person patterns that must never appear in synthetic fiction.
# This is an explicit deny-list, not a semantic similarity check.
DEFAULT_PROHIBITED_IDENTIFIERS: tuple[str, ...] = (
    # Franchise / copyrighted world names
    "harry potter", "hogwarts", "star wars", "star trek", "lord of the rings",
    "middle earth", "marvel", "dc comics", "batman", "superman", "spider-man",
    "spiderman", "avengers", "x-men", "game of thrones", "westeros",
    "sherlock holmes", "221b baker", "watson", "moriarty",
    "conjuring", "insidious", "friday the 13th",
    "naruto", "one piece", "dragon ball", "bleach", "attack on titan",
    "studio ghibli", "totoro", "spirited away",
    # Korean franchises
    "along with the gods", "train to busan", "squid game",
    "the silent sea", "kingdom",
    # Real company/brand names that must not appear as in-world entities
    "google", "samsung", "apple", "microsoft", "openai", "anthropic",
    # Real persons (common reference patterns)
    "elon musk", "일론 머스크",
    "mark zuckerberg", "마크 저커버그",
    "jeff bezos", "제프 베조스",
    "bill gates", "빌 게이츠",
    # Korean franchise character names
    "셜록 홈즈", "홈즈", "왓슨", "모리아티",
)

# Content safety prohibited patterns
_SAFETY_PATTERNS = [
    (re.compile(r"미성년자?\s*성\s*행위|minor\s+sexual", re.IGNORECASE), "sexual content involving minors"),
    (re.compile(r"성\s*폭력|sexual\s+violence", re.IGNORECASE), "sexual violence"),
    (re.compile(r"고문\s*장면|graphic\s+torture", re.IGNORECASE), "graphic torture"),
]


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


class IdentifierPolicy:
    """Prohibited identifier and content-safety policy."""

    def __init__(
        self,
        prohibited_identifiers: Iterable[str] | None = None,
    ):
        raw = (
            tuple(prohibited_identifiers)
            if prohibited_identifiers is not None
            else DEFAULT_PROHIBITED_IDENTIFIERS
        )
        self._prohibited = frozenset(_normalize(tok) for tok in raw)

    @property
    def prohibited_identifiers(self) -> frozenset[str]:
        return self._prohibited

    def check_text(self, text: str, *, field_name: str = "text") -> None:
        """Raise ProhibitedContentError if text contains a prohibited identifier."""
        if not isinstance(text, str):
            return
        normalized = _normalize(text)
        for token in self._prohibited:
            if _word_boundary_contains(normalized, token):
                raise ProhibitedContentError(
                    f"prohibited identifier '{token}' rejected in '{field_name}'"
                )

    def check_safety(self, text: str, *, field_name: str = "text") -> None:
        """Raise ProhibitedContentError if text matches a safety violation pattern."""
        if not isinstance(text, str):
            return
        for pattern, reason in _SAFETY_PATTERNS:
            if pattern.search(text):
                raise ProhibitedContentError(
                    f"prohibited content ({reason}) rejected in '{field_name}'"
                )

    def check_payload(self, payload) -> None:
        """Recursively check all string values in a payload."""
        _walk_and_check(payload, path="", policy=self)


def _word_boundary_contains(haystack: str, needle: str) -> bool:
    """Check if needle appears as a word-boundary substring in haystack."""
    pattern = re.compile(
        r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])",
        re.IGNORECASE,
    )
    return bool(pattern.search(haystack))


def _walk_and_check(node, *, path: str, policy: IdentifierPolicy) -> None:
    if isinstance(node, str):
        policy.check_text(node, field_name=path or "value")
        policy.check_safety(node, field_name=path or "value")
        return
    if isinstance(node, list):
        for idx, item in enumerate(node):
            _walk_and_check(item, path=f"{path}[{idx}]" if path else f"[{idx}]", policy=policy)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            _walk_and_check(value, path=child_path, policy=policy)
        return
    return
