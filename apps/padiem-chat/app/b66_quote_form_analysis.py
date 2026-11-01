"""Conservative suggestions for an owner-provided quote form's cell roles.

Suggestions never authorize writes. An ambiguous candidate must be confirmed by
the owner before a caller can rely on it.
"""
from __future__ import annotations

import re

_REF = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_LABELS = {
    "item": {"품목", "품명", "품목명", "description", "item"},
    "quantity": {"수량", "qty", "quantity"},
    "unit_price": {"단가", "unitprice", "price"},
    "amount": {"금액", "amount"},
    "subtotal": {"소계", "공급가액", "subtotal"},
    "tax": {"부가세", "부가가치세", "vat", "tax"},
    "total": {"총계", "합계", "총합계", "grandtotal", "total"},
    "date": {"견적일", "견적일자", "date"},
    "recipient": {"수신", "수신처", "거래처", "customer", "client"},
}
_HEADER_ROLES = frozenset({"item", "quantity", "unit_price", "amount"})


def _normalize(text):
    return re.sub(r"[\s:：()\[\]._-]+", "", text).casefold()


def _number(col):
    value = 0
    for ch in col:
        value = value * 26 + ord(ch) - 64
    return value


def _letters(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _parse(address):
    match = _REF.fullmatch(address or "")
    return (_number(match.group(1)), int(match.group(2))) if match else None


def _merged_anchor(address, merged):
    point = _parse(address)
    if not point:
        return None
    for entry in merged:
        bounds = entry.split(":")
        start = _parse(bounds[0])
        end = _parse(bounds[-1])
        if start and end and start[0] <= point[0] <= end[0] and start[1] <= point[1] <= end[1]:
            return bounds[0]
    return address


def analyze_quote_form(structure):
    """Return per-role candidates with evidence; duplicate roles remain ambiguous."""
    roles = {name: [] for name in _LABELS}
    for sheet in structure.get("sheets", []):
        name = sheet.get("name")
        if not isinstance(name, str):
            continue
        cells = {c["cell"]: c for c in sheet.get("cells", [])
                 if isinstance(c, dict) and _parse(c.get("cell"))}
        merged = sheet.get("merged", [])
        for address, cell in cells.items():
            if cell.get("formula") or not isinstance(cell.get("text"), str):
                continue
            label = _normalize(cell["text"])
            col, row = _parse(address)
            for role, synonyms in _LABELS.items():
                if label not in synonyms:
                    continue
                if role in _HEADER_ROLES:
                    target = _letters(col) + str(row + 1)
                else:
                    target = _letters(col + 1) + str(row)
                target = _merged_anchor(target, merged)
                existing = cells.get(target)
                if existing and not str(existing.get("text", "")).strip():
                    existing = None
                # Never propose overwriting a label, example value or merged label.
                if not target or target == address:
                    continue
                if existing and not existing.get("formula"):
                    continue
                if existing and role not in {"subtotal", "tax", "total", "amount"}:
                    continue
                roles[role].append({
                    "sheet": name, "cell": target, "label_cell": address,
                    "formula": bool(existing and existing.get("formula")),
                })
    return {
        role: {"candidates": values, "requires_confirmation": len(values) != 1}
        for role, values in roles.items()
    }
