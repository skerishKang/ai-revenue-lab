from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

from .agent_computer import AgentComputerLease, AgentComputerLeaseState
from .contracts import ContractError


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class PreviewShareLeaseState(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class PrivatePreviewEndpoint:
    endpoint_id: str
    run_id: str
    computer_id: str
    internal_port: int
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("endpoint_id", "run_id", "computer_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.internal_port, bool) or not isinstance(self.internal_port, int) or not 1024 <= self.internal_port <= 65535:
            raise ContractError("internal_port must be between 1024 and 65535")
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "run_id": self.run_id,
            "computer_id": self.computer_id,
            "internal_port": self.internal_port,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "private": True,
            "public_url": None,
            "authentication_cookie": False,
        }


@dataclass(frozen=True, slots=True)
class TrustedPreviewShareGrant:
    grant_id: str
    run_id: str
    computer_id: str
    endpoint_id: str
    internal_port: int
    authority_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("grant_id", "run_id", "computer_id", "endpoint_id", "authority_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.internal_port, bool) or not isinstance(self.internal_port, int) or not 1024 <= self.internal_port <= 65535:
            raise ContractError("internal_port must be between 1024 and 65535")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        lifetime = (expires - issued).total_seconds()
        if not 60 <= lifetime <= 900:
            raise ContractError("trusted preview share grant lifetime must be between 60 and 900 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "run_id": self.run_id,
            "computer_id": self.computer_id,
            "endpoint_id": self.endpoint_id,
            "internal_port": self.internal_port,
            "authority_ref": self.authority_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_credentials": False,
            "provider_endpoint": False,
        }


@dataclass(frozen=True, slots=True)
class PreviewShareLease:
    share_id: str
    grant_id: str
    run_id: str
    computer_id: str
    endpoint_id: str
    internal_port: int
    external_ref: str
    issued_at: datetime
    expires_at: datetime
    state: PreviewShareLeaseState = PreviewShareLeaseState.ACTIVE

    def __post_init__(self) -> None:
        for field_name in ("share_id", "grant_id", "run_id", "computer_id", "endpoint_id", "external_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.internal_port, bool) or not isinstance(self.internal_port, int) or not 1024 <= self.internal_port <= 65535:
            raise ContractError("internal_port must be between 1024 and 65535")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 900:
            raise ContractError("preview share lease lifetime must be positive and at most 900 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if not isinstance(self.state, PreviewShareLeaseState):
            try:
                object.__setattr__(self, "state", PreviewShareLeaseState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid preview share lease state") from exc

    @property
    def active(self) -> bool:
        return self.state is PreviewShareLeaseState.ACTIVE

    def safe_dict(self) -> dict[str, Any]:
        return {
            "share_id": self.share_id,
            "grant_id": self.grant_id,
            "run_id": self.run_id,
            "computer_id": self.computer_id,
            "endpoint_id": self.endpoint_id,
            "internal_port": self.internal_port,
            "external_ref": self.external_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
            "temporary": True,
            "permanent_public_url": False,
            "authentication_cookie": False,
            "raw_credentials": False,
        }


class PreviewPortProvider(Protocol):
    def create_private(self, *, computer: AgentComputerLease, internal_port: int, now: datetime) -> PrivatePreviewEndpoint:
        ...

    def share(self, *, endpoint: PrivatePreviewEndpoint, computer: AgentComputerLease, grant: TrustedPreviewShareGrant, now: datetime) -> PreviewShareLease:
        ...

    def release(self, share_id: str, *, now: datetime) -> PreviewShareLease:
        ...


class UnconfiguredPreviewPortProvider:
    def create_private(self, *, computer: AgentComputerLease, internal_port: int, now: datetime) -> PrivatePreviewEndpoint:
        raise ContractError("preview-port provider is not configured")

    def share(self, *, endpoint: PrivatePreviewEndpoint, computer: AgentComputerLease, grant: TrustedPreviewShareGrant, now: datetime) -> PreviewShareLease:
        raise ContractError("preview-port provider is not configured")

    def release(self, share_id: str, *, now: datetime) -> PreviewShareLease:
        raise ContractError("preview-port provider is not configured")


class DeterministicFakePreviewPortProvider:
    def __init__(self) -> None:
        self._private_by_key: dict[tuple[str, int], PrivatePreviewEndpoint] = {}
        self._shares: dict[str, PreviewShareLease] = {}
        self._active_share_by_key: dict[tuple[str, int], str] = {}

    @staticmethod
    def _validate_computer(computer: AgentComputerLease, *, now: datetime) -> datetime:
        if not isinstance(computer, AgentComputerLease):
            raise ContractError("computer must be AgentComputerLease")
        now = _aware(now, "now")
        if computer.state is not AgentComputerLeaseState.ACTIVE or now >= computer.expires_at:
            raise ContractError("preview requires an active Agent Computer")
        if now < computer.issued_at:
            raise ContractError("preview time cannot precede Agent Computer issue time")
        return now

    def create_private(self, *, computer: AgentComputerLease, internal_port: int, now: datetime) -> PrivatePreviewEndpoint:
        now = self._validate_computer(computer, now=now)
        if isinstance(internal_port, bool) or not isinstance(internal_port, int) or not 1024 <= internal_port <= 65535:
            raise ContractError("internal_port must be between 1024 and 65535")
        key = (computer.computer_id, internal_port)
        existing = self._private_by_key.get(key)
        if existing is not None:
            return existing
        digest = hashlib.sha256(f"{computer.run_id}:{computer.computer_id}:{internal_port}".encode("utf-8")).hexdigest()[:24]
        endpoint = PrivatePreviewEndpoint(
            endpoint_id=f"preview:{digest}",
            run_id=computer.run_id,
            computer_id=computer.computer_id,
            internal_port=internal_port,
            created_at=now,
        )
        self._private_by_key[key] = endpoint
        return endpoint

    def share(self, *, endpoint: PrivatePreviewEndpoint, computer: AgentComputerLease, grant: TrustedPreviewShareGrant, now: datetime) -> PreviewShareLease:
        now = self._validate_computer(computer, now=now)
        if not isinstance(endpoint, PrivatePreviewEndpoint) or not isinstance(grant, TrustedPreviewShareGrant):
            raise ContractError("endpoint and grant must use preview-port contracts")
        if endpoint.run_id != computer.run_id or endpoint.computer_id != computer.computer_id:
            raise ContractError("preview endpoint does not belong to Agent Computer")
        expected = self._private_by_key.get((computer.computer_id, endpoint.internal_port))
        if expected != endpoint:
            raise ContractError("preview endpoint is not registered by this provider")
        if (
            grant.run_id != endpoint.run_id
            or grant.computer_id != endpoint.computer_id
            or grant.endpoint_id != endpoint.endpoint_id
            or grant.internal_port != endpoint.internal_port
        ):
            raise ContractError("trusted share grant does not bind this preview endpoint")
        if not (grant.issued_at <= now < grant.expires_at):
            raise ContractError("trusted preview share grant is not currently valid")
        if grant.expires_at > computer.expires_at:
            raise ContractError("preview share grant cannot outlive Agent Computer")
        key = (computer.computer_id, endpoint.internal_port)
        existing_id = self._active_share_by_key.get(key)
        if existing_id is not None and self._shares[existing_id].active:
            raise ContractError("preview port already has an active share lease")
        digest = hashlib.sha256(f"{grant.grant_id}:{endpoint.endpoint_id}".encode("utf-8")).hexdigest()[:24]
        lease = PreviewShareLease(
            share_id=f"share:{digest}",
            grant_id=grant.grant_id,
            run_id=endpoint.run_id,
            computer_id=endpoint.computer_id,
            endpoint_id=endpoint.endpoint_id,
            internal_port=endpoint.internal_port,
            external_ref=f"temporary-share:{digest}",
            issued_at=now,
            expires_at=min(grant.expires_at, computer.expires_at),
        )
        self._shares[lease.share_id] = lease
        self._active_share_by_key[key] = lease.share_id
        return lease

    def release(self, share_id: str, *, now: datetime) -> PreviewShareLease:
        share_id = _ref(share_id, "share_id")
        now = _aware(now, "now")
        try:
            lease = self._shares[share_id]
        except KeyError as exc:
            raise ContractError("preview share lease not found") from exc
        if not lease.active:
            raise ContractError("preview share lease is already terminal")
        if now < lease.issued_at:
            raise ContractError("release time cannot precede share issue time")
        state = PreviewShareLeaseState.EXPIRED if now >= lease.expires_at else PreviewShareLeaseState.RELEASED
        terminal = replace(lease, state=state)
        self._shares[share_id] = terminal
        self._active_share_by_key.pop((lease.computer_id, lease.internal_port), None)
        return terminal


REAL_PREVIEW_PORT_PROVIDER_CONFIGURED = False
PUBLIC_PREVIEW_BY_DEFAULT = False
PERMANENT_PUBLIC_PREVIEW_SUPPORTED = False
