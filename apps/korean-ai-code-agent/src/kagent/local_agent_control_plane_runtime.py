from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any
from urllib.parse import urlsplit

from .contracts import ContractError
from .local_agent_control_plane_channel import ControlPlanePinnedHttpsChannel
from .local_agent_control_plane_https import (
    ControlPlaneHttpsLongPollTransport,
    ControlPlaneHttpsOperation,
    PinnedHttpsJsonRequestPort,
    StdlibPinnedHttpsJsonRequestPort,
)
from .local_agent_pairing import DeviceBinding, DeviceSession
from .local_agent_secure_channel import PinnedOutboundBrokerBinding
from .local_agent_secure_transport import DeviceCredentialStore, OutboundTransportConfig

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_HEARTBEAT_KEYS = frozenset(
    {
        "session_id",
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "last_seen_at",
        "session_expires_at",
        "raw_device_credential",
    }
)


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact bounded safe reference")
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


def _closed_mapping(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != expected:
        raise ContractError(f"{label} schema mismatch")
    return value


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


def _binding_session_exact(binding: DeviceBinding, session: DeviceSession, *, now: datetime) -> None:
    if not isinstance(binding, DeviceBinding):
        raise ContractError("binding must be DeviceBinding")
    if not isinstance(session, DeviceSession):
        raise ContractError("session must be DeviceSession")
    now = _aware(now, "now")
    if not (session.issued_at <= now < session.expires_at):
        raise ContractError("heartbeat requires a current device session")
    expected = (binding.binding_ref, binding.device_id, binding.account_ref, binding.workspace_ref)
    actual = (session.binding_ref, session.device_id, session.account_ref, session.workspace_ref)
    if actual != expected:
        raise ContractError("heartbeat session does not match device binding")


class ControlPlaneRuntimeHttpsOperation(str, Enum):
    HEARTBEAT = "heartbeat"


class RuntimeStdlibPinnedHttpsJsonRequestPort(StdlibPinnedHttpsJsonRequestPort):
    """Existing pinned stdlib HTTPS source plus the bounded heartbeat route."""

    def _path(
        self,
        config: OutboundTransportConfig,
        operation: ControlPlaneHttpsOperation | ControlPlaneRuntimeHttpsOperation,
    ) -> tuple[str, int, str]:
        if operation is not ControlPlaneRuntimeHttpsOperation.HEARTBEAT:
            return super()._path(config, operation)
        host, port, _ = super()._path(config, ControlPlaneHttpsOperation.POLL)
        base = (urlsplit(config.endpoint.url).path or "/").rstrip("/")
        path = f"{base}/heartbeat" if base else "/heartbeat"
        return host, port, path


@dataclass(frozen=True, slots=True)
class ControlPlaneHeartbeatReceipt:
    session_id: str
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    last_seen_at: datetime
    session_expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("session_id", "binding_ref", "device_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "credential_generation", _positive_int(
            self.credential_generation, "credential_generation"
        ))
        last_seen = _aware(self.last_seen_at, "last_seen_at")
        expires = _aware(self.session_expires_at, "session_expires_at")
        if last_seen >= expires:
            raise ContractError("heartbeat last_seen_at must precede session expiry")
        object.__setattr__(self, "last_seen_at", last_seen)
        object.__setattr__(self, "session_expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "last_seen_at": _iso(self.last_seen_at),
            "session_expires_at": _iso(self.session_expires_at),
            "server_last_seen_authority": True,
            "client_last_seen_authority": False,
            "raw_device_credential": False,
        }


class ControlPlanePhysicalRuntimeTransport(ControlPlaneHttpsLongPollTransport):
    """#1719 physical transport completion with an explicit server last-seen heartbeat contract."""

    def __init__(
        self,
        *,
        credential_store: DeviceCredentialStore,
        request_port: PinnedHttpsJsonRequestPort | None = None,
    ) -> None:
        super().__init__(
            credential_store=credential_store,
            request_port=request_port or RuntimeStdlibPinnedHttpsJsonRequestPort(),
        )

    def heartbeat(
        self,
        *,
        config: OutboundTransportConfig,
        binding: DeviceBinding,
        session: DeviceSession,
        now: datetime,
    ) -> ControlPlaneHeartbeatReceipt:
        now = _aware(now, "now")
        _binding_session_exact(binding, session, now=now)
        response = self._post(
            config=config,
            operation=ControlPlaneRuntimeHttpsOperation.HEARTBEAT,
            payload={
                "session_id": session.session_id,
                "binding_ref": binding.binding_ref,
                "credential_b64": self._credential_b64(binding, now=now),
                "now": _iso(now),
            },
            timeout_seconds=min(config.poll_timeout_seconds, 30),
        )
        payload = _closed_mapping(self._success(response, "heartbeat"), _HEARTBEAT_KEYS, "broker heartbeat")
        if payload["raw_device_credential"] is not False:
            raise ContractError("broker heartbeat must not expose raw device credential")
        expected_refs = {
            "session_id": session.session_id,
            "binding_ref": binding.binding_ref,
            "device_id": binding.device_id,
            "account_ref": binding.account_ref,
            "workspace_ref": binding.workspace_ref,
        }
        for field_name, expected in expected_refs.items():
            if _ref(payload[field_name], field_name) != expected:
                raise ContractError(f"broker heartbeat {field_name} mismatch")
        if _positive_int(payload["credential_generation"], "credential_generation") != binding.credential_generation:
            raise ContractError("broker heartbeat credential generation mismatch")
        last_seen = _timestamp(payload["last_seen_at"], "last_seen_at")
        expires = _timestamp(payload["session_expires_at"], "session_expires_at")
        if last_seen != now:
            raise ContractError("broker heartbeat last_seen_at must equal acknowledged heartbeat time")
        if expires != session.expires_at:
            raise ContractError("broker heartbeat session expiry mismatch")
        return ControlPlaneHeartbeatReceipt(
            session_id=session.session_id,
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation,
            last_seen_at=last_seen,
            session_expires_at=expires,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "heartbeat_bounded": True,
            "heartbeat_seconds_min": 5,
            "heartbeat_seconds_max": 300,
            "server_last_seen_required": True,
            "client_last_seen_authority": False,
        }


class ControlPlanePhysicalRuntimeChannel(ControlPlanePinnedHttpsChannel):
    """Canonical physical #1719 channel: session/poll/material/heartbeat/admission-bound ack."""

    def __init__(
        self,
        *,
        authority: PinnedOutboundBrokerBinding,
        transport: ControlPlanePhysicalRuntimeTransport,
    ) -> None:
        if not isinstance(transport, ControlPlanePhysicalRuntimeTransport):
            raise ContractError("transport must be ControlPlanePhysicalRuntimeTransport")
        super().__init__(authority=authority, transport=transport)
        self._runtime_transport = transport

    def heartbeat(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        now: datetime,
    ) -> ControlPlaneHeartbeatReceipt:
        now = _aware(now, "now")
        self.authority.require_current_binding(binding, now=now)
        self.authority.require_session(session, now=now)
        return self._runtime_transport.heartbeat(
            config=self.authority.config,
            binding=binding,
            session=session,
            now=now,
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
        del binding, session, command_id, evidence_ref, now
        raise ContractError(
            "Control Plane HTTPS acknowledgement requires admission_ref and evidence_ref; use acknowledge_admitted"
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "heartbeat_bounded": True,
            "server_last_seen_required": True,
            "generic_acknowledge_disabled": True,
            "admission_bound_acknowledge": True,
        }


HEARTBEAT_BOUNDED = True
SERVER_LAST_SEEN_REQUIRED = True
CLIENT_LAST_SEEN_AUTHORITY = False
GENERIC_ACKNOWLEDGE_DISABLED = True
ADMISSION_BOUND_ACKNOWLEDGE = True
PUBLIC_INBOUND_PORT = False
UPNP = False
LIVE_BROKER_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
