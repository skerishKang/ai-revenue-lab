"""B66 conversational variable extraction for assigned Saved Quote Skills (#3303).

The model is allowed to map one user utterance into bounded variable fields only.
It never calculates totals, mutates the assigned Saved Quote Skill, or renders a
quotation. QuoteCore + the approved B66 renderer remain the only calculation and
rendering authorities in the browser/runtime that consumes this projection.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Protocol

MAX_CONVERSATION_CHARS = 4_000
MAX_RESULT_CHARS = 24_000
MAX_TEXT_CHARS = 2_000
MAX_MEMO_CHARS = 4_000
MAX_ITEMS = 100
MAX_ITEM_NAME_CHARS = 240
MAX_ITEM_DETAIL_CHARS = 240
MAX_ITEM_UNIT_CHARS = 80

TAX_MODES = frozenset({"EXCLUSIVE", "INCLUSIVE", "EXEMPT"})
_ALLOWED_TOP = frozenset(
    {"recipient", "quoteNo", "issueDate", "projectName", "items", "memo", "taxMode", "missing"}
)
_ALLOWED_RECIPIENT = frozenset({"company", "person", "address", "email"})
_ALLOWED_ITEM = frozenset(
    {"sequence", "name", "specification", "unit", "qty", "unitPrice", "rowNote"}
)
_ALLOWED_MISSING = frozenset(
    {"recipient", "quoteNo", "issueDate", "items", "memo", "taxMode"}
)
_FORBIDDEN_KEYS = frozenset(
    {
        "subtotal",
        "supply",
        "supplyAmount",
        "vat",
        "vatAmount",
        "grand",
        "grandTotal",
        "total",
        "amount",
        "computedTotals",
        "template",
        "internalTemplate",
        "sender",
        "approval",
        "fingerprint",
    }
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class B66QuoteConversationError(ValueError):
    pass


class B66QuoteConversationClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Any | None = None,
        additional_system_context: str | None = None,
        attachments: tuple = (),
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class B66QuoteConversationProjection:
    recipient: dict[str, str | None]
    quote_no: str | None
    issue_date: str | None
    items: tuple[dict[str, int | float | str], ...]
    memo: str | None
    tax_mode: str | None
    missing: tuple[str, ...]
    project_name: str | None = None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "recipient": dict(self.recipient),
            "quoteNo": self.quote_no,
            "issueDate": self.issue_date,
            "projectName": self.project_name,
            "items": [dict(item) for item in self.items],
            "memo": self.memo,
            "taxMode": self.tax_mode,
            "missing": list(self.missing),
        }


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in _FORBIDDEN_KEYS or _contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _optional_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise B66QuoteConversationError("invalid_text")
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > limit:
        raise B66QuoteConversationError("text_too_large")
    return text


def _optional_number(value: Any, *, positive: bool) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise B66QuoteConversationError("invalid_number")
    number = float(value)
    if not math.isfinite(number):
        raise B66QuoteConversationError("invalid_number")
    if positive and number <= 0:
        raise B66QuoteConversationError("invalid_number")
    if not positive and number < 0:
        raise B66QuoteConversationError("invalid_number")
    return int(number) if number.is_integer() else number


def normalize_conversation_output(raw: Any) -> B66QuoteConversationProjection:
    """Validate untrusted model output into variable-only quote fields."""

    if isinstance(raw, str):
        if not raw or len(raw) > MAX_RESULT_CHARS:
            raise B66QuoteConversationError("invalid_model_output")
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise B66QuoteConversationError("invalid_model_output") from exc
    if not isinstance(raw, dict):
        raise B66QuoteConversationError("invalid_model_output")
    if set(raw) - _ALLOWED_TOP:
        raise B66QuoteConversationError("unsupported_output_field")
    if _contains_forbidden_key(raw):
        raise B66QuoteConversationError("forbidden_output_field")

    recipient_raw = raw.get("recipient")
    if recipient_raw is None:
        recipient_raw = {}
    if not isinstance(recipient_raw, dict) or set(recipient_raw) - _ALLOWED_RECIPIENT:
        raise B66QuoteConversationError("invalid_recipient")
    recipient = {
        key: _optional_text(recipient_raw.get(key), limit=MAX_TEXT_CHARS)
        for key in ("company", "person", "address", "email")
    }

    quote_no = _optional_text(raw.get("quoteNo"), limit=120)
    issue_date = _optional_text(raw.get("issueDate"), limit=10)
    if issue_date is not None:
        if not _ISO_DATE_RE.fullmatch(issue_date):
            raise B66QuoteConversationError("invalid_issue_date")
        try:
            date.fromisoformat(issue_date)
        except ValueError as exc:
            raise B66QuoteConversationError("invalid_issue_date") from exc

    project_name = _optional_text(raw.get("projectName"), limit=MAX_ITEM_DETAIL_CHARS)

    items_raw = raw.get("items")
    if items_raw is None:
        items_raw = []
    if not isinstance(items_raw, list) or len(items_raw) > MAX_ITEMS:
        raise B66QuoteConversationError("invalid_items")
    items: list[dict[str, int | float | str]] = []