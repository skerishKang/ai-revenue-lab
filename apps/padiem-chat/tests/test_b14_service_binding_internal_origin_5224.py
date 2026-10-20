"""#5224 — B62 Chat sends every B14 call on the internal Service Binding origin.

B14 authorizes platform-credential dispatch only for its internal Service
Binding callers. The B62 Chat product must therefore reach B14 on the
canonical internal origin (``https://b14.internal``) instead of the public
``workers.dev`` address, exactly like the B54 Engine transport and the B62
Chat model-authority read path already do.

The real transport classes are executed in isolation, so no Cloudflare
binding, no network and no provider call is involved.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

WORKER_PATH = Path(__file__).resolve().parents[1] / "worker.py"
INTERNAL_ORIGIN = "https://b14.internal"
PUBLIC_ORIGIN = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"


def _load_transport_class(class_name: str, namespace: dict):
    """Execute one real transport class in isolation."""
    tree = ast.parse(WORKER_PATH.read_text("utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == class_name
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            node,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(WORKER_PATH), "exec"), namespace)
    return namespace[class_name]


def test_completed_json_transport_sends_b14_on_the_internal_origin():
    captured: list[tuple[str, dict]] = []

    class Request:
        def __init__(self, url, **kwargs):
            captured.append((url, kwargs))
            self.js_object = self

    class Response:
        status = 200

    class Binding:
        async def fetch(self, request):
            return Response()

    async def read_body(response, *, max_bytes):
        return b'{"id":"r1"}'

    class TooLarge(Exception):
        pass

    class BadRead(Exception):
        pass

    namespace = {
        "Request": Request,
        "json": json,
        "MAX_B14_RESPONSE_BYTES": 1024 * 1024,
        "MAX_CONFIGURED_B14_RESPONSE_BYTES": 1024 * 1024,
        "read_bounded_service_binding_body": read_body,
        "ServiceBindingResponseTooLarge": TooLarge,
        "ServiceBindingResponseError": BadRead,
    }
    transport_class = _load_transport_class("CloudflareB14ServiceTransport", namespace)
    transport = transport_class(Binding())

    async def scenario():
        await transport.post_json(
            f"{PUBLIC_ORIGIN}/api/pilot/v1/chat/completions",
            {"model": "agnes-ai/agnes-3.0-flash", "messages": []},
        )
        await transport.post_json(
            f"{PUBLIC_ORIGIN}/api/pilot/v1/chat/completions?x=1",
            {"model": "agnes-ai/agnes-3.0-flash", "messages": []},
        )

    asyncio.run(scenario())

    urls = [url for url, _ in captured]
    assert urls == [
        f"{INTERNAL_ORIGIN}/api/pilot/v1/chat/completions",
        f"{INTERNAL_ORIGIN}/api/pilot/v1/chat/completions?x=1",
    ]
    assert all(PUBLIC_ORIGIN not in url for url in urls)


def test_streaming_transport_sends_b14_on_the_internal_origin():
    captured: list[tuple[str, dict]] = []

    class Request:
        def __init__(self, url, **kwargs):
            captured.append((url, kwargs))
            self.js_object = self

    class Response:
        status = 200
        headers = {"content-type": "text/event-stream"}
        body = b"data: {}\n\n"

    class Binding:
        async def fetch(self, request):
            return Response()

    import httpx

    namespace = {
        "Request": Request,
        "httpx": httpx,
        "_CloudflareReadableByteStream": object,
    }
    transport_class = _load_transport_class(
        "CloudflareB14StreamingServiceTransport", namespace,
    )

    # The streaming transport is an httpx transport; only the request
    # construction matters for this contract.
    assert transport_class.B14_INTERNAL_ORIGIN == INTERNAL_ORIGIN
    assert transport_class._internal_service_url(
        f"{PUBLIC_ORIGIN}/api/pilot/v1/chat/completions/stream-preview",
    ) == f"{INTERNAL_ORIGIN}/api/pilot/v1/chat/completions/stream-preview"
    assert transport_class._internal_service_url(
        f"{PUBLIC_ORIGIN}/api/pilot/v1/chat/completions/auto-stream-preview?y=2",
    ) == f"{INTERNAL_ORIGIN}/api/pilot/v1/chat/completions/auto-stream-preview?y=2"
