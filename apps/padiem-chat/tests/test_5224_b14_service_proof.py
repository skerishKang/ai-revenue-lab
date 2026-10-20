"""#5224: B62 proves itself as an approved server-to-server caller to B14.

B14 spends the platform's own Provider credentials on its catalog execution
lane, so the Chat Worker signs every B14 request body with the deployment-owned
proof secret before the Service Binding call.

These tests are network-free: they load the transport classes from the Worker
source the way the existing Service Binding suites do and assert the outbound
request only.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.b14_service_proof import (
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    service_proof_headers,
)

WORKER_PATH = Path(__file__).resolve().parents[1] / "worker.py"

SIGNING_SECRET = "b14-signing-secret-0123456789abcdef"

# One fixed vector for the whole platform. The B14 application asserts the
# same value, so a change in either implementation is caught instead of
# silently breaking the other side.
CONTRACT_SECRET = "b14-contract-vector-secret-0123456789abcdef"
CONTRACT_TIMESTAMP = "1700000000"
CONTRACT_BODY = b'{"model":"x"}'
CONTRACT_PROOF = (
    "b6a1234c77da135333d5a3d01b87ff0a1624c9a1359fef7a25542ea4aba2c1a5"
)


class FakeRequest:
    """Minimal stand-in for the Cloudflare Request used by the transports."""

    def __init__(self, url: str, method: str, headers=None, body=None):
        self.url = url
        self.method = method
        self.headers = dict(headers or {})
        self.body = body
        self.js_object = {
            "url": url,
            "method": method,
            "headers": self.headers,
            "body": body,
        }


class FakeResponse:
    status = 200


class FakeBinding:
    def __init__(self):
        self.requests: list[Any] = []

    async def fetch(self, request: Any):
        self.requests.append(request)
        return FakeResponse()


async def _read_bounded_service_binding_body(response, max_bytes=None):
    return b"{}"


def _load_worker_classes(names: list[str]) -> dict[str, Any]:
    source = WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in names
    ]
    assert [node.name for node in classes] == names
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *classes,
        ],
        type_ignores=[],
    )
    namespace: dict[str, Any] = {
        "Any": Any,
        "Request": FakeRequest,
        "json": json,
        "httpx": httpx,
        "service_proof_headers": service_proof_headers,
        "MAX_B14_RESPONSE_BYTES": 1024,
        "MAX_CONFIGURED_B14_RESPONSE_BYTES": 1024,
        "read_bounded_service_binding_body": _read_bounded_service_binding_body,
        "ServiceBindingResponseTooLarge": Exception,
        "ServiceBindingResponseError": Exception,
        "cloudflare_chunk_bytes": bytes,
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKER_PATH), "exec"), namespace)
    return namespace


def test_shared_contract_vector_is_stable():
    """The proof construction is one shared contract, not two implementations."""
    expected = hmac.new(
        CONTRACT_SECRET.encode("utf-8"),
        CONTRACT_TIMESTAMP.encode("ascii") + b"." + CONTRACT_BODY,
        hashlib.sha256,
    ).hexdigest()
    assert expected == CONTRACT_PROOF


def test_proof_headers_are_absent_without_a_usable_secret():
    """An unconfigured proof must not fabricate a caller signature."""
    assert service_proof_headers(None, CONTRACT_BODY) == {}
    assert service_proof_headers("too-short", CONTRACT_BODY) == {}


def test_completed_transport_signs_the_exact_request_body():
    """The completed B14 request carries a proof bound to its own body."""
    classes = _load_worker_classes(["CloudflareB14ServiceTransport"])
    transport_cls = classes["CloudflareB14ServiceTransport"]
    binding = FakeBinding()
    transport = transport_cls(binding, SIGNING_SECRET)

    payload = {"model": "kira/qwen3.8-flash-free", "messages": []}
    asyncio.run(
        transport.post_json("https://b14.internal/api/pilot/v1/chat/completions", payload)
    )

    assert len(binding.requests) == 1
    sent = binding.requests[0]
    body = sent["body"].encode("utf-8")
    assert body == json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert sent["headers"][PROOF_HEADER]
    assert sent["headers"][PROOF_TIME_HEADER]
    expected = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        sent["headers"][PROOF_TIME_HEADER].encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert sent["headers"][PROOF_HEADER] == expected


def test_streaming_transport_signs_the_exact_request_body():
    """The streaming B14 request carries a proof bound to its own body."""
    classes = _load_worker_classes(["CloudflareB14StreamingServiceTransport"])
    transport_cls = classes["CloudflareB14StreamingServiceTransport"]
    binding = FakeBinding()
    transport = transport_cls(binding, SIGNING_SECRET)

    payload = {"model": "kira/qwen3.8-flash-free", "messages": []}
    request = httpx.Request(
        "POST",
        "https://b14.internal/api/pilot/v1/chat/completions/stream-preview",
        json=payload,
    )
    with pytest.raises(Exception):
        # The fake binding returns a minimal response the transport cannot
        # finish; the outbound request is what this test asserts.
        asyncio.run(transport.handle_async_request(request))

    assert len(binding.requests) == 1
    sent = binding.requests[0]
    body = sent["body"].encode("utf-8")
    assert sent["headers"][PROOF_HEADER]
    expected = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        sent["headers"][PROOF_TIME_HEADER].encode("ascii") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert sent["headers"][PROOF_HEADER] == expected


def test_worker_wires_the_proof_secret_into_both_b14_transports():
    """Both B14 transports receive the deployment-owned proof secret."""
    worker = WORKER_PATH.read_text(encoding="utf-8")
    assert "CloudflareB14ServiceTransport(b14_binding, b14_proof_secret)" in worker
    assert (
        "CloudflareB14StreamingServiceTransport(b14_binding, b14_proof_secret)" in worker
    )
    assert "b14_proof_secret = await resolve_secret_binding(" in worker

