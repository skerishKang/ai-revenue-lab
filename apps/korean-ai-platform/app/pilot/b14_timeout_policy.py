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

READ_SECONDS = 600.0  # model first response / per-chunk inactivity ceiling
# Workers' Fetch-backed HTTPX connect phase can include waiting for response
# headers, not just a native TCP handshake. It must not silently impose a
# second 30/55s wall on otherwise healthy 600s model inference.
CONNECT_SECONDS = READ_SECONDS  # Fetch first-response watchdog (not 30s)
WRITE_SECONDS = 20.0
POOL_SECONDS = 10.0
GATEWAY_WALL_SECONDS = 45.0
ENGINE_MAX_WALL_SECONDS = 60.0  # Core ceiling, NOT its 20s default

assert 0 < POOL_SECONDS <= WRITE_SECONDS < CONNECT_SECONDS
assert 0 < GATEWAY_WALL_SECONDS < ENGINE_MAX_WALL_SECONDS
assert CONNECT_SECONDS == READ_SECONDS  # same first-response/stream idle budget


def build_provider_http_timeout(model_id: str | None = None) -> httpx.Timeout:
    """Uniform first-response/stream-idle budget for exact-model inference.

    Retain an optional model identifier for existing adapter callers; no
    provider-specific 30/55s early cap is permitted. Tool and OAuth transport
    deadlines belong to their separate, short-bound transport policies.
    """
    del model_id
    return httpx.Timeout(
        None,
        connect=CONNECT_SECONDS,
        read=READ_SECONDS,
        write=WRITE_SECONDS,
        pool=POOL_SECONDS,
    )
