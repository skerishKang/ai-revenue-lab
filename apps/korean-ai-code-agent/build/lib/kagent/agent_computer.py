from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

from .contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLease,
    SandboxLeaseState,
)


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class AgentComputerLeaseState(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class AgentComputerRequest:
    request_id: str
    run_id: str
    sandbox_lease_id: str
    workspace_ref: str
    browser_required: bool
    requested_at: datetime
    ttl_seconds: int = 900

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "sandbox_lease_id", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.browser_required, bool):
            raise ContractError("browser_required must be boolean")
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if isinstance(self.ttl_seconds, bool) or not isinstance(self.ttl_seconds, int) or not 60 <= self.ttl_seconds <= 3600:
            raise ContractError("ttl_seconds must be between 60 and 3600")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "sandbox_lease_id": self.sandbox_lease_id,
            "workspace_ref": self.workspace_ref,
            "browser_required": self.browser_required,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "ttl_seconds": self.ttl_seconds,
            "raw_credentials": False,
            "provider_endpoint": False,
            "host_mount": False,
            "runtime_socket": False,
        }


@dataclass(frozen=True, slots=True)
class AgentComputerLease:
    computer_id: str
    request_id: str
    run_id: str
    sandbox_lease_id: str
    workspace_ref: str
    browser_session_ref: str | None
    issued_at: datetime
    expires_at: datetime
    state: AgentComputerLeaseState = AgentComputerLeaseState.ACTIVE

    def __post_init__(self) -> None:
        for field_name in ("computer_id", "request_id", "run_id", "sandbox_lease_id", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.browser_session_ref is not None:
            object.__setattr__(self, "browser_session_ref", _ref(self.browser_session_ref, "browser_session_ref"))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 3600:
            raise ContractError("Agent Computer lease lifetime must be positive and at most 3600 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if not isinstance(self.state, AgentComputerLeaseState):
            try:
                object.__setattr__(self, "state", AgentComputerLeaseState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Agent Computer lease state") from exc

    @property
    def active(self) -> bool:
        return self.state is AgentComputerLeaseState.ACTIVE

    def safe_dict(self) -> dict[str, Any]:
        return {
            "computer_id": self.computer_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "sandbox_lease_id": self.sandbox_lease_id,
            "workspace_ref": self.workspace_ref,
            "browser_session_ref": self.browser_session_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
            "isolated_workspace": True,
            "cross_run_reuse": False,
            "allocation_implies_p01_started": False,
            "raw_credentials": False,
        }


class AgentComputerPort(Protocol):
    def allocate(self, request: AgentComputerRequest, *, sandbox_lease: SandboxLease) -> AgentComputerLease:
        ...

    def release(self, computer_id: str, *, now: datetime) -> AgentComputerLease:
        ...


class UnconfiguredAgentComputerPort:
    def allocate(self, request: AgentComputerRequest, *, sandbox_lease: SandboxLease) -> AgentComputerLease:
        raise ContractError("Agent Computer provider is not configured")

    def release(self, computer_id: str, *, now: datetime) -> AgentComputerLease:
        raise ContractError("Agent Computer provider is not configured")


class DeterministicFakeAgentComputerPort:
    def __init__(self) -> None:
        self._by_id: dict[str, AgentComputerLease] = {}
        self._active_by_run: dict[str, str] = {}
        self._used_workspace_refs: set[str] = set()
        self._used_browser_refs: set[str] = set()

    def allocate(self, request: AgentComputerRequest, *, sandbox_lease: SandboxLease) -> AgentComputerLease:
        if not isinstance(request, AgentComputerRequest):
            raise ContractError("request must be AgentComputerRequest")
        if not isinstance(sandbox_lease, SandboxLease):
            raise ContractError("sandbox_lease must be SandboxLease")
        if sandbox_lease.run_id != request.run_id or sandbox_lease.lease_id != request.sandbox_lease_id:
            raise ContractError("Agent Computer request does not match sandbox lease")
        if sandbox_lease.execution_mode is not ExecutionMode.CLOUD:
            raise ContractError("Agent Computer M1 requires cloud sandbox lease")
        if sandbox_lease.network_policy is not NetworkPolicy.OFF:
            raise ContractError("Agent Computer M1 requires network-off sandbox lease")
        if sandbox_lease.state is not SandboxLeaseState.RESERVED:
            raise ContractError("Agent Computer requires an active reserved sandbox lease")
        if request.requested_at < sandbox_lease.created_at or request.requested_at >= sandbox_lease.expires_at:
            raise ContractError("Agent Computer request time is outside sandbox lease")
        requested_expiry = request.requested_at + timedelta(seconds=request.ttl_seconds)
        if requested_expiry > sandbox_lease.expires_at:
            raise ContractError("Agent Computer TTL cannot outlive sandbox lease")
        if request.run_id in self._active_by_run:
            current = self._by_id[self._active_by_run[request.run_id]]
            if current.active:
                raise ContractError("run already has an active Agent Computer")
        if request.workspace_ref in self._used_workspace_refs:
            raise ContractError("workspace_ref cannot be reused across Agent Computers")

        digest = hashlib.sha256(
            f"{request.run_id}:{request.sandbox_lease_id}:{request.workspace_ref}:{request.request_id}".encode("utf-8")
        ).hexdigest()[:24]
        computer_id = f"computer:{digest}"
        browser_ref = f"browser:{digest}" if request.browser_required else None
        if browser_ref is not None and browser_ref in self._used_browser_refs:
            raise ContractError("browser session cannot be reused")
        lease = AgentComputerLease(
            computer_id=computer_id,
            request_id=request.request_id,
            run_id=request.run_id,
            sandbox_lease_id=request.sandbox_lease_id,
            workspace_ref=request.workspace_ref,
            browser_session_ref=browser_ref,
            issued_at=request.requested_at,
            expires_at=requested_expiry,
        )
        self._by_id[computer_id] = lease
        self._active_by_run[request.run_id] = computer_id
        self._used_workspace_refs.add(request.workspace_ref)
        if browser_ref is not None:
            self._used_browser_refs.add(browser_ref)
        return lease

    def release(self, computer_id: str, *, now: datetime) -> AgentComputerLease:
        computer_id = _ref(computer_id, "computer_id")
        now = _aware(now, "now")
        try:
            lease = self._by_id[computer_id]
        except KeyError as exc:
            raise ContractError("Agent Computer not found") from exc
        if not lease.active:
            raise ContractError("Agent Computer is already terminal")
        if now < lease.issued_at:
            raise ContractError("release time cannot precede issue time")
        state = AgentComputerLeaseState.EXPIRED if now >= lease.expires_at else AgentComputerLeaseState.RELEASED
        terminal = AgentComputerLease(
            computer_id=lease.computer_id,
            request_id=lease.request_id,
            run_id=lease.run_id,
            sandbox_lease_id=lease.sandbox_lease_id,
            workspace_ref=lease.workspace_ref,
            browser_session_ref=lease.browser_session_ref,
            issued_at=lease.issued_at,
            expires_at=lease.expires_at,
            state=state,
        )
        self._by_id[computer_id] = terminal
        self._active_by_run.pop(lease.run_id, None)
        return terminal


REAL_AGENT_COMPUTER_PROVIDER_CONFIGURED = False
AGENT_COMPUTER_ALLOCATION_IMPLIES_P01_START = False
CROSS_RUN_COMPUTER_REUSE_SUPPORTED = False
