from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import MAX_POLL_BATCH, BrokerBindingState, BrokerCommandState
from padiem_control_plane.local_agent_broker_auth import StateBackedLocalAgentBindingAuthenticator
from padiem_control_plane.local_agent_broker_http import LocalAgentMaterialResolutionRequest
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import (
    StateBackedLocalAgentBrokerAuthority,
    terminal_command_result_from_snapshot,
)
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

# #3094 — the device-truth projection is owner-scoped by the server-derived
# identity only; no conversation, device or destination ref is accepted here.
_DEVICE_TRUTH_RPC_KEYS = frozenset({"account_ref", "workspace_ref"})

# #3436 B2c — the device-session authentication RPC accepts exactly the
# caller-held session material and nothing else. No user_id, account_ref,
# workspace_ref, tenant or product key exists: those are derived by the
# canonical authority from the verified binding state, never named by a caller.
_DEVICE_SESSION_AUTH_RPC_KEYS = frozenset({"session_id", "binding_ref", "credential_b64"})

def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


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
        return self.transaction(lambda: self.facade().register_binding(payload))

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
        return self.transaction(lambda: self.facade().open_session(payload))

    def enqueue_command(self, payload: dict) -> dict:
        """Enqueue a command *without* binding material in the same transaction.

        Retained for callers that have no material to bind yet. It cannot reach
        a terminal state: `admit_command` and `acknowledge` refuse a command
        whose material is absent, so a command enqueued this way can never be
        executed or acknowledged. New callers should use
        `enqueue_command_with_material`, which is the atomic product path.

        It still mints a sequence, records the used command_id and can trigger
        terminal-history compaction, so its ledger writes and blob swap commit
        inside the same storage transaction as every other mutator (#3123).
        """
        return self.transaction(lambda: self.facade().enqueue_command(payload))

    def enqueue_command_with_material(self, payload: dict, material: dict) -> dict:
        """#3127 — commit the canonical command and its material atomically.

        Both writes live in this Durable Object's SQLite storage, so one
        `transactionSync` is the whole boundary. Before this existed the two
        writes were two independent operations and a crash between them left a
        durable command with no material: undispatchable, unadmittable and,
        because the #3121 reconciliation exit only serves ADMITTED commands,
        without any terminal path at all.

        The caller supplies the material *body* only. The command id, binding,
        sequence, request fingerprint and revision are the canonical path's to
        decide, and they are decided inside this transaction: the wire is
        assembled from the command the canonical enqueue just persisted, not
        from anything the caller predicted. A caller that guessed a sequence or
        a revision would be guessing a server-owned value, so the atomic API
        does not accept one.

        An exact retry is the #3118/#3120 behaviour applied to both writes at
        once: the canonical command is re-served unchanged and an identical
        material row is reused. A retry whose material body differs from the
        stored one fails closed.
        """

        def operation() -> dict:
            result = self.facade().enqueue_command(payload)
            if result.get("ok") is not True:
                # A canonical refusal (duplicate, scope, ttl) wrote nothing, so
                # there is nothing to bind and nothing to roll back.
                return result
            command = result["command"]
            wire = {
                "contract_version": "claw-local-command-material.v2",
                "command_id": command["command_id"],
                "binding_ref": command["binding_ref"],
                "sequence": command["sequence"],
                "request_fingerprint": command["request_fingerprint"],
                "revision_ref": command["revision_ref"],
                "material": material,
            }
            stored = self.material_store.store(wire)
            return {"ok": True, "command": command, "material": stored}
        return self.transaction(operation)

    def store_command_material(self, wire: dict) -> dict:
        return self.transaction(lambda: self.material_store.store(wire))

    def _persisted_command_state(self, command_id: str) -> Any:
        """The canonical lifecycle state of a command, or `None` if unknown.

        Read from the same persisted snapshot the authority works from, so this
        is a guard condition, never a second authority over the command.
        """

        stored = self.state_port.load(authority_ref=self.authority_ref())
        for command in stored.snapshot.commands:
            if command.command_id == command_id:
                return command.state
        return None

    def _require_material_for_transition(self, command_id: Any, state_name: str, field_name: str) -> None:
        """Fail closed when a *live* transition would run without material.

        The guard is scoped to the one state in which the transition still
        creates a fact. A command that is already terminal is not blocked: its
        material is purged by that very transition, so refusing on presence
        would break the #3118 exact-retry recovery of a lost acknowledgement
        response. Every other state is left to the canonical authority, whose
        refusal is the more precise answer.
        """

        safe = safe_ref(command_id, "command_id")
        if self._persisted_command_state(safe) is not state_name:
            return
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
        """Deliver only commands the device can actually run, without hiding
        the runnable work behind any number of ones it cannot.

        #3127 — a command whose material was never persisted is not
        material-resolvable, so handing it to a device advertises work that
        cannot start: the device would poll it, try to admit it, be refused, and
        learn nothing.

        The canonical authority still decides *which* commands are pollable.
        This withholds only the ones the device could not execute, and it does so
        by **walking the canonical window** rather than by truncating it. Both
        earlier shapes were wrong in the same way: dropping the withheld command
        from the page let a single orphan occupy a one-command page, and capping
        the walk merely moved that threshold to the cap, so 65 orphans hid the
        66th command. A cap is not a fix; the walk has to end on the queue
        being exhausted, not on a counter.

        So the walk runs in `MAX_POLL_BATCH` pages until it has filled the
        caller's page or the canonical eligible queue is genuinely empty. The
        caller's `limit` still bounds what it receives, and the first page is
        requested with that same limit so the canonical authority — not a second
        copy of its rule — validates the caller's limit and cursor.

        Termination is structural rather than numeric: every page strictly
        advances the cursor past what it returned, and the queue is bounded by
        the snapshot's own collection cap, so the walk ends when the queue does.
        The only guard is against an authority that would fail to advance, which
        would spin without making progress.
        """

        def operation() -> dict:
            limit = payload.get("limit", MAX_POLL_BATCH)
            cursor = payload.get("after_sequence", 0)
            # The first page asks for the caller's own limit, so an invalid
            # limit or cursor is refused by the canonical authority exactly as
            # it would be without this layer.
            page = self.facade().poll({**payload, "after_sequence": cursor, "limit": limit})
            if page.get("ok") is not True:
                return page
            deliverable: list[dict] = []
            while True:
                commands = page["commands"]
                if not commands:
                    return {**page, "ok": True, "commands": deliverable}
                advanced = cursor
                for command in commands:
                    advanced = command["sequence"]
                    if self.material_store.has_persisted_material(command["command_id"]):
                        deliverable.append(command)
                        if len(deliverable) == limit:
                            return {**page, "commands": deliverable}
                if advanced <= cursor:
                    # An authority that does not advance the cursor would spin
                    # here forever without reaching later commands.
                    return {**page, "ok": True, "commands": deliverable}
                cursor = advanced
                page = self.facade().poll(
                    {**payload, "after_sequence": cursor, "limit": MAX_POLL_BATCH}
                )
                if page.get("ok") is not True:
                    return page
        return self.transaction(operation)

    def admit_command(self, payload: dict) -> dict:
        def operation() -> dict:
            self._require_material_for_transition(
                payload.get("command_id"), BrokerCommandState.QUEUED, "admission"
            )
            return self.facade().admit_command(payload)
        return self.transaction(operation)

    def acknowledge(self, payload: dict) -> dict:
        def operation() -> dict:
            # Scoped to ADMITTED: a command that is already acknowledged has had
            # its material purged by that acknowledgement, and the #3118 exact
            # retry of a lost response must still reach the canonical idempotent
            # branch instead of being refused for a row that no longer exists.
            self._require_material_for_transition(
                payload.get("command_id"), BrokerCommandState.ADMITTED, "acknowledgement"
            )
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

    def device_truth(self, payload: dict) -> dict:
        """#3094 — one narrow, read-only, owner-scoped canonical device-fact read.

        This is the projection method the B62 "Connect this computer" panel
        consumes through the private Service Binding gateway. It reads only the
        canonical #3080 state this authority already owns and reports the facts
        B62 needs; it derives nothing beyond a pure rename of its own records:

        * ``revoked``   — the binding is revoked;
        * ``credential_expired`` — the stored credential expiry has passed;
        * ``paired_offline`` — everything else.

        ``online`` is deliberately absent from this vocabulary: the canonical
        server-backed ONLINE projection is derived by the B62 consumer through
        the existing ``kagent.local_agent_server_projection`` rule from the
        binding + session + heartbeat facts below. A broker that also claimed
        ONLINE here would be a second ONLINE authority.

        Read-only: no transaction, no compare-and-swap, no material or command
        state is touched. The response is assembled from a closed allowlist and
        never carries the credential digest, session secret or any raw device
        credential.
        """

        try:
            if not isinstance(payload, dict) or not set(payload) <= _DEVICE_TRUTH_RPC_KEYS:
                raise ValueError("device truth schema mismatch")
            account_ref = safe_ref(str(payload["account_ref"]), "account_ref")
            workspace_ref = payload.get("workspace_ref")
            if workspace_ref is not None:
                workspace_ref = safe_ref(str(workspace_ref), "workspace_ref")
        except (KeyError, TypeError, ValueError):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_device_truth_request",
                    "message": "device truth request was rejected",
                },
            }

        stored = self.state_port.load(authority_ref=self.authority_ref())
        snapshot = stored.snapshot
        now = datetime.now(timezone.utc)

        candidates = [
            binding
            for binding in snapshot.bindings
            if binding.account_ref == account_ref
            and (workspace_ref is None or binding.workspace_ref == workspace_ref)
        ]
        if not candidates:
            return {"ok": True, "available": False, "reason": "no_device_binding"}
        # The owner's newest binding is the device this authority considers
        # current; older and revoked bindings never win the tie-break.
        binding = max(candidates, key=lambda item: (item.issued_at, item.credential_generation))

        session = None
        for candidate in snapshot.sessions:
            if candidate.binding_ref != binding.binding_ref:
                continue
            if session is None or candidate.issued_at > session.issued_at:
                session = candidate
        last_seen_at = None
        if session is not None:
            try:
                record = self.http_state.load_session(session.session_id)
            except (ValueError, KeyError, RuntimeError):
                record = None
            if record is not None:
                last_seen_at = record.last_seen_at

        if binding.state is BrokerBindingState.REVOKED:
            canonical_state = "revoked"
        elif now >= binding.credential_expires_at:
            canonical_state = "credential_expired"
        else:
            canonical_state = "paired_offline"

        facts: dict[str, Any] = {
            "canonical_state": canonical_state,
            "binding": {
                "binding_ref": binding.binding_ref,
                "device_id": binding.device_id,
                "account_ref": binding.account_ref,
                "workspace_ref": binding.workspace_ref,
                "credential_generation": binding.credential_generation,
                "issued_at": _iso_utc(binding.issued_at),
                "credential_expires_at": _iso_utc(binding.credential_expires_at),
                "credential_digest_exposed": False,
                "raw_device_credential": False,
            },
            "session": None,
            "heartbeat_last_seen_at": None,
        }
        if session is not None:
            facts["session"] = {
                "session_id": session.session_id,
                "binding_ref": session.binding_ref,
                "device_id": session.device_id,
                "account_ref": session.account_ref,
                "workspace_ref": session.workspace_ref,
                "credential_generation": session.credential_generation,
                "issued_at": _iso_utc(session.issued_at),
                "expires_at": _iso_utc(session.expires_at),
                "raw_session_secret": False,
            }
            if last_seen_at is not None:
                facts["heartbeat_last_seen_at"] = _iso_utc(last_seen_at)
        return {"ok": True, "available": True, "device_truth": facts}

    def terminal_command_result(self, payload: dict) -> dict:
        """#3139 read-only terminal fact from the canonical persisted snapshot."""

        stored = self.state_port.load(authority_ref=self.authority_ref())
        return terminal_command_result_from_snapshot(stored.snapshot, payload)

    def authenticate_device_session(self, payload: dict) -> dict:
        """#3436 B2c — one narrow, read-only device-session authentication projection.

        The read-only RPC the B62 Desktop conversation surface consumes through
        the private Service Binding gateway. It runs exactly the canonical
        verifier preamble the ``poll`` path has always taken — binding digest,
        expiry, revocation, then the full session/binding scope correlation —
        over the canonical persisted state, and projects only the server-derived
        facts the Desktop conversation read needs:

        * ``account_ref`` / ``workspace_ref`` come from the verified canonical
          binding state. The closed RPC key set above has no caller-supplied
          identity field, so a caller can never name its owner or scope.
        * Every denial is one bounded code. Whether the credential was wrong,
          expired, rotated, or the binding revoked is never distinguished here,
          so no deny-reason oracle exists at this boundary.
        * Read-only: no transaction, no compare-and-swap, no state write. The
          response never carries the credential digest or any raw credential.
        """

        try:
            payload = closed_mapping(payload, _DEVICE_SESSION_AUTH_RPC_KEYS, "device session authentication RPC")
            session_id = safe_ref(str(payload["session_id"]), "session_id")
            binding_ref = safe_ref(str(payload["binding_ref"]), "binding_ref")
            credential_b64 = payload["credential_b64"]
            if not isinstance(credential_b64, str) or not credential_b64:
                raise ValueError("credential_b64 must be non-empty text")
            decoded = base64.b64decode(credential_b64, validate=True)
            if not decoded:
                raise ValueError("credential_b64 must decode to non-empty bytes")
        except (KeyError, TypeError, ValueError):
            return {
                "ok": False,
                "error": {
                    "code": "invalid_device_session_auth_request",
                    "message": "device session authentication request was rejected",
                },
            }

        authenticator = StateBackedLocalAgentBindingAuthenticator(
            pepper=str(self._env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8"),
            authority_ref=self.authority_ref(),
            state_port=self.state_port,
        )
        try:
            projection = authenticator.authenticate_device_session(
                session_id=session_id,
                binding_ref=binding_ref,
                credential=decoded,
                now=datetime.now(timezone.utc),
            )
        except (ControlPlaneContractError, ValueError, TypeError, RuntimeError):
            return {
                "ok": False,
                "error": {
                    "code": "device_session_auth_failed",
                    "message": "device session authentication failed",
                },
            }
        return {"ok": True, "device_session": projection}

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
            "missing_material_pollable": False,
            "terminal_result_read_only": True,
            "command_identity_precedes_terminal_fact": True,
            "ambiguous_run_refused": True,
            "terminal_result_owner_scoped": True,
            "second_result_authority": False,
            "second_command_authority": False,
            "production_mutation": False,
            "production_ready": False,
        }


DURABLE_RUNTIME_COMPOSITION_EXTRACTED = True
LIFECYCLE_COORDINATOR_EXTRACTED = True
CANONICAL_BROKER_AUTHORITY_CHANGED = False
# #3094 — the device_truth projection's canonical state vocabulary is a pure
# rename over this authority's own records (revoked / credential_expired /
# paired_offline). It never reports "online": the server-backed ONLINE
# projection is derived by the B62 consumer through the existing
# kagent.local_agent_server_projection rule from the reported facts.
DEVICE_TRUTH_VOCABULARY_HAS_ONLINE = False
DEVICE_TRUTH_ONLINE_AUTHORITY = "kagent.local_agent_server_projection (B62 consumer)"
DEVICE_TRUTH_SECOND_ONLINE_AUTHORITY = False
DEVICE_TRUTH_MUTATION = False
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
MISSING_MATERIAL_POLLABLE = False

# --- #3436 B2c — the device-session authentication projection RPC -----------
NARROW_DEVICE_SESSION_AUTH_PROJECTION = True
DEVICE_SESSION_AUTH_STATE_MUTATION = False
DEVICE_SESSION_AUTH_SECOND_CREDENTIAL_VERIFIER = False
DEVICE_SESSION_AUTH_CALLER_IDENTITY_AUTHORITY = False
DEVICE_SESSION_AUTH_RAW_CREDENTIAL_RETURNED = False
DEVICE_SESSION_AUTH_DENY_REASON_DISCLOSED = False
DEVICE_SESSION_AUTH_PRODUCTION_READY = False
