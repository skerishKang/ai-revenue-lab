from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets


class OpsDeliveryMode(str, Enum):
    CLOUD_MANAGED = "cloud_managed"
    CLOUD_BYOK = "cloud_byok"
    LOCAL = "local"
    SELF_HOSTED = "self_hosted"


class ModelCredentialMode(str, Enum):
    PADIEM_MANAGED = "padiem_managed"
    SECRET_REFERENCE = "secret_reference"
    LOCAL_OR_SELF_HOSTED = "local_or_self_hosted"


class OnboardingStatus(str, Enum):
    ACCOUNT_REQUIRED = "account_required"
    WORKSPACE_REQUIRED = "workspace_required"
    CONNECTORS_OPTIONAL = "connectors_optional"
    READY = "ready"


_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SECRET_PREFIXES = ("sk-", "bearer ", "api_key=", "apikey=", "token=", "secret=", "password=")


def _ref(value: str | None, field_name: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ContractError(f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        if required:
            raise ContractError(f"{field_name} is required")
        return None
    lower = value.lower()
    if lower.startswith(_SECRET_PREFIXES) or redact_secrets(value) != value:
        raise ContractError(f"{field_name} must be an opaque reference, never a raw secret")
    if not _REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} has invalid reference syntax")
    return value


def _bounded_tuple(value: tuple[Any, ...], field_name: str, *, maximum: int) -> tuple[Any, ...]:
    if not isinstance(value, tuple) or len(value) > maximum:
        raise ContractError(f"{field_name} must be a tuple with at most {maximum} entries")
    return value


@dataclass(frozen=True, slots=True)
class SecretReference:
    secret_ref: str
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "secret_ref", _ref(self.secret_ref, "secret_ref"))
        purpose = _ref(self.purpose, "purpose")
        assert purpose is not None
        object.__setattr__(self, "purpose", purpose)

    def safe_dict(self) -> dict[str, str]:
        return {"secret_ref": self.secret_ref, "purpose": self.purpose}


@dataclass(frozen=True, slots=True)
class ConnectorBinding:
    connector_id: str
    account_ref: str
    credential_ref: SecretReference
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "connector_id", _ref(self.connector_id, "connector_id"))
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref"))
        if not isinstance(self.credential_ref, SecretReference):
            raise ContractError("credential_ref must be SecretReference")
        if not isinstance(self.enabled, bool):
            raise ContractError("enabled must be boolean")


@dataclass(frozen=True, slots=True)
class OpsExecutionProfile:
    workspace_id: str
    account_ref: str
    org_ref: str | None
    delivery_mode: OpsDeliveryMode
    model_credential_mode: ModelCredentialMode
    entitlement_ref: str | None = None
    model_secret_ref: SecretReference | None = None
    connectors: tuple[ConnectorBinding, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "org_ref", _ref(self.org_ref, "org_ref", required=False))
        if not isinstance(self.delivery_mode, OpsDeliveryMode):
            try:
                object.__setattr__(self, "delivery_mode", OpsDeliveryMode(self.delivery_mode))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid delivery_mode") from exc
        if not isinstance(self.model_credential_mode, ModelCredentialMode):
            try:
                object.__setattr__(self, "model_credential_mode", ModelCredentialMode(self.model_credential_mode))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid model_credential_mode") from exc
        object.__setattr__(self, "entitlement_ref", _ref(self.entitlement_ref, "entitlement_ref", required=False))
        if self.model_secret_ref is not None and not isinstance(self.model_secret_ref, SecretReference):
            raise ContractError("model_secret_ref must be SecretReference or None")
        _bounded_tuple(self.connectors, "connectors", maximum=32)
        if not all(isinstance(item, ConnectorBinding) for item in self.connectors):
            raise ContractError("connectors must contain ConnectorBinding values")
        if len({item.connector_id for item in self.connectors}) != len(self.connectors):
            raise ContractError("connector_id values must be unique")

        mode = self.delivery_mode
        credential_mode = self.model_credential_mode
        if mode is OpsDeliveryMode.CLOUD_MANAGED:
            if credential_mode is not ModelCredentialMode.PADIEM_MANAGED:
                raise ContractError("Cloud Managed must use Padiem-managed model credentials")
            if self.model_secret_ref is not None:
                raise ContractError("Cloud Managed profile must not carry a model secret reference")
            if self.entitlement_ref is None:
                raise ContractError("Cloud Managed requires a trusted entitlement reference")
        elif mode is OpsDeliveryMode.CLOUD_BYOK:
            if credential_mode is not ModelCredentialMode.SECRET_REFERENCE:
                raise ContractError("Cloud BYOK requires secret-reference credential mode")
            if self.model_secret_ref is None:
                raise ContractError("Cloud BYOK requires an opaque model secret reference")
        elif mode in {OpsDeliveryMode.LOCAL, OpsDeliveryMode.SELF_HOSTED}:
            if credential_mode not in {
                ModelCredentialMode.SECRET_REFERENCE,
                ModelCredentialMode.LOCAL_OR_SELF_HOSTED,
            }:
                raise ContractError("Local/Self-Hosted cannot claim Padiem-managed credential authority")

    @property
    def requires_user_provider_key_input(self) -> bool:
        return self.delivery_mode is OpsDeliveryMode.CLOUD_BYOK

    @property
    def dedicated_ai_workstation_required(self) -> bool:
        return False

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-execution-profile.v1",
            "workspace_id": self.workspace_id,
            "account_ref": self.account_ref,
            "org_ref": self.org_ref,
            "delivery_mode": self.delivery_mode.value,
            "model_credential_mode": self.model_credential_mode.value,
            "entitlement_ref": self.entitlement_ref,
            "model_secret_ref": self.model_secret_ref.safe_dict() if self.model_secret_ref else None,
            "connectors": [
                {
                    "connector_id": item.connector_id,
                    "account_ref": item.account_ref,
                    "credential_ref": item.credential_ref.safe_dict(),
                    "enabled": item.enabled,
                }
                for item in self.connectors
            ],
            "requires_user_provider_key_input": self.requires_user_provider_key_input,
            "dedicated_ai_workstation_required": self.dedicated_ai_workstation_required,
            "raw_secret_values": False,
        }


@dataclass(frozen=True, slots=True)
class ManagedOnboardingProjection:
    account_ref: str | None = None
    workspace_id: str | None = None
    supplier_count: int = 0
    connector_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref", required=False))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id", required=False))
        for field_name in ("supplier_count", "connector_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
                raise ContractError(f"{field_name} must be a bounded non-negative integer")

    @property
    def status(self) -> OnboardingStatus:
        if self.account_ref is None:
            return OnboardingStatus.ACCOUNT_REQUIRED
        if self.workspace_id is None:
            return OnboardingStatus.WORKSPACE_REQUIRED
        if self.connector_count == 0:
            return OnboardingStatus.CONNECTORS_OPTIONAL
        return OnboardingStatus.READY

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-onboarding.v1",
            "account_ref": self.account_ref,
            "workspace_id": self.workspace_id,
            "supplier_count": self.supplier_count,
            "connector_count": self.connector_count,
            "status": self.status.value,
            "provider_api_key_required_for_managed": False,
        }
