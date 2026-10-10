"""#3554: B14 fixed-provider timeout phase evidence only; no request mutation.

Never log exception text, URL, request or response body, headers, account data,
model outputs or credentials. Phase is derived only from httpx exception TYPE.
This is observability, not a timeout increase or a provider retry.
"""
from __future__ import annotations

import logging
import httpx

from .atria_timeout_diagnostics import log_atria_timeout

# Literal provider identifiers from the existing B14 canonical registry. Do
# not use user-supplied provider names or arbitrary exception strings as labels.
_ALLOWED = frozenset((
    "agnes-ai", "atria", "experiential", "google",
    "inception", "kira", "modelscope", "poolside", "sensenova",
))
_MODES = frozenset(("completed", "stream"))


def classify_timeout_phase(exc: BaseException) -> str | None:
    if not isinstance(exc, httpx.TimeoutException):
        return None
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect"
    if isinstance(exc, httpx.ReadTimeout):
        return "read"
    if isinstance(exc, httpx.WriteTimeout):
        return "write"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool"
    return "other"


def log_provider_timeout(
    logger: logging.Logger, provider_id: str, exc: BaseException, mode: str,
) -> None:
    if provider_id not in _ALLOWED:
        return
    phase = classify_timeout_phase(exc)
    if phase is None:
        return
    if provider_id == "atria":
        # Preserve existing specialized Atria diagnostic contract / log key.
        log_atria_timeout(logger, provider_id, exc, mode)
        return
    mode = mode if mode in _MODES else "unknown"
    logger.warning(
        "b14_safe_timeout provider=%s phase=%s mode=%s",
        provider_id, phase, mode,
    )


def log_gateway_deadline(logger: logging.Logger, provider_id: str) -> None:
    """Called only on a real gateway asyncio.TimeoutError (not HTTP 504)."""
    if provider_id not in _ALLOWED:
        return
    logger.warning("b14_gateway_deadline provider=%s phase=overall", provider_id)
