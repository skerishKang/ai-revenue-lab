"""B66 quotation extraction routing under the successor-pending HOLD.

Source wiring only (#3212, retired by the owner final decision 2026-10-07).
This module validates untrusted model output before any QuoteDraft
projection and owns the bounded prompt contracts. It never calls a model,
never touches the network, and never carries credential material.

Extraction routing is FAIL-CLOSED while no successor model is selected:
the retired Space Bunny lane must never be executed and no new model may be
substituted silently. Every request builder raises the deterministic
``model_route_unavailable`` error instead of emitting any model request.

Retired historical lane identity (server-side metadata only; never mirrored
into B66 browser sources, never executed):

```text
B66_TEXT_PRIMARY=stealth/space-bunny-alpha
B66_VISION_PRIMARY=stealth/space-bunny-alpha
B14_ROUTE_ID=kilo/stealth-space-bunny-alpha
```

Reuse (no second authority):

- binary document identity/parsing: ``padiem_ai_core`` document authority
  (same port as ``file_intake.py``);
- scanned-PDF raster: ``padiem_ai_core.pdf_render.render_pdf_pages``
  (adopted PDFium adapter, full-page PNG previews);
- extraction validation: behavioral parity with the model-independent
  ``reference/business-66-padiem-quote-v1/quote-extraction.js`` contract
  (untrusted input, strict nested types, ISO/calendar dates, validDays,
  bounded evidence/warnings, no totals math; missing facts stay ``None``
  and surface as ``UNKNOWN`` at the candidate projection).

Manual fallback is always off for the MVP (``allow_external_fallback`` is
``False`` on every request this module builds).
"""

from __future__ import annotations

import math
import re
from datetime import date
from pathlib import PurePath
from typing import Any, Callable

# Retired historical lane identity (owner final retirement decision,
# 2026-10-07). Metadata only: never an executable route, never a request
# target, never a fallback. B66 extraction stays fail-closed under the
# successor-pending HOLD; no successor model is substituted here.
B66_GOVERNED_ROUTE = "kilo/stealth-space-bunny-alpha"
B66_GOVERNED_UPSTREAM = "stealth/space-bunny-alpha"
B66_GOVERNED_PROVIDER = "kilo"
MANUAL_FALLBACK_ALLOWED = False

# Deterministic fail-closed code raised by every request builder while the
# extraction lane has no executable model (successor pending, retired lane
# never re-activated, no silent substitution).
B66_MODEL_ROUTE_UNAVAILABLE = "model_route_unavailable"

# Execution stays on the canonical non-streaming completion path (#3212:
# staged SSE stays ``model=b14/auto`` text-only and is untouched here).
B66_USE_STREAMING = False

# QuoteCore remains the only amount/tax calculation authority. Extracted
# amounts are source evidence only and are never summed here.
QUOTECORE_CALCULATION_AUTHORITY = True

# Missing model facts stay explicitly unknown; fabrication is forbidden.
UNKNOWN = "UNKNOWN"

# Intake-side bounds reused from the B14/file-intake contract (decoded image
# <= 4 MiB; native text bounded for the gateway text cap).
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_EXTRACTION_TEXT_CHARS = 32000
# Validation bounds below mirror the deployed browser contract
# ``reference/business-66-padiem-quote-v1/quote-extraction.js`` exactly.
MAX_ITEMS = 100
MAX_TEXT_CHARS = 2000
MAX_MEMO_CHARS = 8000
MAX_FILENAME_CHARS = 255
MAX_SOURCE_KIND_CHARS = 64
MAX_EVIDENCE = 200
MAX_EVIDENCE_SNIPPET_CHARS = 1000
MAX_WARNINGS = 50

SENDER_FIELDS = ("company", "rep", "bizNo", "address", "phone", "email")
RECIPIENT_FIELDS = ("company", "person", "address", "email")
TAX_MODES = frozenset({"EXCLUSIVE", "INCLUSIVE", "EXEMPT"})
_ALLOWED_SOURCE_KEYS = frozenset({"kind", "filename"})
_ALLOWED_QUOTE_KEYS = frozenset({"quoteNo", "issueDate", "validDays"})
_ALLOWED_TAX_KEYS = frozenset({"mode"})
_ALLOWED_ITEM_KEYS = frozenset({"name", "qty", "unitPrice"})
_ALLOWED_EVIDENCE_KEYS = frozenset({"field", "page", "snippet", "confidence"})

_IMAGE_MEDIA: dict[str, frozenset[str]] = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
}

_SOURCE_KINDS = frozenset({"text", "native_document", "image", "scanned_pdf"})

# Model output may only carry bounded extraction facts. Computed money/tax
# projections are forbidden anywhere in the payload so QuoteCore math can
# never be bypassed by model text.
_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "totals",
        "grand_total",
        "grandTotal",
        "vat_computed",
        "vat_amount_computed",
        "total_computed",
        "valid_until",
        "validUntil",
        "valid_until_computed",
        "amount_computed",
    }
)

_ALLOWED_TOP_KEYS = frozenset(
    {
        "source",
        "sender",
        "recipient",
        "quote",
        "items",
        "tax",
        "memo",
        "evidence",
        "warnings",
    }
)

_EXTRACTION_JSON_CONTRACT = (
    "반드시 JSON 객체 하나만 반환하십시오. 마크다운/설명 문장을 덧붙이지 마십시오. "
    "최상위 키는 sender, recipient, quote, items, tax, memo, evidence, warnings만 사용하십시오. "
    "source는 서버가 소유하므로 반환하지 마십시오. "
    "sender는 견적서를 보내거나 공급하는 쪽(예: 공급자/공급하는 자/발신자)이고 "
    "recipient는 견적서를 받는 쪽(예: 공급받는 자/수신처/고객/귀하)입니다. "
    "두 역할이 모두 보이면 라벨에 따라 반드시 구분하고 sender 값을 recipient에 복사하거나 반대로 복사하지 마십시오. "
    "sender는 company/rep/bizNo/address/phone/email, recipient는 company/person/address/email, "
    "quote는 quoteNo/issueDate/validDays, items는 name/qty/unitPrice, tax는 mode만 사용하십시오. "
    "evidence 항목은 field/page/snippet/confidence만 사용하십시오. "
    "없는 값은 문자열 UNKNOWN이 아니라 JSON null로 반환하십시오. "
    "금액 합계·부가세 금액·총액·유효일은 계산하거나 만들어내지 마십시오."
)
class B66ExtractionRoutingError(ValueError):
    """Bounded extraction-routing failure (fail closed, Korean-safe code)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_filename(value: Any) -> str:
    if not isinstance(value, str):
        raise B66ExtractionRoutingError("invalid_file_name")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 255:
        raise B66ExtractionRoutingError("invalid_file_name")
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise B66ExtractionRoutingError("invalid_file_name")
    return cleaned


def build_text_extraction_request(
    normalized_text: Any,
    *,
    filename: Any,
    source_kind: Any = "native_document",
) -> dict[str, Any]:
    """Fail closed: no executable extraction lane exists (successor pending).

    The retired Space Bunny lane must never be requested and no successor
    model may be substituted silently, so every request builder raises the
    deterministic ``model_route_unavailable`` error before any model request
    shape could exist.
    """
    raise B66ExtractionRoutingError(B66_MODEL_ROUTE_UNAVAILABLE)


def build_image_extraction_request(
    image_bytes: Any,
    *,
    media_type: Any,
    filename: Any,
    source_kind: Any = "image",
) -> dict[str, Any]:
    """Fail closed: no executable extraction lane exists (successor pending).

    See ``build_text_extraction_request``; every request builder raises the
    deterministic ``model_route_unavailable`` error.
    """
    raise B66ExtractionRoutingError(B66_MODEL_ROUTE_UNAVAILABLE)


def build_scanned_pdf_extraction_requests(
    pdf_bytes: Any,
    *,
    name: Any,
    renderer: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Fail closed: no executable extraction lane exists (successor pending).

    See ``build_text_extraction_request``; the scanned-PDF builder also raises
    the deterministic ``model_route_unavailable`` error without rendering any
    page and without producing any model request.
    """
    raise B66ExtractionRoutingError(B66_MODEL_ROUTE_UNAVAILABLE)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _FORBIDDEN_OUTPUT_KEYS:
                return True
            if _contains_forbidden_key(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _fail(code: str) -> None:
    raise B66ExtractionRoutingError(code)


def _reject_unknown_keys(mapping: dict[str, Any], allowed: frozenset[str], code: str) -> None:
    unknown = set(mapping) - set(allowed)
    if unknown:
        raise B66ExtractionRoutingError(code)


def _optional_text(value: Any, *, max_chars: int, code: str = "invalid_text") -> str | None:
    """Mirror JS ``optionalText``: missing/blank stays ``None``, never fabricated."""
    if value is None:
        return None
    if not isinstance(value, str):
        _fail(code)
    text = value.strip()
    if not text:
        return None
    # UNKNOWN is a UI/candidate display sentinel, never a valid model fact.
    # Model prompts require JSON null for missing values.
    if text == UNKNOWN:
        _fail("reserved_unknown_sentinel")
    if len(text) > max_chars:
        _fail(code)
    return text


def _optional_money(value: Any, *, code: str = "invalid_money") -> int | float | None:
    """Mirror JS ``optionalMoney``: bounded non-negative amounts as numbers."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        _fail(code)
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value < 0:
            _fail(code)
        return value
    if not isinstance(value, str):
        _fail(code)
    compact = "".join(char for char in value if not char.isspace()).replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", compact):
        _fail(code)
    try:
        number: int | float = float(compact) if "." in compact else int(compact)
    except (ValueError, OverflowError):
        # Untrusted oversized digit strings (e.g. beyond the interpreter's
        # integer-string limit) fail closed with the contract code, never as
        # a raw conversion exception escaping normalize_model_output().
        _fail(code)
    if not math.isfinite(number) or number < 0:
        _fail(code)
    return number


def _optional_positive_integer(value: Any, *, code: str) -> int | None:
    """Mirror JS ``optionalPositiveInteger``: bounded positive integers only.

    Like the JS (``/^\\d+$/.test(value.trim())`` → ``Number(value.trim())``),
    surrounding whitespace is trimmed before validation, so ``"30 "`` is 30
    while blank-only strings still fail closed.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        if not re.fullmatch(r"\d+", trimmed):
            _fail(code)
        try:
            number = int(trimmed)
        except (ValueError, OverflowError):
            # See _optional_money: oversized untrusted digit strings fail
            # closed with the contract code, never as a raw exception.
            _fail(code)
    elif isinstance(value, bool):
        _fail(code)
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        _fail(code)
    if number <= 0:
        _fail(code)
    return number


def _optional_iso_date(value: Any) -> str | None:
    """Mirror JS ``optionalISODate``: ``YYYY-MM-DD`` plus a real calendar date."""
    text = _optional_text(value, max_chars=10, code="invalid_issue_date")
    if text is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        _fail("invalid_issue_date")
    year, month, day = int(text[0:4]), int(text[5:7]), int(text[8:10])
    try:
        date(year, month, day)
    except ValueError:
        _fail("invalid_issue_date")
    return text


def _normalize_party(raw: Any, fields: tuple[str, ...], section: str) -> dict[str, str | None]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        _fail(f"invalid_{section}")
    _reject_unknown_keys(raw, frozenset(fields), f"unsupported_{section}_field")
    return {
        field: _optional_text(
            raw.get(field),
            max_chars=MAX_TEXT_CHARS,
            code=f"invalid_{section}_{field}",
        )
        for field in fields
    }


def _normalize_items(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail("invalid_items")
    if len(raw) > MAX_ITEMS:
        _fail("too_many_items")
    items: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            _fail(f"invalid_item_{index}")
        _reject_unknown_keys(entry, _ALLOWED_ITEM_KEYS, "unsupported_item_field")
        items.append(
            {
                "name": _optional_text(
                    entry.get("name"),
                    max_chars=MAX_TEXT_CHARS,
                    code="invalid_item_name",
                ),
                "qty": _optional_money(entry.get("qty"), code="invalid_item_qty"),
                "unitPrice": _optional_money(
                    entry.get("unitPrice"), code="invalid_item_unit_price"
                ),
            }
        )
    return items


def _normalize_evidence(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail("invalid_evidence")
    if len(raw) > MAX_EVIDENCE:
        _fail("too_much_evidence")
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            _fail(f"invalid_evidence_{index}")
        _reject_unknown_keys(entry, _ALLOWED_EVIDENCE_KEYS, "unsupported_evidence_field")
        field = _optional_text(
            entry.get("field"),
            max_chars=MAX_TEXT_CHARS,
            code="invalid_evidence_field",
        )
        if not field:
            _fail("invalid_evidence_field")
        page_raw = entry.get("page")
        page = (
            None
            if page_raw is None
            else _optional_positive_integer(page_raw, code="invalid_evidence_page")
        )
        snippet = _optional_text(
            entry.get("snippet"),
            max_chars=MAX_EVIDENCE_SNIPPET_CHARS,
            code="invalid_evidence_snippet",
        )
        confidence_raw = entry.get("confidence")
        confidence: int | float | None = None
        if confidence_raw is not None:
            if (
                isinstance(confidence_raw, bool)
                or not isinstance(confidence_raw, (int, float))
                or not math.isfinite(confidence_raw)
                or confidence_raw < 0
                or confidence_raw > 1
            ):
                _fail("invalid_evidence_confidence")
            confidence = confidence_raw
        entries.append(
            {"field": field, "page": page, "snippet": snippet, "confidence": confidence}
        )
    return entries


def _normalize_warnings(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail("invalid_warnings")
    if len(raw) > MAX_WARNINGS:
        _fail("too_many_warnings")
    normalized: list[str] = []
    for entry in raw:
        text = _optional_text(entry, max_chars=MAX_TEXT_CHARS, code="invalid_warning")
        if not text:
            _fail("invalid_warning")
        normalized.append(text)
    return normalized


def normalize_model_output(
    raw: Any,
    *,
    source_kind: Any,
    filename: Any,
) -> dict[str, Any]:
    """Validate untrusted model output as extraction evidence only.

    Source identity is server-owned: ``source_kind`` and ``filename`` come
    from the trusted B66 intake/render boundary, never from the model. For
    compatibility, a model payload may include ``source`` only when it exactly
    matches the trusted values; a mismatch fails closed.

    Behavioral parity with the model-independent browser boundary
    ``reference/business-66-padiem-quote-v1/quote-extraction.js``: bounded
    extraction facts with missing values kept as ``None`` (JS ``null``),
    never fabricated. The literal ``"UNKNOWN"`` is reserved for later
    candidate/UI display and is rejected as a model fact. Unknown keys fail
    closed here instead of being silently ignored. Computed totals/tax/validity
    projections are rejected so QuoteCore stays the calculation authority.
    """
    try:
        if source_kind not in _SOURCE_KINDS:
            raise B66ExtractionRoutingError("unsupported_source_kind")
        trusted_filename = _safe_filename(filename)

        if not isinstance(raw, dict):
            raise B66ExtractionRoutingError("invalid_extraction")
        if _contains_forbidden_key(raw):
            raise B66ExtractionRoutingError("computed_totals_forbidden")
        _reject_unknown_keys(raw, _ALLOWED_TOP_KEYS, "unsupported_extraction_field")

        source_raw = raw.get("source")
        if source_raw is not None:
            if not isinstance(source_raw, dict):
                raise B66ExtractionRoutingError("invalid_source")
            _reject_unknown_keys(
                source_raw, _ALLOWED_SOURCE_KEYS, "unsupported_source_field"
            )
            model_kind = source_raw.get("kind")
            model_filename = source_raw.get("filename")
            if model_kind is not None and model_kind != source_kind:
                raise B66ExtractionRoutingError("source_provenance_mismatch")
            if model_filename is not None and model_filename != trusted_filename:
                raise B66ExtractionRoutingError("source_provenance_mismatch")

        kind = source_kind
        filename = trusted_filename

        sender = _normalize_party(raw.get("sender"), SENDER_FIELDS, "sender")
        recipient = _normalize_party(raw.get("recipient"), RECIPIENT_FIELDS, "recipient")

        quote_raw = raw.get("quote")
        if quote_raw is None:
            quote_raw = {}
        if not isinstance(quote_raw, dict):
            raise B66ExtractionRoutingError("invalid_quote")
        _reject_unknown_keys(quote_raw, _ALLOWED_QUOTE_KEYS, "unsupported_quote_field")
        quote = {
            "quoteNo": _optional_text(
                quote_raw.get("quoteNo"),
                max_chars=MAX_TEXT_CHARS,
                code="invalid_quote_number",
            ),
            "issueDate": _optional_iso_date(quote_raw.get("issueDate")),
            "validDays": _optional_positive_integer(
                quote_raw.get("validDays"), code="invalid_valid_days"
            ),
        }

        warnings = _normalize_warnings(raw.get("warnings"))

        tax_raw = raw.get("tax")
        tax_mode: str | None = None
        if tax_raw is not None:
            if not isinstance(tax_raw, dict):
                raise B66ExtractionRoutingError("invalid_tax")
            _reject_unknown_keys(tax_raw, _ALLOWED_TAX_KEYS, "unsupported_tax_field")
            mode = tax_raw.get("mode")
            if mode is not None and mode != "":
                if not isinstance(mode, str):
                    raise B66ExtractionRoutingError("invalid_tax_mode")
                if mode in TAX_MODES:
                    tax_mode = mode
                else:
                    warnings = [*warnings, "unknown_tax_mode"]

        extraction = {
            "source": {"kind": kind, "filename": filename},
            "sender": sender,
            "recipient": recipient,
            "quote": quote,
            "items": _normalize_items(raw.get("items")),
            "tax": {"mode": tax_mode},
            "memo": _optional_text(
                raw.get("memo"), max_chars=MAX_MEMO_CHARS, code="invalid_memo"
            ),
            "evidence": _normalize_evidence(raw.get("evidence")),
            "warnings": warnings,
        }

        unknowns: list[str] = []
        for field_name, value in sender.items():
            if value is None:
                unknowns.append(f"sender.{field_name}")
        for field_name, value in recipient.items():
            if value is None:
                unknowns.append(f"recipient.{field_name}")
        for field_name, value in quote.items():
            if value is None:
                unknowns.append(f"quote.{field_name}")
        if tax_mode is None:
            unknowns.append("tax.mode")
        if extraction["memo"] is None:
            unknowns.append("memo")
        if not extraction["items"]:
            unknowns.append("items")

        return {
            "ok": True,
            "extraction": extraction,
            "unknowns": sorted(unknowns),
            "quotecore_authority": QUOTECORE_CALCULATION_AUTHORITY,
        }
    except B66ExtractionRoutingError as exc:
        return {"ok": False, "code": exc.code}


def _unknown_or(value: Any) -> Any:
    return UNKNOWN if value is None else value


def project_to_quote_draft_candidate(
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """Project validated extraction to the legacy #3147 QuoteDraft seam.

    This compatibility projection is not the Saved Quote Skill approval path
    introduced by #3218 and must not bypass its fixed/default/variable review.
    Missing (``None``) display facts become the explicit ``UNKNOWN`` sentinel
    so absent values stay visible instead of being fabricated. Provenance and
    review material (evidence/warnings) pass through untouched. Totals/VAT math
    is never derived here; downstream QuoteCore owns every computed amount.
    """
    if not isinstance(normalized, dict) or not normalized.get("ok"):
        raise B66ExtractionRoutingError("invalid_extraction")
    extraction = normalized.get("extraction")
    if not isinstance(extraction, dict):
        raise B66ExtractionRoutingError("invalid_extraction")
    if _contains_forbidden_key(extraction):
        raise B66ExtractionRoutingError("computed_totals_forbidden")
    source = extraction.get("source") or {}
    quote = extraction.get("quote") or {}
    sender = extraction.get("sender") or {}
    recipient = extraction.get("recipient") or {}
    tax = extraction.get("tax") or {}
    candidate = {
        "source_kind": source.get("kind", UNKNOWN),
        "filename": _unknown_or(source.get("filename")),
        "quote_number": _unknown_or(quote.get("quoteNo")),
        "quote_date": _unknown_or(quote.get("issueDate")),
        "valid_days": _unknown_or(quote.get("validDays")),
        "sender": {key: _unknown_or(value) for key, value in sender.items()},
        "recipient": {key: _unknown_or(value) for key, value in recipient.items()},
        "items": [dict(item) for item in (extraction.get("items") or [])],
        "tax_mode": _unknown_or(tax.get("mode")),
        "memo": _unknown_or(extraction.get("memo")),
        "unknowns": list(normalized.get("unknowns", [])),
        "review": {
            "evidence": [dict(entry) for entry in (extraction.get("evidence") or [])],
            "warnings": list(extraction.get("warnings") or []),
        },
        "derived_by": "quote-core-pending",
    }
    if "totals" in candidate:
        raise B66ExtractionRoutingError("computed_totals_forbidden")
    return candidate


__all__ = [
    "B66_GOVERNED_PROVIDER",
    "B66_MODEL_ROUTE_UNAVAILABLE",
    "B66_GOVERNED_ROUTE",
    "B66_GOVERNED_UPSTREAM",
    "B66_USE_STREAMING",
    "B66ExtractionRoutingError",
    "MANUAL_FALLBACK_ALLOWED",
    "MAX_EXTRACTION_TEXT_CHARS",
    "MAX_IMAGE_BYTES",
    "QUOTECORE_CALCULATION_AUTHORITY",
    "UNKNOWN",
    "build_image_extraction_request",
    "build_scanned_pdf_extraction_requests",
    "build_text_extraction_request",
    "normalize_model_output",
    "project_to_quote_draft_candidate",
]
