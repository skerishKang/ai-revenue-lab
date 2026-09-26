from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol, TypeVar

from .contracts import ControlPlaneContractError
from .local_agent_broker import (
    BrokerBindingState,
    BrokerCommandAdmission,
    BrokerCommandRecord,
    BrokerCommandState,
    BrokerCompactedCommand,
    BrokerDeviceBinding,
    BrokerDeviceSession,
    InMemoryLocalAgentBrokerAuthority,
)

BROKER_STATE_SCHEMA_VERSION = "padiem.local-agent-broker-state.v1"
_T = TypeVar("_T")

# #3123: proactive retention trigger, in command records. The wire layer's hard
# bound is 10,000 items per collection (local_agent_broker_state_wire), and the
# trigger sits deliberately below it so ordinary mutations reclaim terminal
# history before the bound can turn into a permanent encode failure. Defined
# here rather than imported from the wire module because the wire module
# already imports the snapshot schema from this one.
COMPACTION_PROACTIVE_TRIGGER_COMMANDS = 8_000


def _state_error(code: str, message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


@dataclass(frozen=True, slots=True)
class LocalAgentBrokerStateSnapshot:
    """Closed trusted snapshot of the canonical broker authority state.

    Credential digests are internal trusted state and are persisted; raw device
    credentials are never part of this snapshot or its safe projection.
    """

    authority_ref: str
    bindings: tuple[BrokerDeviceBinding, ...] = ()
    sessions: tuple[BrokerDeviceSession, ...] = ()
    commands: tuple[BrokerCommandRecord, ...] = ()
    last_sequence_by_binding: tuple[tuple[str, int], ...] = ()
    # #3123 compaction state. Tombstones keep compacted terminal command ids
    # rejected and their consumed sequences visible; the folded prefix records
    # how far the contiguous terminal prefix has been absorbed into the
    # watermark. Both default to empty so every pre-#3123 snapshot decodes
    # unchanged.
    compacted_commands: tuple[BrokerCompactedCommand, ...] = ()
    compacted_through_by_binding: tuple[tuple[str, int], ...] = ()
    schema_version: str = BROKER_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BROKER_STATE_SCHEMA_VERSION:
            raise _state_error("unsupported_local_agent_broker_state", "unsupported Local Agent broker state schema")
        if not isinstance(self.authority_ref, str) or not self.authority_ref:
            raise _state_error("invalid_local_agent_broker_state", "broker state authority_ref is required")
        if any(not isinstance(item, BrokerDeviceBinding) for item in self.bindings):
            raise _state_error("invalid_local_agent_broker_state", "broker state bindings are invalid")
        if any(not isinstance(item, BrokerDeviceSession) for item in self.sessions):
            raise _state_error("invalid_local_agent_broker_state", "broker state sessions are invalid")
        if any(not isinstance(item, BrokerCommandRecord) for item in self.commands):
            raise _state_error("invalid_local_agent_broker_state", "broker state commands are invalid")
        if any(not isinstance(item, BrokerCompactedCommand) for item in self.compacted_commands):
            raise _state_error("invalid_local_agent_broker_state", "broker state compaction tombstones are invalid")

        bindings = {item.binding_ref: item for item in self.bindings}
        sessions = {item.session_id: item for item in self.sessions}
        commands = {item.command_id: item for item in self.commands}
        if len(bindings) != len(self.bindings):
            raise _state_error("invalid_local_agent_broker_state", "duplicate binding_ref in broker state")
        if len(sessions) != len(self.sessions):
            raise _state_error("invalid_local_agent_broker_state", "duplicate session_id in broker state")
        if len(commands) != len(self.commands):
            raise _state_error("invalid_local_agent_broker_state", "duplicate command_id in broker state")

        active_devices: set[str] = set()
        for binding in self.bindings:
            if binding.state is BrokerBindingState.ACTIVE:
                if binding.device_id in active_devices:
                    raise _state_error("invalid_local_agent_broker_state", "device has multiple active broker bindings")
                active_devices.add(binding.device_id)

        for session in self.sessions:
            binding = bindings.get(session.binding_ref)
            if binding is None:
                raise _state_error("invalid_local_agent_broker_state", "broker session references unknown binding")
            expected = (
                binding.device_id,
                binding.account_ref,
                binding.workspace_ref,
                binding.credential_generation,
            )
            actual = (
                session.device_id,
                session.account_ref,
                session.workspace_ref,
                session.credential_generation,
            )
            if actual != expected:
                raise _state_error("invalid_local_agent_broker_state", "broker session binding correlation mismatch")
            if binding.state is BrokerBindingState.REVOKED:
                raise _state_error("invalid_local_agent_broker_state", "revoked binding cannot retain broker session")
            if session.issued_at < binding.issued_at or session.expires_at > binding.credential_expires_at:
                raise _state_error("invalid_local_agent_broker_state", "broker session lies outside credential lifetime")

        seen_admissions: set[str] = set()
        seen_evidence: set[str] = set()
        max_sequence: dict[str, int] = {}
        seen_sequences: dict[str, set[int]] = {}
        for command in self.commands:
            binding = bindings.get(command.binding_ref)
            if binding is None:
                raise _state_error("invalid_local_agent_broker_state", "broker command references unknown binding")
            if command.credential_generation > binding.credential_generation:
                raise _state_error("invalid_local_agent_broker_state", "broker command generation is newer than binding")
            values = seen_sequences.setdefault(command.binding_ref, set())
            if command.sequence in values:
                raise _state_error("invalid_local_agent_broker_state", "duplicate command sequence within binding")
            values.add(command.sequence)
            max_sequence[command.binding_ref] = max(max_sequence.get(command.binding_ref, 0), command.sequence)
            if command.admission_ref is not None:
                if command.admission_ref in seen_admissions:
                    raise _state_error("invalid_local_agent_broker_state", "duplicate broker admission_ref")
                seen_admissions.add(command.admission_ref)
            if command.evidence_ref is not None:
                if command.evidence_ref in seen_evidence:
                    raise _state_error("invalid_local_agent_broker_state", "duplicate broker evidence_ref")
                seen_evidence.add(command.evidence_ref)

        sequence_map: dict[str, int] = {}
        for item in self.last_sequence_by_binding:
            if type(item) is not tuple or len(item) != 2:
                raise _state_error("invalid_local_agent_broker_state", "broker sequence state entry is invalid")
            binding_ref, sequence = item
            if binding_ref not in bindings:
                raise _state_error("invalid_local_agent_broker_state", "broker sequence state references unknown binding")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
                raise _state_error("invalid_local_agent_broker_state", "broker sequence state must be positive integer")
            if binding_ref in sequence_map:
                raise _state_error("invalid_local_agent_broker_state", "duplicate broker sequence state entry")
            sequence_map[binding_ref] = sequence
        # #3123: the watermark is a monotonic high-water mark, not a mirror of
        # the persisted history. Compaction removes terminal records without
        # lowering it, so it may now exceed the maximum persisted sequence —
        # but it may never fall below one, and every binding that still owns a
        # persisted command must have its watermark recorded. This relaxation
        # is exactly what lets terminal history be compacted without ever
        # re-minting or reusing a sequence.
        for binding_ref, highest in max_sequence.items():
            if sequence_map.get(binding_ref, 0) < highest:
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "broker sequence state must be at or above every persisted command sequence",
                )

        # #3123 tombstone invariants. A tombstone proves three facts: the id is
        # consumed, the sequence is consumed, and neither can be minted again.
        # Those facts are only provable if the tombstone collection itself is
        # collision-free and consistent with the live records and the
        # watermark, so the snapshot validates all three rather than trusting
        # whoever built it.
        compacted_ids: set[str] = set()
        tombstone_sequences: dict[str, set[int]] = {}
        for tombstone in self.compacted_commands:
            if tombstone.command_id in commands:
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "broker command cannot be both persisted and compacted",
                )
            if tombstone.command_id in compacted_ids:
                raise _state_error("invalid_local_agent_broker_state", "duplicate compacted command_id in broker state")
            compacted_ids.add(tombstone.command_id)
            if tombstone.binding_ref not in bindings:
                raise _state_error("invalid_local_agent_broker_state", "broker compaction tombstone references unknown binding")
            if tombstone.sequence > sequence_map.get(tombstone.binding_ref, 0):
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "compacted sequence cannot exceed the binding sequence watermark",
                )
            known = tombstone_sequences.setdefault(tombstone.binding_ref, set())
            if tombstone.sequence in known:
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "compacted sequence reuse within binding",
                )
            known.add(tombstone.sequence)
        for binding_ref, sequence in ((item.binding_ref, item.sequence) for item in self.commands):
            if sequence in tombstone_sequences.get(binding_ref, set()):
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "sequence cannot be both live and compacted within a binding",
                )

        # The folded prefix: how far the contiguous terminal prefix of each
        # binding has been absorbed into the watermark. It must stay within the
        # watermark and must not claim any sequence that is still visible as a
        # live command or a tombstone — otherwise the "consumed" proof it
        # carries would be a lie.
        folded_prefixes: set[str] = set()
        for item in self.compacted_through_by_binding:
            if type(item) is not tuple or len(item) != 2:
                raise _state_error("invalid_local_agent_broker_state", "broker compaction prefix entry is invalid")
            binding_ref, folded_through = item
            if binding_ref not in bindings:
                raise _state_error("invalid_local_agent_broker_state", "broker compaction prefix references unknown binding")
            if isinstance(folded_through, bool) or not isinstance(folded_through, int) or folded_through < 0:
                raise _state_error("invalid_local_agent_broker_state", "broker compaction prefix must be a non-negative integer")
            if binding_ref in folded_prefixes:
                raise _state_error("invalid_local_agent_broker_state", "duplicate broker compaction prefix entry")
            folded_prefixes.add(binding_ref)
            if folded_through > sequence_map.get(binding_ref, 0):
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "compaction prefix cannot exceed the binding sequence watermark",
                )
            live_below = any(
                command.binding_ref == binding_ref and command.sequence <= folded_through
                for command in self.commands
            )
            tombstone_below = any(
                tombstone.binding_ref == binding_ref and tombstone.sequence <= folded_through
                for tombstone in self.compacted_commands
            )
            if live_below or tombstone_below:
                raise _state_error(
                    "invalid_local_agent_broker_state",
                    "compaction prefix cannot claim a visible command or tombstone sequence",
                )

    @classmethod
    def empty(cls, *, authority_ref: str) -> "LocalAgentBrokerStateSnapshot":
        return cls(authority_ref=authority_ref)

    @classmethod
    def capture(cls, authority: InMemoryLocalAgentBrokerAuthority) -> "LocalAgentBrokerStateSnapshot":
        if type(authority) is not InMemoryLocalAgentBrokerAuthority:
            raise ValueError("authority must be exact InMemoryLocalAgentBrokerAuthority")
        return cls(
            authority_ref=authority.authority_ref,
            bindings=tuple(sorted(authority._bindings.values(), key=lambda item: item.binding_ref)),
            sessions=tuple(sorted(authority._sessions.values(), key=lambda item: item.session_id)),
            commands=tuple(sorted(authority._commands.values(), key=lambda item: (item.binding_ref, item.sequence))),
            last_sequence_by_binding=tuple(sorted(authority._last_sequence_by_binding.items())),
            compacted_commands=tuple(
                sorted(authority._compacted_commands.values(), key=lambda item: (item.binding_ref, item.sequence, item.command_id))
            ),
            compacted_through_by_binding=tuple(sorted(authority._compacted_through_by_binding.items())),
        )

    def restore(self, *, pepper: bytes) -> InMemoryLocalAgentBrokerAuthority:
        authority = InMemoryLocalAgentBrokerAuthority(pepper=pepper, authority_ref=self.authority_ref)
        authority._bindings = {item.binding_ref: item for item in self.bindings}
        authority._sessions = {item.session_id: item for item in self.sessions}
        authority._commands = {item.command_id: item for item in self.commands}
        authority._last_sequence_by_binding = dict(self.last_sequence_by_binding)
        authority._compacted_commands = {item.command_id: item for item in self.compacted_commands}
        authority._compacted_through_by_binding = dict(self.compacted_through_by_binding)
        return authority

    def safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority_ref": self.authority_ref,
            "binding_count": len(self.bindings),
            "session_count": len(self.sessions),
            "command_count": len(self.commands),
            "sequence_binding_count": len(self.last_sequence_by_binding),
            "compacted_command_count": len(self.compacted_commands),
            "compacted_prefix_binding_count": len(self.compacted_through_by_binding),
            "credential_digest_exposed": False,
            "raw_device_credential": False,
        }


@dataclass(frozen=True, slots=True)
class VersionedLocalAgentBrokerState:
    version: int
    snapshot: LocalAgentBrokerStateSnapshot

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise ValueError("broker state version must be a non-negative integer")
        if not isinstance(self.snapshot, LocalAgentBrokerStateSnapshot):
            raise ValueError("snapshot must be LocalAgentBrokerStateSnapshot")


class LocalAgentBrokerStatePort(Protocol):
    durable: bool

    def load(self, *, authority_ref: str) -> VersionedLocalAgentBrokerState:
        ...

    def compare_and_swap(
        self,
        *,
        authority_ref: str,
        expected_version: int,
        snapshot: LocalAgentBrokerStateSnapshot,
    ) -> VersionedLocalAgentBrokerState:
        ...


class InMemoryLocalAgentBrokerStatePort:
    """Deterministic CAS reference port. Explicitly not durable."""

    durable = False

    def __init__(self) -> None:
        self._state: dict[str, VersionedLocalAgentBrokerState] = {}

    def load(self, *, authority_ref: str) -> VersionedLocalAgentBrokerState:
        if not isinstance(authority_ref, str) or not authority_ref:
            raise ValueError("authority_ref is required")
        return self._state.get(
            authority_ref,
            VersionedLocalAgentBrokerState(
                version=0,
                snapshot=LocalAgentBrokerStateSnapshot.empty(authority_ref=authority_ref),
            ),
        )

    def compare_and_swap(
        self,
        *,
        authority_ref: str,
        expected_version: int,
        snapshot: LocalAgentBrokerStateSnapshot,
    ) -> VersionedLocalAgentBrokerState:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(snapshot, LocalAgentBrokerStateSnapshot) or snapshot.authority_ref != authority_ref:
            raise ValueError("snapshot authority mismatch")
        current = self.load(authority_ref=authority_ref)
        if current.version != expected_version:
            raise _state_error(
                "stale_local_agent_broker_state",
                "Local Agent broker state changed concurrently; stale write refused",
            )
        stored = VersionedLocalAgentBrokerState(version=current.version + 1, snapshot=snapshot)
        self._state[authority_ref] = stored
        return stored

    def safe_dict(self) -> dict[str, Any]:
        return {
            "atomic_compare_and_swap": True,
            "durable": False,
            "production_store": False,
        }


class StateBackedLocalAgentBrokerAuthority(InMemoryLocalAgentBrokerAuthority):
    """CAS composition around the canonical broker authority core.

    Security semantics stay in `InMemoryLocalAgentBrokerAuthority`. Each mutation
    loads the latest closed snapshot, delegates exactly once to that authority,
    and atomically saves the resulting state. A CAS conflict fails closed and is
    deliberately not retried here because replaying a mutation is an authority
    decision, not a persistence convenience.
    """

    def __init__(
        self,
        *,
        pepper: bytes,
        authority_ref: str,
        state_port: LocalAgentBrokerStatePort,
    ) -> None:
        super().__init__(pepper=pepper, authority_ref=authority_ref)
        for method_name in ("load", "compare_and_swap"):
            if not callable(getattr(state_port, method_name, None)):
                raise ValueError("state_port must implement atomic broker state operations")
        if type(getattr(state_port, "durable", None)) is not bool:
            raise ValueError("state_port must explicitly declare durable boolean")
        self._state_port = state_port

    def _loaded(self) -> tuple[VersionedLocalAgentBrokerState, InMemoryLocalAgentBrokerAuthority]:
        stored = self._state_port.load(authority_ref=self.authority_ref)
        if not isinstance(stored, VersionedLocalAgentBrokerState):
            raise _state_error("invalid_local_agent_broker_state", "state port returned invalid broker state")
        if stored.snapshot.authority_ref != self.authority_ref:
            raise _state_error("invalid_local_agent_broker_state", "state port returned wrong authority state")
        return stored, stored.snapshot.restore(pepper=self._pepper)

    def _mutate(
        self,
        operation: Callable[[InMemoryLocalAgentBrokerAuthority], _T],
        *,
        now: datetime | None = None,
    ) -> _T:
        stored, authority = self._loaded()
        result = operation(authority)
        if now is not None and len(authority._commands) >= COMPACTION_PROACTIVE_TRIGGER_COMMANDS:
            # #3123 proactive retention: with the persisted history pressing on
            # the wire bound, reclaim terminal records before the bound turns
            # into a permanent encode failure. This runs on the same trusted
            # server clock as the mutation itself and never touches live or
            # unresolved records (see `compact_terminal_history`).
            authority.compact_terminal_history(now=now)
        try:
            self._compare_and_swap(authority, expected_version=stored.version)
            return result
        except ControlPlaneContractError as exc:
            # #3123 reactive escape. The real wire/CAS path raised under
            # pressure (collection or byte bound). Anything else — including a
            # CAS race — must propagate untouched.
            if exc.code != "local_agent_broker_state_wire_too_large" or now is None:
                raise
        # One real compaction pass, then exactly one retry. If the state still
        # cannot be encoded, the failure propagates: pressure that retention
        # cannot relieve fails closed here, it does not wedge in a retry loop
        # and it does not invent a smaller state.
        authority.compact_terminal_history(now=now)
        self._compare_and_swap(authority, expected_version=stored.version)
        return result

    def _compare_and_swap(
        self,
        authority: InMemoryLocalAgentBrokerAuthority,
        *,
        expected_version: int,
    ) -> None:
        self._state_port.compare_and_swap(
            authority_ref=self.authority_ref,
            expected_version=expected_version,
            snapshot=LocalAgentBrokerStateSnapshot.capture(authority),
        )

    def _read(self, operation: Callable[[InMemoryLocalAgentBrokerAuthority], _T]) -> _T:
        _, authority = self._loaded()
        return operation(authority)

    def register_binding(
        self,
        *,
        binding_ref: str,
        device_id: str,
        account_ref: str,
        workspace_ref: str,
        credential: bytes,
        now: datetime,
        credential_ttl_seconds: int = 2_592_000,
    ) -> BrokerDeviceBinding:
        return self._mutate(
            lambda authority: authority.register_binding(
                binding_ref=binding_ref,
                device_id=device_id,
                account_ref=account_ref,
                workspace_ref=workspace_ref,
                credential=credential,
                now=now,
                credential_ttl_seconds=credential_ttl_seconds,
            ),
            now=now,
        )

    def rotate_credential(
        self,
        binding_ref: str,
        *,
        expected_generation: int,
        new_credential: bytes,
        now: datetime,
        credential_ttl_seconds: int = 2_592_000,
    ) -> BrokerDeviceBinding:
        return self._mutate(
            lambda authority: authority.rotate_credential(
                binding_ref,
                expected_generation=expected_generation,
                new_credential=new_credential,
                now=now,
                credential_ttl_seconds=credential_ttl_seconds,
            ),
            now=now,
        )

    def revoke_binding(self, binding_ref: str, *, now: datetime) -> BrokerDeviceBinding:
        return self._mutate(lambda authority: authority.revoke_binding(binding_ref, now=now), now=now)

    def open_session(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 900,
    ) -> BrokerDeviceSession:
        return self._mutate(
            lambda authority: authority.open_session(
                session_id=session_id,
                binding_ref=binding_ref,
                credential=credential,
                account_ref=account_ref,
                workspace_ref=workspace_ref,
                now=now,
                ttl_seconds=ttl_seconds,
            ),
            now=now,
        )

    def enqueue_command(
        self,
        *,
        command_id: str,
        binding_ref: str,
        run_id: str,
        tool_request_ref: str,
        request_fingerprint: str,
        now: datetime,
        ttl_seconds: int = 300,
    ) -> BrokerCommandRecord:
        return self._mutate(
            lambda authority: authority.enqueue_command(
                command_id=command_id,
                binding_ref=binding_ref,
                run_id=run_id,
                tool_request_ref=tool_request_ref,
                request_fingerprint=request_fingerprint,
                now=now,
                ttl_seconds=ttl_seconds,
            ),
            now=now,
        )

    def poll(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        after_sequence: int,
        now: datetime,
        limit: int = 32,
    ) -> tuple[BrokerCommandRecord, ...]:
        return self._read(
            lambda authority: authority.poll(
                session_id=session_id,
                binding_ref=binding_ref,
                credential=credential,
                after_sequence=after_sequence,
                now=now,
                limit=limit,
            )
        )

    def admit_command(
        self,
        *,
        admission_ref: str,
        evidence_ref: str,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        request_fingerprint: str,
        request_id: str,
        now: datetime,
    ) -> BrokerCommandAdmission:
        return self._mutate(
            lambda authority: authority.admit_command(
                admission_ref=admission_ref,
                evidence_ref=evidence_ref,
                session_id=session_id,
                binding_ref=binding_ref,
                credential=credential,
                command_id=command_id,
                request_fingerprint=request_fingerprint,
                request_id=request_id,
                now=now,
            ),
            now=now,
        )

    def acknowledge(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        admission_ref: str,
        evidence_ref: str,
        revision_ref: str,
        termination: str,
        request_id: str,
        exit_code: int | None,
        now: datetime,
    ) -> BrokerCommandRecord:
        return self._mutate(
            lambda authority: authority.acknowledge(
                session_id=session_id,
                binding_ref=binding_ref,
                credential=credential,
                command_id=command_id,
                admission_ref=admission_ref,
                evidence_ref=evidence_ref,
                revision_ref=revision_ref,
                termination=termination,
                request_id=request_id,
                exit_code=exit_code,
                now=now,
            ),
            now=now,
        )

    def reconcile_expired_command(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        admission_ref: str,
        revision_ref: str,
        request_id: str,
        request_fingerprint: str,
        termination: str | None,
        exit_code: int | None,
        now: datetime,
    ) -> BrokerCommandRecord:
        return self._mutate(
            lambda authority: authority.reconcile_expired_command(
                session_id=session_id,
                binding_ref=binding_ref,
                credential=credential,
                command_id=command_id,
                admission_ref=admission_ref,
                revision_ref=revision_ref,
                request_id=request_id,
                request_fingerprint=request_fingerprint,
                termination=termination,
                exit_code=exit_code,
                now=now,
            ),
            now=now,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "state_backed_authority": True,
            "canonical_broker_authority_reused": True,
            "second_replay_sequence_authority": False,
            "atomic_compare_and_swap": True,
            "state_port_durable": self._state_port.durable,
            "raw_device_credential_persisted": False,
            "production_database_selected": False,
            "production_store_configured": False,
            "production_ready": False,
        }


DURABLE_BROKER_STATE_PORT_DEFINED = True
VERSIONED_BROKER_SNAPSHOT = True
ATOMIC_COMPARE_AND_SWAP = True
CANONICAL_BROKER_AUTHORITY_REUSED = True
SECOND_REPLAY_SEQUENCE_AUTHORITY = False
BINDING_STATE_PERSISTABLE = True
SESSION_STATE_PERSISTABLE = True
COMMAND_STATE_PERSISTABLE = True
MONOTONIC_SEQUENCE_PERSISTABLE = True
ROTATION_REVOCATION_ATOMIC = True
RAW_DEVICE_CREDENTIAL_PERSISTED = False
IN_MEMORY_STATE_PORT_COUNTS_AS_DURABLE = False
PRODUCTION_DATABASE_SELECTED = False
PRODUCTION_STORE_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
