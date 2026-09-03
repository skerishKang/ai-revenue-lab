from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .connector_trust import (
    ConnectorBindingProjection,
    ConnectorBindingState,
    ConnectorHealthProjection,
    ConnectorHealthState,
)
from .contracts import ContractError
from .local_agent_management import LocalAgentManagementSnapshot
from .local_agent_pairing import DeviceLifecycle
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_MAX_LABEL_CHARS = 160
_MAX_REASON_CHARS = 1000
_MAX_ITEMS = 128
_WRITE_MARKERS = (
    "write",
    "create",
    "update",
    "delete",
    "send",
    "post",
    "deploy",
    "rollback",
    "mutate",
    "admin",
    "manage",
    "edit",
    "commit",
    "push",
)
_MATERIAL_MARKERS = (
    "delete",
    "deploy",
    "rollback",
    "admin",
    "billing",
    "dns",
    "secret",
    "grant",
    "revoke",
    "membership",
)


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    normalized = value.strip()
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    normalized = redact_secrets(value.strip())
    if not normalized or len(normalized) > maximum:
        raise ContractError(f"{field_name} must be bounded non-empty text")
    return normalized


def _refs(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or len(values) > _MAX_ITEMS:
        raise ContractError(f"{field_name} must be a bounded tuple")
    normalized = tuple(_ref(item, field_name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{field_name} values must be unique")
    return normalized


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    EXPIRED = "expired"
    ACTION_REQUIRED = "action_required"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"


class ConnectorAccessClass(str, Enum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    MATERIAL_WRITE = "material_write"


class AccountExposure(str, Enum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class ConnectionManagementAction(str, Enum):
    RECONNECT = "reconnect"
    DISCONNECT = "disconnect"
    REVOKE = "revoke"


class DeviceManagementAction(str, Enum):
    DISABLE = "disable"
    REVOKE = "revoke"
    DELETE = "delete"
    UPDATE = "update"


class DeviceCompatibility(str, Enum):
    CURRENT = "current"
    UPDATE_AVAILABLE = "update_available"
    UPDATE_REQUIRED = "update_required"
    UNKNOWN = "unknown"


class EscalationSensitivity(str, Enum):
    STANDARD = "standard"
    SENSITIVE = "sensitive"
    HIGH = "high"


class EscalationTargetKind(str, Enum):
    CONNECTOR = "connector"
    LOCAL_AGENT = "local_agent"


@dataclass(frozen=True, slots=True)
class ConnectionsCenterActivity:
    action_ref: str
    action_name: str
    target_ref: str
    occurred_at: datetime
    evidence_ref: str
    material: bool

    def __post_init__(self) -> None:
        for field_name in ("action_ref", "action_name", "target_ref", "evidence_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at, "occurred_at"))
        if not isinstance(self.material, bool):
            raise ContractError("material must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action_ref": self.action_ref,
            "action_name": self.action_name,
            "target_ref": self.target_ref,
            "occurred_at": _iso(self.occurred_at),
            "evidence_ref": self.evidence_ref,
            "material": self.material,
            "payload_present": False,
            "secret_value_present": False,
        }


def derive_connection_status(
    *,
    binding: ConnectorBindingProjection,
    health: ConnectorHealthProjection | None,
    now: datetime,
) -> ConnectionStatus:
    if not isinstance(binding, ConnectorBindingProjection):
        raise ContractError("binding must be ConnectorBindingProjection")
    now = _aware(now, "now")
    if binding.state is ConnectorBindingState.REVOKED:
        return ConnectionStatus.REVOKED
    if binding.expires_at is not None and now >= binding.expires_at:
        return ConnectionStatus.EXPIRED
    if health is None:
        return ConnectionStatus.ACTION_REQUIRED
    if not isinstance(health, ConnectorHealthProjection) or health.binding_ref != binding.binding_ref:
        raise ContractError("connector health must match connector binding")
    if health.state is ConnectorHealthState.REVOKED:
        return ConnectionStatus.REVOKED
    if not health.fresh_at(now):
        return ConnectionStatus.ACTION_REQUIRED
    if health.state is ConnectorHealthState.UNAVAILABLE:
        return ConnectionStatus.UNAVAILABLE
    if health.state is ConnectorHealthState.DEGRADED:
        return ConnectionStatus.ACTION_REQUIRED
    return ConnectionStatus.CONNECTED


def derive_connector_access_class(capabilities: tuple[str, ...]) -> ConnectorAccessClass:
    capabilities = _refs(capabilities, "granted_capability")
    lowered = tuple(item.casefold() for item in capabilities)
    if any(marker in item for item in lowered for marker in _MATERIAL_MARKERS):
        return ConnectorAccessClass.MATERIAL_WRITE
    if any(marker in item for item in lowered for marker in _WRITE_MARKERS):
        return ConnectorAccessClass.READ_WRITE
    return ConnectorAccessClass.READ_ONLY


@dataclass(frozen=True, slots=True)
class ConnectorAccountCard:
    service_label: str
    binding: ConnectorBindingProjection
    health: ConnectorHealthProjection | None
    now: datetime
    account_exposure: AccountExposure = AccountExposure.PRIVATE
    last_successful_probe_at: datetime | None = None
    last_material_action: ConnectionsCenterActivity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "service_label", _text(self.service_label, "service_label", _MAX_LABEL_CHARS))
        if not isinstance(self.binding, ConnectorBindingProjection):
            raise ContractError("binding must be ConnectorBindingProjection")
        if self.health is not None:
            if not isinstance(self.health, ConnectorHealthProjection) or self.health.binding_ref != self.binding.binding_ref:
                raise ContractError("health must match connector binding")
        object.__setattr__(self, "now", _aware(self.now, "now"))
        if not isinstance(self.account_exposure, AccountExposure):
            try:
                object.__setattr__(self, "account_exposure", AccountExposure(self.account_exposure))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid account exposure") from exc
        if self.last_successful_probe_at is not None:
            probe = _aware(self.last_successful_probe_at, "last_successful_probe_at")
            if probe > self.now:
                raise ContractError("last_successful_probe_at cannot be in the future")
            object.__setattr__(self, "last_successful_probe_at", probe)
        if self.last_material_action is not None:
            if not isinstance(self.last_material_action, ConnectionsCenterActivity) or not self.last_material_action.material:
                raise ContractError("last_material_action must be a material ConnectionsCenterActivity")
            if self.last_material_action.occurred_at > self.now:
                raise ContractError("last material action cannot be in the future")

    @property
    def status(self) -> ConnectionStatus:
        return derive_connection_status(binding=self.binding, health=self.health, now=self.now)

    @property
    def access_class(self) -> ConnectorAccessClass:
        return derive_connector_access_class(self.binding.granted_capabilities)

    @property
    def management_actions(self) -> tuple[ConnectionManagementAction, ...]:
        if self.status is ConnectionStatus.REVOKED:
            return ()
        if self.status in {ConnectionStatus.EXPIRED, ConnectionStatus.ACTION_REQUIRED, ConnectionStatus.UNAVAILABLE}:
            return (
                ConnectionManagementAction.RECONNECT,
                ConnectionManagementAction.DISCONNECT,
                ConnectionManagementAction.REVOKE,
            )
        return (ConnectionManagementAction.DISCONNECT, ConnectionManagementAction.REVOKE)

    def safe_dict(self) -> dict[str, Any]:
        warning = None
        if self.account_exposure is AccountExposure.SHARED:
            warning = "shared_account_scope_review_required"
        elif self.account_exposure is AccountExposure.PUBLIC:
            warning = "public_account_high_risk_scope_review_required"
        return {
            "service_label": self.service_label,
            "connector_id": self.binding.connector_id,
            "binding_ref": self.binding.binding_ref,
            "account_ref": self.binding.account_ref,
            "workspace_ref": self.binding.workspace_ref,
            "status": self.status.value,
            "granted_scopes": list(self.binding.granted_scopes),
            "granted_capabilities": list(self.binding.granted_capabilities),
            "access_class": self.access_class.value,
            "read_capability_visible": True,
            "write_capability_visible": self.access_class is not ConnectorAccessClass.READ_ONLY,
            "account_exposure": self.account_exposure.value,
            "account_warning": warning,
            "health": self.health.safe_dict() if self.health else None,
            "last_successful_probe_at": _iso(self.last_successful_probe_at),
            "last_material_action": self.last_material_action.safe_dict() if self.last_material_action else None,
            "management_actions": [action.value for action in self.management_actions],
            "action_required_visible": self.status in {
                ConnectionStatus.EXPIRED,
                ConnectionStatus.ACTION_REQUIRED,
                ConnectionStatus.UNAVAILABLE,
            },
            "ui_action_authority": False,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "raw_client_secret": False,
            "raw_api_key": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAgentDeviceCard:
    snapshot: LocalAgentManagementSnapshot
    arch: str
    client_version: str
    compatibility: DeviceCompatibility
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, LocalAgentManagementSnapshot):
            raise ContractError("snapshot must be LocalAgentManagementSnapshot")
        object.__setattr__(self, "arch", _ref(self.arch, "arch"))
        object.__setattr__(self, "client_version", _ref(self.client_version, "client_version"))
        if not isinstance(self.compatibility, DeviceCompatibility):
            try:
                object.__setattr__(self, "compatibility", DeviceCompatibility(self.compatibility))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid device compatibility") from exc
        if self.last_seen_at is not None:
            object.__setattr__(self, "last_seen_at", _aware(self.last_seen_at, "last_seen_at"))
        if self.snapshot.binding.state is DeviceLifecycle.UPDATE_REQUIRED and self.compatibility is not DeviceCompatibility.UPDATE_REQUIRED:
            raise ContractError("update-required lifecycle must be visible as update-required compatibility")

    @property
    def management_actions(self) -> tuple[DeviceManagementAction, ...]:
        if self.snapshot.binding.state is DeviceLifecycle.REVOKED:
            return (DeviceManagementAction.DELETE,)
        actions: list[DeviceManagementAction] = [
            DeviceManagementAction.DISABLE,
            DeviceManagementAction.REVOKE,
            DeviceManagementAction.DELETE,
        ]
        if self.compatibility in {DeviceCompatibility.UPDATE_AVAILABLE, DeviceCompatibility.UPDATE_REQUIRED}:
            actions.append(DeviceManagementAction.UPDATE)
        return tuple(actions)

    def safe_dict(self) -> dict[str, Any]:
        snapshot = self.snapshot.safe_dict()
        last_action = snapshot["recent_activity"][0] if snapshot["recent_activity"] else None
        return {
            "device_id": snapshot["device_id"],
            "device_name": snapshot["device_name"],
            "workspace_ref": snapshot["workspace_ref"],
            "paired_account_ref": self.snapshot.binding.account_ref,
            "platform": snapshot["platform"],
            "arch": self.arch,
            "client_version": self.client_version,
            "status": snapshot["status"],
            "last_seen_at": _iso(self.last_seen_at),
            "compatibility": self.compatibility.value,
            "roots": snapshot["roots"],
            "global_capabilities": snapshot["global_capabilities"],
            "last_local_action": last_action,
            "management_actions": [action.value for action in self.management_actions],
            "outbound_only": True,
            "whole_pc_grant": False,
            "ui_action_authority": False,
            "raw_device_credential": False,
            "raw_command_output": False,
        }


@dataclass(frozen=True, slots=True)
class CapabilityEscalationReview:
    review_ref: str
    target_kind: EscalationTargetKind
    target_ref: str
    current_scope: tuple[str, ...]
    requested_scope: tuple[str, ...]
    reason: str
    sensitivity: EscalationSensitivity
    requested_at: datetime
    trusted_approval_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "review_ref", _ref(self.review_ref, "review_ref"))
        object.__setattr__(self, "target_ref", _ref(self.target_ref, "target_ref"))
        if not isinstance(self.target_kind, EscalationTargetKind):
            object.__setattr__(self, "target_kind", EscalationTargetKind(self.target_kind))
        object.__setattr__(self, "current_scope", _refs(self.current_scope, "current_scope"))
        object.__setattr__(self, "requested_scope", _refs(self.requested_scope, "requested_scope"))
        object.__setattr__(self, "reason", _text(self.reason, "reason", _MAX_REASON_CHARS))
        if not isinstance(self.sensitivity, EscalationSensitivity):
            object.__setattr__(self, "sensitivity", EscalationSensitivity(self.sensitivity))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if self.trusted_approval_ref is not None:
            object.__setattr__(self, "trusted_approval_ref", _ref(self.trusted_approval_ref, "trusted_approval_ref"))

    @property
    def additions(self) -> tuple[str, ...]:
        current = set(self.current_scope)
        return tuple(item for item in self.requested_scope if item not in current)

    @property
    def removals(self) -> tuple[str, ...]:
        requested = set(self.requested_scope)
        return tuple(item for item in self.current_scope if item not in requested)

    @property
    def widens_capability(self) -> bool:
        return bool(self.additions)

    @property
    def approval_required(self) -> bool:
        return self.widens_capability

    def require_authorized_widening(self) -> None:
        if self.widens_capability and self.trusted_approval_ref is None:
            raise ContractError("capability widening requires a trusted approval reference")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "review_ref": self.review_ref,
            "target_kind": self.target_kind.value,
            "target_ref": self.target_ref,
            "current_scope": list(self.current_scope),
            "requested_scope": list(self.requested_scope),
            "additions": list(self.additions),
            "removals": list(self.removals),
            "reason": self.reason,
            "sensitivity": self.sensitivity.value,
            "requested_at": _iso(self.requested_at),
            "widens_capability": self.widens_capability,
            "approval_required": self.approval_required,
            "trusted_approval_present": self.trusted_approval_ref is not None,
            "trusted_approval_ref": self.trusted_approval_ref,
            "ui_may_apply_without_trusted_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ConnectionsDevicesCenterSnapshot:
    workspace_ref: str
    generated_at: datetime
    connectors: tuple[ConnectorAccountCard, ...]
    devices: tuple[LocalAgentDeviceCard, ...]
    escalation_reviews: tuple[CapabilityEscalationReview, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "generated_at", _aware(self.generated_at, "generated_at"))
        if not isinstance(self.connectors, tuple) or len(self.connectors) > _MAX_ITEMS:
            raise ContractError("connectors must be a bounded tuple")
        if not all(isinstance(item, ConnectorAccountCard) for item in self.connectors):
            raise ContractError("connectors must contain ConnectorAccountCard values")
        if not isinstance(self.devices, tuple) or len(self.devices) > _MAX_ITEMS:
            raise ContractError("devices must be a bounded tuple")
        if not all(isinstance(item, LocalAgentDeviceCard) for item in self.devices):
            raise ContractError("devices must contain LocalAgentDeviceCard values")
        if not isinstance(self.escalation_reviews, tuple) or len(self.escalation_reviews) > _MAX_ITEMS:
            raise ContractError("escalation_reviews must be a bounded tuple")
        if not all(isinstance(item, CapabilityEscalationReview) for item in self.escalation_reviews):
            raise ContractError("escalation_reviews must contain CapabilityEscalationReview values")
        if any(item.binding.workspace_ref != self.workspace_ref for item in self.connectors):
            raise ContractError("connector card workspace mismatch")
        if any(item.snapshot.device.workspace_ref != self.workspace_ref for item in self.devices):
            raise ContractError("device card workspace mismatch")
        connector_refs = [item.binding.binding_ref for item in self.connectors]
        device_refs = [item.snapshot.device.device_id for item in self.devices]
        if len(connector_refs) != len(set(connector_refs)) or len(device_refs) != len(set(device_refs)):
            raise ContractError("Connections Center identities must be unique")

    def safe_dict(self) -> dict[str, Any]:
        connector_cards = [item.safe_dict() for item in self.connectors]
        device_cards = [item.safe_dict() for item in self.devices]
        revocation_targets = [
            {
                "kind": "connector",
                "target_ref": item.binding.binding_ref,
                "actions": [action.value for action in item.management_actions if action in {
                    ConnectionManagementAction.DISCONNECT,
                    ConnectionManagementAction.REVOKE,
                }],
            }
            for item in self.connectors
            if item.management_actions
        ]
        revocation_targets.extend(
            {
                "kind": "local_agent",
                "target_ref": item.snapshot.device.device_id,
                "actions": [action.value for action in item.management_actions if action in {
                    DeviceManagementAction.DISABLE,
                    DeviceManagementAction.REVOKE,
                    DeviceManagementAction.DELETE,
                }],
            }
            for item in self.devices
        )
        return {
            "contract_version": "claw-connections-devices-center.v1",
            "workspace_ref": self.workspace_ref,
            "generated_at": _iso(self.generated_at),
            "connectors": connector_cards,
            "devices": device_cards,
            "escalation_reviews": [item.safe_dict() for item in self.escalation_reviews],
            "revocation_targets": revocation_targets,
            "revocation_one_place": True,
            "secret_value_visible": False,
            "ui_action_authority": False,
            "client_asserted_approval_authority": False,
            "real_backend_wired": False,
        }


REAL_CONNECTIONS_CENTER_BACKEND_WIRED = False
SECRET_VALUE_VISIBLE = False
UI_ACTION_AUTHORITY = False
CAPABILITY_ESCALATION_SILENT = False
REVOCATION_ONE_PLACE = True
