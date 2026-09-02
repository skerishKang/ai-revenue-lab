from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, TypeVar

from .security import redact_secrets


class ContractError(ValueError):
    pass


class ExecutionMode(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


class ClawRunStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class NetworkPolicy(str, Enum):
    OFF = "off"
    RESTRICTED = "restricted"


class ResourceClass(str, Enum):
    SMALL = "small"
    STANDARD = "standard"
    LARGE = "large"


class SandboxLeaseState(str, Enum):
    RESERVED = "reserved"
    RELEASED = "released"
    EXPIRED = "expired"


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EnumT = TypeVar("_EnumT", bound=Enum)


def _safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_ID_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} has an invalid identifier shape")
    return normalized


def _bounded_text(value: str, field_name: str, *, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ContractError(f"{field_name} is required")
    if len(normalized) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(normalized):
        raise ContractError(f"{field_name} contains control characters")
    return normalized


def _enum_member(enum_type: type[_EnumT], value: object, field_name: str) -> _EnumT:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(str(member.value) for member in enum_type)
        raise ContractError(f"{field_name} must be one of: {allowed}") from exc


def _bounded_int(value: int, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _strict_bool(value: bool, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be a boolean")
    return value


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ContractError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ClawTaskIntent:
    """Product-owned task handoff contract.

    It intentionally contains no provider/model credential, sandbox host, or
    execution endpoint field. Those authorities remain in their owning layers.
    """

    task_id: str
    task: str
    repository_ref: str
    execution_mode: ExecutionMode = ExecutionMode.LOCAL
    requested_revision: str | None = None
    source_surface: str = "cli"
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _safe_id(self.task_id, "task_id"))
        object.__setattr__(self, "task", _bounded_text(self.task, "task", limit=12_000))
        object.__setattr__(
            self,
            "repository_ref",
            _bounded_text(self.repository_ref, "repository_ref", limit=1_024),
        )
        object.__setattr__(
            self,
            "execution_mode",
            _enum_member(ExecutionMode, self.execution_mode, "execution_mode"),
        )
        object.__setattr__(
            self,
            "source_surface",
            _safe_id(self.source_surface, "source_surface"),
        )
        if self.requested_revision is not None:
            object.__setattr__(
                self,
                "requested_revision",
                _bounded_text(self.requested_revision, "requested_revision", limit=256),
            )
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", _safe_id(self.trace_id, "trace_id"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-task-intent.v1",
            "task_id": self.task_id,
            "task": redact_secrets(self.task),
            "repository_ref": redact_secrets(self.repository_ref),
            "execution_mode": self.execution_mode.value,
            "requested_revision": self.requested_revision,
            "source_surface": self.source_surface,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class SandboxLeaseRequest:
    run_id: str
    execution_mode: ExecutionMode
    repository_ref: str
    requested_revision: str | None = None
    resource_class: ResourceClass = ResourceClass.STANDARD
    ttl_seconds: int = 900
    network_policy: NetworkPolicy = NetworkPolicy.OFF
    writable_workspace: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "execution_mode",
            _enum_member(ExecutionMode, self.execution_mode, "execution_mode"),
        )
        object.__setattr__(
            self,
            "repository_ref",
            _bounded_text(self.repository_ref, "repository_ref", limit=1_024),
        )
        if self.requested_revision is not None:
            object.__setattr__(
                self,
                "requested_revision",
                _bounded_text(self.requested_revision, "requested_revision", limit=256),
            )
        object.__setattr__(
            self,
            "resource_class",
            _enum_member(ResourceClass, self.resource_class, "resource_class"),
        )
        object.__setattr__(
            self,
            "ttl_seconds",
            _bounded_int(self.ttl_seconds, "ttl_seconds", minimum=60, maximum=3_600),
        )
        object.__setattr__(
            self,
            "network_policy",
            _enum_member(NetworkPolicy, self.network_policy, "network_policy"),
        )
        object.__setattr__(
            self,
            "writable_workspace",
            _strict_bool(self.writable_workspace, "writable_workspace"),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "sandbox-lease-request.v1",
            "run_id": self.run_id,
            "execution_mode": self.execution_mode.value,
            "repository_ref": redact_secrets(self.repository_ref),
            "requested_revision": self.requested_revision,
            "resource_class": self.resource_class.value,
            "ttl_seconds": self.ttl_seconds,
            "network_policy": self.network_policy.value,
            "writable_workspace": self.writable_workspace,
        }


@dataclass(frozen=True, slots=True)
class SandboxLease:
    lease_id: str
    run_id: str
    execution_mode: ExecutionMode
    resource_class: ResourceClass
    network_policy: NetworkPolicy
    writable_workspace: bool
    created_at: datetime
    expires_at: datetime
    state: SandboxLeaseState = SandboxLeaseState.RESERVED

    def __post_init__(self) -> None:
        object.__setattr__(self, "lease_id", _safe_id(self.lease_id, "lease_id"))
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "execution_mode",
            _enum_member(ExecutionMode, self.execution_mode, "execution_mode"),
        )
        object.__setattr__(
            self,
            "resource_class",
            _enum_member(ResourceClass, self.resource_class, "resource_class"),
        )
        object.__setattr__(
            self,
            "network_policy",
            _enum_member(NetworkPolicy, self.network_policy, "network_policy"),
        )
        object.__setattr__(
            self,
            "writable_workspace",
            _strict_bool(self.writable_workspace, "writable_workspace"),
        )
        object.__setattr__(
            self,
            "state",
            _enum_member(SandboxLeaseState, self.state, "state"),
        )
        created = _aware_utc(self.created_at, "created_at")
        expires = _aware_utc(self.expires_at, "expires_at")
        if expires <= created:
            raise ContractError("expires_at must be after created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)

    def with_state(self, state: SandboxLeaseState) -> "SandboxLease":
        normalized_state = _enum_member(SandboxLeaseState, state, "state")
        if self.state is not SandboxLeaseState.RESERVED:
            raise ContractError("only a reserved lease may change state")
        if normalized_state is SandboxLeaseState.RESERVED:
            return self
        return SandboxLease(
            lease_id=self.lease_id,
            run_id=self.run_id,
            execution_mode=self.execution_mode,
            resource_class=self.resource_class,
            network_policy=self.network_policy,
            writable_workspace=self.writable_workspace,
            created_at=self.created_at,
            expires_at=self.expires_at,
            state=normalized_state,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "sandbox-lease.v1",
            "lease_id": self.lease_id,
            "run_id": self.run_id,
            "execution_mode": self.execution_mode.value,
            "resource_class": self.resource_class.value,
            "network_policy": self.network_policy.value,
            "writable_workspace": self.writable_workspace,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class RunProjection:
    run_id: str
    task_id: str
    status: ClawRunStatus
    execution_mode: ExecutionMode
    summary: str = ""
    changed_files: tuple[str, ...] = field(default_factory=tuple)
    approval_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(self, "task_id", _safe_id(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "status",
            _enum_member(ClawRunStatus, self.status, "status"),
        )
        object.__setattr__(
            self,
            "execution_mode",
            _enum_member(ExecutionMode, self.execution_mode, "execution_mode"),
        )
        object.__setattr__(
            self,
            "summary",
            _bounded_text(self.summary, "summary", limit=2_000, allow_empty=True),
        )
        if not isinstance(self.changed_files, tuple):
            raise ContractError("changed_files must be a tuple")
        if len(self.changed_files) > 100:
            raise ContractError("changed_files exceeds 100 entries")
        normalized_files: list[str] = []
        for path in self.changed_files:
            normalized_files.append(_bounded_text(path, "changed_file", limit=512))
        object.__setattr__(self, "changed_files", tuple(normalized_files))
        object.__setattr__(
            self,
            "approval_required",
            _strict_bool(self.approval_required, "approval_required"),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-run-projection.v1",
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "execution_mode": self.execution_mode.value,
            "summary": redact_secrets(self.summary),
            "changed_files": list(self.changed_files),
            "approval_required": self.approval_required,
            "terminal": self.status.terminal,
        }
