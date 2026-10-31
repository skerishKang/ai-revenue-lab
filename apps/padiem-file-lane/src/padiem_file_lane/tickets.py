"""Verify Chat-issued bearer tickets; no user credentials are stored here.

The proof construction matches Chat b14_service_proof:
HMAC-SHA256(deployment_secret, timestamp_ascii + b'.' + raw_claims).
File tickets use their own secret and header namespace. Signed expires is
this capability's lifetime; B14's 60-second request skew is not an upload TTL.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import time

TICKET_HEADER = "x-padiem-file-ticket"
TIME_HEADER = "x-padiem-file-time"
PROOF_HEADER = "x-padiem-file-proof"
USER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_@+.-]{0,127}\Z")


class InvalidTicket(ValueError):
    pass


@dataclass(frozen=True)
class Ticket:
    user_id: str
    max_bytes: int
    expires: int


def verify_ticket(headers, secret: str, *, now: int | None = None) -> Ticket:
    """Validate exact signed bytes before trusting any claim or path component."""
    now = int(time.time()) if now is None else now
    encoded = headers.get(TICKET_HEADER, "")
    stamp = headers.get(TIME_HEADER, "")
    proof = headers.get(PROOF_HEADER, "")
    if (len(secret) < 32 or not encoded or len(encoded) > 4096
            or not re.fullmatch(r"[0-9]{1,20}", stamp)
            or not re.fullmatch(r"[a-f0-9]{64}", proof)):
        raise InvalidTicket("invalid_ticket")
    try:
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        expected = hmac.new(secret.encode(), stamp.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(proof, expected):
            raise InvalidTicket("invalid_ticket")
        claims = json.loads(raw)
        if not isinstance(claims, dict) or set(claims) != {"user_id", "max_bytes", "expires"}:
            raise InvalidTicket("invalid_ticket")
        user, maximum, expires = claims["user_id"], claims["max_bytes"], claims["expires"]
        if (not isinstance(user, str) or not USER_PATTERN.fullmatch(user)
                or type(maximum) is not int or maximum <= 0
                or type(expires) is not int or expires <= now
                or int(stamp) > now or int(stamp) >= expires):
            raise InvalidTicket("invalid_ticket")
        return Ticket(user, maximum, expires)
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise InvalidTicket("invalid_ticket") from None
