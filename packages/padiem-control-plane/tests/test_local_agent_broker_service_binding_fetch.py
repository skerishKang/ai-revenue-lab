from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
from pathlib import Path
import sys
import types

from padiem_control_plane.local_agent_broker_http import MAX_LOCAL_AGENT_HTTP_BODY_BYTES


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)

_ROOT = Path(__file__).parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


edge = _load("padiem_local_agent_edge_fetch_test", "local_agent_broker_edge_worker.py")
state = _load("padiem_local_agent_state_fetch_test", "local_agent_broker_worker.py")


class _AsyncBody:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    def __aiter__(self):
        async def _iterate():
            for chunk in self._chunks:
                yield chunk

        return _iterate()


class _Request:
    def __init__(
        self,
        *,
        url: str = "https://local-agent.padiem.net/session",
        method: str = "POST",
        body: bytes = b"{}",
        content_type: str = "application/json",
    ) -> None:
        self.url = url
        self.method = method
        self._body_bytes = body
        self._content_type = content_type
        self.body = _AsyncBody(body)
        self.headers = {"content-type": content_type}

    def clone(self):
        return _Request(
            url=self.url,
            method=self.method,
            body=self._body_bytes,
            content_type=self._content_type,
        )


class _EdgeBinding:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response or _FakeResponse(
            json.dumps({"ok": False, "error": {"code": "local_agent_http_auth_required"}}),
            status=401,
            headers={"cache-control": "no-store", "content-type": "application/json"},
        )
        self.error = error
        self.requests = []

    async def fetch(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


class _EdgeEnv:
    def __init__(self, binding: _EdgeBinding) -> None:
        self.LOCAL_AGENT_BROKER_SERVICE = binding


class _StateStub:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self.result = result or {
            "status": 401,
            "headers": {"cache-control": "no-store", "content-type": "application/json"},
            "body": {
                "ok": False,
                "error": {
                    "code": "local_agent_http_auth_required",
                    "message": "authenticated Local Agent broker access is required",
                },
            },
        }
        self.error = error
        self.envelopes: list[dict] = []

    async def handle_device_http(self, envelope):
        self.envelopes.append(envelope)
        if self.error is not None:
            raise self.error
        return self.result


class _Namespace:
    def __init__(self, stub: _StateStub) -> None:
        self.stub = stub
        self.names: list[str] = []

    def idFromName(self, name: str):
        self.names.append(name)
        return f"do::{name}"

    def get(self, object_id: str):
        assert object_id == f"do::{self.names[-1]}"
        return self.stub


class _StateEnv:
    def __init__(self, stub: _StateStub) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = "control-plane.local-agent-broker.production.v1"
        self.LOCAL_AGENT_BROKER_STATE = _Namespace(stub)


def _decoded(response: _FakeResponse) -> dict:
    return json.loads(response.body)


def test_edge_forwards_exact_valid_request_through_private_service_fetch() -> None:
    binding = _EdgeBinding()
    request = _Request()
    response = asyncio.run(edge.Default(_EdgeEnv(binding)).fetch(request))

    assert len(binding.requests) == 1
    forwarded = binding.requests[0]
    assert forwarded is not request
    assert forwarded.url == request.url
    assert forwarded.method == request.method
    assert forwarded.headers == request.headers
    assert forwarded._body_bytes == request._body_bytes
    assert response is binding.response
    assert response.status == 401
    assert edge.PRIVATE_SERVICE_BINDING_FETCH is True
    assert edge.EDGE_TO_STATE_DEVICE_TRANSPORT == "service_binding_fetch"
    assert edge.BOUNDED_BODY is True
    assert edge.BOUNDED_BODY_REVALIDATED_BY_PRIVATE_STATE is True


def test_edge_keeps_closed_public_boundary_before_private_binding() -> None:
    binding = _EdgeBinding()
    entrypoint = edge.Default(_EdgeEnv(binding))

    get_response = asyncio.run(entrypoint.fetch(_Request(method="GET")))
    missing_response = asyncio.run(
        entrypoint.fetch(_Request(url="https://local-agent.padiem.net/not-a-device-route"))
    )

    assert get_response.status == 405
    assert _decoded(get_response)["error"]["code"] == "local_agent_http_post_required"
    assert missing_response.status == 404
    assert _decoded(missing_response)["error"]["code"] == "local_agent_http_route_not_found"
    assert binding.requests == []


def test_edge_private_binding_failure_is_generic_503() -> None:
    binding = _EdgeBinding(error=RuntimeError("private runtime unavailable"))
    response = asyncio.run(edge.Default(_EdgeEnv(binding)).fetch(_Request()))

    assert response.status == 503
    assert _decoded(response)["error"]["code"] == "local_agent_http_dependency_unavailable"


def test_state_private_fetch_builds_canonical_closed_device_envelope() -> None:
    stub = _StateStub()
    request = _Request(body=b"{}")
    response = asyncio.run(state.Default(_StateEnv(stub)).fetch(request))

    assert response.status == 401
    assert _decoded(response)["error"]["code"] == "local_agent_http_auth_required"
    assert len(stub.envelopes) == 1
    assert stub.envelopes[0] == {
        "method": "POST",
        "route": "/session",
        "content_type": "application/json",
        "body_b64": base64.b64encode(b"{}").decode("ascii"),
        "tls_verified": True,
    }
    assert state.PRIVATE_SERVICE_BINDING_FETCH is True
    assert state.EDGE_TO_STATE_DEVICE_TRANSPORT == "service_binding_fetch"
    assert state.PUBLIC_ENDPOINT_ADDED is False
    assert state.ADMIN_BROKER_RPC_PUBLIC is False


def test_state_private_fetch_rejects_unknown_route_and_non_post_without_do_call() -> None:
    stub = _StateStub()
    entrypoint = state.Default(_StateEnv(stub))

    unknown = asyncio.run(
        entrypoint.fetch(_Request(url="https://local-agent.padiem.net/not-a-device-route"))
    )
    non_post = asyncio.run(entrypoint.fetch(_Request(method="GET")))

    assert unknown.status == 404
    assert non_post.status == 405
    assert _decoded(non_post)["error"]["code"] == "local_agent_http_post_required"
    assert stub.envelopes == []


def test_state_private_fetch_enforces_body_bound_before_do_call() -> None:
    stub = _StateStub()
    response = asyncio.run(
        state.Default(_StateEnv(stub)).fetch(
            _Request(body=b"x" * (MAX_LOCAL_AGENT_HTTP_BODY_BYTES + 1))
        )
    )

    assert response.status == 413
    assert _decoded(response)["error"]["code"] == "local_agent_http_body_too_large"
    assert stub.envelopes == []


def test_state_private_do_failure_is_generic_503() -> None:
    stub = _StateStub(error=RuntimeError("durable object unavailable"))
    response = asyncio.run(state.Default(_StateEnv(stub)).fetch(_Request()))

    assert response.status == 503
    assert _decoded(response)["error"]["code"] == "local_agent_http_dependency_unavailable"


class _JsDict(dict):
    """Analog of workers-py JsDict: RPC'd dicts deserialize to a dict subclass."""


def _jsdict(value):
    if isinstance(value, dict):
        return _JsDict({key: _jsdict(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_jsdict(item) for item in value]
    return value


def test_state_private_fetch_accepts_dict_subclass_rpc_result() -> None:
    plain = {
        "status": 401,
        "headers": {"cache-control": "no-store", "content-type": "application/json"},
        "body": {
            "ok": False,
            "error": {
                "code": "local_agent_http_auth_required",
                "message": "authenticated Local Agent broker access is required",
            },
        },
    }
    result = _jsdict(plain)
    assert type(result) is _JsDict and isinstance(result, dict)
    assert type(result["headers"]) is _JsDict and isinstance(result["headers"], dict)
    assert type(result["body"]) is _JsDict and isinstance(result["body"], dict)

    stub = _StateStub(result=result)
    response = asyncio.run(state.Default(_StateEnv(stub)).fetch(_Request()))

    assert response.status == 401
    assert _decoded(response)["error"]["code"] == "local_agent_http_auth_required"
