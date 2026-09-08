from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .contracts import ContractError
from .local_agent_command_admission import TrustedDeviceCommandAdmissionEvidence
from .local_agent_pairing import DeviceCommandEnvelope


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

_COMMAND_KEYS = frozenset(
    {
        "command_id",
        "run_id",
        "tool_request_ref",
        "binding_ref",
        "credential_generation",
        "sequence",
        "request_fingerprint",
        "issued_at",
        "expires_at",
        "state",
        "admission_ref",
        "evidence_ref",
        "admitted_session_id",
        "admitted_at",
        "acknowledged_at",
        "raw_argv",
        "raw_file_content",
        "raw_device_credential",
        "p01_approval_payload",
    }
)

_ADMISSION_KEYS = frozenset(
    {
        "admission_ref",
        "authority_ref",
        "command_id",
        "session_id",
        "binding_ref",
        "run_id",
        "tool_request_ref",
        "sequence",
        "request_fingerprint",
        "evidence_ref",
        "accepted_at",
        "expires_at",
        "raw_argv",
        "raw_device_credential",
    }
)


def _closed_mapping(payload: dict[str, Any], expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(payload) is not dict:
        raise ContractError(f"{label} projection must be a plain mapping")
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        detail: list[str] = []
        if missing:
            detail.append(f"missing={','.join(missing)}")
        if unknown:
            detail.append(f"unknown={','.join(unknown)}")
        raise ContractError(f"{label} projection schema mismatch ({'; '.join(detail)})")
    return payload


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact lowercase SHA-256 digest")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{field_name} must be a positive integer without coercion")
    return value


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


def _require_false(payload: dict[str, Any], field_name: str) -> None:
    if payload[field_name] is not False:
        raise ContractError(f"{field_name} must remain false at the broker projection boundary")


def _require_none(payload: dict[str, Any], field_name: str) -> None:
    if payload[field_name] is not None:
        raise ContractError(f"queued broker command {field_name} must be null")


@dataclass(frozen=True, slots=True)
class ConformedControlPlaneBrokerCommand:
    """A reviewed Control Plane command projection reduced to B54 authority inputs."""

    envelope: DeviceCommandEnvelope
    credential_generation: int
    request_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, DeviceCommandEnvelope):
            raise ContractError("envelope must be DeviceCommandEnvelope")
        object.__setattr__(
            self,
            "credential_generation",
            _positive_int(self.credential_generation, "credential_generation"),
        )
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-control-plane-broker-command-conformance.v1",
            "command": self.envelope.safe_dict(),
            "credential_generation": self.credential_generation,
            "request_fingerprint": self.request_fingerprint,
            "raw_argv": False,
            "raw_file_content": False,
            "raw_device_credential": False,
            "control_plane_runtime_dependency": False,
        }


@dataclass(frozen=True, slots=True)
class ConformedControlPlaneBrokerAdmission:
    """Control Plane admission plus the evidence ref needed for exact broker ack."""

    evidence: TrustedDeviceCommandAdmissionEvidence
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, TrustedDeviceCommandAdmissionEvidence):
            raise ContractError("evidence must be TrustedDeviceCommandAdmissionEvidence")
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-control-plane-broker-admission-conformance.v1",
            "evidence": self.evidence.safe_dict(),
            "evidence_ref": self.evidence_ref,
            "raw_argv": False,
            "raw_device_credential": False,
            "control_plane_runtime_dependency": False,
        }


def parse_control_plane_broker_command(
    payload: dict[str, Any],
    *,
    expected_binding_ref: str,
    expected_credential_generation: int,
    now: datetime,
) -> ConformedControlPlaneBrokerCommand:
    """Fail-closed parser for `BrokerCommandRecord.safe_dict()` queued projections."""

    payload = _closed_mapping(payload, _COMMAND_KEYS, "broker command")
    expected_binding_ref = _ref(expected_binding_ref, "expected_binding_ref")
    expected_generation = _positive_int(expected_credential_generation, "expected_credential_generation")
    now = _aware(now, "now")

    if payload["state"] != "queued":
        raise ContractError("broker command must be queued before B54 admission")
    for field_name in ("raw_argv", "raw_file_content", "raw_device_credential", "p01_approval_payload"):
        _require_false(payload, field_name)
    for field_name in ("admission_ref", "evidence_ref", "admitted_session_id", "admitted_at", "acknowledged_at"):
        _require_none(payload, field_name)

    binding_ref = _ref(payload["binding_ref"], "binding_ref")
    if binding_ref != expected_binding_ref:
        raise ContractError("broker command binding_ref mismatch")
    generation = _positive_int(payload["credential_generation"], "credential_generation")
    if generation != expected_generation:
        raise ContractError("broker command credential_generation mismatch")

    sequence = _positive_int(payload["sequence"], "sequence")
    fingerprint = _digest(payload["request_fingerprint"], "request_fingerprint")
    issued_at = _timestamp(payload["issued_at"], "issued_at")
    expires_at = _timestamp(payload["expires_at"], "expires_at")
    if now < issued_at or now >= expires_at:
        raise ContractError("broker command projection is not currently valid")

    envelope = DeviceCommandEnvelope(
        command_id=_ref(payload["command_id"], "command_id"),
        run_id=_ref(payload["run_id"], "run_id"),
        tool_request_ref=_ref(payload["tool_request_ref"], "tool_request_ref"),
        binding_ref=binding_ref,
        sequence=sequence,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return ConformedControlPlaneBrokerCommand(
        envelope=envelope,
        credential_generation=generation,
        request_fingerprint=fingerprint,
    )


def parse_control_plane_broker_admission(
    payload: dict[str, Any],
    *,
    command: ConformedControlPlaneBrokerCommand,
    expected_authority_ref: str,
    expected_session_id: str,
    now: datetime,
) -> ConformedControlPlaneBrokerAdmission:
    """Fail-closed parser for `BrokerCommandAdmission.to_public_dict()` projections."""

    payload = _closed_mapping(payload, _ADMISSION_KEYS, "broker admission")
    if not isinstance(command, ConformedControlPlaneBrokerCommand):
        raise ContractError("command must be ConformedControlPlaneBrokerCommand")
    expected_authority_ref = _ref(expected_authority_ref, "expected_authority_ref")
    expected_session_id = _ref(expected_session_id, "expected_session_id")
    now = _aware(now, "now")

    _require_false(payload, "raw_argv")
    _require_false(payload, "raw_device_credential")

    authority_ref = _ref(payload["authority_ref"], "authority_ref")
    if authority_ref != expected_authority_ref:
        raise ContractError("broker admission authority_ref mismatch")
    session_id = _ref(payload["session_id"], "session_id")
    if session_id != expected_session_id:
        raise ContractError("broker admission session_id mismatch")

    envelope = command.envelope
    correlations = {
        "command_id": envelope.command_id,
        "binding_ref": envelope.binding_ref,
        "run_id": envelope.run_id,
        "tool_request_ref": envelope.tool_request_ref,
    }
    for field_name, expected in correlations.items():
        if _ref(payload[field_name], field_name) != expected:
            raise ContractError(f"broker admission {field_name} mismatch")

    sequence = _positive_int(payload["sequence"], "sequence")
    if sequence != envelope.sequence:
        raise ContractError("broker admission sequence mismatch")
    fingerprint = _digest(payload["request_fingerprint"], "request_fingerprint")
    if fingerprint != command.request_fingerprint:
        raise ContractError("broker admission request_fingerprint mismatch")

    accepted_at = _timestamp(payload["accepted_at"], "accepted_at")
    expires_at = _timestamp(payload["expires_at"], "expires_at")
    if accepted_at < envelope.issued_at:
        raise ContractError("broker admission cannot predate the command envelope")
    if accepted_at > now:
        raise ContractError("broker admission cannot be from the future")
    if expires_at > envelope.expires_at:
        raise ContractError("broker admission cannot outlive the command envelope")
    if now >= expires_at:
        raise ContractError("broker admission projection has expired")

    evidence = TrustedDeviceCommandAdmissionEvidence(
        admission_ref=_ref(payload["admission_ref"], "admission_ref"),
        authority_ref=authority_ref,
        command_id=envelope.command_id,
        session_id=session_id,
        binding_ref=envelope.binding_ref,
        run_id=envelope.run_id,
        tool_request_ref=envelope.tool_request_ref,
        sequence=envelope.sequence,
        request_fingerprint=fingerprint,
        accepted_at=accepted_at,
        expires_at=expires_at,
    )
    return ConformedControlPlaneBrokerAdmission(
        evidence=evidence,
        evidence_ref=_ref(payload["evidence_ref"], "evidence_ref"),
    )


CONTROL_PLANE_TO_B54_COMMAND_CONFORMANCE = True
CONTROL_PLANE_TO_B54_ADMISSION_CONFORMANCE = True
EVIDENCE_REF_PRESERVED = True
EXPECTED_CREDENTIAL_GENERATION_EXACT = True
UNKNOWN_WIRE_FIELDS_FAIL_CLOSED = True
NUMERIC_COERCION = False
CONTROL_PLANE_RUNTIME_DEPENDENCY_IN_B54 = False
NETWORK_CONFIGURED = False
PRODUCTION_READY = False
