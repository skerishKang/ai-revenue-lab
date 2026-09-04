from __future__ import annotations

import base64
import json
from typing import Callable, TypeVar
from urllib.parse import urlparse

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.local_agent_broker_http import (
    MAX_LOCAL_AGENT_HTTP_BODY_BYTES,
    DurableLocalAgentSessionRecord,
    LocalAgentMaterialResolutionRequest,
)
from local_agent_broker_device_http import DEVICE_HTTP_ROUTES, LocalAgentBrokerDeviceHttpService
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_material_store import (
    MAX_DURABLE_COMMAND_MATERIAL_BYTES,
    CloudflareDurableObjectCommandMaterialStore,
)
from local_agent_broker_sql_state import (
    CloudflareDurableObjectHttpSessionState,
    CloudflareDurableObjectSerializedStateBackend,
    safe_ref,
)

_T = TypeVar("_T")
_PRIVATE_DEVICE_ROUTE_SET = frozenset(DEVICE_HTTP_ROUTES)
_PRIVATE_RESPONSE_HEADERS = {"cache-control": "no-store", "content-type": "application/json"}


def _private_response(status: int, body: dict) -> Response:
    return Response(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        status=status,
        headers=_PRIVATE_RESPONSE_HEADERS,
    )


def _private_error(status: int, code: str, message: str) -> Response:
    return _private_response(status, {"ok": False, "error": {"code": code, "message": message}})


async def _bounded_private_request_body(request) -> bytes:
    if request.body is None:
        return b""
    output = bytearray()
    async for chunk in request.body:
        to_bytes = getattr(chunk, "to_bytes", None)
        raw = to_bytes() if callable(to_bytes) else bytes(chunk)
        if not isinstance(raw, bytes):
            raw = bytes(raw)
        if len(output) + len(raw) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            raise OverflowError("Local Agent private device request exceeds size bound")
        output.extend(raw)
    return bytes(output)


class LocalAgentBrokerDurableObject(DurableObject):
    """Thin platform entrypoint over the durable broker runtime composition."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self._runtime = LocalAgentBrokerDurableRuntime(storage=ctx.storage, env=env)
        self._storage = ctx.storage
        self._backend = self._runtime.backend
        self._state_port = self._runtime.state_port
        self.http_state = self._runtime.http_state
        self.material_store = self._runtime.material_store
        self._device_http = LocalAgentBrokerDeviceHttpService(
            state_port=self._runtime.state_port,
            pepper=str(env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8"),
            authority_ref=self._runtime.authority_ref(),
            rpc_factory=self._runtime.facade,
            http_state=self._runtime.http_state,
            material_resolver=self._runtime.material_store,
        )

    def _authority_ref(self) -> str:
        return self._runtime.authority_ref()

    def _facade(self):
        return self._runtime.facade()

    def _transaction(self, operation: Callable[[], _T]) -> _T:
        return self._runtime.transaction(operation)

    async def register_binding(self, payload: dict) -> dict:
        return self._runtime.register_binding(payload)

    async def rotate_credential(self, payload: dict) -> dict:
        return self._runtime.rotate_credential(payload)

    async def revoke_binding(self, payload: dict) -> dict:
        return self._runtime.revoke_binding(payload)

    async def open_session(self, payload: dict) -> dict:
        return self._runtime.open_session(payload)

    async def enqueue_command(self, payload: dict) -> dict:
        return self._runtime.enqueue_command(payload)

    async def store_command_material(self, wire: dict) -> dict:
        return self._runtime.store_command_material(wire)

    async def resolve_command_material(self, payload: dict) -> dict:
        return self._runtime.resolve_command_material(payload)

    async def poll(self, payload: dict) -> dict:
        return self._runtime.poll(payload)

    async def admit_command(self, payload: dict) -> dict:
        return self._runtime.admit_command(payload)

    async def acknowledge(self, payload: dict) -> dict:
        return self._runtime.acknowledge(payload)

    async def handle_device_http(self, envelope: dict) -> dict:
        return self._device_http.handle(envelope)

    async def fetch(self, request):
        del request
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})


class Default(WorkerEntrypoint):
    """Private Service Binding gateway to the server-owned broker object."""

    def _authority_ref(self) -> str:
        return safe_ref(str(self.env.LOCAL_AGENT_BROKER_AUTHORITY_REF), "authority_ref")

    def _stub(self):
        authority_ref = self._authority_ref()
        namespace = self.env.LOCAL_AGENT_BROKER_STATE
        object_id = namespace.idFromName(authority_ref)
        return namespace.get(object_id)

    async def register_binding(self, payload: dict) -> dict:
        return await self._stub().register_binding(payload)

    async def rotate_credential(self, payload: dict) -> dict:
        return await self._stub().rotate_credential(payload)

    async def revoke_binding(self, payload: dict) -> dict:
        return await self._stub().revoke_binding(payload)

    async def open_session(self, payload: dict) -> dict:
        return await self._stub().open_session(payload)

    async def enqueue_command(self, payload: dict) -> dict:
        return await self._stub().enqueue_command(payload)

    async def store_command_material(self, wire: dict) -> dict:
        return await self._stub().store_command_material(wire)

    async def resolve_command_material(self, payload: dict) -> dict:
        return await self._stub().resolve_command_material(payload)

    async def poll(self, payload: dict) -> dict:
        return await self._stub().poll(payload)

    async def admit_command(self, payload: dict) -> dict:
        return await self._stub().admit_command(payload)

    async def acknowledge(self, payload: dict) -> dict:
        return await self._stub().acknowledge(payload)

    async def handle_device_http(self, envelope: dict) -> dict:
        return await self._stub().handle_device_http(envelope)

    async def fetch(self, request):
        parsed = urlparse(str(getattr(request, "url", "")))
        if parsed.path not in _PRIVATE_DEVICE_ROUTE_SET:
            return Response("Not Found", status=404, headers={"cache-control": "no-store"})
        if parsed.scheme.lower() != "https":
            return _private_error(403, "local_agent_http_tls_required", "Local Agent broker requires HTTPS")
        if getattr(request, "method", None) != "POST":
            return _private_error(405, "local_agent_http_post_required", "Local Agent broker routes accept POST only")

        try:
            body = await _bounded_private_request_body(request)
        except OverflowError:
            return _private_error(413, "local_agent_http_body_too_large", "Local Agent broker request body exceeds size bound")
        except Exception:
            return _private_error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid")

        headers = getattr(request, "headers", None)
        content_type = headers.get("content-type") if headers is not None else None
        envelope = {
            "method": "POST",
            "route": parsed.path,
            "content_type": str(content_type) if content_type is not None else "",
            "body_b64": base64.b64encode(body).decode("ascii"),
            "tls_verified": True,
        }

        try:
            result = await self._stub().handle_device_http(envelope)
        except Exception:
            return _private_error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")

        if (
            type(result) is not dict
            or type(result.get("status")) is not int
            or type(result.get("headers")) is not dict
            or type(result.get("body")) is not dict
            or not 100 <= result["status"] <= 599
        ):
            return _private_error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")
        return _private_response(result["status"], result["body"])


CLOUDFLARE_DO_ADAPTER = True
FOUNDATION_PACKAGE_SIDE_EFFECT_FREE = True
SQLITE_BACKED_DURABLE_OBJECT = True
SERVER_OWNED_AUTHORITY_ROUTING = True
M2G_SERIALIZED_STATE_REUSED = True
ATOMIC_VERSION_CAS = True
STALE_CAS_FAILS_CLOSED = True
M2E_HTTP_SESSION_STATE_DURABLE = True
LAST_SEEN_MONOTONIC = True
CANONICAL_BROKER_RPC_REUSED = True
SECOND_REPLAY_SEQUENCE_AUTHORITY = False
RAW_DEVICE_CREDENTIAL_PERSISTED = False
PUBLIC_FETCH = False
PRIVATE_SERVICE_BINDING_FETCH = True
EDGE_TO_STATE_DEVICE_TRANSPORT = "service_binding_fetch"
DURABLE_COMMAND_MATERIAL_STORE = True
CANONICAL_MATERIAL_WIRE_REUSED = True
SECOND_FINGERPRINT_ALGORITHM = False
BROKER_METADATA_EXPANDED_WITH_ARGV = False
EXACT_COMMAND_CORRELATION_ON_STORE = True
EXACT_RESOLUTION_CORRELATION = True
QUEUED_STATE_REQUIRED_FOR_STORE = True
MATERIAL_EXPIRY_BOUNDED = True
ACK_PURGES_MATERIAL = True
ROTATION_REVOCATION_PURGES_MATERIAL = True
M2E_RESOLVER_PORT_IMPLEMENTED = True
BEHAVIOR_PRESERVING_REFACTOR = True
THIN_WORKER_ENTRYPOINT = True
DURABLE_RUNTIME_COMPOSITION_EXTRACTED = True
BROKER_SQL_STATE_MODULE_SEPARATED = True
HTTP_SESSION_STATE_SEPARATED = True
COMMAND_MATERIAL_STORE_SEPARATED = True
LIFECYCLE_COORDINATOR_EXTRACTED = True
CLOUD_PLATFORM_IMPORT_REQUIRED_FOR_CORE_TESTS = False
CANONICAL_BROKER_AUTHORITY_CHANGED = False
FINGERPRINT_AUTHORITY_CHANGED = False
BROKER_MATERIAL_BOUNDARY_CHANGED = False
P01_AUTHORITY_CHANGED = False
WIRE_CONTRACT_CHANGED = False
DB_SEMANTICS_INTENTIONALLY_CHANGED = False
PRIVATE_DEVICE_HTTP_SERVICE = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
ADMIN_BROKER_RPC_PUBLIC = False
PUBLIC_ENDPOINT_ADDED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_SECRET_BOUND = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
