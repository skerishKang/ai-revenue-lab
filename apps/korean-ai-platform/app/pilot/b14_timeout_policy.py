"""Bounded B14 provider-attempt and fallback-chain timeout policy.

The request deadline is split into observable phases: time to the first response
body byte, total time for one provider attempt, idle time between stream chunks,
and a cumulative fallback-chain budget. The gateway and HTTP adapters read the
effective policy at request time so Worker env bindings collected on the first
request remain effective.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
import os
import time

import httpx

FIRST_BYTE_TIMEOUT_ENV = "BUSINESS14_FIRST_BYTE_TIMEOUT_SECONDS"
ATTEMPT_TIMEOUT_ENV = "BUSINESS14_ATTEMPT_TIMEOUT_SECONDS"
STREAM_IDLE_TIMEOUT_ENV = "BUSINESS14_STREAM_IDLE_TIMEOUT_SECONDS"
CHAIN_BUDGET_ENV = "BUSINESS14_CHAIN_BUDGET_SECONDS"

DEFAULT_FIRST_BYTE_SECONDS = 15.0
DEFAULT_ATTEMPT_SECONDS = 40.0
DEFAULT_STREAM_IDLE_SECONDS = 20.0
DEFAULT_CHAIN_BUDGET_SECONDS = 55.0
WRITE_SECONDS = 120.0
POOL_SECONDS = 60.0
ENGINE_MAX_WALL_SECONDS = 60.0  # legacy Engine setting; not a B14 inference limit

# Backwards-compatible default aliases for diagnostics/tests. Runtime callers
# use get_timeout_policy() so per-deployment env overrides are read dynamically.
CONNECT_SECONDS = DEFAULT_FIRST_BYTE_SECONDS
READ_SECONDS = DEFAULT_STREAM_IDLE_SECONDS
ATTEMPT_SECONDS = DEFAULT_ATTEMPT_SECONDS
GATEWAY_WALL_SECONDS = DEFAULT_CHAIN_BUDGET_SECONDS


@dataclass(frozen=True, slots=True)
class B14TimeoutPolicy:
    first_byte_seconds: float = DEFAULT_FIRST_BYTE_SECONDS
    attempt_seconds: float = DEFAULT_ATTEMPT_SECONDS
    stream_idle_seconds: float = DEFAULT_STREAM_IDLE_SECONDS
    chain_budget_seconds: float = DEFAULT_CHAIN_BUDGET_SECONDS


def _positive_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def get_timeout_policy() -> B14TimeoutPolicy:
    """Read non-secret deployment overrides without exposing their values."""
    return B14TimeoutPolicy(
        first_byte_seconds=_positive_seconds(FIRST_BYTE_TIMEOUT_ENV, DEFAULT_FIRST_BYTE_SECONDS),
        attempt_seconds=_positive_seconds(ATTEMPT_TIMEOUT_ENV, DEFAULT_ATTEMPT_SECONDS),
        stream_idle_seconds=_positive_seconds(STREAM_IDLE_TIMEOUT_ENV, DEFAULT_STREAM_IDLE_SECONDS),
        chain_budget_seconds=_positive_seconds(CHAIN_BUDGET_ENV, DEFAULT_CHAIN_BUDGET_SECONDS),
    )


class ProviderAttemptTimeout(TimeoutError):
    """A bounded upstream wait, classified without preserving vendor text."""

    def __init__(self, reason: str) -> None:
        if reason not in {"first_byte", "attempt_total"}:
            raise ValueError("unknown provider timeout reason")
        self.reason = reason
        self.timeout_reason = reason
        super().__init__(reason)


async def send_provider_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> tuple[httpx.Response, float]:
    """Open a streaming response under the first-byte deadline.

    The first-byte clock includes response headers and the first non-empty body
    chunk. The body iterator below carries the same start time across both
    phases, so fast headers cannot grant another full first-byte interval.
    """
    policy = get_timeout_policy()
    started_at = time.monotonic()
    request = client.build_request(method, url, **kwargs)
    first_deadline = min(policy.first_byte_seconds, policy.attempt_seconds)
    first_byte_is_limiting = policy.first_byte_seconds <= policy.attempt_seconds
    try:
        async with asyncio.timeout(first_deadline):
            response = await client.send(
                request, stream=True, follow_redirects=False,
            )
    except (TimeoutError, httpx.TimeoutException) as exc:
        reason = "first_byte" if first_byte_is_limiting else "attempt_total"
        raise ProviderAttemptTimeout(reason) from exc
    return response, started_at


async def iter_provider_response_bytes(
    response: httpx.Response,
    *,
    started_at: float,
):
    """Yield upstream bytes with first-byte, attempt-total and stream-idle limits."""
    policy = get_timeout_policy()
    iterator = response.aiter_bytes().__aiter__()
    first_byte_seen = False
    while True:
        elapsed = time.monotonic() - started_at
        attempt_remaining = policy.attempt_seconds - elapsed
        if attempt_remaining <= 0:
            raise ProviderAttemptTimeout("attempt_total")
        if first_byte_seen:
            timeout_seconds = min(policy.stream_idle_seconds, attempt_remaining)
            timeout_reason = "attempt_total"
        else:
            first_remaining = policy.first_byte_seconds - elapsed
            if first_remaining <= 0:
                raise ProviderAttemptTimeout("first_byte")
            timeout_seconds = min(first_remaining, attempt_remaining)
            timeout_reason = (
                "first_byte" if first_remaining <= attempt_remaining else "attempt_total"
            )
        try:
            async with asyncio.timeout(timeout_seconds):
                chunk = await iterator.__anext__()
        except StopAsyncIteration:
            return
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderAttemptTimeout(timeout_reason) from exc
        if not chunk:
            continue
        first_byte_seen = True
        yield chunk


def build_provider_http_timeout(model_id: str | None = None) -> httpx.Timeout:
    """Build phase-specific HTTPX guards; total/idle budgets live in policy helpers."""
    del model_id
    policy = get_timeout_policy()
    return httpx.Timeout(
        None,
        connect=policy.first_byte_seconds,
        read=policy.stream_idle_seconds,
        write=WRITE_SECONDS,
        pool=POOL_SECONDS,
    )
