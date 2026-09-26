from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from urllib.parse import urlsplit

from .contracts import ContractError
from .control_plane_broker_conformance import (
    ConformedControlPlaneBrokerAdmission,
    ConformedControlPlaneBrokerCommand,
    parse_control_plane_broker_admission,
)
from .local_agent import LocalCommandRequest
from .local_agent_command_admission import (
    AdmittedLocalAgentExecutionBridge,
    AdmittedLocalCommandExecutionReceipt,
    DeterministicTrustedDeviceCommandAdmissionClient,
)
from .local_agent_command_material import ResolvedLocalCommandMaterial
from .local_agent_durable_run import (
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
)
from .local_agent_control_plane_https import (
    ControlPlaneHttpsOperation,
    PinnedHttpsJsonRequestPort,
)
from .local_agent_control_plane_runtime import (
    ControlPlanePhysicalRuntimeChannel,
    ControlPlanePhysicalRuntimeTransport,
    RuntimeStdlibPinnedHttpsJsonRequestPort,
)
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceSession
from .local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from .local_agent_secure_channel import PinnedOutboundBrokerBinding
from .local_agent_secure_transport import DeviceCredentialStore, OutboundTransportConfig


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field_name} must be valid ISO-8601 text") from exc
    return _aware(parsed, field_name)


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ContractError(f"{field_name} must be bounded non-empty text")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:/@+-"
    if value[0] not in allowed or any(char not in allowed for char in value):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value


class ControlPlaneAdmissionHttpsOperation(str, Enum):
    ADMISSION = "admission"


class AdmissionRuntimeStdlibPinnedHttpsJsonRequestPort(RuntimeStdlibPinnedHttpsJsonRequestPort):
    """Existing pinned stdlib HTTPS source plus the server-owned admission route."""

    def _path(
        self,
        config: OutboundTransportConfig,
        operation: ControlPlaneHttpsOperation | ControlPlaneAdmissionHttpsOperation,
    ) -> tuple[str, int, str]:
        if operation is not ControlPlaneAdmissionHttpsOperation.ADMISSION:
            return super()._path(config, operation)
        host, port, _ = super()._path(config, ControlPlaneHttpsOperation.POLL)
        base = (urlsplit(config.endpoint.url).path or "/").rstrip("/")
        path = f"{base}/admission" if base else "/admission"
        return host, port, path


class ControlPlanePhysicalAdmissionTransport(ControlPlanePhysicalRuntimeTransport):
    """Physical runtime transport plus canonical server-owned broker admission."""

    def __init__(
        self,
        *,
        credential_store: DeviceCredentialStore,
        expected_admission_authority_ref: str,
        request_port: PinnedHttpsJsonRequestPort | None = None,
    ) -> None:
        self._expected_admission_authority_ref = _ref(
            expected_admission_authority_ref,
            "expected_admission_authority_ref",
        )
        super().__init__(
            credential_store=credential_store,
            request_port=request_port or AdmissionRuntimeStdlibPinnedHttpsJsonRequestPort(),
        )

    def _observed_command(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        now: datetime,
    ) -> ConformedControlPlaneBrokerCommand:
        fingerprint = self.request_fingerprint_for(
            config=config,
            binding=binding,
            session=session,
            command=command,
            now=now,
        )
        try:
            observed_session_id, observed = self._polled[command.command_id]
        except KeyError as exc:
            raise ContractError("broker admission requires exact previously-polled command metadata") from exc
        if observed_session_id != session.session_id or observed.envelope != command:
            raise ContractError("broker admission command/session correlation mismatch")
        if observed.request_fingerprint != fingerprint:
            raise ContractError("broker admission fingerprint does not match polled metadata")
        return observed

    def admit_resolved(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        resolved: ResolvedLocalCommandMaterial,
        now: datetime,
    ) -> ConformedControlPlaneBrokerAdmission:
        if not isinstance(resolved, ResolvedLocalCommandMaterial):
            raise ContractError("resolved must be ResolvedLocalCommandMaterial")
        now = _aware(now, "now")
        observed = self._observed_command(
            config=config,
            binding=binding,
            session=session,
            command=command,
            now=now,
        )
        expected = (
            command.command_id,
            command.binding_ref,
            command.sequence,
            observed.request_fingerprint,
            command.revision_ref,
        )
        actual = (
            resolved.command_id,
            resolved.binding_ref,
            resolved.sequence,
            resolved.request_fingerprint,
            resolved.revision_ref,
        )
        if actual != expected:
            raise ContractError("broker admission requires exact resolved command material")
        if resolved.request.run_id != command.run_id or resolved.request.device_id != session.device_id:
            raise ContractError("resolved material does not match command/session execution context")

        response = self._post(
            config=config,
            operation=ControlPlaneAdmissionHttpsOperation.ADMISSION,
            payload={
                "session_id": session.session_id,
                "binding_ref": binding.binding_ref,
                "credential_b64": self._credential_b64(binding, now=now),
                "command_id": command.command_id,
                "request_fingerprint": observed.request_fingerprint,
                "request_id": resolved.request.request_id,
                "now": now.isoformat().replace("+00:00", "Z"),
            },
            timeout_seconds=min(config.poll_timeout_seconds, 30),
        )
        raw = self._success(response, "admission")
        if type(raw) is not dict:
            raise ContractError("physical broker admission must be a plain mapping")

        # accepted_at is canonical broker/server time. Use it only to avoid an
        # invalid same-operation client/server clock equality assumption; the
        # conformance parser still bounds it by the exact command lifetime.
        server_accepted_at = _timestamp(raw.get("accepted_at"), "accepted_at")
        conformance_now = max(now, server_accepted_at)
        return parse_control_plane_broker_admission(
            raw,
            command=observed,
            expected_authority_ref=self._expected_admission_authority_ref,
            expected_session_id=session.session_id,
            expected_request_id=resolved.request.request_id,
            now=conformance_now,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "physical_admission_evidence_source": True,
            "server_owned_admission_refs": True,
            "client_admission_authority": False,
            "control_plane_admission_conformance_reused": True,
            "evidence_ref_preserved": True,
            "caller_endpoint_override": False,
            "live_broker_configured": False,
            "production_ready": False,
        }


class ControlPlanePhysicalAdmissionChannel(ControlPlanePhysicalRuntimeChannel):
    """Pinned physical channel with post-material canonical broker admission."""

    def __init__(
        self,
        *,
        authority: PinnedOutboundBrokerBinding,
        transport: ControlPlanePhysicalAdmissionTransport,
    ) -> None:
        if not isinstance(transport, ControlPlanePhysicalAdmissionTransport):
            raise ContractError("transport must be ControlPlanePhysicalAdmissionTransport")
        super().__init__(authority=authority, transport=transport)
        self._admission_transport = transport

    def admit_resolved(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        resolved: ResolvedLocalCommandMaterial,
        now: datetime,
    ) -> ConformedControlPlaneBrokerAdmission:
        now = _aware(now, "now")
        self.authority.require_current_binding(binding, now=now)
        self.authority.require_session(session, now=now)
        self._prune_polled_commands(now=now)
        observed = self._polled_commands.get(command.command_id)
        if observed is None or observed != (session.session_id, command):
            raise ContractError("admission requires exact command previously polled by this channel/session")
        return self._admission_transport.admit_resolved(
            config=self.authority.config,
            binding=binding,
            session=session,
            command=command,
            resolved=resolved,
            now=now,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "post_material_admission": True,
            "server_owned_admission_refs": True,
            "evidence_ref_preserved": True,
            "client_admission_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ControlPlaneAdmittedExecutionReceipt:
    execution: AdmittedLocalCommandExecutionReceipt
    evidence_ref: str
    acknowledged_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.execution, AdmittedLocalCommandExecutionReceipt):
            raise ContractError("execution must be AdmittedLocalCommandExecutionReceipt")
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "acknowledged_at", _aware(self.acknowledged_at, "acknowledged_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-control-plane-admitted-execution.v1",
            "execution": self.execution.safe_dict(),
            "evidence_ref": self.evidence_ref,
            "acknowledged_at": self.acknowledged_at.isoformat().replace("+00:00", "Z"),
            "revision_ref": self.execution.revision_ref,
            "termination": self.execution.termination.value,
            "request_id": self.execution.request_id,
            "exit_code": self.execution.exit_code,
            "revision_semantics": "opaque_correlation_only",
            "material_before_admission": True,
            "ack_exact_admission_evidence": True,
            "ack_revision_ref_opaque_correlation": True,
            "ack_bounded_termination_returned": True,
            "ack_request_id_returned": True,
            "ack_bounded_exit_code_returned": True,
            "ack_raw_stdout_returned": False,
            "ack_raw_stderr_returned": False,
            "raw_argv": False,
            "stdout": False,
            "stderr": False,
            "raw_device_credential": False,
            "p01_payload": False,
        }


class LocalAgentDurableRunRecoveryPort(Protocol):
    """The durable run store surface the execution order depends on.

    #3128 owns the order, not a second store: admit, persist the admitted
    correlation, execute, persist the terminal result, acknowledge, and only
    then record the server fact. Every method is the existing DurableRunStore API.
    """

    def put(self, record: DurableRunRecord) -> None:
        ...

    def record_terminal(self, record: DurableRunRecord) -> None:
        ...

    def acknowledge(self, *, command_id: str, acknowledged_at: datetime) -> None:
        ...


class ControlPlaneAdmittedExecutionCoordinator:
    """Close the physical material -> admission -> Windows execution -> ack seam.

    This coordinator intentionally creates no replay set, fingerprint algorithm,
    P01 authorization or execution policy. It only orders existing authorities.
    """

    def __init__(
        self,
        *,
        channel: ControlPlanePhysicalAdmissionChannel,
        assembly: BoundLocalAgentRuntimeAssembly,
        clock: Callable[[], datetime],
        durable_store: LocalAgentDurableRunRecoveryPort,
    ) -> None:
        if not isinstance(channel, ControlPlanePhysicalAdmissionChannel):
            raise ContractError("channel must be ControlPlanePhysicalAdmissionChannel")
        if not isinstance(assembly, BoundLocalAgentRuntimeAssembly):
            raise ContractError("assembly must be BoundLocalAgentRuntimeAssembly")
        if not callable(clock):
            raise ContractError("clock must be callable")
        for method_name in ("put", "record_terminal", "acknowledge"):
            if not callable(getattr(durable_store, method_name, None)):
                raise ContractError("durable_store must implement the durable run store writes")
        self._channel = channel
        self._assembly = assembly
        self._clock = clock
        # #3128: mandatory, not optional. Without a durable store the runner
        # cannot persist a terminal result before acknowledging, so there is
        # deliberately no construction path that executes without one.
        self._durable_store = durable_store

    def _now(self) -> datetime:
        return _aware(self._clock(), "runtime_clock")

    def execute_polled_command(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        material_request_ref: str,
        on_execution_start: Callable[[str], None] | None = None,
        on_execution_end: Callable[[], None] | None = None,
    ) -> ControlPlaneAdmittedExecutionReceipt:
        material_now = self._now()
        resolved = self._channel.resolve_broker_material(
            binding=binding,
            session=session,
            command=command,
            request_ref=_ref(material_request_ref, "material_request_ref"),
            now=material_now,
        )

        admission_now = self._now()
        conformed = self._channel.admit_resolved(
            binding=binding,
            session=session,
            command=command,
            resolved=resolved,
            now=admission_now,
        )

        # #3128: the admitted correlation is durable before anything executes, so a
        # crash after this point still leaves a record recovery can act on.
        admitted_record = self._durable_record(
            command=command,
            session=session,
            binding=binding,
            conformed=conformed,
            request=resolved.request,
        )
        self._durable_store.put(admitted_record)

        # The existing admitted-execution bridge remains the execution gate.
        # Feed it the freshly conformed trusted evidence through its existing
        # client port rather than introducing a second validation path.
        admission_client = DeterministicTrustedDeviceCommandAdmissionClient((conformed.evidence,))
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=conformed.evidence.authority_ref,
            admission_client=admission_client,
        )
        execution_now = max(self._now(), conformed.evidence.accepted_at)
        started_at = execution_now
        try:
            if on_execution_start is not None:
                on_execution_start(resolved.request.request_id)
            execution = bridge.execute(
                session=session,
                command=command,
                request=resolved.request,
                assembly=self._assembly,
                now=execution_now,
            )
        finally:
            if on_execution_end is not None:
                on_execution_end()

        # #3128: the terminal result is durable BEFORE the acknowledgement is
        # emitted. If this write fails the exception propagates and no
        # acknowledgement is sent, so the broker is never told about an execution
        # whose result the device could not durably keep.
        terminated_at = max(self._now(), started_at)
        self._durable_store.record_terminal(
            replace(
                admitted_record,
                state=DurableRunState.TERMINAL,
                termination=DurableRunTermination(execution.termination.value),
                started_at=started_at,
                terminated_at=terminated_at,
                exit_code=execution.exit_code,
            )
        )

        # No acknowledgement is emitted unless the existing execution bridge
        # returned a fully correlated execution receipt. The acknowledgement time
        # never precedes the durable termination it reports.
        ack_now = max(self._now(), terminated_at)
        if execution.revision_ref != command.revision_ref:
            raise ContractError("execution revision_ref does not match the polled command envelope")
        if execution.request_id != resolved.request.request_id:
            raise ContractError("execution request_id does not match the resolved material request")
        self._channel.acknowledge_admitted(
            binding=binding,
            session=session,
            command_id=command.command_id,
            admission_ref=conformed.evidence.admission_ref,
            evidence_ref=conformed.evidence_ref,
            revision_ref=execution.revision_ref,
            termination=execution.termination.value,
            request_id=execution.request_id,
            exit_code=execution.exit_code,
            now=ack_now,
        )
        # #3128: the orthogonal server fact is recorded only once the canonical
        # broker accepted the acknowledgement, and it never reopens the record.
        self._durable_store.acknowledge(command_id=command.command_id, acknowledged_at=ack_now)
        return ControlPlaneAdmittedExecutionReceipt(
            execution=execution,
            evidence_ref=conformed.evidence_ref,
            acknowledged_at=ack_now,
        )

    def _durable_record(
        self,
        *,
        command: DeviceCommandEnvelope,
        session: DeviceSession,
        binding: DeviceBinding,
        conformed: Any,
        request: LocalCommandRequest,
    ) -> DurableRunRecord:
        """Copy the admitted correlation verbatim into one durable record."""

        evidence = conformed.evidence
        return DurableRunRecord(
            command_id=command.command_id,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            request_id=request.request_id,
            revision_ref=command.revision_ref,
            device_id=session.device_id,
            binding_ref=command.binding_ref,
            session_id=session.session_id,
            account_ref=session.account_ref,
            workspace_ref=session.workspace_ref,
            sequence=command.sequence,
            credential_generation=binding.credential_generation,
            request_fingerprint=evidence.request_fingerprint,
            fingerprint_source="broker",
            command_issued_at=command.issued_at,
            command_expires_at=command.expires_at,
            admitted_at=evidence.accepted_at,
            admission_ref=evidence.admission_ref,
            admission_evidence_ref=conformed.evidence_ref,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "physical_admission_evidence_source": True,
            "post_material_admission_order": True,
            "control_plane_admission_conformance_reused": True,
            "admitted_execution_bridge_reused": True,
            "windows_authorization_reused": True,
            "ack_exact_admission_evidence": True,
            "ack_on_execution_failure": False,
            "ack_revision_ref_opaque_correlation": True,
            "ack_bounded_termination_returned": True,
            "ack_request_id_returned": True,
            "ack_bounded_exit_code_returned": True,
            "ack_raw_stdout_returned": False,
            "ack_raw_stderr_returned": False,
            "second_replay_sequence_authority": False,
            "second_fingerprint_authority": False,
            "p01_authority_duplicated": False,
            "public_inbound_port": False,
            "live_broker_configured": False,
            "live_windows_acceptance": False,
            "production_ready": False,
            "durable_terminal_before_ack": True,
            "durable_admitted_before_execution": True,
            "durable_server_ack_after_broker_ack": True,
        }


PHYSICAL_ADMISSION_EVIDENCE_SOURCE = True
SERVER_OWNED_ADMISSION_REFS = True
CLIENT_ADMISSION_AUTHORITY = False
POST_MATERIAL_ADMISSION_ORDER = True
CONTROL_PLANE_ADMISSION_CONFORMANCE_REUSED = True
EVIDENCE_REF_END_TO_END = True
ADMITTED_EXECUTION_BRIDGE_REUSED = True
WINDOWS_AUTHORIZATION_REUSED = True
ACK_EXACT_ADMISSION_EVIDENCE = True
ACK_ON_EXECUTION_FAILURE = False
ACK_REVISION_REF_OPAQUE_CORRELATION = True
ACK_BOUNDED_TERMINATION_RETURNED = True
ACK_REQUEST_ID_RETURNED = True
ACK_BOUNDED_EXIT_CODE_RETURNED = True
ACK_RAW_STDOUT_RETURNED = False
ACK_RAW_STDERR_RETURNED = False
SECOND_REPLAY_SEQUENCE_AUTHORITY = False
SECOND_FINGERPRINT_AUTHORITY = False
P01_AUTHORITY_DUPLICATED = False
REVISION_CORRELATION = True
REVISION_CORRELATION_THROUGH_MATERIAL = True
REQUEST_ID_RETURNED_AND_EXACT = True
EXIT_CODE_BOUNDED_RETURN = True
RESULT_RETURN_IS_BOUNDED = True
RAW_STDOUT_STDERR_RETURNED = False
RAW_DEVICE_SECRET_RETURNED = False
CAPABILITY_AUTHORITY_DUPLICATED = False
TASK_ADMISSION_AUTHORITY_DUPLICATED = False
REPLAY_AUTHORITY_DUPLICATED = False
PUBLIC_INBOUND_PORT = False
LIVE_BROKER_CONFIGURED = False
LIVE_WINDOWS_ACCEPTANCE = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
