"""#6613 — one pooled client serves every identity RPC, not one per call.

The 11-02 journal showed a password login spending 6,721 ms in identity: six
serial RPCs at about 1.1 s each. The calls are fixed by security invariants; what
was avoidable is that `HttpRpcBinding` built a new `httpx.AsyncClient` for each
call, so every RPC also paid a TCP+TLS handshake to the identity origin.

These scenes pin the reuse without touching anything that made the call correct:
the same proof headers, the same 409 replay retry, the same timeout, and an
injected client still belonging to its caller.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import app.local_service_bridge as bridge_module
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.local_service_bridge import HttpRpcBinding, RPC_MAX_ATTEMPTS

SECRET = "synthetic-rpc-secret-0123456789abcdef"
ORIGIN = "https://identity.example.test"


def _counting_transport(handler, seen: list):
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(respond)


def _ok(link_id: str = "lnk_1") -> dict:
    return {"ok": True, "link": {
        "product_id": "b62", "product_user_id": "usr_1",
        "canonical_subject_id": "sub_" + "a" * 32, "state": "active",
    }}


def _install_client_factory(monkeypatch, transport, built: list, *, verify_headers=None):
    """Every client the binding builds goes through the mock transport."""

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        client = real(transport=transport, **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(bridge_module.httpx, "AsyncClient", factory)


def test_six_identity_rpcs_build_one_client(monkeypatch):
    seen: list = []
    built: list = []
    _install_client_factory(monkeypatch, _counting_transport(lambda r: httpx.Response(200, json=_ok()), seen), built)

    binding = HttpRpcBinding(ORIGIN, SECRET)
    payloads = [{"product_id": "b62", "product_user_id": f"usr_{i}",
                 "auth_provider": "password", "provider_subject": f"owner{i}@example.test"}
                for i in range(6)]

    async def run_all():
        return [await binding.resolve_or_create_product_link(payload) for payload in payloads]

    results = asyncio.run(run_all())

    assert all(result["ok"] is True for result in results)
    assert len(seen) == 6, len(seen)                # six RPCs went out
    assert len(built) == 1, len(built)              # over one client
    assert binding._client is built[0]
    for request in seen:                            # proof contract untouched
        assert request.headers["x-padiem-service-proof"].startswith("v2=")
        assert request.headers["x-padiem-service-id"]
        assert request.url.path == "/internal/rpc/resolve_or_create_product_link"
    asyncio.run(binding.aclose())


def test_the_identity_authority_shares_the_same_client(monkeypatch):
    seen: list = []
    built: list = []
    _install_client_factory(monkeypatch, _counting_transport(lambda r: httpx.Response(200, json=_ok()), seen), built)
    authority = CloudflareControlPlaneIdentityAuthority(HttpRpcBinding(ORIGIN, SECRET))

    async def twice():
        first = await authority.resolve_or_create_product_link(
            product_id="b62", product_user_id="usr_1",
            auth_provider="password", provider_subject="owner@example.test")
        second = await authority.resolve_or_create_product_link(
            product_id="b62", product_user_id="usr_1",
            auth_provider="password", provider_subject="owner@example.test")
        return first, second

    first, second = asyncio.run(twice())
    assert first.canonical_subject_id == second.canonical_subject_id
    assert len(seen) == 2
    assert len(built) == 1
    asyncio.run(authority._binding.aclose())


def test_a_closed_client_is_reopened_on_the_next_call(monkeypatch):
    seen: list = []
    built: list = []
    _install_client_factory(monkeypatch, _counting_transport(lambda r: httpx.Response(200, json=_ok()), seen), built)
    binding = HttpRpcBinding(ORIGIN, SECRET)

    assert asyncio.run(binding.probe({"x": 1}))["ok"] is True
    asyncio.run(binding.aclose())
    assert binding._client is None
    assert asyncio.run(binding.probe({"x": 2}))["ok"] is True

    assert len(seen) == 2
    assert len(built) == 2                          # one per lifetime, not per call
    asyncio.run(binding.aclose())


def test_an_injected_client_is_used_and_never_closed_by_the_binding(monkeypatch):
    seen: list = []
    built: list = []
    # Built before the factory is installed: this client belongs to the caller.
    injected = httpx.AsyncClient(transport=_counting_transport(lambda r: httpx.Response(200, json=_ok()), seen))
    _install_client_factory(monkeypatch, _counting_transport(lambda r: httpx.Response(200, json=_ok()), seen), built)
    binding = HttpRpcBinding(ORIGIN, SECRET, client=injected)

    async def call():
        assert (await binding.probe({"x": 1}))["ok"] is True
        await binding.aclose()
        assert binding._client is None
        # The caller's client still works after the binding let go of it.
        assert (await injected.post(ORIGIN + "/internal/rpc/probe", json={})).status_code == 200

    asyncio.run(call())
    assert built == []                              # nothing constructed here
    asyncio.run(injected.aclose())


def test_timeout_and_the_replay_retry_are_unchanged(monkeypatch):
    seen: list = []
    built: list = []
    statuses = [409, 409, 200]

    def handler(request):
        status = statuses[len(seen) - 1]
        return httpx.Response(status, json=_ok() if status == 200 else {"ok": False})

    _install_client_factory(monkeypatch, _counting_transport(handler, seen), built)
    binding = HttpRpcBinding(ORIGIN, SECRET, timeout_seconds=17.5)

    assert asyncio.run(binding.probe({"x": 1}))["ok"] is True
    assert len(seen) == RPC_MAX_ATTEMPTS == 3       # the same bounded retry
    assert binding._client.timeout == httpx.Timeout(17.5)
    asyncio.run(binding.aclose())


def test_a_dropped_connection_does_not_poison_the_pool(monkeypatch):
    """The second call transparently opens a new connection on the same client."""
    seen: list = []
    built: list = []
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("dropped", request=request)
        return httpx.Response(200, json=_ok())

    _install_client_factory(monkeypatch, _counting_transport(handler, seen), built)
    binding = HttpRpcBinding(ORIGIN, SECRET)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(binding.probe({"x": 1}))
    assert asyncio.run(binding.probe({"x": 2}))["ok"] is True

    assert len(built) == 1                          # same client, new connection
    asyncio.run(binding.aclose())
