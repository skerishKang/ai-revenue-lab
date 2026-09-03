from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError
from .local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from .local_agent_secure_transport import (
    OutboundLocalAgentTransportPort,
    OutboundPollRequest,
    OutboundTransportConfig,
)
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")


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


def _credential_ref_fingerprint(binding: DeviceBinding) -> str:
    return hashlib.sha256(binding.credential_ref.encode("utf-8")).hexdigest()


def _config_fingerprint(config: OutboundTransportConfig) -> str:
    canonical = json.dumps(config.safe_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PinnedOutboundBrokerBinding:
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_ref_fingerprint: str
    config: OutboundTransportConfig

    @classmethod
    def from_binding(
        cls,
        *,
        binding: DeviceBinding,
        config: OutboundTransportConfig,
    ) -> "PinnedOutboundBrokerBinding":
        if not isinstance(binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        if not isinstance(config, OutboundTransportConfig):
            raise ContractError("config must be OutboundTransportConfig")
        return cls(
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation,
            credential_ref_fingerprint=_credential_ref_fingerprint(binding),
            config=config,
        )

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "device_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.credential_generation, bool) or not isinstance(self.credential_generation, int) or self.credential_generation < 1:
            raise ContractError("credential_generation must be a positive integer")
        fingerprint = self.credential_ref_fingerprint.strip().lower() if isinstance(self.credential_ref_fingerprint, str) else ""
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ContractError("credential_ref_fingerprint must be SHA-256")
        object.__setattr__(self, "credential_ref_fingerprint", fingerprint)
        if not isinstance(self.config, OutboundTransportConfig):
            raise ContractError("config must be OutboundTransportConfig")

    @property
    def config_fingerprint(self) -> str:
        return _config_fingerprint(self.config)

    def require_current_binding(self, binding: DeviceBinding, *, now: datetime) -> None:
        if not isinstance(binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        now = _aware(now, "now")
        if binding.state in {DeviceLifecycle.UNPAIRED, DeviceLifecycle.REVOKED, DeviceLifecycle.CREDENTIAL_EXPIRED}:
            raise ContractError("pinned outbound binding is not usable")
        if now >= binding.credential_expires_at:
            raise ContractError("pinned outbound binding credential is expired")
        expected = (
            self.binding_ref,
            self.device_id,
            self.account_ref,
            self.workspace_ref,
            self.credential_generation,
            self.credential_ref_fingerprint,
        )
        actual = (
            binding.binding_ref,
            binding.device_id,
            binding.account_ref,
            binding.workspace_ref,
            binding.credential_generation,
            _credential_ref_fingerprint(binding),
        )
        if actual != expected:
            raise ContractError("device binding no longer matches pinned outbound broker authority")

    def require_session(self, session: DeviceSession, *, now: datetime) -> None:
        if not isinstance(session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        now = _aware(now, "now")
        if not (session.issued_at <= now < session.expires_at):
            raise ContractError("device session is not current")
        expected = (self.binding_ref, self.device_id, self.account_ref, self.workspace_ref)
        actual = (session.binding_ref, session.device_id, session.account_ref, session.workspace_ref)
        if actual != expected:
            raise ContractError("device session does not match pinned outbound broker authority")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "credential_ref_fingerprint": self.credential_ref_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "endpoint": self.config.endpoint.safe_dict(),
            "tls_required": True,
            "public_inbound_port": False,
            "caller_endpoint_override": False,
            "credential_ref_present": False,
            "raw_device_credential": False,
        }


class PinnedOutboundLocalAgentChannel:
    """Caller-facing channel that owns one trusted broker config; callers cannot supply a URL/config per operation."""

    def __init__(
        self,
        *,
        authority: PinnedOutboundBrokerBinding,
        transport: OutboundLocalAgentTransportPort,
    ) -> None:
        if not isinstance(authority, PinnedOutboundBrokerBinding):
            raise ContractError("authority must be PinnedOutboundBrokerBinding")
        if not hasattr(transport, "poll") or not hasattr(transport, "acknowledge"):
            raise ContractError("transport must implement poll/acknowledge")
        self._authority = authority
        self._transport = transport

    @property
    def authority(self) -> PinnedOutboundBrokerBinding:
        return self._authority

    def poll(
        self,
        *,
        binding: DeviceBinding,
        request: OutboundPollRequest,
    ):
        if not isinstance(request, OutboundPollRequest):
            raise ContractError("request must be OutboundPollRequest")
        now = request.requested_at
        self._authority.require_current_binding(binding, now=now)
        self._authority.require_session(request.session, now=now)
        return self._transport.poll(
            config=self._authority.config,
            binding=binding,
            request=request,
        )

    def acknowledge(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command_id: str,
        evidence_ref: str,
        now: datetime,
    ) -> None:
        now = _aware(now, "now")
        self._authority.require_current_binding(binding, now=now)
        self._authority.require_session(session, now=now)
        self._transport.acknowledge(
            config=self._authority.config,
            binding=binding,
            session=session,
            command_id=_ref(command_id, "command_id"),
            evidence_ref=_ref(evidence_ref, "evidence_ref"),
            now=now,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "authority": self._authority.safe_dict(),
            "caller_endpoint_override": False,
            "public_inbound_port": False,
            "raw_device_credential": False,
            "real_broker_configured": False,
        }


CALLER_FACING_CONFIG_ARGUMENT = False
PINNED_BROKER_AUTHORITY = True
