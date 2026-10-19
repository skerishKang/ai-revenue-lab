from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


class LocalCapability(str, Enum):
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    FILESYSTEM_DELETE = "filesystem.delete"
    PROCESS_EXECUTE = "process.execute"
    GIT_READ = "git.read"
    GIT_WRITE_LOCAL = "git.write_local"
    GIT_COMMIT = "git.commit"
    GIT_NETWORK = "git.network"
    BROWSER_OPEN = "browser.open"
    BROWSER_CONTROL = "browser.control"
    CLIPBOARD_READ = "clipboard.read"
    CLIPBOARD_WRITE = "clipboard.write"
    NETWORK_OUTBOUND = "network.outbound"
    ADMIN_ELEVATION = "admin.elevation"


class LocalPolicyMode(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class LocalEnforcementResult(str, Enum):
    LOCALLY_ALLOWED = "locally_allowed"
    REQUIRE_P01_APPROVAL = "require_p01_approval"
    DENIED = "denied"


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


@dataclass(frozen=True, slots=True)
class CapabilityRule:
    capability: LocalCapability
    mode: LocalPolicyMode

    def __post_init__(self) -> None:
        if not isinstance(self.capability, LocalCapability):
            try:
                object.__setattr__(self, "capability", LocalCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid local capability") from exc
        if not isinstance(self.mode, LocalPolicyMode):
            try:
                object.__setattr__(self, "mode", LocalPolicyMode(self.mode))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid local policy mode") from exc


@dataclass(frozen=True, slots=True)
class RootPermissionPolicy:
    root_ref: str
    rules: tuple[CapabilityRule, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_ref", _ref(self.root_ref, "root_ref"))
        if not isinstance(self.rules, tuple) or not self.rules:
            raise ContractError("root rules must be a non-empty tuple")
        if not all(isinstance(rule, CapabilityRule) for rule in self.rules):
            raise ContractError("root rules must contain CapabilityRule values")
        capabilities = [rule.capability for rule in self.rules]
        if any(capability not in _ROOT_SCOPED for capability in capabilities):
            raise ContractError("root policy contains a non-root capability")
        if len(set(capabilities)) != len(capabilities):
            raise ContractError("root capability rules must be unique")

    def mode_for(self, capability: LocalCapability) -> LocalPolicyMode:
        for rule in self.rules:
            if rule.capability is capability:
                return rule.mode
        return LocalPolicyMode.DENY


@dataclass(frozen=True, slots=True)
class DevicePermissionProfile:
    device_id: str
    workspace_ref: str
    roots: tuple[RootPermissionPolicy, ...]
    global_rules: tuple[CapabilityRule, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _ref(self.device_id, "device_id"))
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.roots, tuple) or not self.roots:
            raise ContractError("permission profile requires root policies")
        if not all(isinstance(root, RootPermissionPolicy) for root in self.roots):
            raise ContractError("roots must contain RootPermissionPolicy values")
        root_refs = [root.root_ref for root in self.roots]
        if len(set(root_refs)) != len(root_refs):
            raise ContractError("root permission refs must be unique")
        if not isinstance(self.global_rules, tuple):
            raise ContractError("global_rules must be a tuple")
        if not all(isinstance(rule, CapabilityRule) for rule in self.global_rules):
            raise ContractError("global_rules must contain CapabilityRule values")
        capabilities = [rule.capability for rule in self.global_rules]
        if any(capability in _ROOT_SCOPED for capability in capabilities):
            raise ContractError("global policy contains a root-scoped capability")
        if len(set(capabilities)) != len(capabilities):
            raise ContractError("global capability rules must be unique")

    def root_policy(self, root_ref: str) -> RootPermissionPolicy:
        root_ref = _ref(root_ref, "root_ref")
        for root in self.roots:
            if root.root_ref == root_ref:
                return root
        raise ContractError("root permission has been revoked or was never granted")

    def global_mode(self, capability: LocalCapability) -> LocalPolicyMode:
        for rule in self.global_rules:
            if rule.capability is capability:
                return rule.mode
        return LocalPolicyMode.DENY

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "workspace_ref": self.workspace_ref,
            "roots": [
                {
                    "root_ref": root.root_ref,
                    "rules": [
                        {"capability": rule.capability.value, "mode": rule.mode.value}
                        for rule in root.rules
                    ],
                }
                for root in self.roots
            ],
            "global_rules": [
                {"capability": rule.capability.value, "mode": rule.mode.value}
                for rule in self.global_rules
            ],
            "whole_pc_grant": False,
            "p01_authority_duplicated": False,
        }


@dataclass(frozen=True, slots=True)
class LocalPermissionRequest:
    action_id: str
    run_id: str
    device_id: str
    capability: LocalCapability
    target_ref: str
    root_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("action_id", "run_id", "device_id", "target_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.capability, LocalCapability):
            try:
                object.__setattr__(self, "capability", LocalCapability(self.capability))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid local capability") from exc
        if self.root_ref is not None:
            object.__setattr__(self, "root_ref", _ref(self.root_ref, "root_ref"))
        if self.capability in _ROOT_SCOPED and self.root_ref is None:
            raise ContractError("root-scoped capability requires root_ref")
        if self.capability not in _ROOT_SCOPED and self.root_ref is not None:
            raise ContractError("global capability must not carry root_ref")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "capability": self.capability.value,
            "target_ref": self.target_ref,
            "root_ref": self.root_ref,
            "client_approval_authority": False,
        }


@dataclass(frozen=True, slots=True)
class LocalPermissionDecision:
    action_id: str
    result: LocalEnforcementResult
    capability: LocalCapability
    root_ref: str | None
    p01_approval_required: bool
    local_policy_may_only_narrow: bool = True

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "result": self.result.value,
            "capability": self.capability.value,
            "root_ref": self.root_ref,
            "p01_approval_required": self.p01_approval_required,
            "local_policy_may_only_narrow": self.local_policy_may_only_narrow,
        }


def default_device_permission_profile(
    *,
    device: LocalAgentDeviceProfile,
) -> DevicePermissionProfile:
    if not isinstance(device, LocalAgentDeviceProfile):
        raise ContractError("device must be LocalAgentDeviceProfile")
    root_rules = (
        CapabilityRule(LocalCapability.FILESYSTEM_READ, LocalPolicyMode.ALLOW),
        CapabilityRule(LocalCapability.FILESYSTEM_WRITE, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.FILESYSTEM_DELETE, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.PROCESS_EXECUTE, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.GIT_READ, LocalPolicyMode.ALLOW),
        CapabilityRule(LocalCapability.GIT_WRITE_LOCAL, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.GIT_COMMIT, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.GIT_NETWORK, LocalPolicyMode.DENY),
    )
    roots = tuple(RootPermissionPolicy(root.root_ref, root_rules) for root in device.roots)
    global_rules = (
        CapabilityRule(LocalCapability.BROWSER_OPEN, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.BROWSER_CONTROL, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.CLIPBOARD_READ, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.CLIPBOARD_WRITE, LocalPolicyMode.ASK),
        CapabilityRule(LocalCapability.NETWORK_OUTBOUND, LocalPolicyMode.DENY),
        CapabilityRule(LocalCapability.ADMIN_ELEVATION, LocalPolicyMode.DENY),
    )
    return DevicePermissionProfile(
        device_id=device.device_id,
        workspace_ref=device.workspace_ref,
        roots=roots,
        global_rules=global_rules,
    )


def evaluate_local_permission(
    *,
    profile: DevicePermissionProfile,
    request: LocalPermissionRequest,
) -> LocalPermissionDecision:
    if not isinstance(profile, DevicePermissionProfile):
        raise ContractError("profile must be DevicePermissionProfile")
    if not isinstance(request, LocalPermissionRequest):
        raise ContractError("request must be LocalPermissionRequest")
    if profile.device_id != request.device_id:
        raise ContractError("permission request device mismatch")

    if request.capability in _ROOT_SCOPED:
        mode = profile.root_policy(request.root_ref or "").mode_for(request.capability)
    else:
        mode = profile.global_mode(request.capability)

    if mode is LocalPolicyMode.DENY:
        result = LocalEnforcementResult.DENIED
        approval_required = False
    elif mode is LocalPolicyMode.ASK:
        result = LocalEnforcementResult.REQUIRE_P01_APPROVAL
        approval_required = True
    else:
        result = LocalEnforcementResult.LOCALLY_ALLOWED
        approval_required = False

    return LocalPermissionDecision(
        action_id=request.action_id,
        result=result,
        capability=request.capability,
        root_ref=request.root_ref,
        p01_approval_required=approval_required,
    )


def revoke_root(
    profile: DevicePermissionProfile,
    *,
    root_ref: str,
) -> DevicePermissionProfile:
    root_ref = _ref(root_ref, "root_ref")
    remaining = tuple(root for root in profile.roots if root.root_ref != root_ref)
    if len(remaining) == len(profile.roots):
        raise ContractError("root permission not found")
    if not remaining:
        raise ContractError("cannot remove the final selected root from this profile")
    return DevicePermissionProfile(
        device_id=profile.device_id,
        workspace_ref=profile.workspace_ref,
        roots=remaining,
        global_rules=profile.global_rules,
    )


WHOLE_PC_GRANT_SUPPORTED = False
NETWORK_DEFAULT_ENABLED = False
GIT_PUSH_DEFAULT_ENABLED = False
ADMIN_ELEVATION_DEFAULT_ALLOWED = False
BROWSER_CONTROL_IMPLIED_BY_FILESYSTEM = False
P01_APPROVAL_AUTHORITY_DUPLICATED = False
LOCAL_AGENT_CAN_WEAKEN_P01_POLICY = False
LOCAL_AGENT_MAY_FAIL_CLOSED = True
UNBOUNDED_SECRET_ENV_INHERITANCE = False
