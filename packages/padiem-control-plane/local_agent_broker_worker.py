from __future__ import annotations
from typing import Callable, TypeVar

from workers import DurableObject, Response, WorkerEntrypoint
from padiem_control_plane.local_agent_broker_http import DurableLocalAgentSessionRecord, LocalAgentMaterialResolutionRequest
from local_agent_broker_device_http import LocalAgentBrokerDeviceHttpService
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_material_store import MAX_DURABLE_COMMAND_MATERIAL_BYTES, CloudflareDurableObjectCommandMaterialStore
from local_agent_broker_private_http_bridge import handle_private_device_fetch
from local_agent_broker_office_chunks import compose_broker_office_chunks, read_broker_office_part_rpc
from local_agent_broker_sql_state import (
    CloudflareDurableObjectHttpSessionState, CloudflareDurableObjectSerializedStateBackend, safe_ref,
)

_T = TypeVar("_T")


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
        self.office_chunks = compose_broker_office_chunks(
            storage=ctx.storage, state_port=self._runtime.state_port,
            authority_ref=self._runtime.authority_ref(), env=env,
        )
        self._device_http = LocalAgentBrokerDeviceHttpService(
            state_port=self._runtime.state_port,
            pepper=str(env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8"),
            authority_ref=self._runtime.authority_ref(),
            rpc_factory=self._runtime.facade,
            http_state=self._runtime.http_state,
            material_resolver=self._runtime.material_store,
            session_open_transaction=self._storage.transactionSync,
            office_chunks=self.office_chunks,
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

    async def enqueue_command_with_material(self, payload: dict, material: dict) -> dict:
        return self._runtime.enqueue_command_with_material(payload, material)

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

    async def reconcile_expired_command(self, payload: dict) -> dict:
        return self._runtime.reconcile_expired_command(payload)

    async def handle_device_http(self, envelope: dict) -> dict:
        return self._device_http.handle(envelope)

    async def device_truth(self, payload: dict) -> dict:
        return self._runtime.device_truth(payload)

    async def authenticate_device_session(self, payload: dict) -> dict:
        return self._runtime.authenticate_device_session(payload)

    async def terminal_command_result(self, payload: dict) -> dict:  # #3139 read-only RPC
        return self._runtime.terminal_command_result(payload)

    async def read_office_artifact_part(self, payload: dict) -> dict:
        return read_broker_office_part_rpc(self.office_chunks, payload)

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

    # #3127: only atomic enqueue+material is public through this gateway.
    async def enqueue_command_with_material(self, payload: dict, material: dict) -> dict:
        return await self._stub().enqueue_command_with_material(payload, material)

    async def resolve_command_material(self, payload: dict) -> dict:
        return await self._stub().resolve_command_material(payload)

    async def poll(self, payload: dict) -> dict:
        return await self._stub().poll(payload)

    async def admit_command(self, payload: dict) -> dict:
        return await self._stub().admit_command(payload)

    async def acknowledge(self, payload: dict) -> dict:
        return await self._stub().acknowledge(payload)

    async def reconcile_expired_command(self, payload: dict) -> dict:
        return await self._stub().reconcile_expired_command(payload)

    async def handle_device_http(self, envelope: dict) -> dict:
        return await self._stub().handle_device_http(envelope)

    async def device_truth(self, payload: dict) -> dict:
        return await self._stub().device_truth(payload)

    async def authenticate_device_session(self, payload: dict) -> dict:
        return await self._stub().authenticate_device_session(payload)

    async def terminal_command_result(self, payload: dict) -> dict:
        return await self._stub().terminal_command_result(payload)

    async def read_office_artifact_part(self, payload: dict) -> dict:
        return await self._stub().read_office_artifact_part(payload)

    async def fetch(self, request):
        return await handle_private_device_fetch(request, self._stub)


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
SESSION_OPEN_TRANSACTION_WIRED = True
SESSION_OPEN_TRANSACTION_SOURCE = "ctx.storage.transactionSync"
SESSION_OPEN_ATOMIC = True
SESSION_DOUBLE_WRITE_PRESENT = False
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
# #3094 narrow read-only device-fact projection (see the durable runtime for
# the fact vocabulary; ONLINE is derived by the B62 consumer's canonical rule).
NARROW_DEVICE_TRUTH_PROJECTION = True
DEVICE_TRUTH_VOCABULARY_HAS_ONLINE = False
DEVICE_TRUTH_SECOND_ONLINE_AUTHORITY = False
DEVICE_TRUTH_MUTATION = False
# #3436 B2c adds the read-only device-session authentication passthrough per
# entrypoint class, exactly like #3094's device_truth and #3139's terminal
# result: thin forwarding only. Its contract markers live in the durable
# runtime module.
PRODUCTION_DEPLOYMENT = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_SECRET_BOUND = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
