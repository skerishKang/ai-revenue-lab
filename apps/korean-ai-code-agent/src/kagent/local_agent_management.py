from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile
from .local_agent_pairing import DeviceBinding, DeviceLifecycle
from .local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPolicyMode,
    RootPermissionPolicy,
    revoke_root,
)
from .windows_local_executor import (
    UnconfiguredWindowsExecutionAuthorizationPort,
    WindowsExecutableProfile,
    WindowsExecutionAuthorizationPort,
    WindowsExecutionReceipt,
    WindowsSubprocessLocalAgentRuntime,
    WorktreeStatePort,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_MAX_DEVICE_NAME_CHARS = 120
_MAX_ACTIVITY = 20
_ROOT_SCOPED = frozenset(
    {
        LocalCapability.FILESYSTEM_READ,
        LocalCapability.FILESYSTEM_WRITE,
        LocalCapability.FILESYSTEM_DELETE,
        LocalCapability.PROCESS_EXECUTE,
        LocalCapability.GIT_READ,
        LocalCapability.GIT_WRITE_LOCAL,
        LocalCapability.GIT_COMMIT,
        LocalCapability.GIT_NETWORK,
    }
)


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _device_name(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("device_name must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_DEVICE_NAME_CHARS or any(ord(ch) < 32 for ch in normalized):
        raise ContractError("device_name must be bounded printable text")
    return normalized


@dataclass(frozen=True, slots=True)
class TrustedLocalAgentManagementAuthority:
    authority_ref: str
    actor_ref: str
    workspace_ref: str
    device_id: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("authority_ref", "actor_ref", "workspace_ref", "device_id"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 3600:
            raise ContractError("management authority lifetime must be positive and at most one hour")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def require_current(self, *, workspace_ref: str, device_id: str, now: datetime) -> None:
        now = _aware(now, "now")
        if self.workspace_ref != _ref(workspace_ref, "workspace_ref") or self.device_id != _ref(device_id, "device_id"):
            raise ContractError("management authority workspace/device mismatch")
        if not (self.issued_at <= now < self.expires_at):
            raise ContractError("management authority is not current")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "authority_ref": self.authority_ref,
            "actor_ref": self.actor_ref,
            "workspace_ref": self.workspace_ref,
            "device_id": self.device_id,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "client_asserted_authority": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAgentActivitySummary:
    request_id: str
    run_id: str
    root_ref: str
    executable_profile_ref: str
    termination: str
    started_at: datetime
    ended_at: datetime
    exit_code: int | None
    dirty_worktree_before: bool
    dirty_worktree_after: bool

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "root_ref", "executable_profile_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.termination not in {"exited", "cancelled", "timed_out"}:
            raise ContractError("invalid Local Agent activity termination")
        started = _aware(self.started_at, "started_at")
        ended = _aware(self.ended_at, "ended_at")
        if ended < started:
            raise ContractError("activity ended_at cannot precede started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "ended_at", ended)
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)):
            raise ContractError("activity exit_code must be an integer or None")
        if not isinstance(self.dirty_worktree_before, bool) or not isinstance(self.dirty_worktree_after, bool):
            raise ContractError("activity dirty-worktree flags must be boolean")

    @classmethod
    def from_execution_receipt(cls, receipt: WindowsExecutionReceipt) -> "LocalAgentActivitySummary":
        if not isinstance(receipt, WindowsExecutionReceipt):
            raise ContractError("receipt must be WindowsExecutionReceipt")
        result = receipt.result
        return cls(
            request_id=result.request_id,
            run_id=result.run_id,
            root_ref=result.root_ref,
            executable_profile_ref=receipt.executable_profile_ref,
            termination=receipt.termination.value,
            started_at=result.started_at,
            ended_at=result.ended_at,
            exit_code=result.exit_code,
            dirty_worktree_before=result.dirty_worktree_before,
            dirty_worktree_after=result.dirty_worktree_after,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "root_ref": self.root_ref,
            "executable_profile_ref": self.executable_profile_ref,
            "termination": self.termination,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "ended_at": self.ended_at.isoformat().replace("+00:00", "Z"),
            "exit_code": self.exit_code,
            "dirty_worktree_before": self.dirty_worktree_before,
            "dirty_worktree_after": self.dirty_worktree_after,
            "raw_argv": False,
            "stdout": False,
            "stderr": False,
            "authorization_payload": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAgentManagementSnapshot:
    device_name: str
    device: LocalAgentDeviceProfile
    binding: DeviceBinding
    permissions: DevicePermissionProfile
    recent_activity: tuple[LocalAgentActivitySummary, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_name", _device_name(self.device_name))
        if not isinstance(self.device, LocalAgentDeviceProfile):
            raise ContractError("device must be LocalAgentDeviceProfile")
        if not isinstance(self.binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        if not isinstance(self.permissions, DevicePermissionProfile):
            raise ContractError("permissions must be DevicePermissionProfile")
        if self.binding.device_id != self.device.device_id or self.permissions.device_id != self.device.device_id:
            raise ContractError("Local Agent management device correlation mismatch")
        if self.binding.workspace_ref != self.device.workspace_ref or self.permissions.workspace_ref != self.device.workspace_ref:
            raise ContractError("Local Agent management workspace correlation mismatch")
        if not isinstance(self.recent_activity, tuple) or len(self.recent_activity) > _MAX_ACTIVITY:
            raise ContractError("recent_activity must contain at most 20 entries")
        if not all(isinstance(item, LocalAgentActivitySummary) for item in self.recent_activity):
            raise ContractError("recent_activity must contain LocalAgentActivitySummary values")
        known_roots = {root.root_ref for root in self.device.roots}
        if any(item.root_ref not in known_roots for item in self.recent_activity):
            raise ContractError("recent activity references an unknown selected root")

    def safe_dict(self) -> dict[str, Any]:
        root_paths = {root.root_ref: root.windows_path for root in self.device.roots}
        root_policies = []
        for root in self.permissions.roots:
            root_policies.append(
                {
                    "root_ref": root.root_ref,
                    "windows_path": root_paths.get(root.root_ref),
                    "capabilities": [
                        {"capability": rule.capability.value, "mode": rule.mode.value}
                        for rule in root.rules
                    ],
                }
            )
        return {
            "contract_version": "claw-local-agent-management.v1",
            "device_id": self.device.device_id,
            "device_name": self.device_name,
            "workspace_ref": self.device.workspace_ref,
            "platform": self.device.platform.value,
            "status": self.binding.state.value,
            "roots": root_policies,
            "global_capabilities": [
                {"capability": rule.capability.value, "mode": rule.mode.value}
                for rule in self.permissions.global_rules
            ],
            "recent_activity": [item.safe_dict() for item in self.recent_activity],
            "device_revocable": self.binding.state is not DeviceLifecycle.REVOKED,
            "raw_device_credential": False,
            "raw_command_output": False,
            "execution_authority": False,
            "client_mutation_authority": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAgentManagementReceipt:
    operation_ref: str
    operation: str
    authority_ref: str
    actor_ref: str
    workspace_ref: str
    device_id: str
    target_ref: str
    applied_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "operation_ref",
            "authority_ref",
            "actor_ref",
            "workspace_ref",
            "device_id",
            "target_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.operation not in {"rename_device", "set_capability_policy", "revoke_root", "revoke_device"}:
            raise ContractError("invalid Local Agent management operation")
        object.__setattr__(self, "applied_at", _aware(self.applied_at, "applied_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "operation_ref": self.operation_ref,
            "operation": self.operation,
            "authority_ref": self.authority_ref,
            "actor_ref": self.actor_ref,
            "workspace_ref": self.workspace_ref,
            "device_id": self.device_id,
            "target_ref": self.target_ref,
            "applied_at": self.applied_at.isoformat().replace("+00:00", "Z"),
            "client_mutation_authority": False,
            "credential_payload": False,
        }


class DeviceRevocationPort(Protocol):
    def revoke(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        ...


def _receipt(
    *,
    operation_ref: str,
    operation: str,
    authority: TrustedLocalAgentManagementAuthority,
    target_ref: str,
    now: datetime,
) -> LocalAgentManagementReceipt:
    return LocalAgentManagementReceipt(
        operation_ref=operation_ref,
        operation=operation,
        authority_ref=authority.authority_ref,
        actor_ref=authority.actor_ref,
        workspace_ref=authority.workspace_ref,
        device_id=authority.device_id,
        target_ref=target_ref,
        applied_at=now,
    )


def rename_device(
    *,
    current_name: str,
    new_name: str,
    authority: TrustedLocalAgentManagementAuthority,
    device: LocalAgentDeviceProfile,
    operation_ref: str,
    now: datetime,
) -> tuple[str, LocalAgentManagementReceipt]:
    _device_name(current_name)
    new_name = _device_name(new_name)
    authority.require_current(workspace_ref=device.workspace_ref, device_id=device.device_id, now=now)
    return new_name, _receipt(
        operation_ref=operation_ref,
        operation="rename_device",
        authority=authority,
        target_ref=device.device_id,
        now=now,
    )


def set_capability_policy(
    *,
    permissions: DevicePermissionProfile,
    authority: TrustedLocalAgentManagementAuthority,
    capability: LocalCapability,
    mode: LocalPolicyMode,
    operation_ref: str,
    now: datetime,
    root_ref: str | None = None,
) -> tuple[DevicePermissionProfile, LocalAgentManagementReceipt]:
    if not isinstance(permissions, DevicePermissionProfile):
        raise ContractError("permissions must be DevicePermissionProfile")
    if not isinstance(capability, LocalCapability):
        raise ContractError("capability must be LocalCapability")
    if not isinstance(mode, LocalPolicyMode):
        raise ContractError("mode must be LocalPolicyMode")
    authority.require_current(
        workspace_ref=permissions.workspace_ref,
        device_id=permissions.device_id,
        now=now,
    )
    if capability is LocalCapability.ADMIN_ELEVATION and mode is not LocalPolicyMode.DENY:
        raise ContractError("admin elevation cannot be enabled by Local Agent management")

    if capability in _ROOT_SCOPED:
        if root_ref is None:
            raise ContractError("root-scoped capability policy requires root_ref")
        root_ref = _ref(root_ref, "root_ref")
        old_root = permissions.root_policy(root_ref)
        new_rules = tuple(
            CapabilityRule(rule.capability, mode if rule.capability is capability else rule.mode)
            for rule in old_root.rules
        )
        if not any(rule.capability is capability for rule in old_root.rules):
            new_rules = (*new_rules, CapabilityRule(capability, mode))
        new_root = RootPermissionPolicy(root_ref=root_ref, rules=new_rules)
        roots = tuple(new_root if item.root_ref == root_ref else item for item in permissions.roots)
        target_ref = f"root:{root_ref}:{capability.value}"
        updated = DevicePermissionProfile(
            device_id=permissions.device_id,
            workspace_ref=permissions.workspace_ref,
            roots=roots,
            global_rules=permissions.global_rules,
        )
    else:
        if root_ref is not None:
            raise ContractError("device-global capability policy must not carry root_ref")
        new_rules = tuple(
            CapabilityRule(rule.capability, mode if rule.capability is capability else rule.mode)
            for rule in permissions.global_rules
        )
        if not any(rule.capability is capability for rule in permissions.global_rules):
            new_rules = (*new_rules, CapabilityRule(capability, mode))
        target_ref = f"device:{capability.value}"
        updated = DevicePermissionProfile(
            device_id=permissions.device_id,
            workspace_ref=permissions.workspace_ref,
            roots=permissions.roots,
            global_rules=new_rules,
        )

    return updated, _receipt(
        operation_ref=operation_ref,
        operation="set_capability_policy",
        authority=authority,
        target_ref=target_ref,
        now=now,
    )


def revoke_selected_root(
    *,
    permissions: DevicePermissionProfile,
    authority: TrustedLocalAgentManagementAuthority,
    root_ref: str,
    operation_ref: str,
    now: datetime,
) -> tuple[DevicePermissionProfile, LocalAgentManagementReceipt]:
    authority.require_current(
        workspace_ref=permissions.workspace_ref,
        device_id=permissions.device_id,
        now=now,
    )
    root_ref = _ref(root_ref, "root_ref")
    updated = revoke_root(permissions, root_ref=root_ref)
    return updated, _receipt(
        operation_ref=operation_ref,
        operation="revoke_root",
        authority=authority,
        target_ref=root_ref,
        now=now,
    )


def revoke_device(
    *,
    binding: DeviceBinding,
    authority: TrustedLocalAgentManagementAuthority,
    revocation_port: DeviceRevocationPort,
    operation_ref: str,
    now: datetime,
) -> tuple[DeviceBinding, LocalAgentManagementReceipt]:
    if not isinstance(binding, DeviceBinding):
        raise ContractError("binding must be DeviceBinding")
    authority.require_current(workspace_ref=binding.workspace_ref, device_id=binding.device_id, now=now)
    if binding.state is DeviceLifecycle.REVOKED:
        raise ContractError("Local Agent device is already revoked")
    revoked = revocation_port.revoke(binding.binding_ref, now=now)
    if not isinstance(revoked, DeviceBinding):
        raise ContractError("device revocation port returned invalid binding")
    if (
        revoked.binding_ref != binding.binding_ref
        or revoked.device_id != binding.device_id
        or revoked.workspace_ref != binding.workspace_ref
        or revoked.state is not DeviceLifecycle.REVOKED
    ):
        raise ContractError("device revocation receipt correlation mismatch")
    return revoked, _receipt(
        operation_ref=operation_ref,
        operation="revoke_device",
        authority=authority,
        target_ref=binding.binding_ref,
        now=now,
    )


def compose_fail_closed_windows_runtime(
    *,
    device: LocalAgentDeviceProfile,
    executable_profiles: tuple[WindowsExecutableProfile, ...],
    authorization_port: WindowsExecutionAuthorizationPort | None,
    worktree_state_port: WorktreeStatePort | None,
) -> WindowsSubprocessLocalAgentRuntime:
    """Canonical product composition seam for real Windows execution.

    The underlying executor keeps deterministic test seams for unit coverage.
    Product composition is stricter: neither trusted authorization nor a real
    worktree-state probe may be omitted, so absence can never be interpreted as
    authorization or as a clean Git state.
    """
    if authorization_port is None or isinstance(authorization_port, UnconfiguredWindowsExecutionAuthorizationPort):
        raise ContractError("real Windows runtime composition requires trusted authorization")
    if worktree_state_port is None:
        raise ContractError("real Windows runtime composition requires explicit worktree-state probe")
    return WindowsSubprocessLocalAgentRuntime(
        device=device,
        executable_profiles=executable_profiles,
        authorization_port=authorization_port,
        worktree_state_port=worktree_state_port,
    )


DEVICE_STATUS_VISIBLE = True
ALLOWED_ROOTS_VISIBLE = True
CAPABILITY_POLICY_VISIBLE = True
RECENT_ACTIVITY_BOUNDED = True
CLIENT_MANAGEMENT_MUTATION_AUTHORITY = False
RAW_DEVICE_CREDENTIAL_VISIBLE = False
RAW_COMMAND_OUTPUT_VISIBLE = False
WORKTREE_PROBE_REQUIRED_FOR_REAL_RUNTIME = True
PRODUCTION_REMOTE_CONTROL_CLAIMED = False
