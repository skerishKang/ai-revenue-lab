"""B14 provider transport phase policy for Cloudflare Python Worker.

The model read timeout is a *per-chunk idle* watchdog, not a total response
deadline. Align its 600-second default with ZCode's documented stream idle
policy. HTTPX resets read timeout whenever more response data arrives; it
does not impose a fixed 600-second limit on a healthy generating response.

The 45-second GATEWAY_WALL_SECONDS is a separate **retry/fallback chain**
budget. It caps *additional* automatic fallbacks and manual retries, but not
the initial attempt (manual or automatic) when inference exceeds 45s.
Callers (Core, Chat, Engine) retain their own deadlines until updated by
their owners. Do not interpret this source change as end-to-end support.

Transport bounds are neither additive nor a total request deadline:
- connect is the phase reported by the Worker/Pyodide HTTPX Fetch patch;
- read waits for the next inbound chunk;
- write waits for outbound request-body progress;
- pool waits to acquire a connection.
"""
from __future__ import annotations

import httpx

CONNECT_SECONDS = 30.0
# Exact Gemini-compatible Gemma 31B route: a verified healthy completed model
# response took 31.8 seconds, while another request failed at ~30.5 seconds.
# Workers' Fetch-backed HTTPX connect phase can cover first-response waiting;
# the phase name is not proof of a native TCP/TLS handshake bottleneck.
# Scope the extra room to this ID only, below Engine's 60-second ceiling.
GEMMA_31B_MODEL_ID = "google/gemma-4-31b-it"
GEMMA_31B_CONNECT_SECONDS = 55.0
READ_SECONDS = 600.0  # ZCode-style per-chunk model idle watchdog
WRITE_SECONDS = 20.0
POOL_SECONDS = 10.0
GATEWAY_WALL_SECONDS = 45.0
ENGINE_MAX_WALL_SECONDS = 60.0  # Core ceiling, NOT its 20s default

assert 0 < POOL_SECONDS <= WRITE_SECONDS <= CONNECT_SECONDS < GATEWAY_WALL_SECONDS
assert 0 < GATEWAY_WALL_SECONDS < ENGINE_MAX_WALL_SECONDS
assert CONNECT_SECONDS < GEMMA_31B_CONNECT_SECONDS < ENGINE_MAX_WALL_SECONDS
assert READ_SECONDS >= GATEWAY_WALL_SECONDS  # independent model idle budget


def build_provider_http_timeout(model_id: str | None = None) -> httpx.Timeout:
    """Fresh timeout for completed/SSE; one exact Gemma route gets extra TTFB room.

    This does not authorize retries or widen any other provider's connection
    window. The initial inference attempt has no separate 45s wall ceiling.
    """
    return httpx.Timeout(
        None,
        connect=GEMMA_31B_CONNECT_SECONDS if model_id == GEMMA_31B_MODEL_ID else CONNECT_SECONDS,
        read=READ_SECONDS,
        write=WRITE_SECONDS,
        pool=POOL_SECONDS,
    )
