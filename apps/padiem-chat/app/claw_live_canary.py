"""#3930 bounded live SSE canary admission by canonical Control Plane subject only.

The single allowlisted subject is server-owned secret configuration, never a
cookie, request field, header, model ID, or public capability response.
"""
from __future__ import annotations

import hmac
import re

_SUBJECT = re.compile(r"^sub_[A-Za-z0-9_-]{16,128}$")


def valid_canonical_subject(value: object) -> bool:
    return isinstance(value, str) and _SUBJECT.fullmatch(value) is not None


def canary_allowed(state: object, subject_id: object) -> bool:
    allowed = getattr(state, "claw_live_sse_canary_subject_id", None)
    return (
        getattr(state, "claw_live_sse_enabled", False) is True
        and valid_canonical_subject(subject_id)
        and valid_canonical_subject(allowed)
        and hmac.compare_digest(subject_id, allowed)
    )
