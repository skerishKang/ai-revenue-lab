"""#6724: one same-route retry for an upstream that failed before answering.

CTO decision 2026-11-10: a B14 upstream call that has not put a single answer
byte in front of the caller may be dispatched once more on the SAME provider
route, after a 0.5 s pause. Same model, same route — nothing else is
substituted here, and the grade roster keeps its own decision (#6821). Once a
visible answer byte has left B14 a failure stays terminal: the caller already
has part of the answer, so replaying the call would deliver a second answer
instead of an honest error.

Retried (pre-answer only):

* a transport/connection failure or an upstream 5xx (``UpstreamServerError``);
* a timeout that expired while connecting or sending the request
  (``timeout_phase`` connect/pool/write). A provider that received the request
  and was merely slow is a different class and is deliberately not retried;
* the first streamed frame carrying an error envelope (``{"error": ...}``),
  which some providers send with HTTP 200 (``error_envelope``).

Never retried: any 4xx (auth, hourly quota/limit, rejected request), a
malformed body that is not an error envelope, an empty answer, an exhausted
chain budget, and anything that arrived after the first visible byte.

The ledger keeps both physical attempts: the failed one closes with its own
error code and no usage, the answered one carries the consumption.
"""

from __future__ import annotations

from .errors import (
    MalformedUpstreamResponse,
    UpstreamServerError,
    UpstreamTimeout,
)

#: One extra dispatch, never two. A second retry would multiply a failing
#: provider's outage into the caller's latency for no new evidence.
PRESTREAM_RETRY_LIMIT = 1

#: Fixed pause before the retry. Short enough to stay inside the first-byte
#: expectation the caller already has, long enough to outlast a 5xx blip.
PRESTREAM_RETRY_DELAY_SECONDS = 0.5

#: Transport phases that fail before the provider has the request in hand.
#: ``read`` is excluded on purpose: the request was delivered, so a slow answer
#: is the provider's own latency, not a connect failure.
CONNECT_TIMEOUT_PHASES = frozenset({"connect", "pool", "write"})

#: A streamed frame whose whole payload is an error object. Its presence before
#: the first answer byte is the provider refusing the call, not a wire change.
ERROR_ENVELOPE_REASON = "error_envelope"


def is_prestream_retryable(exc: BaseException) -> bool:
    """Whether this failure happened before any answer byte and may be retried."""
    if isinstance(exc, UpstreamServerError):
        # HTTP 5xx and connection failures that never produced a response.
        return True
    if isinstance(exc, UpstreamTimeout):
        return getattr(exc, "timeout_phase", None) in CONNECT_TIMEOUT_PHASES
    if isinstance(exc, MalformedUpstreamResponse):
        return exc.reason == ERROR_ENVELOPE_REASON
    return False
