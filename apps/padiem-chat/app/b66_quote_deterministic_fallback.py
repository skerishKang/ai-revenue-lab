"""Deterministic Korean free-form fallback for the B66 first MVP.

This parser is intentionally narrow. It is used only when the bounded model
interpreter is unavailable. It extracts literal quote facts from a small,
reviewed Korean grammar and returns None for anything ambiguous.

It never computes totals, invents prices, selects a Saved Quote Skill, mutates
CompanyProfile, or renders a quote.
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_UNIT = r"(?:미터|m|M|개|ea|EA|대|식|장|kg|KG|킬로그램|세트|박스)"

_STEM_RE = re.compile(
    rf"^\s*(?P<recipient>[^,\n]{{1,80}}?)에\s+"
    rf"(?P<item>[^,\n]{{1,120}}?)\s+"
    rf"(?P<qty>{_NUMBER})\s*(?P<unit>{_UNIT})(?=\s|,|$)",
)

_PRICE_RE = re.compile(
    rf"(?:미터당|m당|M당|개당|ea당|EA당|대당|식당|장당|kg당|KG당|킬로그램당|세트당|박스당|"
    rf"단가(?:는|가)?|단가)\s*[:=]?\s*(?P<price>{_NUMBER})\s*원",
)

_TAX_PATTERNS = (
    (re.compile(r"부가세\s*(?:별도|제외)"), "EXCLUSIVE"),
    (re.compile(r"부가세\s*(?:포함|포함가)"), "INCLUSIVE"),
    (re.compile(r"(?:부가세\s*)?(?:면세|비과세)"), "EXEMPT"),
)

_UNIT_CANONICAL = {
    "m": "미터",
    "M": "미터",
    "ea": "개",
    "EA": "개",
    "kg": "kg",
    "KG": "kg",
}


def _number(raw: str) -> int | float:
    value = float(raw.replace(",", ""))
    return int(value) if value.is_integer() else value


def parse_b66_mvp_fallback(message: str) -> dict[str, Any] | None:
    """Extract one simple quote item from explicit Korean wording.

    Accepted MVP shape:
      <recipient>에 <item> <qty><unit> [, <unit/단가>당 <price>원] [, 부가세 ...]

    A pending follow-up may append the missing unit price on a later line.
    Anything outside this confidence boundary returns None.
    """

    if not isinstance(message, str):
        return None
    text = message.strip()
    if not text or len(text) > 4_000:
        return None

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    match = _STEM_RE.search(first_line)
    if match is None:
        return None

    recipient = " ".join(match.group("recipient").split())
    item_name = " ".join(match.group("item").split())
    if not recipient or not item_name:
        return None

    try:
        qty = _number(match.group("qty"))
    except ValueError:
        return None
    if qty <= 0:
        return None

    unit_raw = match.group("unit")
    unit = _UNIT_CANONICAL.get(unit_raw, unit_raw)

    item: dict[str, Any] = {
        "name": item_name,
        "qty": qty,
        "unit": unit,
    }

    price_match = _PRICE_RE.search(text)
    if price_match is not None:
        try:
            unit_price = _number(price_match.group("price"))
        except ValueError:
            return None
        if unit_price < 0:
            return None
        item["unitPrice"] = unit_price

    tax_mode = None
    for pattern, mode in _TAX_PATTERNS:
        if pattern.search(text):
            tax_mode = mode
            break

    result: dict[str, Any] = {
        "recipient": {"company": recipient},
        "items": [item],
        "missing": [],
    }
    if tax_mode is not None:
        result["taxMode"] = tax_mode
    return result
