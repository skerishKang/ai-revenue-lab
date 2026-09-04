from __future__ import annotations

from typing import Any, Callable, TypeVar

from padiem_control_plane.local_agent_broker_http import LocalAgentMaterialResolutionRequest
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import SerializedLocalAgentBrokerStatePort

from local_agent_broker_material_store import CloudflareDurableObjectCommandMaterialStore, closed_mapping
from local_agent_broker_sql_state import (
    CloudflareDurableObjectHttpSessionState,
    CloudflareDurableObjectSerializedStateBackend,
    parse_iso,
    safe_ref,
)

_T = TypeVar("_T")
_MATERIAL_RESOLVE_RPC_KEYS = frozenset(
    {
        "request_ref",
        "session_id",
        "binding_ref",
        "command_id",
        "request_fingerprint",
        "server_requested_at",
    }
)


class LocalAgentBrokerDurableRuntime:
    """Cloud-platform-neutral composition for the durable Local Agent broker authority."""

    def __init__(self, *, storage: Any, env: Any) -> None:
        self._storage = storage
        self._env = env
        self.backend = CloudflareDurableObjectSerializedStateBackend(storage)
        self.state_port = SerializedLocalAgentBrokerStatePort(backend=self.backend)
        self.http_state = CloudflareDurableObjectHttpSessionState(storage)
        self.material_store = CloudflareDurableObjectCommandMaterialStore(
            storage,
            state_port=self.state_port,
            authority_ref=self.authority_ref(),
        )

    def authority_ref(self) -> str:
        return safe_ref(str(self._env.LOCAL_AGENT_BROKER_AUTHORITY_REF), "authority_ref")

    def facade(self) -> LocalAgentBrokerRpcFacade:
        pepper = str(self._env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8")
        authority = StateBackedLocalAgentBrokerAuthority(
            pepper=pepper,
            authority_ref=self.authority_ref(),
            state_port=self.state_port,
        )
        return LocalAgentBrokerRpcFacade(authority=authority)

    def transaction(self, operation: Callable[[], _T]) -> _T:
        transaction_sync = getattr(self._storage, "transactionSync", None)
        if not callable(transaction_sync):
            raise RuntimeError("SQLite-backed Durable Object transactionSync is required")
        return transaction_sync(operation)

    def register_binding(self, payload: dict) -> dict:
        return self.facade().register_binding(payload)

    def rotate_credential(self, payload: dict) -> dict:
        def operation() -> dict:
            result = self.facade().rotate_credential(payload)
            if result.get("ok") is True:
                self.material_store.purge_binding(result["binding"]["binding_ref"])
            return result
        return self.transaction(operation)

    def revoke_binding(self, payload: dict) -> dict:
        def operation() -> dict:
            result = self.facade().revoke_binding(payload)
            if result.get("ok") is True:
                self.material_store.purge_binding(result["binding"]["binding_ref"])
            return result
        return self.transaction(operation)

    def open_session(self, payload: dict) -> dict:
        return self.facade().open_session(payload)

    def enqueue_command(self, payload: dict) -> dict:
        return self.facade().enqueue_command(payload)

    def store_command_material(self, wire: dict) -> dict:
        return self.transaction(lambda: self.material_store.store(wire))

    def resolve_command_material(self, payload: dict) -> dict:
        payload = closed_mapping(payload, _MATERIAL_RESOLVE_RPC_KEYS, "material resolution RPC")
        request = LocalAgentMaterialResolutionRequest(
            request_ref=payload["request_ref"],
            session_id=payload["session_id"],
            binding_ref=payload["binding_ref"],
            command_id=payload["command_id"],
            request_fingerprint=payload["request_fingerprint"],
            server_requested_at=parse_iso(payload["server_requested_at"], "server_requested_at"),
        )
        return {"ok": True, "material": self.material_store.resolve(request)}

    def poll(self, payload: dict) -> dict:
        return self.facade().poll(payload)

    def admit_command(self, payload: dict) -> dict:
        return self.facade().admit_command(payload)

    def acknowledge(self, payload: dict) -> dict:
        def operation() -> dict:
            result = self.facade().acknowledge(payload)
            if result.get("ok") is True:
                self.material_store.purge_command(result["command"]["command_id"])
            return result
        return self.transaction(operation)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "durable_runtime_composition": True,
            "lifecycle_coordinator": True,
            "canonical_broker_rpc_reused": True,
            "second_replay_sequence_authority": False,
            "fingerprint_authority_changed": False,
            "p01_authority_changed": False,
            "wire_contract_changed": False,
            "production_mutation": False,
            "production_ready": False,
        }


DURABLE_RUNTIME_COMPOSITION_EXTRACTED = True
LIFECYCLE_COORDINATOR_EXTRACTED = True
CANONICAL_BROKER_AUTHORITY_CHANGED = False
SECOND_REPLAY_SEQUENCE_AUTHORITY = False
FINGERPRINT_AUTHORITY_CHANGED = False
P01_AUTHORITY_CHANGED = False
WIRE_CONTRACT_CHANGED = False
CLOUD_PLATFORM_IMPORT_REQUIRED = False
