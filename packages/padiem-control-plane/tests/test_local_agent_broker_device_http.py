from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types

from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    MAX_LOCAL_AGENT_HTTP_BODY_BYTES,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import (
    InMemoryLocalAgentBrokerStatePort,
    StateBackedLocalAgentBrokerAuthority,
)

from local_agent_broker_device_http import (
    ADMIN_BROKER_RPC_PUBLIC,
    CANONICAL_BINDING_AUTH_REUSED,
    DEVICE_HTTP_ROUTES,
    M2E_HANDLER_REUSED,
    PRIVATE_SERVICE_BOUNDARY,
    RAW_DEVICE_SECRET_LOGGED,
    SECOND_CREDENTIAL_VERIFIER,
    SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY,
    LocalAgentBrokerDeviceHttpService,
)


BASE = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.device-http-test.v1"
PEPPER = b"device-http-service-test-pepper-value"
CREDENTIAL = b"device-http-service-credential-value"


class _DurableMemoryStatePort(InMemoryLocalAgentBrokerStatePort):
    durable = True


class _DurableHttpState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        if record.session_id in self.records:
            raise RuntimeError("duplicate durable HTTP session")
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("durable HTTP session not found") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _UnusedMaterialResolver:
    def resolve(self, request):
        del request
        raise RuntimeError("material resolver is not used by this test")


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _service_fixture():
    state = _DurableMemoryStatePort()
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state,
    )
    authority.register_binding(
        binding_ref="binding.http.1",
        device_id="device.http.1",
        account_ref="account.http.1",
        workspace_ref="workspace.http.1",
        credential=CREDENTIAL,
        now=BASE,
        credential_ttl_seconds=3600,
    )
    http_state = _DurableHttpState()

    def rpc_factory() -> LocalAgentBrokerRpcFacade:
        return LocalAgentBrokerRpcFacade(
            authority=StateBackedLocalAgentBrokerAuthority(
                pepper=PEPPER,
                authority_ref=AUTHORITY_REF,
                state_port=state,
            )
        )

    service = LocalAgentBrokerDeviceHttpService(
        state_port=state,
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=rpc_factory,
        http_state=http_state,
        material_resolver=_UnusedMaterialResolver(),
        clock=lambda: BASE + timedelta(seconds=10),
    )
    return state, authority, http_state, service


def _session_body(*, session_id: str, account_ref: str = "account.http.1", credential: bytes = CREDENTIAL) -> bytes:
    return json.dumps(
        {
            "session_id": session_id,
            "binding_ref": "binding.http.1",
            "credential_b64": _encoded(credential),
            "account_ref": account_ref,
            "workspace_ref": "workspace.http.1",
            "now": BASE.isoformat(),
            "ttl_seconds": 900,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _envelope(body: bytes, *, route: str = "/session", tls_verified: bool = True) -> dict:
    return {
        "method": "POST",
        "route": route,
        "content_type": "application/json",
        "body_b64": _encoded(body),
        "tls_verified": tls_verified,
    }


def test_device_service_derives_scope_from_canonical_binding_and_reuses_m2e_handler() -> None:
    _, _, http_state, service = _service_fixture()
    result = service.handle(_envelope(_session_body(session_id="session.http.1")))

    assert result["status"] == 200
    assert result["body"]["ok"] is True
    assert result["body"]["session"]["account_ref"] == "account.http.1"
    assert result["body"]["session"]["workspace_ref"] == "workspace.http.1"
    assert "session.http.1" in http_state.records
    assert result["headers"] == {
        "cache-control": "no-store",
        "content-type": "application/json",
    }


def test_self_asserted_account_scope_is_not_authentication_authority() -> None:
    _, _, http_state, service = _service_fixture()
    result = service.handle(
        _envelope(
            _session_body(
                session_id="session.scope-mismatch.1",
                account_ref="account.attacker.1",
            )
        )
    )

    assert result["status"] == 403
    assert result["body"]["ok"] is False
    assert result["body"]["error"]["code"] == "local_agent_http_scope_mismatch"
    assert "session.scope-mismatch.1" not in http_state.records


def test_wrong_or_revoked_credential_fails_as_generic_auth_without_scope_leak() -> None:
    _, authority, _, service = _service_fixture()
    wrong = service.handle(
        _envelope(
            _session_body(
                session_id="session.wrong.1",
                credential=b"wrong-device-credential",
            )
        )
    )
    assert wrong["status"] == 401
    assert wrong["body"] == {
        "ok": False,
        "error": {
            "code": "local_agent_http_auth_required",
            "message": "authenticated Local Agent broker access is required",
        },
    }

    authority.revoke_binding("binding.http.1", now=BASE + timedelta(seconds=5))
    revoked = service.handle(_envelope(_session_body(session_id="session.revoked.1")))
    assert revoked["status"] == 401
    assert revoked["body"] == wrong["body"]


def test_device_service_rejects_transport_shape_before_credential_auth() -> None:
    _, _, _, service = _service_fixture()
    body = _session_body(session_id="session.transport.1")

    no_tls = service.handle(_envelope(body, tls_verified=False))
    assert no_tls["status"] == 403

    wrong_method = _envelope(body)
    wrong_method["method"] = "GET"
    assert service.handle(wrong_method)["status"] == 405

    assert service.handle(_envelope(body, route="/register_binding"))["status"] == 404

    wrong_type = _envelope(body)
    wrong_type["content_type"] = "text/plain"
    assert service.handle(wrong_type)["status"] == 415

    oversized = _envelope(b"x" * (MAX_LOCAL_AGENT_HTTP_BODY_BYTES + 1))
    assert service.handle(oversized)["status"] == 413


def test_device_service_boundary_truth() -> None:
    assert DEVICE_HTTP_ROUTES == ("/acknowledge", "/heartbeat", "/material", "/poll", "/session")
    assert PRIVATE_SERVICE_BOUNDARY is True
    assert CANONICAL_BINDING_AUTH_REUSED is True
    assert M2E_HANDLER_REUSED is True
    assert SECOND_CREDENTIAL_VERIFIER is False
    assert SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY is False
    assert ADMIN_BROKER_RPC_PUBLIC is False
    assert RAW_DEVICE_SECRET_LOGGED is False


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx=None, env=None):
        self.ctx = ctx
        self.env = env


_fake_workers = types.ModuleType("workers")
_fake_workers.Response = _FakeResponse
_fake_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_fake_workers.DurableObject = _FakeDurableObject
sys.modules["workers"] = _fake_workers

_EDGE_PATH = Path(__file__).parents[1] / "local_agent_broker_edge_worker.py"
_EDGE_SPEC = importlib.util.spec_from_file_location("padiem_local_agent_broker_edge_test", _EDGE_PATH)
assert _EDGE_SPEC is not None and _EDGE_SPEC.loader is not None
edge = importlib.util.module_from_spec(_EDGE_SPEC)
sys.modules[_EDGE_SPEC.name] = edge
_EDGE_SPEC.loader.exec_module(edge)


class _Chunk:
    def __init__(self, value: bytes) -> None:
        self._value = value

    def to_bytes(self) -> bytes:
        return self._value


class _BodyStream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return _Chunk(next(self._iterator))
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _Headers:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str):
        return self._values.get(name.lower())


class _Request:
    def __init__(self, *, url: str, method: str = "POST", body: bytes = b"{}", content_type: str = "application/json") -> None:
        self.url = url
        self.method = method
        self._body_bytes = body
        self._content_type = content_type
        self.body = _BodyStream((body,)) if body is not None else None
        self.headers = _Headers({"content-type": content_type})

    def clone(self):
        return _Request(
            url=self.url,
            method=self.method,
            body=self._body_bytes,
            content_type=self._content_type,
        )


class _PrivateBrokerService:
    def __init__(self) -> None:
        self.calls: list[tuple[_Request, bytes]] = []

    async def fetch(self, request: _Request):
        body = bytearray()
        if request.body is not None:
            async for chunk in request.body:
                body.extend(chunk.to_bytes())
        self.calls.append((request, bytes(body)))
        return _FakeResponse(
            json.dumps({"ok": True, "forwarded": True}, sort_keys=True, separators=(",", ":")),
            status=200,
            headers={"cache-control": "no-store", "content-type": "application/json"},
        )


class _EdgeEnv:
    def __init__(self, service: _PrivateBrokerService) -> None:
        self.LOCAL_AGENT_BROKER_SERVICE = service


def _edge(service: _PrivateBrokerService):
    return edge.Default(_EdgeEnv(service))


def test_edge_forwards_only_https_post_device_routes_over_private_binding() -> None:
    service = _PrivateBrokerService()
    response = asyncio.run(
        _edge(service).fetch(
            _Request(
                url="https://agent.example.test/session",
                body=b'{"binding_ref":"binding.http.1"}',
            )
        )
    )
    assert response.status == 200
    assert json.loads(response.body) == {"forwarded": True, "ok": True}
    assert len(service.calls) == 1
    forwarded, forwarded_body = service.calls[0]
    assert forwarded.method == "POST"
    assert forwarded.url == "https://agent.example.test/session"
    assert forwarded.headers.get("content-type") == "application/json"
    assert forwarded_body == b'{"binding_ref":"binding.http.1"}'

    for request_value, expected_status in (
        (_Request(url="http://agent.example.test/session"), 403),
        (_Request(url="https://agent.example.test/session", method="GET"), 405),
        (_Request(url="https://agent.example.test/register_binding"), 404),
    ):
        response = asyncio.run(_edge(service).fetch(request_value))
        assert response.status == expected_status
    assert len(service.calls) == 1


def test_edge_bounds_body_before_private_service_call() -> None:
    service = _PrivateBrokerService()
    response = asyncio.run(
        _edge(service).fetch(
            _Request(
                url="https://agent.example.test/poll",
                body=b"x" * (MAX_LOCAL_AGENT_HTTP_BODY_BYTES + 1),
            )
        )
    )
    assert response.status == 413
    assert service.calls == []


def test_edge_config_has_private_service_binding_but_no_route_or_preview() -> None:
    config_path = Path(__file__).parents[1] / ("wrang" + "ler.local-agent-broker-edge.jsonc")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["main"] == "local_agent_broker_edge_worker.py"
    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert config["services"] == [
        {
            "binding": "LOCAL_AGENT_BROKER_SERVICE",
            "service": "padiem-local-agent-broker-state",
        }
    ]
    assert "routes" not in config
