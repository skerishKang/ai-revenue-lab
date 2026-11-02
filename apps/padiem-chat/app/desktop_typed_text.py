"""#6460 — a value typed on the PC never rests in the record.

The dispatch row names a typed value only by its length, a digest prefix and
an unguessable reference. The value itself is deposited into the queue's
in-memory one-shot store and taken exactly once by the executor that claimed
that dispatch. The direct desktop lane and the Engine's model-driven loop both
hand their value over through this one door, so neither can grow a second
storage path.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

MAX_TYPED_CHARS = 20000


def text_marker(text: str) -> str:
    """Length plus eight hex digits of the digest: no way back to the text."""
    return "%d:%s" % (len(text), hashlib.sha256(text.encode("utf-8")).hexdigest()[:8])


def type_marker_op(text: str, ref: str) -> str:
    return "desktop:type\n#" + text_marker(text) + ":" + ref


def text_is_deliverable(text: Any) -> bool:
    return (isinstance(text, str) and bool(text) and len(text) <= MAX_TYPED_CHARS
            and "\x00" not in text and "\r" not in text)


async def deposit_typed_text(queue_client: Any, text: Any) -> str | None:
    """Hand one value to the one-shot store; return its reference or None.

    None means the value could not be handed over safely. The caller then does
    not create a dispatch at all: a typed value that would have to sit in the
    audit row is refused rather than recorded.
    """
    if not text_is_deliverable(text):
        return None
    call = getattr(queue_client, "call", None)
    if not callable(call):
        return None
    ref = secrets.token_hex(16)
    try:
        deposited = await call("deposit_desktop_text", ref=ref, text=text)
    except Exception:
        return None
    return ref if deposited is True else None
