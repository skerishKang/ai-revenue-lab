from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent import LocalCommandRequest
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceSession
from .local_agent_secure_transport import OutboundLocalAgentTransportPort, OutboundTransportConfig
from .windows_local_executor import command_request_fingerprint


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_COMMAND_MATERIAL_BYTES = 196_608

_WIRE_KEYS = frozenset(
    {
        "contract_version",
        "command_id",
        "binding_ref",
        "sequence",
        "request_fingerprint",
        "material",
    }
)
_MATERIAL_KEYS = frozenset(
    {
        "request_id",
        "run_id",
        "device_id",
        "root_ref",
        "argv",
        "cwd_relative",
        "requested_at",
        "timeout_seconds",
        "shell_authority",
        "admin_elevation",
        "environment_payload",
        "provider_authority",
        "p01_approval_payload",
    }
)
_CONTRACT_VERSION = "claw-local-command-material.v1"


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact lowercase SHA-256 digest")
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


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{field_name} must be a positive integer without coercion")
    return value


def _closed_mapping(payload: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(payload) is not dict:
        raise ContractError(f"{label} must be a plain mapping")
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise ContractError(f"{label} schema mismatch ({'; '.join(details)})")
    return payload


def _require_false(payload: dict[str, Any], field_name: str) -> None:
    if payload[field_name] is not False:
        raise ContractError(f"{field_name} must remain false in Local Agent command material")


def _require_none(payload: dict[str, Any], field_name: str) -> None:
    if payload[field_name] is not None:
        raise ContractError(f"{field_name} must remain null in Local Agent command material")


@dataclass(frozen=True, slots=True)
class OutboundCommandMaterialRequest:
    """One outbound request for material belonging to an already-polled command."""

    request_ref: str
    session: DeviceSession
    command: DeviceCommandEnvelope
    request_fingerprint: str
    requested_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_ref", _ref(self.request_ref, "request_ref"))
        if not isinstance(self.session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        if not isinstance(self.command, DeviceCommandEnvelope):
            raise ContractError("command must be DeviceCommandEnvelope")
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        requested = _aware(self.requested_at, "requested_at")
        if not (self.session.issued_at <= requested < self.session.expires_at):
            raise ContractError("command material resolution requires a current device session")
        if self.command.binding_ref != self.session.binding_ref:
            raise ContractError("command material command/session binding mismatch")
        if not (self.command.issued_at <= requested < self.command.expires_at):
            raise ContractError("command material resolution requires a current polled command")
        object.__setattr__(self, "requested_at", requested)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_ref": self.request_ref,
            "session": self.session.safe_dict(),
            "command": self.command.safe_dict(),
            "request_fingerprint": self.request_fingerprint,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "outbound_only": True,
            "raw_argv": False,
            "environment_payload": False,
            "shell_authority": False,
            "admin_elevation": False,
            "caller_endpoint_override": False,
        }


@dataclass(frozen=True, slots=True)
class ResolvedLocalCommandMaterial:
    command_id: str
    binding_ref: str
    sequence: int
    request_fingerprint: str
    request: LocalCommandRequest

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", _ref(self.command_id, "command_id"))
        object.__setattr__(self, "binding_ref", _ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "sequence", _positive_int(self.sequence, "sequence"))
        object.__setattr__(
            self,
            "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        if not isinstance(self.request, LocalCommandRequest):
            raise ContractError("request must be LocalCommandRequest")
        if command_request_fingerprint(self.request) != self.request_fingerprint:
            raise ContractError("resolved Local Agent material fingerprint mismatch")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-resolved-local-command-material.v1",
            "command_id": self.command_id,
            "binding_ref": self.binding_ref,
            "sequence": self.sequence,
            "request_fingerprint": self.request_fingerprint,
            "request": self.request.safe_dict(),
            "raw_argv": False,
            "environment_payload": False,
            "shell_authority": False,
            "admin_elevation": False,
        }


class OutboundCommandMaterialTransportPort(Protocol):
    """Physical extension implemented by the same outbound broker transport object."""

    def resolve_material(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        request: OutboundCommandMaterialRequest,
    ) -> dict[str, Any]:
        ...


class OutboundLocalAgentMaterialTransportPort(OutboundLocalAgentTransportPort, Protocol):
    """Existing poll/ack transport plus bounded command-material resolution."""

    def resolve_material(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        request: OutboundCommandMaterialRequest,
    ) -> dict[str, Any]:
        ...


class UnconfiguredOutboundCommandMaterialTransportPort:
    def resolve_material(self, **_: Any) -> dict[str, Any]:
        raise ContractError("real Local Agent command material transport is not configured")


def build_command_material_wire_projection(
    *,
    command: DeviceCommandEnvelope,
    request: LocalCommandRequest,
    request_fingerprint: str,
) -> dict[str, Any]:
    """Canonical encoder for deterministic broker/server integration tests.

    This is serialization only. It creates no approval, broker admission, device
    session or execution authority.
    """

    if not isinstance(command, DeviceCommandEnvelope):
        raise ContractError("command must be DeviceCommandEnvelope")
    if not isinstance(request, LocalCommandRequest):
        raise ContractError("request must be LocalCommandRequest")
    fingerprint = _digest(request_fingerprint, "request_fingerprint")
    if request.run_id != command.run_id:
        raise ContractError("command material run_id must match command envelope")
    if request.requested_at > command.issued_at:
        raise ContractError("command material must be materialized before command issuance")
    if command_request_fingerprint(request) != fingerprint:
        raise ContractError("command material encoder request fingerprint mismatch")

    payload = {
        "contract_version": _CONTRACT_VERSION,
        "command_id": command.command_id,
        "binding_ref": command.binding_ref,
        "sequence": command.sequence,
        "request_fingerprint": fingerprint,
        "material": {
            "request_id": request.request_id,
            "run_id": request.run_id,
            "device_id": request.device_id,
            "root_ref": request.root_ref,
            "argv": list(request.argv),
            "cwd_relative": request.cwd_relative,
            "requested_at": request.requested_at.isoformat().replace("+00:00", "Z"),
            "timeout_seconds": request.timeout_seconds,
            "shell_authority": False,
            "admin_elevation": False,
            "environment_payload": None,
            "provider_authority": None,
            "p01_approval_payload": None,
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_COMMAND_MATERIAL_BYTES:
        raise ContractError("Local Agent command material exceeds wire size bound")
    return payload


def parse_command_material_wire_projection(
    payload: dict[str, Any],
    *,
    outbound_request: OutboundCommandMaterialRequest,
) -> ResolvedLocalCommandMaterial:
    """Convert untrusted decoded broker JSON to canonical LocalCommandRequest."""

    if not isinstance(outbound_request, OutboundCommandMaterialRequest):
        raise ContractError("outbound_request must be OutboundCommandMaterialRequest")
    payload = _closed_mapping(payload, _WIRE_KEYS, "command material projection")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_COMMAND_MATERIAL_BYTES:
        raise ContractError("Local Agent command material exceeds wire size bound")
    if payload["contract_version"] != _CONTRACT_VERSION:
        raise ContractError("unsupported Local Agent command material contract version")

    command = outbound_request.command
    if _ref(payload["command_id"], "command_id") != command.command_id:
        raise ContractError("command material command_id mismatch")
    if _ref(payload["binding_ref"], "binding_ref") != command.binding_ref:
        raise ContractError("command material binding_ref mismatch")
    if _positive_int(payload["sequence"], "sequence") != command.sequence:
        raise ContractError("command material sequence mismatch")
    fingerprint = _digest(payload["request_fingerprint"], "request_fingerprint")
    if fingerprint != outbound_request.request_fingerprint:
        raise ContractError("command material broker fingerprint mismatch")

    material = _closed_mapping(payload["material"], _MATERIAL_KEYS, "command material")
    _require_false(material, "shell_authority")
    _require_false(material, "admin_elevation")
    for field_name in ("environment_payload", "provider_authority", "p01_approval_payload"):
        _require_none(material, field_name)

    argv = material["argv"]
    if type(argv) is not list:
        raise ContractError("command material argv must be a JSON list")
    if not all(type(item) is str for item in argv):
        raise ContractError("command material argv must contain text only")
    timeout_seconds = material["timeout_seconds"]
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ContractError("timeout_seconds must be an integer without coercion")

    local_request = LocalCommandRequest(
        request_id=_ref(material["request_id"], "request_id"),
        run_id=_ref(material["run_id"], "run_id"),
        device_id=_ref(material["device_id"], "device_id"),
        root_ref=_ref(material["root_ref"], "root_ref"),
        argv=tuple(argv),
        cwd_relative=material["cwd_relative"],
        requested_at=_timestamp(material["requested_at"], "material.requested_at"),
        timeout_seconds=timeout_seconds,
    )

    if local_request.run_id != command.run_id:
        raise ContractError("command material run_id mismatch")
    if local_request.device_id != outbound_request.session.device_id:
        raise ContractError("command material device_id mismatch")
    if local_request.requested_at > command.issued_at:
        raise ContractError("command material requested_at cannot follow command issuance")
    recomputed = command_request_fingerprint(local_request)
    if recomputed != fingerprint:
        raise ContractError("command material recomputed request fingerprint mismatch")

    return ResolvedLocalCommandMaterial(
        command_id=command.command_id,
        binding_ref=command.binding_ref,
        sequence=command.sequence,
        request_fingerprint=fingerprint,
        request=local_request,
    )


EXISTING_OUTBOUND_TRANSPORT_REUSED = True
COMMAND_MATERIAL_RESOLUTION_CONTRACT = True
LOCAL_COMMAND_REQUEST_RECONSTRUCTED = True
REQUEST_FINGERPRINT_RECOMPUTED = True
EXACT_POLLED_COMMAND_CORRELATION = True
UNKNOWN_WIRE_FIELDS_FAIL_CLOSED = True
NUMERIC_COERCION = False
ENVIRONMENT_PAYLOAD = False
SHELL_AUTHORITY = False
ADMIN_AUTHORITY = False
PUBLIC_ENDPOINT = False
REAL_COMMAND_MATERIAL_TRANSPORT_CONFIGURED = False
REAL_REMOTE_EXECUTION = False
PRODUCTION_READY = False
