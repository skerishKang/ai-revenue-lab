"""BookAI records v1 HMAC, shared by COM2 records and app AI ingress."""
from __future__ import annotations

import hashlib
import hmac
import re

SIGNATURE_WINDOW_SECONDS = 300
_SIGNATURE = re.compile(r"[0-9a-f]{64}")


def signature_time_error(timestamp: str, signature: str, *, now: float) -> str | None:
    if not re.fullmatch(r"[0-9]{1,12}", timestamp) or not _SIGNATURE.fullmatch(signature):
        return "invalid_app_signature"
    if abs(now - int(timestamp)) > SIGNATURE_WINDOW_SECONDS:
        return "app_signature_expired"
    return None


def signature_matches(*, secret: str, method: str, path: str, timestamp: str,
                      subject: str, body: bytes | bytearray, signature: str) -> bool:
    # Preserve the exact query string in PATH. GET signs an empty body.
    canonical = "\n".join((method, path, timestamp, subject, hashlib.sha256(body).hexdigest()))
    expected = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
