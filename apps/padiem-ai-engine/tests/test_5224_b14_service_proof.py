"""#5224: the Engine proves itself as an approved server-to-server caller to B14.

B14 spends the platform's own Provider credentials on its catalog execution
lane, so that lane is reachable only by a proven PADIEM server-to-server
caller. The Engine signs every B14 request body with the deployment-owned
proof secret before the Service Binding call.

These tests are network-free: they assert the outbound Service Binding request
only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from app.b14_service_proof import (
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    service_proof_headers,
)
from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)

SIGNING_SECRET = "b14-signing-secret-0123456789abcdef"

# One fixed vector for the whole platform. The B14 application and the B62
# Chat suite assert the same value, so a change in either implementation is
# caught instead of silently breaking the other side.
CONTRACT_SECRET = "b14-contract-vector-secret-0123456789abcdef"
CONTRACT_TIMESTAMP = "1700000000"
CONTRACT_BODY = b'{"model":"x"}'
CONTRACT_PROOF = (
    "b6a1234c77da135333d5a3d01b87ff0a1624c9a1359fef7a25542ea4aba2c1a5"
)


class FakeReader:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self):
        if self._chunks:
            return SimpleNamespace(done=False, value=self._chunks.pop(0))
        return SimpleNamespace(done=True, value=None)

    async def cancel(self):
        return None

    def releaseLock(self):
        return None


class FakeJsProxyChunk:
    def __init__(self, values):
        self._values = list(values)

    def to_py(self):
        return list(self._values)


class FakeBody:
    def __init__(self, chunks):
        self.reader = FakeReader(chunks)

    def getReader(self):
        return self.reader


class FakeHeaders:
    def __init__(self, content_type="application/json"):
        self.content_type = content_type

    def get(self, name):
        if name.lower() == "content-type":
            return self.content_type
        return None


class FakeResponse:
    def __init__(self, chunks):
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self.body = FakeBody(chunks)


class FakeBinding:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def fetch(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class FakeWorkerRequest:
    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.js_object = self


class RequestFactory:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        request = FakeWorkerRequest(url, **kwargs)
        self.calls.append(request)
        return request


def test_shared_contract_vector_is_stable() -> None:
    """The proof construction is one shared contract, not two implementations."""
    expected = hmac.new(
        CONTRACT_SECRET.encode("utf-8"),
        CONTRACT_TIMESTAMP.encode("ascii") + b"." + CONTRACT_BODY,
        hashlib.sha256,
    ).hexdigest()
    assert expected == CONTRACT_PROOF


def test_proof_headers_are_absent_without_a_usable_secret() -> None:
    """An unconfigured proof must not fabricate a caller signature."""
    assert service_proof_headers(None, CONTRACT_BODY) == {}
    assert service_proof_headers("too-short", CONTRACT_BODY) == {}


@pytest.mark.asyncio
async def test_engine_b14_request_carries_a_body_bound_proof() -> None:
    response = FakeResponse(chunks=[FakeJsProxyChunk(b'{"ok":true}')])
    binding = FakeBinding(response=response)
    factory = RequestFactory()
    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=factory,
        proof_secret=SIGNING_SECRET,
    )

    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream(
            "POST",
            B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions",
            json={"hello": "world"},
        ) as result:
            _ = [chunk async for chunk in result.aiter_bytes()]

    assert len(factory.calls) == 1
    request = factory.calls[0]
    headers = request.kwargs["headers"]
    body = request.kwargs["body"].encode("utf-8")
    assert json.loads(request.kwargs["body"])["hello"] == "world"

    assert headers[PROOF_HEADER]
    assert headers[PROOF_TIME_HEADER]
    expected = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        headers[PROOF_TIME_HEADER].encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers[PROOF_HEADER] == expected


@pytest.mark.asyncio
async def test_engine_b14_request_without_a_secret_is_not_claimed_as_proven() -> None:
    """An unconfigured Engine sends no proof, so B14 refuses the dispatch."""
    response = FakeResponse(chunks=[FakeJsProxyChunk(b'{"ok":true}')])
    binding = FakeBinding(response=response)
    factory = RequestFactory()
    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=factory,
    )

    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream(
            "POST",
            B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions",
            json={"hello": "world"},
        ) as result:
            _ = [chunk async for chunk in result.aiter_bytes()]

    headers = factory.calls[0].kwargs["headers"]
    assert PROOF_HEADER not in headers
    assert PROOF_TIME_HEADER not in headers




