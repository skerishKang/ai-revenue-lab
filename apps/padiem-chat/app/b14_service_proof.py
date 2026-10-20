"""Server-to-server caller proof for the B14 platform-credential dispatch lane.

B14 spends the platform's own Provider credentials on its catalog execution
lane, so that lane is reachable only by a proven PADIEM server-to-server
caller. The Chat Worker therefore signs every B14 request body with the
deployment-owned proof secret before the Service Binding call.

The construction is the same one the Engine -> Chat desktop lane already uses::

    proof = HMAC-SHA256(secret, "<unix timestamp>.<raw request body>")

The proof is body-bound, so a captured header cannot authorize a different
request, and time-bound, so a captured proof cannot be replayed outside the
skew window. The secret value is never logged, returned, or stored in source.
"""

from __future__ import annotations

import hashlib
import hmac
import time

PROOF_HEADER = "X-Padiem-B14-Proof"
PROOF_TIME_HEADER = "X-Padiem-B14-Time"
MIN_PROOF_SECRET_LENGTH = 32


def service_proof_headers(secret: str | None, raw_body: bytes) -> dict[str, str]:
    """Return the proof headers for one exact B14 request body.

    An absent or too-short secret yields no headers. B14 then refuses the
    dispatch, so an unconfigured proof fails closed instead of silently
    allowing an unproven caller.
    """
    if not isinstance(secret, str) or len(secret) < MIN_PROOF_SECRET_LENGTH:
        return {}
    timestamp = str(int(time.time()))
    message = timestamp.encode("ascii") + b"." + bytes(raw_body)
    proof = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {PROOF_HEADER: proof, PROOF_TIME_HEADER: timestamp}
