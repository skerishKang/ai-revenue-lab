from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
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
from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform
from .local_agent_permissions import (
    DevicePermissionProfile,
    LocalCapability,
    LocalEnforcementResult,
    LocalPermissionRequest,
    evaluate_local_permission,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_RELATIVE_PATH_CHARS = 1024
MAX_SELECTED_ROOT_FILE_BYTES = 1_048_576
_MAX_GRANT_TTL = timedelta(minutes=5)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class LocalFileOperation(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


_OPERATION_CAPABILITY = {
    LocalFileOperation.READ: LocalCapability.FILESYSTEM_READ,
    LocalFileOperation.WRITE: LocalCapability.FILESYSTEM_WRITE,
    LocalFileOperation.DELETE: LocalCapability.FILESYSTEM_DELETE,
}

_OPERATION_TOOL_ID = {
    LocalFileOperation.READ: "local.filesystem.read",
    LocalFileOperation.WRITE: "local.filesystem.write",
    LocalFileOperation.DELETE: "local.filesystem.delete",
}


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


def _relative_file_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_RELATIVE_PATH_CHARS:
        raise ContractError("path_relative must be a bounded relative Windows file path")
    raw = value.strip().replace("/", "\\")
    path = PureWindowsPath(raw)
    if path.is_absolute() or path.drive:
        raise ContractError("path_relative must remain inside the selected root")
    if any(part == ".." for part in path.parts):
        raise ContractError("path_relative traversal is not allowed")
    normalized_parts = tuple(part for part in path.parts if part not in {".", ""})
    if not normalized_parts:
        raise ContractError("path_relative must name a file")
    normalized = PureWindowsPath(*normalized_parts)
    if normalized.name in {"", ".", ".."}:
        raise ContractError("path_relative must name a file")
    return str(normalized)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _bounded_content(value: bytes | None, *, operation: LocalFileOperation) -> bytes | None:
    if operation is LocalFileOperation.WRITE:
        if not isinstance(value, bytes):
            raise ContractError("write operation requires bytes content")
        if len(value) > MAX_SELECTED_ROOT_FILE_BYTES:
            raise ContractError("write content exceeds selected-root file size limit")
        return value
    if value is not None:
        raise ContractError("read/delete operation must not carry content")
    return None


@dataclass(frozen=True, slots=True)
class LocalFileRequest:
    action_id: str
    run_id: str
    device_id: str
    root_ref: str
    operation: LocalFileOperation
    path_relative: str
    requested_at: datetime
    content: bytes | None = None

    def __post_init__(self) -> None:
        for field_name in ("action_id", "run_id", "device_id", "root_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.operation, LocalFileOperation):
            try:
                object.__setattr__(self, "operation", LocalFileOperation(self.operation))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid local file operation") from exc
        object.__setattr__(self, "path_relative", _relative_file_path(self.path_relative))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        object.__setattr__(self, "content", _bounded_content(self.content, operation=self.operation))

    @property
    def capability(self) -> LocalCapability:
        return _OPERATION_CAPABILITY[self.operation]

    @property
    def content_sha256(self) -> str | None:
        return _sha256_bytes(self.content) if self.content is not None else None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "root_ref": self.root_ref,
            "operation": self.operation.value,
            "path_relative": self.path_relative,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "content_bytes": len(self.content) if self.content is not None else 0,
            "content_sha256": self.content_sha256,
            "raw_content": False,
            "directory_enumeration": False,
            "recursive_delete": False,
        }


def file_request_fingerprint(request: LocalFileRequest) -> str:
    if not isinstance(request, LocalFileRequest):
        raise ContractError("request must be LocalFileRequest")
    payload = {
        "action_id": request.action_id,
        "run_id": request.run_id,
        "device_id": request.device_id,
        "root_ref": request.root_ref,
        "operation": request.operation.value,
        "path_relative": request.path_relative,
        "requested_at": request.requested_at.isoformat(),
        "content_bytes": len(request.content) if request.content is not None else 0,
        "content_sha256": request.content_sha256,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def windows_file_tool_invocation(request: LocalFileRequest) -> ToolInvocation:
    if not isinstance(request, LocalFileRequest):
        raise ContractError("request must be LocalFileRequest")
    try:
        return ToolInvocation(
            tool_id=_OPERATION_TOOL_ID[request.operation],
            arguments={
                "action_id": request.action_id,
                "run_id": request.run_id,
                "device_id": request.device_id,
                "root_ref": request.root_ref,
                "operation": request.operation.value,
                "path_relative": request.path_relative,
                "requested_at": request.requested_at.isoformat(),
                "request_fingerprint": file_request_fingerprint(request),
                "content_bytes": len(request.content) if request.content is not None else 0,
                "content_sha256": request.content_sha256,
                "directory_enumeration": False,
                "recursive_delete": False,
                "admin_elevation": False,
            },
        )
    except ValueError as exc:
        raise ContractError("local file request cannot be represented by canonical P01 ToolInvocation") from exc


@dataclass(frozen=True, slots=True)
class LocalFileResult:
    action_id: str
    run_id: str
    device_id: str
    root_ref: str
    operation: LocalFileOperation
    path_relative: str
    completed_at: datetime
    bytes_count: int
    content_sha256: str | None
    content: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for field_name in ("action_id", "run_id", "device_id", "root_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.operation, LocalFileOperation):
            try:
                object.__setattr__(self, "operation", LocalFileOperation(self.operation))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid local file result operation") from exc
        object.__setattr__(self, "path_relative", _relative_file_path(self.path_relative))
        object.__setattr__(self, "completed_at", _aware(self.completed_at, "completed_at"))
        if isinstance(self.bytes_count, bool) or not isinstance(self.bytes_count, int) or self.bytes_count < 0:
            raise ContractError("bytes_count must be a non-negative integer")
        if self.bytes_count > MAX_SELECTED_ROOT_FILE_BYTES:
            raise ContractError("file result exceeds selected-root file size limit")
        if self.content_sha256 is not None:
            object.__setattr__(self, "content_sha256", _digest(self.content_sha256, "content_sha256"))
        if self.operation is LocalFileOperation.READ:
            if not isinstance(self.content, bytes) or len(self.content) != self.bytes_count:
                raise ContractError("read result must carry exact bounded bytes content")
            if _sha256_bytes(self.content) != self.content_sha256:
                raise ContractError("read result content digest mismatch")
        elif self.content is not None:
            raise ContractError("write/delete result must not retain raw file content")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "root_ref": self.root_ref,
            "operation": self.operation.value,
            "path_relative": self.path_relative,
            "completed_at": self.completed_at.isoformat().replace("+00:00", "Z"),
            "bytes_count": self.bytes_count,
            "content_sha256": self.content_sha256,
            "raw_content": False,
        }


@dataclass(frozen=True, slots=True)
class TrustedWindowsFileGrant:
    grant_ref: str
    request_fingerprint: str
    device_id: str
    root_ref: str
    capability_ref: str
    p01_approval_ref: str
    local_policy_ref: str
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "grant_ref",
            "device_id",
            "root_ref",
            "capability_ref",
            "p01_approval_ref",
            "local_policy_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))

    def validate(self, *, request: LocalFileRequest, now: datetime) -> None:
        now = _aware(now, "now")
        if self.expires_at <= now:
            raise ContractError("Windows file grant has expired")
        if self.request_fingerprint != file_request_fingerprint(request):
            raise ContractError("Windows file grant request fingerprint mismatch")
        if self.device_id != request.device_id or self.root_ref != request.root_ref:
            raise ContractError("Windows file grant device/root mismatch")
        if self.capability_ref != request.capability.value:
            raise ContractError("Windows file grant capability mismatch")


class WindowsFileAuthorizationPort(Protocol):
    def authorize(self, *, request: LocalFileRequest, now: datetime) -> TrustedWindowsFileGrant:
        ...


class UnconfiguredWindowsFileAuthorizationPort:
    def authorize(self, *, request: LocalFileRequest, now: datetime) -> TrustedWindowsFileGrant:
        del request, now
        raise ContractError("trusted Windows file authorization is not configured")


class DeterministicFakeWindowsFileAuthorizationPort:
    """Network-free test adapter only; never production authority."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, *, request: LocalFileRequest, now: datetime) -> TrustedWindowsFileGrant:
        now = _aware(now, "now")
        self.calls.append(request.action_id)
        return TrustedWindowsFileGrant(
            grant_ref=f"fake_file_grant_{request.action_id}",
            request_fingerprint=file_request_fingerprint(request),
            device_id=request.device_id,
            root_ref=request.root_ref,
            capability_ref=request.capability.value,
            p01_approval_ref="fake_p01_approval",
            local_policy_ref="fake_local_policy",
            expires_at=now + timedelta(minutes=5),
        )


@dataclass(frozen=True, slots=True)
class WindowsFileAuthorityEvidence:
    evidence_ref: str
    request_fingerprint: str
    permission_request: LocalPermissionRequest
    approval_pause: ApprovalPause
    approval_decision: VerifiedApprovalDecision
    local_policy_ref: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ref", _ref(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        object.__setattr__(self, "local_policy_ref", _ref(self.local_policy_ref, "local_policy_ref"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if not isinstance(self.permission_request, LocalPermissionRequest):
            raise ContractError("permission_request must be LocalPermissionRequest")
        if not isinstance(self.approval_pause, ApprovalPause):
            raise ContractError("approval_pause must be canonical ApprovalPause")
        if not isinstance(self.approval_decision, VerifiedApprovalDecision):
            raise ContractError("approval_decision must be canonical VerifiedApprovalDecision")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-windows-file-authority-evidence.v1",
            "evidence_ref": self.evidence_ref,
            "request_fingerprint": self.request_fingerprint,
            "permission_capability": self.permission_request.capability.value,
            "approval_pause_id": self.approval_pause.pause_id,
            "approval_decision_id": self.approval_decision.decision_id,
            "local_policy_ref": self.local_policy_ref,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "client_permission_decision_authority": False,
            "raw_file_content": False,
            "raw_credentials": False,
        }


class WindowsFileAuthorityEvidencePort(Protocol):
    def resolve(self, request_fingerprint: str) -> WindowsFileAuthorityEvidence:
        ...


class UnconfiguredWindowsFileAuthorityEvidencePort:
    def resolve(self, request_fingerprint: str) -> WindowsFileAuthorityEvidence:
        _digest(request_fingerprint, "request_fingerprint")
        raise ContractError("trusted Windows file authority evidence is not configured")


class DeterministicWindowsFileAuthorityEvidencePort:
    """Network-free evidence source for conformance tests only."""

    def __init__(self, evidence: tuple[WindowsFileAuthorityEvidence, ...]) -> None:
        if not isinstance(evidence, tuple) or not evidence:
            raise ContractError("deterministic file evidence port requires evidence")
        if not all(isinstance(item, WindowsFileAuthorityEvidence) for item in evidence):
            raise ContractError("deterministic file evidence port contains invalid evidence")
        by_fingerprint = {item.request_fingerprint: item for item in evidence}
        if len(by_fingerprint) != len(evidence):
            raise ContractError("deterministic file evidence fingerprints must be unique")
        self._evidence = by_fingerprint
        self.calls: list[str] = []

    def resolve(self, request_fingerprint: str) -> WindowsFileAuthorityEvidence:
        fingerprint = _digest(request_fingerprint, "request_fingerprint")
        self.calls.append(fingerprint)
        try:
            return self._evidence[fingerprint]
        except KeyError as exc:
            raise ContractError("no trusted Windows file authority evidence exists for this request") from exc


def _validate_file_permission_request(
    *,
    request: LocalFileRequest,
    fingerprint: str,
    permission_request: LocalPermissionRequest,
) -> None:
    if permission_request.run_id != request.run_id or permission_request.device_id != request.device_id:
        raise ContractError("local file permission evidence run/device mismatch")
    if permission_request.target_ref != fingerprint:
        raise ContractError("local file permission evidence is not bound to the exact request fingerprint")
    if permission_request.capability is not request.capability:
        raise ContractError("local file permission evidence capability mismatch")
    if permission_request.root_ref != request.root_ref:
        raise ContractError("local file permission evidence must bind the exact selected root")


def _validate_file_p01_approval(
    *,
    request: LocalFileRequest,
    evidence: WindowsFileAuthorityEvidence,
    now: datetime,
) -> None:
    pause = evidence.approval_pause
    decision = evidence.approval_decision
    if pause.run_id != request.run_id:
        raise ContractError("P01 file approval pause run mismatch")
    invocation = windows_file_tool_invocation(request)
    if pause.tool_id != invocation.tool_id:
        raise ContractError("P01 file approval pause tool mismatch")
    if pause.invocation_sha256 != tool_invocation_digest(invocation):
        raise ContractError("P01 file approval pause is not bound to the exact file invocation")
    if request.capability.value not in set(pause.approval_scope):
        raise ContractError("P01 file approval scope does not cover the required capability")
    if decision.outcome is not ApprovalOutcome.APPROVED:
        raise ContractError("Windows file operation requires an approved canonical P01 decision")
    try:
        state = resolve_approval_pause(pause, decision, now=now)
    except AgentApprovalError as exc:
        raise ContractError("canonical P01 file approval evidence is invalid") from exc
    if state.status is not ContinuationStatus.RESUMABLE:
        raise ContractError("canonical P01 file approval is denied or expired")


class P01LocalPermissionWindowsFileAuthorizationPort(WindowsFileAuthorizationPort):
    """Issue one-shot file grants from canonical P01 + recomputed local policy."""

    def __init__(
        self,
        *,
        permission_profile: DevicePermissionProfile,
        evidence_port: WindowsFileAuthorityEvidencePort | None = None,
    ) -> None:
        if not isinstance(permission_profile, DevicePermissionProfile):
            raise ContractError("permission_profile must be DevicePermissionProfile")
        self._permission_profile = permission_profile
        self._evidence_port = evidence_port or UnconfiguredWindowsFileAuthorityEvidencePort()
        self._consumed_fingerprints: set[str] = set()
        self._consumed_decisions: set[str] = set()
        self._lock = threading.Lock()

    def authorize(self, *, request: LocalFileRequest, now: datetime) -> TrustedWindowsFileGrant:
        if not isinstance(request, LocalFileRequest):
            raise ContractError("request must be LocalFileRequest")
        now = _aware(now, "now")
        if self._permission_profile.device_id != request.device_id:
            raise ContractError("local file permission profile device mismatch")
        fingerprint = file_request_fingerprint(request)
        evidence = self._evidence_port.resolve(fingerprint)
        if not isinstance(evidence, WindowsFileAuthorityEvidence):
            raise ContractError("file authority evidence port returned invalid evidence")
        if evidence.request_fingerprint != fingerprint:
            raise ContractError("file authority evidence fingerprint mismatch")
        if evidence.expires_at <= now:
            raise ContractError("Windows file authority evidence has expired")

        _validate_file_permission_request(
            request=request,
            fingerprint=fingerprint,
            permission_request=evidence.permission_request,
        )
        decision = evaluate_local_permission(
            profile=self._permission_profile,
            request=evidence.permission_request,
        )
        if decision.result is LocalEnforcementResult.DENIED:
            raise ContractError(f"local policy denied {request.capability.value}")
        if decision.capability is not request.capability or decision.action_id != evidence.permission_request.action_id:
            raise ContractError("recomputed local file permission decision correlation mismatch")

        _validate_file_p01_approval(request=request, evidence=evidence, now=now)

        with self._lock:
            if fingerprint in self._consumed_fingerprints:
                raise ContractError("Windows file authorization has already been consumed")
            if evidence.approval_decision.decision_id in self._consumed_decisions:
                raise ContractError("canonical P01 approval decision has already been consumed for file access")
            self._consumed_fingerprints.add(fingerprint)
            self._consumed_decisions.add(evidence.approval_decision.decision_id)

        expires_at = min(evidence.expires_at, evidence.approval_pause.expires_at, now + _MAX_GRANT_TTL)
        if expires_at <= now:
            raise ContractError("Windows file grant would already be expired")
        grant_payload = {
            "evidence_ref": evidence.evidence_ref,
            "request_fingerprint": fingerprint,
            "decision_id": evidence.approval_decision.decision_id,
            "local_policy_ref": evidence.local_policy_ref,
            "capability_ref": request.capability.value,
        }
        encoded = json.dumps(grant_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        grant_ref = f"windows_file_grant_{hashlib.sha256(encoded).hexdigest()[:24]}"
        return TrustedWindowsFileGrant(
            grant_ref=grant_ref,
            request_fingerprint=fingerprint,
            device_id=request.device_id,
            root_ref=request.root_ref,
            capability_ref=request.capability.value,
            p01_approval_ref=evidence.approval_decision.decision_id,
            local_policy_ref=evidence.local_policy_ref,
            expires_at=expires_at,
        )


def _require_file_request_not_future(request: LocalFileRequest, *, now: datetime) -> None:
    if not isinstance(request, LocalFileRequest):
        raise ContractError("request must be LocalFileRequest")
    now = _aware(now, "now")
    if request.requested_at > now:
        raise ContractError("file request cannot be future-dated")


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ContractError("selected-root path metadata is unavailable") from exc
    if path.is_symlink():
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT)


def _assert_no_reparse_descendants(root: Path, candidate: Path, *, include_candidate: bool) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError("file path escapes the selected root") from exc
    parts = relative.parts if include_candidate else relative.parts[:-1]
    current = root
    for part in parts:
        current = current / part
        if not os.path.lexists(current):
            raise ContractError("selected-root file path parent does not exist")
        if _is_reparse_or_symlink(current):
            raise ContractError("file path crosses a symlink or reparse point")


def _root_path(device: LocalAgentDeviceProfile, root_ref: str) -> Path:
    if not isinstance(device, LocalAgentDeviceProfile) or device.platform is not LocalAgentPlatform.WINDOWS:
        raise ContractError("Windows selected-root file runtime requires a Windows Local Agent device")
    root = Path(device.root(root_ref).windows_path).resolve(strict=True)
    if not root.is_dir():
        raise ContractError("selected root must be an existing directory")
    return root


def _lexical_target(root: Path, path_relative: str) -> Path:
    relative = _relative_file_path(path_relative)
    return root / Path(relative.replace("\\", os.sep))


def _ensure_contained(root: Path, candidate: Path) -> None:
    try:
        common = os.path.commonpath((str(root), str(candidate)))
    except ValueError as exc:
        raise ContractError("file path is outside the selected root") from exc
    if os.path.normcase(common) != os.path.normcase(str(root)):
        raise ContractError("file path escapes the selected root")


def _existing_file_target(device: LocalAgentDeviceProfile, request: LocalFileRequest) -> Path:
    root = _root_path(device, request.root_ref)
    lexical = _lexical_target(root, request.path_relative)
    _assert_no_reparse_descendants(root, lexical, include_candidate=True)
    try:
        candidate = lexical.resolve(strict=True)
    except OSError as exc:
        raise ContractError("selected-root file does not exist") from exc
    _ensure_contained(root, candidate)
    if not candidate.is_file():
        raise ContractError("selected-root target must be a regular file")
    return candidate


def _write_file_target(device: LocalAgentDeviceProfile, request: LocalFileRequest) -> Path:
    root = _root_path(device, request.root_ref)
    lexical = _lexical_target(root, request.path_relative)
    _assert_no_reparse_descendants(root, lexical, include_candidate=False)
    try:
        parent = lexical.parent.resolve(strict=True)
    except OSError as exc:
        raise ContractError("selected-root write parent does not exist") from exc
    _ensure_contained(root, parent)
    if not parent.is_dir():
        raise ContractError("selected-root write parent must be a directory")
    target = parent / lexical.name
    _ensure_contained(root, target)
    if os.path.lexists(target):
        if _is_reparse_or_symlink(target):
            raise ContractError("write target must not be a symlink or reparse point")
        if target.is_dir():
            raise ContractError("write target must be a file, not a directory")
    return target


def _read_bounded(target: Path) -> bytes:
    try:
        if target.stat().st_size > MAX_SELECTED_ROOT_FILE_BYTES:
            raise ContractError("selected-root read exceeds file size limit")
        with target.open("rb") as handle:
            content = handle.read(MAX_SELECTED_ROOT_FILE_BYTES + 1)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("selected-root file read failed") from exc
    if len(content) > MAX_SELECTED_ROOT_FILE_BYTES:
        raise ContractError("selected-root read exceeds file size limit")
    return content


def _atomic_write_bounded(target: Path, content: bytes) -> None:
    if len(content) > MAX_SELECTED_ROOT_FILE_BYTES:
        raise ContractError("selected-root write exceeds file size limit")
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".padiem-write-", dir=target.parent, delete=False) as handle:
            temp_path = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
    except OSError as exc:
        raise ContractError("selected-root file write failed") from exc
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


class WindowsSelectedRootFileRuntime:
    def __init__(
        self,
        *,
        device: LocalAgentDeviceProfile,
        authorization_port: WindowsFileAuthorizationPort | None = None,
    ) -> None:
        if not isinstance(device, LocalAgentDeviceProfile) or device.platform is not LocalAgentPlatform.WINDOWS:
            raise ContractError("Windows selected-root file runtime requires a Windows Local Agent device")
        self._device = device
        self._authorization = authorization_port or UnconfiguredWindowsFileAuthorizationPort()

    def perform(self, request: LocalFileRequest, *, now: datetime) -> LocalFileResult:
        if os.name != "nt":
            raise ContractError("real selected-root file I/O is Windows-only in Local Agent M1")
        now = _aware(now, "now")
        _require_file_request_not_future(request, now=now)
        if request.device_id != self._device.device_id:
            raise ContractError("file request does not match Local Agent device")
        self._device.root(request.root_ref)

        grant = self._authorization.authorize(request=request, now=now)
        if not isinstance(grant, TrustedWindowsFileGrant):
            raise ContractError("authorization port returned invalid Windows file grant")
        grant.validate(request=request, now=now)

        if request.operation is LocalFileOperation.READ:
            target = _existing_file_target(self._device, request)
            content = _read_bounded(target)
            return LocalFileResult(
                action_id=request.action_id,
                run_id=request.run_id,
                device_id=request.device_id,
                root_ref=request.root_ref,
                operation=request.operation,
                path_relative=request.path_relative,
                completed_at=datetime.now(timezone.utc),
                bytes_count=len(content),
                content_sha256=_sha256_bytes(content),
                content=content,
            )

        if request.operation is LocalFileOperation.WRITE:
            target = _write_file_target(self._device, request)
            content = request.content or b""
            _atomic_write_bounded(target, content)
            return LocalFileResult(
                action_id=request.action_id,
                run_id=request.run_id,
                device_id=request.device_id,
                root_ref=request.root_ref,
                operation=request.operation,
                path_relative=request.path_relative,
                completed_at=datetime.now(timezone.utc),
                bytes_count=len(content),
                content_sha256=_sha256_bytes(content),
            )

        target = _existing_file_target(self._device, request)
        try:
            size = target.stat().st_size
            target.unlink()
        except OSError as exc:
            raise ContractError("selected-root file delete failed") from exc
        return LocalFileResult(
            action_id=request.action_id,
            run_id=request.run_id,
            device_id=request.device_id,
            root_ref=request.root_ref,
            operation=request.operation,
            path_relative=request.path_relative,
            completed_at=datetime.now(timezone.utc),
            bytes_count=min(size, MAX_SELECTED_ROOT_FILE_BYTES),
            content_sha256=None,
        )


REAL_SELECTED_ROOT_FILE_IO_IMPLEMENTED = True
FILESYSTEM_READ_IMPLEMENTED = True
FILESYSTEM_WRITE_IMPLEMENTED = True
FILESYSTEM_DELETE_FILE_ONLY = True
CANONICAL_P01_APPROVAL_REUSED = True
SECOND_APPROVAL_AUTHORITY = False
DIRECTORY_ENUMERATION_SUPPORTED = False
RECURSIVE_DELETE_SUPPORTED = False
RAW_HOST_CREDENTIAL_DISCOVERY = False
ADMIN_ELEVATION_SUPPORTED = False
PRODUCTION_REMOTE_CONTROL_CLAIMED = False
