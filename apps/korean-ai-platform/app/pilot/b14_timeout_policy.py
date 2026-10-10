"""Single B14 HTTPX transport policy for Cloudflare Python Worker (Pyodide).

The caller-facing synchronous gateway owns one 45-second wall-clock attempt
budget: historically chosen under the Engine *maximum* 60-second ceiling.
Some actual callers use a 20-second default or 50-second completion budget;
none are silently widened by this patch. These four
HTTPX phase bounds are NOT additive and NOT a total request deadline:
- connect is the phase that the Worker/Pyodide HTTPX Fetch patch reports,
  not evidence of a specific socket TCP/TLS handshake;
- read is maximum idle time between inbound chunks, not generation wall time;
- write covers outbound body sends;
- pool covers acquiring a pooled connection.

B14 calls create a fresh AsyncClient, but we retain a finite pool bound.
All registered providers use the same bounded baseline; no price/reasoning/
model-specific exceptions, no auto retry/fallback. Longer-than-45s full
model generations require a separately designed asynchronous or streaming
product flow and Engine/client budget adjustment, not more per-phase knobs.
"""
from __future__ import annotations

import httpx

CONNECT_SECONDS = 30.0
READ_SECONDS = 40.0
WRITE_SECONDS = 20.0
POOL_SECONDS = 10.0
GATEWAY_WALL_SECONDS = 45.0
ENGINE_MAX_WALL_SECONDS = 60.0  # Core ceiling, NOT its 20s default

assert 0 < POOL_SECONDS <= WRITE_SECONDS <= CONNECT_SECONDS < GATEWAY_WALL_SECONDS
assert 0 < READ_SECONDS < GATEWAY_WALL_SECONDS < ENGINE_MAX_WALL_SECONDS


def build_provider_http_timeout() -> httpx.Timeout:
    """Fresh immutable-equivalent policy for both B14 completed and SSE."""
    return httpx.Timeout(
        None,
        connect=CONNECT_SECONDS,
        read=READ_SECONDS,
        write=WRITE_SECONDS,
        pool=POOL_SECONDS,
    )
