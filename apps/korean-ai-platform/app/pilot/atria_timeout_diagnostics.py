"""Atria exact-model timeout phase diagnostics (#3922).

Log only an allowlisted httpx timeout class and fixed transport path.
No exception messages, request data, response bodies, credentials, URLs,
account identifiers, or latency heuristics. This is not a timeout fix.
"""
from __future__ import annotations

import logging
import httpx


def classify_atria_timeout(provider_id: str, exc: BaseException) -> str | None:
    if provider_id != "atria" or not isinstance(exc, httpx.TimeoutException):
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


def log_atria_timeout(
    logger: logging.Logger, provider_id: str, exc: BaseException, mode: str
) -> None:
    phase=classify_atria_timeout(provider_id, exc)
    if phase is None:
        return
    if mode not in ("completed", "stream"):
        mode="unknown"
    logger.warning(
        "atria_safe_timeout provider=atria phase=%s mode=%s",
        phase, mode,
    )
