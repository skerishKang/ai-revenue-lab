"""#3930 authenticated-user live SSE admission, without a single-subject allowlist.

The server flag enables the feature globally for canonical signed-in users.
The caller must first resolve the canonical CP-backed subject server-side.
A request header, body, or cookie cannot grant this admission.
"""
from __future__ import annotations
import re

_SUBJECT = re.compile(r"^sub_[A-Za-z0-9_-]{16,128}$")


def valid_canonical_subject(value: object) -> bool:
    return isinstance(value, str) and _SUBJECT.fullmatch(value) is not None


def live_stream_allowed(state: object, subject_id: object) -> bool:
    return (
        getattr(state, "claw_live_sse_enabled", False) is True
        and valid_canonical_subject(subject_id)
    )
