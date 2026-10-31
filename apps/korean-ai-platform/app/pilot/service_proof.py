"""Deployment-owned caller proof for the B14 provider-dispatch lanes.

The B14 Worker is publicly routable, so an anonymous internet caller could
otherwise reach an execution lane and make B14 send a Provider request. Every
lane that dispatches a Provider request therefore requires the existing PADIEM
server-to-server caller proof before any credential is resolved.

Contract (the same construction the Engine -> Chat desktop lane already uses)::

    proof = HMAC-SHA256(secret, "<unix timestamp>.<raw request body>")

The secret is the deployment-owned Secrets Store object
``PADIEM_B14_SERVICE_PROOF_SECRET``. No new customer authentication step and
no second authority are introduced: the value is an internal server-to-server
proof key, never a Provider credential. The proof is body-bound, so a captured
header cannot authorize a different request, and time-bound, so a captured
proof cannot be replayed outside the skew window.

The request-carried credential lane (#5824 PR-3a) is proved the same way. Who
may make B14 dispatch is a separate question from whose key the dispatch spends,
and a caller-supplied Provider key does not answer the first one; without this
gate a public caller could also use the Worker as a relay for its own key.

The legacy ``X-Business14-Provider-Key`` header route predates that decision and
keeps its own contract (#5224 pins it). The read-only model-authority reads are
not affected: they dispatch no Provider request.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from starlette.requests import Request

# Deployment-owned proof secret. The value lives only in Cloudflare Secrets
# Store; the binding name is the only thing that appears in source.
SERVICE_PROOF_BINDING = "PADIEM_B14_SERVICE_PROOF_SECRET"

PROOF_HEADER = "x-padiem-b14-proof"
PROOF_TIME_HEADER = "x-padiem-b14-time"

MAX_PROOF_SKEW_SECONDS = 60
MIN_PROOF_SECRET_LENGTH = 32

ERROR_PROOF_REQUIRED = "b14_service_proof_required"
ERROR_PROOF_UNCONFIGURED = "b14_service_proof_unconfigured"

_PROOF_MESSAGE = (
    "이 실행 경로는 인증된 서버 간 호출만 허용합니다. "
    "Provider 키를 사용한 요청은 X-Business14-Provider-Key 헤더를 사용하십시오."
)


@dataclass(frozen=True)
class ServiceProofDenial:
    """A refused platform-credential dispatch. Carries a bounded error code."""

    code: str
    status_code: int


async def resolve_service_proof_secret() -> str:
    """Return the deployment-owned proof secret, or "" when unavailable.

    Worker requests read the request-scoped Secrets Store value; a local CLI
    or test process may provide the same binding name through the process
    environment. No global fallback ever substitutes a different credential.
    """
    from .worker_env import load_request_secret, scoped_secret

    await load_request_secret(SERVICE_PROOF_BINDING)
    scoped = scoped_secret(SERVICE_PROOF_BINDING)
    raw = os.environ.get(SERVICE_PROOF_BINDING, "") if scoped is None else scoped
    return raw if isinstance(raw, str) else ""


def compute_service_proof(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Return the caller proof for one exact request body."""
    message = timestamp.encode("ascii") + b"." + bytes(raw_body)
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_service_proof(
    secret: str,
    timestamp: str,
    proof: str,
    raw_body: bytes,
    *,
    now_seconds: int | None = None,
) -> bool:
    """Return whether the caller proof authenticates this exact request."""
    if not isinstance(secret, str) or len(secret) < MIN_PROOF_SECRET_LENGTH:
        return False
    if not isinstance(timestamp, str) or not timestamp.isdigit() or len(timestamp) > 20:
        return False
    if not isinstance(proof, str) or len(proof) != 64:
        return False
    now = int(time.time()) if now_seconds is None else int(now_seconds)
    if abs(now - int(timestamp)) > MAX_PROOF_SKEW_SECONDS:
        return False
    expected = compute_service_proof(secret, timestamp, raw_body)
    return hmac.compare_digest(proof, expected)


async def service_proof_denial(
    request: Request, raw_body: bytes
) -> ServiceProofDenial | None:
    """Return a refusal when the caller may not spend platform credentials.

    ``None`` means the caller is proven and the dispatch may continue.
    """
    secret = await resolve_service_proof_secret()
    if not secret or len(secret) < MIN_PROOF_SECRET_LENGTH:
        return ServiceProofDenial(ERROR_PROOF_UNCONFIGURED, 503)
    timestamp = request.headers.get(PROOF_TIME_HEADER, "")
    proof = request.headers.get(PROOF_HEADER, "")
    if not verify_service_proof(secret, timestamp, proof, raw_body):
        return ServiceProofDenial(ERROR_PROOF_REQUIRED, 401)
    return None


def service_proof_message() -> str:
    """Return the caller-facing refusal message."""
    return _PROOF_MESSAGE
