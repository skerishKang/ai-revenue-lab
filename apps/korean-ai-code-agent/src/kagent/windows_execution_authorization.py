from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
from typing import Any, Protocol

from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalOutcome,
    ApprovalPause,
    ContinuationStatus,
    VerifiedApprovalDecision,
    resolve_approval_pause,
    tool_invocation_digest,
)
from padiem_ai_core.tool_runtime import ToolInvocation

from .contracts import ContractError
from .local_agent import LocalCommandRequest
from .local_agent_permissions import (
    DevicePermissionProfile,
    LocalCapability,
    LocalEnforcementResult,
    LocalPermissionRequest,
    evaluate_local_permission,
)
from .windows_local_executor import (
    TrustedWindowsExecutionGrant,
    WindowsExecutableProfile,
    WindowsExecutionAuthorizationPort,
    command_request_fingerprint,
)

WINDOWS_EXECUTION_TOOL_ID = "local.process.execute"
_MAX_GRANT_TTL = timedelta(minutes=5)
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SUPPORTED_EXECUTION_CAPABILITIES = frozenset(
    {
        LocalCapability.PROCESS_EXECUTE,
        LocalCapability.NETWORK_OUTBOUND,
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


def _digest(value: str, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def windows_execution_tool_invocation(
    request: LocalCommandRequest,
    profile: WindowsExecutableProfile,
) -> ToolInvocation:
    """Build the exact canonical P01 invocation approved for a local process.

    The approval pause stores only ToolRuntime's invocation digest. Raw argv is
    present only transiently while constructing that canonical digest.
    """
    if not isinstance(request, LocalCommandRequest):
        raise ContractError("request must be LocalCommandRequest")
    if not isinstance(profile, WindowsExecutableProfile):
        raise ContractError("profile must be WindowsExecutableProfile")
    try:
        return ToolInvocation(
            tool_id=WINDOWS_EXECUTION_TOOL_ID,
            arguments={
                "request_id": request.request_id,
                "run_id": request.run_id,
                "device_id": request.device_id,
                "root_ref": request.root_ref,
                "argv": list(request.argv),
                "cwd_relative": request.cwd_relative,
                "requested_at": request.requested_at.isoformat(),
                "timeout_seconds": request.timeout_seconds,
                "command_fingerprint": command_request_fingerprint(request),
                "executable_profile_ref": profile.profile_ref,
                "required_capabilities": list(profile.required_capabilities),
                "shell": False,
                "admin_elevation": False,
            },
        )
    except ValueError as exc:
        raise ContractError("local process invocation cannot be represented by the canonical P01 ToolInvocation") from exc


@dataclass(frozen=True, slots=True)
class WindowsExecutionAuthorityEvidence:
    evidence_ref: str
    request_fingerprint: str
    permission_requests: tuple[LocalPermissionRequest, ...]
    approval_pause: ApprovalPause
    approval_decision: VerifiedApprovalDecision
    local_policy_ref: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        object.__setattr__(self, "local_policy_ref", _ref(self.local_policy_ref, "local_policy_ref"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if not isinstance(self.permission_requests, tuple) or not self.permission_requests:
            raise ContractError("permission_requests must be a non-empty tuple")
        if not all(isinstance(item, LocalPermissionRequest) for item in self.permission_requests):
            raise ContractError("permission_requests must contain LocalPermissionRequest values")
        capabilities = [item.capability for item in self.permission_requests]
        if len(capabilities) != len(set(capabilities)):
            raise ContractError("permission evidence must contain each capability exactly once")
        if not isinstance(self.approval_pause, ApprovalPause):
            raise ContractError("approval_pause must be canonical ApprovalPause")
        if not isinstance(self.approval_decision, VerifiedApprovalDecision):
            raise ContractError("approval_decision must be canonical VerifiedApprovalDecision")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-windows-execution-authority-evidence.v1",
            "evidence_ref": self.evidence_ref,
            "request_fingerprint": self.request_fingerprint,
            "permission_capabilities": sorted(item.capability.value for item in self.permission_requests),
            "approval_pause_id": self.approval_pause.pause_id,
            "approval_decision_id": self.approval_decision.decision_id,
            "local_policy_ref": self.local_policy_ref,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "client_permission_decision_authority": False,
            "raw_argv": False,
            "raw_credentials": False,
        }


class WindowsExecutionAuthorityEvidencePort(Protocol):
    def resolve(self, request_fingerprint: str) -> WindowsExecutionAuthorityEvidence:
        ...


class UnconfiguredWindowsExecutionAuthorityEvidencePort:
    def resolve(self, request_fingerprint: str) -> WindowsExecutionAuthorityEvidence:
        _digest(request_fingerprint, "request_fingerprint")
        raise ContractError("trusted Windows execution authority evidence is not configured")


class DeterministicWindowsExecutionAuthorityEvidencePort:
    """Network-free evidence source for conformance tests only."""

    def __init__(self, evidence: tuple[WindowsExecutionAuthorityEvidence, ...]) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ContractError("deterministic evidence port requires evidence")
        if not all(isinstance(item, WindowsExecutionAuthorityEvidence) for item in evidence):
            raise ContractError("deterministic evidence port contains invalid evidence")
        by_fingerprint = {item.request_fingerprint: item for item in evidence}
        if len(by_fingerprint) != len(evidence):
            raise ContractError("deterministic evidence fingerprints must be unique")
        self._evidence = by_fingerprint
        self.calls: list[str] = []

    def resolve(self, request_fingerprint: str) -> WindowsExecutionAuthorityEvidence:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        self.calls.append(fingerprint)
        try:
            return self._evidence[fingerprint]
        except KeyError as exc:
            raise ContractError("no trusted Windows execution authority evidence exists for this command") from exc


def _required_local_capabilities(profile: WindowsExecutableProfile) -> tuple[LocalCapability, ...]:
    if not isinstance(profile, WindowsExecutableProfile):
        raise ContractError("profile must be WindowsExecutableProfile")
    capabilities: list[LocalCapability] = []
    for ref in profile.required_capabilities:
        try:
            capability = LocalCapability(ref)
        except ValueError as exc:
            raise ContractError("Windows executable profile requires an unsupported local capability") from exc
        if capability not in _SUPPORTED_EXECUTION_CAPABILITIES:
            raise ContractError("Windows execution adapter supports process.execute and network.outbound only")
        capabilities.append(capability)
    if LocalCapability.PROCESS_EXECUTE not in capabilities:
        raise ContractError("Windows execution authorization requires process.execute")
    return tuple(capabilities)


def _validate_permission_request(
    *,
    request: LocalCommandRequest,
    fingerprint: str,
    permission_request: LocalPermissionRequest,
) -> None:
    if permission_request.run_id != request.run_id or permission_request.device_id != request.device_id:
        raise ContractError("local permission evidence run/device mismatch")
    if permission_request.target_ref != fingerprint:
        raise ContractError("local permission evidence is not bound to the exact command fingerprint")
    if permission_request.capability is LocalCapability.PROCESS_EXECUTE:
        if permission_request.root_ref != request.root_ref:
            raise ContractError("process.execute permission must bind the exact selected root")
    elif permission_request.capability is LocalCapability.NETWORK_OUTBOUND:
        if permission_request.root_ref is not None:
            raise ContractError("network.outbound permission must remain device-global")
    else:
        raise ContractError("unsupported local capability in Windows execution evidence")


def _validate_p01_approval(
    *,
    request: LocalCommandRequest,
    profile: WindowsExecutableProfile,
    evidence: WindowsExecutionAuthorityEvidence,
    now: datetime,
) -> None:
    pause = evidence.approval_pause
    decision = evidence.approval_decision
    if pause.run_id != request.run_id:
        raise ContractError("P01 approval pause run mismatch")
    if pause.tool_id != WINDOWS_EXECUTION_TOOL_ID:
        raise ContractError("P01 approval pause tool mismatch")
    invocation = windows_execution_tool_invocation(request, profile)
    if pause.invocation_sha256 != tool_invocation_digest(invocation):
        raise ContractError("P01 approval pause is not bound to the exact local command invocation")
    if not set(profile.required_capabilities).issubset(set(pause.approval_scope)):
        raise ContractError("P01 approval scope does not cover all executable capabilities")
    if decision.outcome is not ApprovalOutcome.APPROVED:
        raise ContractError("Windows execution requires an approved canonical P01 decision")
    try:
        state = resolve_approval_pause(pause, decision, now=now)
    except AgentApprovalError as exc:
        raise ContractError("canonical P01 approval evidence is invalid") from exc
    if state.status is not ContinuationStatus.RESUMABLE:
        raise ContractError("canonical P01 approval is denied or expired")


class P01LocalPermissionWindowsExecutionAuthorizationPort(WindowsExecutionAuthorizationPort):
    """Issue executor grants only from canonical P01 + recomputed local policy.

    This adapter is intentionally stricter than a local ALLOW rule: local process
    execution still requires canonical P01 approval. Local policy may deny or
    narrow authority, but can never mint or widen P01 approval.
    """

    def __init__(
        self,
        *,
        permission_profile: DevicePermissionProfile,
        evidence_port: WindowsExecutionAuthorityEvidencePort | None = None,
    ) -> None:
        if not isinstance(permission_profile, DevicePermissionProfile):
            raise ContractError("permission_profile must be DevicePermissionProfile")
        self._permission_profile = permission_profile
        self._evidence_port = evidence_port or UnconfiguredWindowsExecutionAuthorityEvidencePort()
        self._consumed_fingerprints: set[str] = set()
        self._consumed_decisions: set[str] = set()
        self._lock = threading.Lock()

    def authorize(
        self,
        *,
        request: LocalCommandRequest,
        profile: WindowsExecutableProfile,
        now: datetime,
    ) -> TrustedWindowsExecutionGrant:
        if not isinstance(request, LocalCommandRequest):
            raise ContractError("request must be LocalCommandRequest")
        if not isinstance(profile, WindowsExecutableProfile):
            raise ContractError("profile must be WindowsExecutableProfile")
        now = _aware(now, "now")
        if self._permission_profile.device_id != request.device_id:
            raise ContractError("local permission profile device mismatch")

        fingerprint = command_request_fingerprint(request)
        evidence = self._evidence_port.resolve(fingerprint)
        if not isinstance(evidence, WindowsExecutionAuthorityEvidence):
            raise ContractError("authority evidence port returned invalid evidence")
        if evidence.request_fingerprint != fingerprint:
            raise ContractError("authority evidence command fingerprint mismatch")
        if evidence.expires_at <= now:
            raise ContractError("Windows execution authority evidence has expired")

        required = _required_local_capabilities(profile)
        requests_by_capability = {item.capability: item for item in evidence.permission_requests}
        if set(requests_by_capability) != set(required):
            raise ContractError("local permission evidence must exactly cover executable capabilities")

        for capability in required:
            permission_request = requests_by_capability[capability]
            _validate_permission_request(
                request=request,
                fingerprint=fingerprint,
                permission_request=permission_request,
            )
            decision = evaluate_local_permission(
                profile=self._permission_profile,
                request=permission_request,
            )
            if decision.result is LocalEnforcementResult.DENIED:
                raise ContractError(f"local policy denied {capability.value}")
            if decision.capability is not capability or decision.action_id != permission_request.action_id:
                raise ContractError("recomputed local permission decision correlation mismatch")

        _validate_p01_approval(
            request=request,
            profile=profile,
            evidence=evidence,
            now=now,
        )

        with self._lock:
            if fingerprint in self._consumed_fingerprints:
                raise ContractError("Windows execution command authorization has already been consumed")
            if evidence.approval_decision.decision_id in self._consumed_decisions:
                raise ContractError("canonical P01 approval decision has already been consumed for execution")
            self._consumed_fingerprints.add(fingerprint)
            self._consumed_decisions.add(evidence.approval_decision.decision_id)

        expires_at = min(evidence.expires_at, evidence.approval_pause.expires_at, now + _MAX_GRANT_TTL)
        if expires_at <= now:
            raise ContractError("Windows execution grant would already be expired")
        grant_payload = {
            "evidence_ref": evidence.evidence_ref,
            "request_fingerprint": fingerprint,
            "decision_id": evidence.approval_decision.decision_id,
            "local_policy_ref": evidence.local_policy_ref,
            "executable_profile_ref": profile.profile_ref,
        }
        encoded = json.dumps(grant_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        grant_ref = f"windows_grant_{hashlib.sha256(encoded).hexdigest()[:24]}"
        return TrustedWindowsExecutionGrant(
            grant_ref=grant_ref,
            request_fingerprint=fingerprint,
            device_id=request.device_id,
            root_ref=request.root_ref,
            executable_profile_ref=profile.profile_ref,
            capability_refs=tuple(item.value for item in required),
            p01_approval_ref=evidence.approval_decision.decision_id,
            local_policy_ref=evidence.local_policy_ref,
            expires_at=expires_at,
        )


REAL_WINDOWS_P01_PERMISSION_AUTHORIZATION_ADAPTER_IMPLEMENTED = True
CLIENT_PERMISSION_DECISION_AUTHORITY = False
P01_APPROVAL_AUTHORITY_DUPLICATED = False
LOCAL_POLICY_MAY_WIDEN_P01 = False
PRODUCTION_REMOTE_CONTROL_CLAIMED = False
