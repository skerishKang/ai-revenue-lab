"""B66 quotation extraction routing toward the governed Space Bunny lane.

Source wiring only (#3212). This module builds bounded extraction requests
for the already-registered explicit manual lane and validates untrusted
model output before any QuoteDraft projection. It never calls a model,
never touches the network, and never carries credential material.

Governed lane (server-side only; never mirrored into B66 browser sources):

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
- image execution schema: the canonical B14 ``multimodal_contract`` shape
  (``text`` + exactly one ``image_url`` data URL, JPEG/PNG/WebP, decoded
  image <= 4 MiB, remote URL forbidden). This module emits that shape and
  the gateway revalidates it; no second image schema is defined here.
- extraction validation: behavioral parity with the model-independent
  ``reference/business-66-padiem-quote-v1/quote-extraction.js`` contract
  (untrusted input, strict nested types, ISO/calendar dates, validDays,
  bounded evidence/warnings, no totals math; missing facts stay ``None``
  and surface as ``UNKNOWN`` at the candidate projection).

Manual fallback is always off for the MVP (``allow_external_fallback`` is
``False`` on every request this module builds).
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from datetime import date
from pathlib import PurePath
from typing import Any, Callable

# Governed Space Bunny lane. Server-side routing metadata only. The B66
# browser must never import or inline these values (static contract guard).
B66_GOVERNED_ROUTE = "kilo/stealth-space-bunny-alpha"
B66_GOVERNED_UPSTREAM = "stealth/space-bunny-alpha"
B66_GOVERNED_PROVIDER = "kilo"
MANUAL_FALLBACK_ALLOWED = False

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

_TEXT_PROMPT = (
    "다음 견적서 텍스트에서 견적 추출 사실만 한국어로 추출하십시오. "
    "금액 합계·부가세 계산·유효일 계산은 하지 마십시오. "
    "없는 값은 UNKNOWN으로 유지하고 값을 지어내지 마십시오."
)
_IMAGE_PROMPT = (
    "다음 견적서 이미지에서 견적 추출 사실만 한국어로 추출하십시오. "
    "금액 합계·부가세 계산·유효일 계산은 하지 마십시오. "
    "없는 값은 UNKNOWN으로 유지하고 값을 지어내지 마십시오."
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


def _checked_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise B66ExtractionRoutingError("empty_text")
    text = value.strip()
    if len(text) > MAX_EXTRACTION_TEXT_CHARS:
        raise B66ExtractionRoutingError("text_too_large")
    return text


def _image_magic_matches(media_type: str, payload: bytes) -> bool:
    if media_type == "image/jpeg":
        return payload.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return payload.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return (
            len(payload) >= 12
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
        )
    return False


def _checked_image_bytes(payload: Any, *, media_type: str) -> bytes:
    if media_type not in _IMAGE_MEDIA:
        raise B66ExtractionRoutingError("unsupported_image_type")
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise B66ExtractionRoutingError("empty_file")
    raw = bytes(payload)
    if len(raw) > MAX_IMAGE_BYTES:
        raise B66ExtractionRoutingError("image_too_large")
    if not _image_magic_matches(media_type, raw):
        raise B66ExtractionRoutingError("image_magic_mismatch")
    return raw


def _checked_image_request_args(
    *, filename: str, media_type: Any
) -> tuple[str, str]:
    name = _safe_filename(filename)
    if not isinstance(media_type, str) or media_type not in _IMAGE_MEDIA:
        raise B66ExtractionRoutingError("unsupported_image_type")
    suffix = PurePath(name.lower()).suffix
    if suffix not in _IMAGE_MEDIA[media_type]:
        raise B66ExtractionRoutingError("media_extension_mismatch")
    return name, media_type


def build_text_extraction_request(
    normalized_text: Any,
    *,
    filename: Any,
    source_kind: Any = "native_document",
) -> dict[str, Any]:
    """Build a bounded text extraction request for the governed lane.

    Native path: PDF native text / DOCX / XLSX / other normalized native
    document text produced through the Core document authority.
    """
    if source_kind not in ("text", "native_document"):
        raise B66ExtractionRoutingError("unsupported_source_kind")
    name = _safe_filename(filename)
    text = _checked_text(normalized_text)
    return {
        "model": B66_GOVERNED_ROUTE,
        "messages": [
            {
                "role": "user",
                "content": f"{_TEXT_PROMPT}\n\n[출처: {name}]\n{text}",
            }
        ],
        "business14": {"allow_external_fallback": MANUAL_FALLBACK_ALLOWED},
        "b66": {
            "source_kind": source_kind,
            "filename": name,
            "route_mode": "manual",
            "fallback_allowed": MANUAL_FALLBACK_ALLOWED,
            "stream": B66_USE_STREAMING,
        },
    }


def build_image_extraction_request(
    image_bytes: Any,
    *,
    media_type: Any,
    filename: Any,
    source_kind: Any = "image",
) -> dict[str, Any]:
    """Build one canonical B14 multimodal request for the governed lane.

    Emits the canonical ``text`` + exactly one ``image_url`` data-URL shape
    (JPEG/PNG/WebP, base64 data URL only, decoded image <= 4 MiB). The B14
    gateway revalidates this shape with ``multimodal_contract``; nothing
    here redefines that contract.
    """
    if source_kind not in ("image", "scanned_pdf"):
        raise B66ExtractionRoutingError("unsupported_source_kind")
    name, safe_media = _checked_image_request_args(
        filename=filename, media_type=media_type
    )
    raw = _checked_image_bytes(image_bytes, media_type=safe_media)
    encoded = base64.b64encode(raw).decode("ascii")
    data_url = f"data:{safe_media};base64,{encoded}"
    if len(raw) > MAX_IMAGE_BYTES:
        raise B66ExtractionRoutingError("image_too_large")
    return {
        "model": B66_GOVERNED_ROUTE,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _IMAGE_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "business14": {
            "allow_external_fallback": MANUAL_FALLBACK_ALLOWED,
            "required_capabilities": ["image"],
        },
        "b66": {
            "source_kind": source_kind,
            "filename": name,
            "media_type": safe_media,
            "byte_size": len(raw),
            "route_mode": "manual",
            "fallback_allowed": MANUAL_FALLBACK_ALLOWED,
            "stream": B66_USE_STREAMING,
        },
    }


def build_scanned_pdf_extraction_requests(
    pdf_bytes: Any,
    *,
    name: Any,
    renderer: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Render a scanned PDF via the Core authority, then build image requests.

    Uses ``padiem_ai_core.pdf_render.render_pdf_pages`` (adopted PDFium
    adapter). No custom rendering or OCR lives here. One canonical
    multimodal request is produced per rendered page (the B14 contract
    carries exactly one image per request).
    """
    filename = _safe_filename(name)
    suffix = PurePath(filename.lower()).suffix
    if suffix != ".pdf":
        raise B66ExtractionRoutingError("unsupported_file_type")
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not pdf_bytes:
        raise B66ExtractionRoutingError("empty_file")

    if renderer is None:
        from padiem_ai_core.pdf_render import render_pdf_pages as _render

        renderer = _render

    try:
        result = renderer(
            name=filename, media_type="application/pdf", payload=bytes(pdf_bytes)
        )
    except B66ExtractionRoutingError:
        raise
    except Exception as exc:
        # Fail closed like the intake boundary: a missing render authority is
        # reported distinctly so callers never mistake it for a bad document.
        if getattr(exc, "code", None) == "pdf_render_dependency_unavailable":
            raise B66ExtractionRoutingError("render_authority_unavailable") from exc
        raise B66ExtractionRoutingError("document_render_failed") from exc

    pages = getattr(result, "pages", None)
    if not pages:
        raise B66ExtractionRoutingError("document_render_failed")

    requests: list[dict[str, Any]] = []
    stem = PurePath(filename).stem or "scan"
    for page in pages:
        data = getattr(page, "data", None)
        page_number = getattr(page, "page_number", len(requests) + 1)
        raw = _checked_image_bytes(data, media_type="image/png")
        page_name = f"{stem}-p{page_number}.png"
        requests.append(
            build_image_extraction_request(
                raw,
                media_type="image/png",
                filename=page_name,
                source_kind="scanned_pdf",
            )
        )
    if not requests:
        raise B66ExtractionRoutingError("document_render_failed")
    return requests


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
    number: int | float = float(compact) if "." in compact else int(compact)
    if not math.isfinite(number) or number < 0:
        _fail(code)
    return number


def _optional_positive_integer(value: Any, *, code: str) -> int | None:
    """Mirror JS ``optionalPositiveInteger``: bounded positive integers only."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        if not re.fullmatch(r"\d+", value):
            _fail(code)
        number = int(value)
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


def normalize_model_output(raw: Any) -> dict[str, Any]:
    """Validate untrusted model output as extraction evidence only.

    Behavioral parity with the model-independent browser boundary
    ``reference/business-66-padiem-quote-v1/quote-extraction.js``: bounded
    layout facts (extract/normalize/infer) with missing values kept as
    ``None`` (JS ``null``), never fabricated. One deliberate hardening over
    the JS: unknown keys fail closed here instead of being silently ignored.
    Computed totals/tax/validity projections are rejected so QuoteCore stays
    the calculation authority. Never raises for reviewable input; returns a
    bounded ``ok`` envelope instead. The B66 ``UNKNOWN`` sentinel is applied
    at the review/candidate projection, not inside this JS-shaped result.
    """
    try:
        if not isinstance(raw, dict):
            raise B66ExtractionRoutingError("invalid_extraction")
        if _contains_forbidden_key(raw):
            raise B66ExtractionRoutingError("computed_totals_forbidden")
        _reject_unknown_keys(raw, _ALLOWED_TOP_KEYS, "unsupported_extraction_field")

        source_raw = raw.get("source")
        if not isinstance(source_raw, dict):
            raise B66ExtractionRoutingError("invalid_source")
        _reject_unknown_keys(source_raw, _ALLOWED_SOURCE_KEYS, "unsupported_source_field")
        kind = _optional_text(
            source_raw.get("kind"),
            max_chars=MAX_SOURCE_KIND_CHARS,
            code="invalid_source_kind",
        )
        if not kind or kind not in _SOURCE_KINDS:
            raise B66ExtractionRoutingError("unsupported_source_kind")
        filename = _optional_text(
            source_raw.get("filename"),
            max_chars=MAX_FILENAME_CHARS,
            code="invalid_source_filename",
        )

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
    """Project validated extraction to a QuoteDraft candidate boundary.

    Missing (``None``) display facts become the explicit ``UNKNOWN`` sentinel
    so absent values stay visible instead of being fabricated. Provenance and
    review material (evidence/warnings) pass through untouched for the
    approval UI. The candidate carries source evidence only: totals/VAT math
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
