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
- extraction validation: mirrors the model-independent
  ``reference/business-66-padiem-quote-v1/quote-extraction.js`` contract
  (untrusted input, bounded facts, no totals math).

Manual fallback is always off for the MVP (``allow_external_fallback`` is
``False`` on every request this module builds).
"""

from __future__ import annotations

import base64
import binascii
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
MAX_ITEMS = 100
MAX_TEXT_CHARS = 2000
MAX_MEMO_CHARS = 8000
MAX_EVIDENCE_ITEMS = 8

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


def _optional_text(value: Any, *, max_chars: int) -> str:
    if value is None:
        return UNKNOWN
    if not isinstance(value, str):
        raise B66ExtractionRoutingError("invalid_text")
    text = value.strip()
    if not text:
        return UNKNOWN
    if len(text) > max_chars:
        raise B66ExtractionRoutingError("text_too_long")
    return text


def _optional_money_source(value: Any) -> str:
    if value is None:
        return UNKNOWN
    if isinstance(value, (int, float)):
        if not isinstance(value, bool) and value >= 0:
            return str(value)
        raise B66ExtractionRoutingError("invalid_money")
    if not isinstance(value, str):
        raise B66ExtractionRoutingError("invalid_money")
    text = value.strip().replace(",", "").replace(" ", "")
    if not text:
        return UNKNOWN
    if text == UNKNOWN:
        return UNKNOWN
    compact = text.replace(".", "", 1)
    if not compact.isdigit():
        raise B66ExtractionRoutingError("invalid_money")
    return value.strip()


def normalize_model_output(raw: Any) -> dict[str, Any]:
    """Validate untrusted model output as extraction evidence only.

    Mirrors the model-independent ``quote-extraction.js`` boundary: bounded
    layout facts (extract/normalize/infer) with missing values kept as
    ``UNKNOWN``. Computed totals/tax/validity projections are rejected so
    QuoteCore stays the calculation authority. Never raises for reviewable
    input; returns a bounded ``ok`` envelope instead.
    """
    try:
        if not isinstance(raw, dict):
            raise B66ExtractionRoutingError("invalid_extraction")
        if _contains_forbidden_key(raw):
            raise B66ExtractionRoutingError("computed_totals_forbidden")
        unknown_top = set(raw) - _ALLOWED_TOP_KEYS
        if unknown_top:
            raise B66ExtractionRoutingError("unsupported_extraction_field")

        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        kind = source.get("kind")
        if kind not in _SOURCE_KINDS:
            raise B66ExtractionRoutingError("unsupported_source_kind")

        sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
        recipient = (
            raw.get("recipient") if isinstance(raw.get("recipient"), dict) else {}
        )
        quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
        tax = raw.get("tax") if isinstance(raw.get("tax"), dict) else {}

        items_raw = raw.get("items", [])
        if items_raw is None:
            items_raw = []
        if not isinstance(items_raw, list) or len(items_raw) > MAX_ITEMS:
            raise B66ExtractionRoutingError("invalid_items")

        items: list[dict[str, str]] = []
        for entry in items_raw:
            if not isinstance(entry, dict):
                raise B66ExtractionRoutingError("invalid_items")
            unknown_item = set(entry) - {"description", "name", "quantity", "qty",
                                         "unit_price", "unitPrice", "amount",
                                         "amount_source"}
            if unknown_item:
                raise B66ExtractionRoutingError("unsupported_extraction_field")
            description = entry.get("description", entry.get("name"))
            quantity = entry.get("quantity", entry.get("qty"))
            unit_price = entry.get("unit_price", entry.get("unitPrice"))
            amount_source = entry.get("amount", entry.get("amount_source"))
            items.append(
                {
                    "description": _optional_text(
                        description, max_chars=MAX_TEXT_CHARS
                    ),
                    "quantity": _optional_money_source(quantity),
                    "unit_price": _optional_money_source(unit_price),
                    "amount_source": _optional_money_source(amount_source),
                }
            )

        tax_mode = tax.get("mode")
        if tax_mode is None or (isinstance(tax_mode, str) and not tax_mode.strip()):
            tax_mode = UNKNOWN
        elif tax_mode not in ("EXCLUSIVE", "INCLUSIVE", "EXEMPT"):
            raise B66ExtractionRoutingError("invalid_tax_mode")

        extraction = {
            "source_kind": kind,
            "quote_number": _optional_text(
                quote.get("quote_number", quote.get("quoteNo")),
                max_chars=MAX_TEXT_CHARS,
            ),
            "quote_date": _optional_text(
                quote.get("quote_date", quote.get("issueDate")),
                max_chars=10,
            ),
            "sender_company": _optional_text(
                sender.get("company", sender.get("sender")),
                max_chars=MAX_TEXT_CHARS,
            ),
            "recipient_company": _optional_text(
                recipient.get("company", recipient.get("recipient")),
                max_chars=MAX_TEXT_CHARS,
            ),
            "items": items,
            "supply_amount_source": _optional_money_source(
                raw.get("supply_amount_source", quote.get("supply_amount_source"))
                if isinstance(raw.get("supply_amount_source"), str)
                or isinstance(raw.get("supply_amount_source"), (int, float))
                or raw.get("supply_amount_source") is None
                else "##invalid##"
            ),
            "tax_mode": tax_mode,
            "memo": _optional_text(raw.get("memo"), max_chars=MAX_MEMO_CHARS),
        }

        unknowns = sorted(
            key for key, value in extraction.items()
            if value == UNKNOWN
        )
        if all(item["description"] == UNKNOWN for item in items) and items:
            unknowns.append("items")

        return {
            "ok": True,
            "extraction": extraction,
            "unknowns": unknowns,
            "warnings": [],
            "quotecore_authority": QUOTECORE_CALCULATION_AUTHORITY,
        }
    except B66ExtractionRoutingError as exc:
        return {"ok": False, "code": exc.code}


def project_to_quote_draft_candidate(
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """Project validated extraction to a QuoteDraft candidate boundary.

    The candidate carries source evidence only. Totals/VAT/validity math is
    never derived here; downstream QuoteCore owns every computed amount.
    """
    if not isinstance(normalized, dict) or not normalized.get("ok"):
        raise B66ExtractionRoutingError("invalid_extraction")
    extraction = normalized.get("extraction")
    if not isinstance(extraction, dict):
        raise B66ExtractionRoutingError("invalid_extraction")
    if _contains_forbidden_key(extraction):
        raise B66ExtractionRoutingError("computed_totals_forbidden")
    candidate = {
        "source_kind": extraction.get("source_kind", UNKNOWN),
        "quote_number": extraction.get("quote_number", UNKNOWN),
        "quote_date": extraction.get("quote_date", UNKNOWN),
        "sender_company": extraction.get("sender_company", UNKNOWN),
        "recipient_company": extraction.get("recipient_company", UNKNOWN),
        "items": extraction.get("items", []),
        "memo": extraction.get("memo", UNKNOWN),
        "unknowns": list(normalized.get("unknowns", [])),
        "derived_by": "quote-core-pending",
    }
    if "totals" in candidate or "vat" in candidate and isinstance(
        candidate.get("vat"), (int, float)
    ):
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
