"""Safe structural classification for completed Provider responses (#1452).

The classifier is deliberately network-free and value-blind.  It accepts raw
JSON bytes solely so it can distinguish invalid JSON from valid JSON with an
unexpected top-level shape.  Diagnostics expose only a fixed allow-list of key
*names*, JSON container/type categories, and list counts.  Raw response values,
prompts, credentials, and arbitrary upstream key names are never returned.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

CATEGORY_INVALID_JSON = "invalid_json"
CATEGORY_NON_OBJECT = "non_object"
CATEGORY_MISSING_CHOICES = "missing_choices"
CATEGORY_CHOICES_NOT_LIST = "choices_not_list"
CATEGORY_CHOICES_EMPTY = "choices_empty"
CATEGORY_NORMAL_CHAT_COMPLETION = "normal_chat_completion"

# Key names that are part of the OpenAI-compatible completed-response contract.
# Values are intentionally never copied into diagnostics.
_SAFE_TOP_LEVEL_KEYS = frozenset(
    {
        "id",
        "object",
        "created",
        "model",
        "choices",
        "usage",
        "system_fingerprint",
    }
)


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    # classify_completed_response_structure only passes values decoded by json,
    # but fail closed without exposing an arbitrary Python class name.
    return "unknown"


@dataclass(frozen=True, slots=True)
class CompletedResponseStructure:
    """Value-blind structural metadata safe for forensic logging/tests."""

    category: str
    decoded_type: str
    safe_top_level_keys: tuple[str, ...] = ()
    choices_type: str | None = None
    choices_count: int | None = None

    def safe_log_fields(self) -> dict[str, str | int | None]:
        """Return a bounded diagnostic mapping containing no upstream values."""

        return {
            "category": self.category,
            "decoded_type": self.decoded_type,
            "safe_top_level_keys": ",".join(self.safe_top_level_keys),
            "choices_type": self.choices_type,
            "choices_count": self.choices_count,
        }


def classify_completed_response_structure(raw_body: bytes | str) -> CompletedResponseStructure:
    """Classify an OpenAI-compatible completed-response envelope safely.

    This function does not normalize or accept alternate Provider schemas.  It
    only explains why a body does or does not satisfy the current top-level
    completed-response contract.
    """

    try:
        payload: Any = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return CompletedResponseStructure(
            category=CATEGORY_INVALID_JSON,
            decoded_type="unparsed",
        )

    if not isinstance(payload, dict):
        return CompletedResponseStructure(
            category=CATEGORY_NON_OBJECT,
            decoded_type=_json_type_name(payload),
        )

    safe_keys = tuple(
        sorted(
            key
            for key in payload
            if isinstance(key, str) and key in _SAFE_TOP_LEVEL_KEYS
        )
    )

    if "choices" not in payload:
        return CompletedResponseStructure(
            category=CATEGORY_MISSING_CHOICES,
            decoded_type="object",
            safe_top_level_keys=safe_keys,
        )

    choices = payload["choices"]
    choices_type = _json_type_name(choices)
    if not isinstance(choices, list):
        return CompletedResponseStructure(
            category=CATEGORY_CHOICES_NOT_LIST,
            decoded_type="object",
            safe_top_level_keys=safe_keys,
            choices_type=choices_type,
        )

    if not choices:
        return CompletedResponseStructure(
            category=CATEGORY_CHOICES_EMPTY,
            decoded_type="object",
            safe_top_level_keys=safe_keys,
            choices_type="array",
            choices_count=0,
        )

    return CompletedResponseStructure(
        category=CATEGORY_NORMAL_CHAT_COMPLETION,
        decoded_type="object",
        safe_top_level_keys=safe_keys,
        choices_type="array",
        choices_count=len(choices),
    )
