"""#7273 후속: one product rule for every schedule turn.

Representative decision (2026-11-09): "캘린더·일정" belongs to the PADIEM
workspace calendar by default; only an explicit "구글 캘린더" names the
external Google one. The streaming route and the orchestration route both ask
``calendar_turn_product`` for this verdict, so the two surfaces cannot answer
the same ask differently. Explicit Drive/Gmail naming keeps its connector
lane; a broad Drive intent is untouched.

Calendar intent detection does not need a timezone: the existing planner
already separates calendar vocabulary from other asks (a missing timezone is
its own "clarify" op), so this rule delegates to that parser instead of
keeping a second vocabulary list.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .chat_connector_tools import google_calendar_named, google_connector_intent
from .native_calendar_intent import parse_native_calendar_intent

PRODUCT_PADIEM = "padiem"
PRODUCT_GOOGLE = "google"

_CALENDAR_OPS = frozenset({"read", "create_appointment", "clarify"})


def calendar_turn_product(
    user_text: Any, *, timezone_name: str | None = None
) -> str | None:
    """The product that owns this turn's calendar ask, or ``None``.

    Google only when the external calendar is named. Any other schedule ask
    (read, create, or the planner's clarification) stays with the PADIEM
    workspace calendar even when a Google grant exists.
    """

    if google_calendar_named(user_text):
        return PRODUCT_GOOGLE
    if google_connector_intent(user_text):
        # Explicit Drive/Gmail naming is not a calendar ask.
        return None
    if not isinstance(user_text, str) or not user_text.strip():
        return None
    try:
        op = parse_native_calendar_intent(
            user_text, timezone_name=timezone_name
        ).get("op")
    except Exception:  # noqa: BLE001 - an unparsable ask is not a calendar turn
        return None
    return PRODUCT_PADIEM if op in _CALENDAR_OPS else None


def native_calendar_turn_key(
    *,
    uid: str | None,
    conversation_id: str | None,
    message_count: int,
    latest_user_text: str | None,
    timezone_name: str | None = None,
    client_turn_id: str | None = None,
) -> str:
    """The one deterministic native-calendar turn key both routes use."""

    material = "|" + client_turn_id if client_turn_id is not None else ""
    digest = hashlib.sha256(
        "|".join(
            (str(latest_user_text), str(timezone_name or ""), material)
        ).encode("utf-8")
    ).hexdigest()[:16]
    return (
        "chat-"
        + str(uid)
        + "-"
        + str(conversation_id or "anon")
        + "-"
        + str(message_count)
        + "-"
        + digest
    )


__all__ = [
    "PRODUCT_GOOGLE",
    "PRODUCT_PADIEM",
    "calendar_turn_product",
    "native_calendar_turn_key",
]
