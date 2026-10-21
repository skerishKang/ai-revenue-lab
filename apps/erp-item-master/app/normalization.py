"""Deterministic normalization rules for item-master fields.

Every rule here is reversible in meaning: it cleans a value, it never invents
one. A value that cannot be cleaned into a usable form stays unusable and is
reported for review instead of being replaced by a default.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from .contracts import FieldOrigin, FieldValue

#: Zero-width and other invisible characters that carry no meaning in a name.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")

#: Runs of whitespace, including the ideographic space, collapse to one space.
_WHITESPACE = re.compile(r"[\s\u3000]+")

#: Currency markers stripped before an amount is parsed.
_CURRENCY = re.compile(r"[₩￦원KRWUSD$€£]")

#: Thousands separators, including the Korean grouped form.
_GROUPING = re.compile(r"(?<=\d),(?=\d{3}(\D|$))")

#: A leading zero-padded or prefixed sign that Excel would read as a formula.
_FORMULA_PREFIX = ("=", "+", "-", "@")

#: Longest accepted price text. A longer token is treated as unparsable text.
MAX_PRICE_CHARS = 40
#: Longest accepted free-text field.
MAX_TEXT_CHARS = 500
#: Longest accepted item code.
MAX_CODE_CHARS = 64


def _fold_fullwidth_ascii(text: str) -> str:
    """Fold full-width ASCII printables to half-width.

    Korean catalogs mix the two forms freely, so ``６２０５`` and ``6205`` are
    the same code. Only the full-width ASCII block is folded, so Korean text,
    symbols and the ideographic space keep their meaning.
    """

    return "".join(
        chr(ord(ch) - 0xFEE0) if 0xFF01 <= ord(ch) <= 0xFF5E else ch for ch in text
    )


def normalize_text(value: object) -> str:
    """Trim, drop invisible characters, fold full-width ASCII and collapse runs."""

    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if not isinstance(value, str):
        value = str(value)
    cleaned = _INVISIBLE.sub("", value)
    cleaned = _fold_fullwidth_ascii(cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned)
    return cleaned.strip()[:MAX_TEXT_CHARS]


def normalize_code(value: object) -> str:
    """Normalize an item code to an uppercase, space-free identifier.

    A code is never generated. When the source has no code the result is an
    empty string and the caller records a review reason.
    """

    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    cleaned = cleaned.replace(" ", "").upper()
    return cleaned[:MAX_CODE_CHARS]


def parse_price(value: object) -> tuple[str | None, str | None]:
    """Parse a price cell into a plain decimal string.

    Returns ``(amount, error)``. ``amount`` is ``None`` when the cell holds no
    price at all and ``error`` explains why a present price could not be read.
    A price is never invented: an empty cell stays empty.
    """

    cleaned = normalize_text(value)
    if not cleaned:
        return None, None
    if len(cleaned) > MAX_PRICE_CHARS:
        return None, "price_too_long"
    without_currency = _CURRENCY.sub("", cleaned)
    without_grouping = _GROUPING.sub("", without_currency).strip()
    if not without_grouping:
        return None, "price_not_numeric"
    negative = without_grouping.startswith("-")
    digits = without_grouping[1:] if negative else without_grouping
    if not digits.isdigit():
        return None, "price_not_numeric"
    try:
        amount = Decimal(digits)
    except InvalidOperation:  # pragma: no cover - digits are already validated
        return None, "price_not_numeric"
    if amount < 0:
        return None, "price_negative"
    return (f"-{amount}" if negative else str(amount)), None


def looks_like_formula(value: str) -> bool:
    """Whether a text value would be read as a formula by a spreadsheet."""

    return value.startswith(_FORMULA_PREFIX)


def source_field(
    value: object,
    *,
    locator: str,
    confidence: str = "1",
    note: str = "",
) -> FieldValue:
    """Build a field value that was read straight from the source row."""

    cleaned = normalize_text(value)
    if not cleaned:
        return FieldValue(
            value="",
            origin=FieldOrigin.MISSING,
            confidence=Decimal("0"),
            source_locator=locator,
            note=note or "empty_in_source",
        )
    return FieldValue(
        value=cleaned,
        origin=FieldOrigin.SOURCE,
        confidence=Decimal(confidence),
        source_locator=locator,
        note=note,
    )


def rule_field(
    value: str,
    *,
    locator: str,
    confidence: str = "1",
    note: str = "",
) -> FieldValue:
    """Build a field value a normalization rule produced."""

    if not value:
        return FieldValue(
            value="",
            origin=FieldOrigin.MISSING,
            confidence=Decimal("0"),
            source_locator=locator,
            note=note or "empty_after_normalization",
        )
    return FieldValue(
        value=value,
        origin=FieldOrigin.RULE,
        confidence=Decimal(confidence),
        source_locator=locator,
        note=note,
    )


def normalize_form_name(value: str) -> str:
    """Produce the comparison key used for duplicate detection.

    The key keeps the characters that distinguish two products and drops the
    ones that only reflect how a supplier typed them: case, spaces around
    punctuation and repeated separators.
    """

    cleaned = normalize_text(value)
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[\s\-_/,.()\[\]]+", "", cleaned)
    return unicodedata.normalize("NFC", cleaned)
