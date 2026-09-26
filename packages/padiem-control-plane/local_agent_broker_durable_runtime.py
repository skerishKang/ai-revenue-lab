from __future__ import annotations

from typing import Any, Callable, TypeVar

from padiem_control_plane.contracts import ControlPlaneContractError
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
        """Enqueue a command *without* binding material in the same transaction.

        Retained for callers that have no material to bind yet. It cannot reach
        a terminal state: `admit_command` and `acknowledge` refuse a command
        whose material is absent, so a command enqueued this way can never be
        executed or acknowledged. New callers should use
        `enqueue_command_with_material`, which is the atomic product path.
        """
        return self.facade().enqueue_command(payload)

    def enqueue_command_with_material(self, payload: dict, wire: dict) -> dict:
        """#3127 — commit the canonical command and its material atomically.

        Both writes live in this Durable Object's SQLite storage, so one
        `transactionSync` is the whole boundary. Before this existed the two
        writes were two independent operations and a crash between them left a
        durable command with no material: undispatchable, unadmittable and,
        because the #3121 reconciliation exit only serves ADMITTED commands,
        without any terminal path at all.

        The canonical enqueue keeps its own authority. Nothing here mints a
        sequence, a revision or a fingerprint: the material wire is validated
        against the command the canonical path just persisted, so a mismatch
        fails the whole transaction closed.

        An exact retry is the #3118/#3120 behaviour applied to both writes at
        once: the canonical command is re-served unchanged and the identical
        material row is reused. A retry whose material differs from the stored
        one fails closed.
        """

        def operation() -> dict:
            result = self.facade().enqueue_command(payload)
            if result.get("ok") is not True:
                # A canonical refusal (duplicate, scope, ttl) wrote nothing, so
                # there is nothing to bind and nothing to roll back.
                return result
            material = self.material_store.store(wire)
            return {"ok": True, "command": result["command"], "material": material}
        return self.transaction(operation)

    def store_command_material(self, wire: dict) -> dict:
        return self.transaction(lambda: self.material_store.store(wire))

    def _require_persisted_material(self, command_id: Any, field_name: str) -> None:
        """Fail closed when a command has no durable material.

        A command with no material cannot be run, so admitting it would create a
        terminal fact for work that never happened, and acknowledging it would
        record a fabricated execution result. Both are refused at the Durable
        Object boundary, before the canonical authority is consulted.
        """

        safe = safe_ref(command_id, "command_id")
        if not self.material_store.has_persisted_material(safe):
            raise ControlPlaneContractError(
                "broker_command_material_missing",
                f"{field_name} requires the command's durable material to be persisted",
            )

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
        def operation() -> dict:
            self._require_persisted_material(payload.get("command_id"), "admission")
            return self.facade().admit_command(payload)
        return self.transaction(operation)

    def acknowledge(self, payload: dict) -> dict:
        def operation() -> dict:
            self._require_persisted_material(payload.get("command_id"), "acknowledgement")
            result = self.facade().acknowledge(payload)
            if result.get("ok") is True:
                self.material_store.purge_command(result["command"]["command_id"])
            return result
        return self.transaction(operation)

    def reconcile_expired_command(self, payload: dict) -> dict:
        """#3121 — reconcile one expired ADMITTED command without replay.

        Like a canonical acknowledgement, a successful reconciliation is
        terminal, so the stored command material is purged in the same
        transaction and can never resolve again.
        """
        def operation() -> dict:
            result = self.facade().reconcile_expired_command(payload)
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
            "enqueue_material_atomic": True,
            "material_reused_on_exact_retry": True,
            "material_less_admission_refused": True,
            "material_less_acknowledgement_refused": True,
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
ENQUEUE_MATERIAL_ATOMIC = True
MATERIAL_WRITTEN_IN_SEPARATE_TRANSACTION = False
MATERIAL_LESS_COMMAND_ADMITTABLE = False
MATERIAL_LESS_COMMAND_ACKNOWLEDGABLE = False
SECOND_MATERIAL_SEQUENCE_MINT = False
SECOND_MATERIAL_REVISION_MINT = False
