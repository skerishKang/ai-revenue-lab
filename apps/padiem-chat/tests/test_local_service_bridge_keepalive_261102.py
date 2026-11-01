"""#6460 4-1: the pooled identity RPC client outlives the scope-cache window.

The client used to inherit httpx's 5s idle limit, so the first identity RPC
after the 30s scope-cache window paid a fresh TCP+TLS handshake (the measured
~2s call). The configured 75s is bounded — never unlimited — and must be
matched by the identity service's own uvicorn keep-alive timeout.
"""
import asyncio

from app.local_service_bridge import HttpRpcBinding


def test_the_shared_client_keeps_idle_connections_longer_than_the_scope_window():
    binding = HttpRpcBinding("https://identity.example.test", "s" * 32)

    async def probe():
        binding._shared_client()
        # httpcore keeps the expiry on the connection pool the client owns.
        return binding._shared_client()._transport._pool._keepalive_expiry

    assert asyncio.run(probe()) == 75.0


def test_the_same_client_is_shared_across_calls():
    binding = HttpRpcBinding("https://identity.example.test", "s" * 32)

    async def probe():
        first = binding._shared_client()
        second = binding._shared_client()
        return first is second

    assert asyncio.run(probe()) is True
