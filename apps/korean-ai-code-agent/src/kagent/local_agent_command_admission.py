from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent import LocalCommandRequest
from .local_agent_pairing import DeviceCommandEnvelope, DeviceSession
from .local_agent_runtime_assembly import LocalAgentRuntimeAssemblyReceipt
from .windows_local_executor import WindowsExecutionTermination, command_request_fingerprint

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_ADMISSION_LIFETIME_SECONDS = 900


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _digest(value: str, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedDeviceCommandAdmissionEvidence:
    """Trusted evidence that #1634 admitted one command/request materialization.

    The real broker/control plane remains responsible for authenticating the
    device session and running the canonical #1634 replay/sequence admission
    before constructing this evidence. No raw command arguments are carried.
    """

    admission_ref: str
    authority_ref: str
    command_id: str
    session_id: str
    binding_ref: str
    run_id: str
    tool_request_ref: str
    sequence: int
    request_fingerprint: str
    accepted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "admission_ref",
            "authority_ref",
            "command_id",
            "session_id",
            "binding_ref",
            "run_id",
            "tool_request_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ContractError("sequence must be a positive integer")
        accepted = _aware(self.accepted_at, "accepted_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= accepted:
            raise ContractError("admission evidence expires_at must be after accepted_at")
        if (expires - accepted).total_seconds() > _MAX_ADMISSION_LIFETIME_SECONDS:
            raise ContractError("admission evidence lifetime cannot exceed 900 seconds")
        object.__setattr__(self, "accepted_at", accepted)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-trusted-device-command-admission.v1",
            "admission_ref": self.admission_ref,
            "authority_ref": self.authority_ref,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "binding_ref": self.binding_ref,
            "run_id": self.run_id,
            "tool_request_ref": self.tool_request_ref,
            "sequence": self.sequence,
            "request_fingerprint": self.request_fingerprint,
            "accepted_at": self.accepted_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_argv": False,
            "raw_file_content": False,
            "raw_device_credential": False,
            "broker_token": False,
            "approval_payload": False,
            "client_admission_authority": False,
        }


class TrustedDeviceCommandAdmissionClient(Protocol):
    """Trusted broker/control-plane evidence reader; transport is external to B54."""

    def resolve(
        self,
        *,
        command_id: str,
        request_fingerprint: str,
    ) -> TrustedDeviceCommandAdmissionEvidence:
        ...


class UnconfiguredTrustedDeviceCommandAdmissionClient:
    def resolve(
        self,
        *,
        command_id: str,
        request_fingerprint: str,
    ) -> TrustedDeviceCommandAdmissionEvidence:
        _ref(command_id, "command_id")
        _digest(request_fingerprint, "request_fingerprint")
        raise ContractError("trusted device command admission client is not configured")


class DeterministicTrustedDeviceCommandAdmissionClient:
    """Network-free trusted admission double for deterministic CI only."""

    def __init__(self, evidence: tuple[TrustedDeviceCommandAdmissionEvidence, ...]) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ContractError("deterministic admission client requires evidence")
        if not all(isinstance(item, TrustedDeviceCommandAdmissionEvidence) for item in evidence):
            raise ContractError("deterministic admission client contains invalid evidence")
        by_key = {(item.command_id, item.request_fingerprint): item for item in evidence}
        if len(by_key) != len(evidence):
            raise ContractError("deterministic admission evidence keys must be unique")
        self._evidence = by_key
        self.calls: list[tuple[str, str]] = []

    def resolve(
        self,
        *,
        command_id: str,
        request_fingerprint: str,
    ) -> TrustedDeviceCommandAdmissionEvidence:
        command_id = _ref(command_id, "command_id")
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        key = (command_id, fingerprint)
        self.calls.append(key)
        try:
            return self._evidence[key]
        except KeyError as exc:
            raise ContractError("trusted command admission evidence does not exist for this materialization") from exc


class LocalAgentExecutionAssemblyPort(Protocol):
    def execute(
        self,
        *,
        session: DeviceSession,
        request: LocalCommandRequest,
        now: datetime,
    ) -> LocalAgentRuntimeAssemblyReceipt:
        ...


@dataclass(frozen=True, slots=True)
class AdmittedLocalCommandExecutionReceipt:
    admission_ref: str
    command_id: str
    tool_request_ref: str
    sequence: int
    session_id: str
    binding_ref: str
    request_id: str
    run_id: str
    request_fingerprint: str
    assembly_ref: str
    authorization_ref: str
    termination: WindowsExecutionTermination

    def __post_init__(self) -> None:
        for field_name in (
            "admission_ref",
            "command_id",
            "tool_request_ref",
            "session_id",
            "binding_ref",
            "request_id",
            "run_id",
            "assembly_ref",
            "authorization_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ContractError("sequence must be a positive integer")
        if not isinstance(self.termination, WindowsExecutionTermination):
            try:
                object.__setattr__(self, "termination", WindowsExecutionTermination(self.termination))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid execution termination") from exc

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-admitted-local-command-execution-receipt.v1",
            "admission_ref": self.admission_ref,
            "command_id": self.command_id,
            "tool_request_ref": self.tool_request_ref,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "binding_ref": self.binding_ref,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "request_fingerprint": self.request_fingerprint,
            "assembly_ref": self.assembly_ref,
            "authorization_ref": self.authorization_ref,
            "termination": self.termination.value,
            "raw_argv": False,
            "stdout": False,
            "stderr": False,
            "raw_device_credential": False,
            "broker_payload": False,
        }


class AdmittedLocalAgentExecutionBridge:
    """Verify trusted command admission evidence before runtime assembly execution.

    This bridge intentionally owns no replay set. Canonical replay/sequence
    admission remains #1634, and canonical P01 execution grant consumption
    remains the existing Windows authorization path.
    """

    def __init__(
        self,
        *,
        expected_admission_authority_ref: str,
        admission_client: TrustedDeviceCommandAdmissionClient | None = None,
    ) -> None:
        self._expected_authority_ref = _ref(
            expected_admission_authority_ref,
            "expected_admission_authority_ref",
        )
        self._client = admission_client or UnconfiguredTrustedDeviceCommandAdmissionClient()

    def execute(
        self,
        *,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        request: LocalCommandRequest,
        assembly: LocalAgentExecutionAssemblyPort,
        now: datetime,
    ) -> AdmittedLocalCommandExecutionReceipt:
        if not isinstance(session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        if not isinstance(command, DeviceCommandEnvelope):
            raise ContractError("command must be DeviceCommandEnvelope")
        if not isinstance(request, LocalCommandRequest):
            raise ContractError("request must be LocalCommandRequest")
        if not hasattr(assembly, "execute"):
            raise ContractError("assembly must provide execute")
        now = _aware(now, "now")

        if now < session.issued_at or now >= session.expires_at:
            raise ContractError("device session is not current")
        if now < command.issued_at or now >= command.expires_at:
            raise ContractError("device command is not currently valid")
        if command.binding_ref != session.binding_ref:
            raise ContractError("command binding does not match the current device session")
        if command.run_id != request.run_id:
            raise ContractError("command run does not match the materialized local request")
        if request.device_id != session.device_id:
            raise ContractError("materialized local request device does not match the current session")
        if request.requested_at > command.issued_at:
            raise ContractError("materialized local request cannot follow the command envelope issuance")
        if request.requested_at > now:
            raise ContractError("materialized local request cannot be from the future")

        fingerprint = command_request_fingerprint(request)
        evidence = self._client.resolve(
            command_id=command.command_id,
            request_fingerprint=fingerprint,
        )
        if not isinstance(evidence, TrustedDeviceCommandAdmissionEvidence):
            raise ContractError("trusted command admission client returned invalid evidence")
        if evidence.authority_ref != self._expected_authority_ref:
            raise ContractError("trusted command admission authority mismatch")
        if evidence.command_id != command.command_id:
            raise ContractError("trusted admission command_id mismatch")
        if evidence.session_id != session.session_id:
            raise ContractError("trusted admission session mismatch")
        if evidence.binding_ref != command.binding_ref or evidence.binding_ref != session.binding_ref:
            raise ContractError("trusted admission binding mismatch")
        if evidence.run_id != command.run_id or evidence.run_id != request.run_id:
            raise ContractError("trusted admission run mismatch")
        if evidence.tool_request_ref != command.tool_request_ref:
            raise ContractError("trusted admission tool_request_ref mismatch")
        if evidence.sequence != command.sequence:
            raise ContractError("trusted admission sequence mismatch")
        if evidence.request_fingerprint != fingerprint:
            raise ContractError("trusted admission request fingerprint mismatch")
        if evidence.accepted_at < command.issued_at:
            raise ContractError("trusted admission cannot predate the command envelope")
        if evidence.accepted_at < request.requested_at:
            raise ContractError("trusted admission cannot predate local request materialization")
        if evidence.accepted_at > now:
            raise ContractError("trusted admission cannot be from the future")
        if evidence.expires_at > command.expires_at:
            raise ContractError("trusted admission cannot outlive the command envelope")
        if now >= evidence.expires_at:
            raise ContractError("trusted command admission evidence has expired")

        assembly_receipt = assembly.execute(session=session, request=request, now=now)
        if not isinstance(assembly_receipt, LocalAgentRuntimeAssemblyReceipt):
            raise ContractError("Local Agent assembly returned an invalid receipt")
        if assembly_receipt.session_id != session.session_id:
            raise ContractError("Local Agent assembly receipt session mismatch")
        if assembly_receipt.binding_ref != command.binding_ref:
            raise ContractError("Local Agent assembly receipt binding mismatch")
        if assembly_receipt.request_id != request.request_id or assembly_receipt.run_id != request.run_id:
            raise ContractError("Local Agent assembly receipt request/run mismatch")
        if assembly_receipt.request_fingerprint != fingerprint:
            raise ContractError("Local Agent assembly receipt fingerprint mismatch")

        return AdmittedLocalCommandExecutionReceipt(
            admission_ref=evidence.admission_ref,
            command_id=command.command_id,
            tool_request_ref=command.tool_request_ref,
            sequence=command.sequence,
            session_id=session.session_id,
            binding_ref=command.binding_ref,
            request_id=request.request_id,
            run_id=request.run_id,
            request_fingerprint=fingerprint,
            assembly_ref=assembly_receipt.assembly_ref,
            authorization_ref=assembly_receipt.authorization_ref,
            termination=assembly_receipt.termination,
        )


COMMAND_REQUEST_INTEGRITY_BINDING = True
REQUEST_FINGERPRINT_RECOMPUTED = True
SESSION_BINDING_RUN_EXACT = True
TOOL_REQUEST_REF_EXACT = True
SEQUENCE_EXACT = True
COMMAND_EXPIRY_NOT_WIDENED = True
REQUEST_MATERIAL_AT_OR_BEFORE_COMMAND_ISSUANCE = True
REPLAY_MODEL_DUPLICATED = False
BROKER_WIRE_PROTOCOL_INVENTED = False
RAW_ARGV_IN_ADMISSION_EVIDENCE = False
CLIENT_ADMISSION_AUTHORITY = False
REAL_REMOTE_BROKER_CONFIGURED = False
PRODUCTION_READY = False