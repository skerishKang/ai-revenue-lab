from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import threading
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalCommandResult

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_CAPTURE_CHARS = 8193
_BLOCKED_EXECUTABLE_NAMES = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "wscript.exe",
        "cscript.exe",
        "mshta.exe",
        "rundll32.exe",
    }
)
_BLOCKED_SCRIPT_SUFFIXES = frozenset({".bat", ".cmd", ".ps1", ".vbs", ".wsf", ".hta"})
_SAFE_ENV_NAMES = ("SystemRoot", "WINDIR", "SystemDrive", "TEMP", "TMP")


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


def _windows_executable(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ContractError("executable_path must be a bounded absolute Windows path")
    normalized = value.strip().replace("/", "\\")
    path = PureWindowsPath(normalized)
    if not path.is_absolute() or not path.drive or path.drive.startswith("\\"):
        raise ContractError("executable_path must be an absolute local Windows path")
    name = path.name.casefold()
    if name in _BLOCKED_EXECUTABLE_NAMES or path.suffix.casefold() in _BLOCKED_SCRIPT_SUFFIXES:
        raise ContractError("shell and script-host executables are prohibited")
    return str(path)


def command_request_fingerprint(request: LocalCommandRequest) -> str:
    if not isinstance(request, LocalCommandRequest):
        raise ContractError("request must be LocalCommandRequest")
    payload = {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "device_id": request.device_id,
        "root_ref": request.root_ref,
        "argv": list(request.argv),
        "cwd_relative": request.cwd_relative,
        "requested_at": request.requested_at.isoformat(),
        "timeout_seconds": request.timeout_seconds,
        "shell": False,
        "admin_elevation": False,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_request_not_future(request: LocalCommandRequest, *, now: datetime) -> None:
    if not isinstance(request, LocalCommandRequest):
        raise ContractError("request must be LocalCommandRequest")
    now = _aware(now, "now")
    requested_at = _aware(request.requested_at, "requested_at")
    if requested_at > now:
        raise ContractError("command request cannot be future-dated")


@dataclass(frozen=True, slots=True)
class WindowsExecutableProfile:
    profile_ref: str
    executable_path: str
    required_capabilities: tuple[str, ...] = ("process.execute",)
    may_access_network: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_ref", _ref(self.profile_ref, "profile_ref"))
        object.__setattr__(self, "executable_path", _windows_executable(self.executable_path))
        if not isinstance(self.required_capabilities, tuple) or not self.required_capabilities:
            raise ContractError("required_capabilities must be a non-empty tuple")
        capabilities = tuple(_ref(item, "required_capability") for item in self.required_capabilities)
        if "process.execute" not in capabilities:
            raise ContractError("Windows executable profile must require process.execute")
        if len(capabilities) != len(set(capabilities)):
            raise ContractError("required_capabilities must be unique")
        if not isinstance(self.may_access_network, bool):
            raise ContractError("may_access_network must be boolean")
        if self.may_access_network and "network.outbound" not in capabilities:
            raise ContractError("network-capable executable profile must require network.outbound")
        object.__setattr__(self, "required_capabilities", capabilities)

    def matches(self, executable: str) -> bool:
        candidate = _windows_executable(executable)
        return candidate.casefold() == self.executable_path.casefold()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "profile_ref": self.profile_ref,
            "executable_path": self.executable_path,
            "required_capabilities": list(self.required_capabilities),
            "may_access_network": self.may_access_network,
            "shell": False,
            "admin_elevation": False,
        }


@dataclass(frozen=True, slots=True)
class TrustedWindowsExecutionGrant:
    grant_ref: str
    request_fingerprint: str
    device_id: str
    root_ref: str
    executable_profile_ref: str
    capability_refs: tuple[str, ...]
    p01_approval_ref: str
    local_policy_ref: str
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "grant_ref",
            "device_id",
            "root_ref",
            "executable_profile_ref",
            "p01_approval_ref",
            "local_policy_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        if not isinstance(self.capability_refs, tuple) or not self.capability_refs:
            raise ContractError("capability_refs must be a non-empty tuple")
        capabilities = tuple(_ref(item, "capability_ref") for item in self.capability_refs)
        if len(capabilities) != len(set(capabilities)):
            raise ContractError("capability_refs must be unique")
        object.__setattr__(self, "capability_refs", capabilities)
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))

    def validate(
        self,
        *,
        request: LocalCommandRequest,
        profile: WindowsExecutableProfile,
        now: datetime,
    ) -> None:
        now = _aware(now, "now")
        if self.expires_at <= now:
            raise ContractError("Windows execution grant has expired")
        if self.request_fingerprint != command_request_fingerprint(request):
            raise ContractError("Windows execution grant request fingerprint mismatch")
        if self.device_id != request.device_id or self.root_ref != request.root_ref:
            raise ContractError("Windows execution grant device/root mismatch")
        if self.executable_profile_ref != profile.profile_ref:
            raise ContractError("Windows execution grant executable profile mismatch")
        missing = set(profile.required_capabilities) - set(self.capability_refs)
        if missing:
            raise ContractError("Windows execution grant lacks required capabilities")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "grant_ref": self.grant_ref,
            "request_fingerprint": self.request_fingerprint,
            "device_id": self.device_id,
            "root_ref": self.root_ref,
            "executable_profile_ref": self.executable_profile_ref,
            "capability_refs": list(self.capability_refs),
            "p01_approval_ref": self.p01_approval_ref,
            "local_policy_ref": self.local_policy_ref,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "client_asserted_authority": False,
        }


class WindowsExecutionAuthorizationPort(Protocol):
    def authorize(
        self,
        *,
        request: LocalCommandRequest,
        profile: WindowsExecutableProfile,
        now: datetime,
    ) -> TrustedWindowsExecutionGrant:
        ...


class UnconfiguredWindowsExecutionAuthorizationPort:
    def authorize(
        self,
        *,
        request: LocalCommandRequest,
        profile: WindowsExecutableProfile,
        now: datetime,
    ) -> TrustedWindowsExecutionGrant:
        raise ContractError("trusted Windows execution authorization is not configured")


class DeterministicFakeWindowsExecutionAuthorizationPort:
    """Network-free test adapter only; never production authority."""

    def __init__(self, *, capability_refs: tuple[str, ...]) -> None:
        self.capability_refs = capability_refs
        self.calls: list[str] = []

    def authorize(
        self,
        *,
        request: LocalCommandRequest,
        profile: WindowsExecutableProfile,
        now: datetime,
    ) -> TrustedWindowsExecutionGrant:
        now = _aware(now, "now")
        self.calls.append(request.request_id)
        return TrustedWindowsExecutionGrant(
            grant_ref=f"fake_grant_{request.request_id}",
            request_fingerprint=command_request_fingerprint(request),
            device_id=request.device_id,
            root_ref=request.root_ref,
            executable_profile_ref=profile.profile_ref,
            capability_refs=self.capability_refs,
            p01_approval_ref="fake_p01_approval",
            local_policy_ref="fake_local_policy",
            expires_at=now + timedelta(minutes=5),
        )


class WindowsExecutionTermination(str, Enum):
    EXITED = "exited"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class WindowsExecutionReceipt:
    result: LocalCommandResult
    termination: WindowsExecutionTermination
    executable_profile_ref: str
    authorization_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.result, LocalCommandResult):
            raise ContractError("result must be LocalCommandResult")
        if not isinstance(self.termination, WindowsExecutionTermination):
            try:
                object.__setattr__(self, "termination", WindowsExecutionTermination(self.termination))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Windows execution termination") from exc
        object.__setattr__(self, "executable_profile_ref", _ref(self.executable_profile_ref, "executable_profile_ref"))
        object.__setattr__(self, "authorization_ref", _ref(self.authorization_ref, "authorization_ref"))
        if self.termination is WindowsExecutionTermination.CANCELLED and not self.result.cancelled:
            raise ContractError("cancelled receipt requires cancelled command result")
        if self.termination is WindowsExecutionTermination.TIMED_OUT and self.result.cancelled:
            raise ContractError("timeout must remain distinct from explicit cancellation")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "termination": self.termination.value,
            "executable_profile_ref": self.executable_profile_ref,
            "authorization_ref": self.authorization_ref,
            "result": self.result.safe_dict(),
            "shell": False,
            "admin_elevation": False,
            "environment_inheritance": "bounded_allowlist",
        }


class WorktreeStatePort(Protocol):
    def is_dirty(self, cwd: str) -> bool:
        ...


class DeterministicWorktreeStatePort:
    def __init__(self, *, dirty: bool = False) -> None:
        self.dirty = dirty
        self.calls: list[str] = []

    def is_dirty(self, cwd: str) -> bool:
        self.calls.append(cwd)
        return self.dirty


def _bounded_environment() -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in _SAFE_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _contained_working_directory(root_path: str, cwd_relative: str) -> str:
    root = Path(root_path).resolve(strict=True)
    candidate = (root / Path(cwd_relative.replace("\\", os.sep))).resolve(strict=True)
    try:
        common = os.path.commonpath((str(root), str(candidate)))
    except ValueError as exc:
        raise ContractError("working directory is outside the selected root") from exc
    if os.path.normcase(common) != os.path.normcase(str(root)):
        raise ContractError("working directory escapes the selected root")
    if not candidate.is_dir():
        raise ContractError("working directory must be an existing directory")
    return str(candidate)


def _drain_bounded(stream: Any, chunks: list[str]) -> None:
    kept = 0
    try:
        while True:
            chunk = stream.read(1024)
            if chunk == "" or chunk is None:
                break
            if kept < _MAX_CAPTURE_CHARS:
                remaining = _MAX_CAPTURE_CHARS - kept
                piece = chunk[:remaining]
                chunks.append(piece)
                kept += len(piece)
    finally:
        try:
            stream.close()
        except Exception:
            pass


class WindowsSubprocessLocalAgentRuntime:
    def __init__(
        self,
        *,
        device: LocalAgentDeviceProfile,
        executable_profiles: tuple[WindowsExecutableProfile, ...],
        authorization_port: WindowsExecutionAuthorizationPort | None = None,
        worktree_state_port: WorktreeStatePort | None = None,
    ) -> None:
        if not isinstance(device, LocalAgentDeviceProfile) or device.platform is not LocalAgentPlatform.WINDOWS:
            raise ContractError("Windows subprocess runtime requires a Windows Local Agent device")
        if not isinstance(executable_profiles, tuple) or not executable_profiles:
            raise ContractError("Windows subprocess runtime requires explicit executable profiles")
        if not all(isinstance(item, WindowsExecutableProfile) for item in executable_profiles):
            raise ContractError("executable_profiles must contain WindowsExecutableProfile values")
        refs = [item.profile_ref for item in executable_profiles]
        paths = [item.executable_path.casefold() for item in executable_profiles]
        if len(refs) != len(set(refs)) or len(paths) != len(set(paths)):
            raise ContractError("Windows executable profiles must be unique")
        self._device = device
        self._profiles = executable_profiles
        self._authorization = authorization_port or UnconfiguredWindowsExecutionAuthorizationPort()
        self._worktree = worktree_state_port or DeterministicWorktreeStatePort(dirty=False)
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def _profile_for(self, executable: str) -> WindowsExecutableProfile:
        for profile in self._profiles:
            if profile.matches(executable):
                return profile
        raise ContractError("requested executable is not in the trusted executable profile allowlist")

    def _validate_request(self, request: LocalCommandRequest) -> tuple[WindowsExecutableProfile, str]:
        if not isinstance(request, LocalCommandRequest):
            raise ContractError("request must be LocalCommandRequest")
        if request.device_id != self._device.device_id:
            raise ContractError("command request does not match Local Agent device")
        root = self._device.root(request.root_ref)
        profile = self._profile_for(request.argv[0])
        cwd = _contained_working_directory(root.windows_path, request.cwd_relative)
        return profile, cwd

    def execute(self, request: LocalCommandRequest, *, now: datetime) -> LocalCommandResult:
        return self.execute_with_receipt(request, now=now).result

    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        if os.name != "nt":
            raise ContractError("real Local Agent subprocess execution is Windows-only in M1")
        now = _aware(now, "now")
        _require_request_not_future(request, now=now)
        profile, cwd = self._validate_request(request)
        grant = self._authorization.authorize(request=request, profile=profile, now=now)
        if not isinstance(grant, TrustedWindowsExecutionGrant):
            raise ContractError("authorization port returned invalid Windows execution grant")
        grant.validate(request=request, profile=profile, now=now)

        dirty_before = self._worktree.is_dirty(cwd)
        environment = _bounded_environment()
        process = subprocess.Popen(
            list(request.argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise ContractError("Windows subprocess did not expose bounded output pipes")

        with self._lock:
            if request.request_id in self._active:
                process.kill()
                raise ContractError("command request is already active")
            self._active[request.request_id] = process

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_thread = threading.Thread(target=_drain_bounded, args=(process.stdout, stdout_chunks), daemon=True)
        stderr_thread = threading.Thread(target=_drain_bounded, args=(process.stderr, stderr_chunks), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            try:
                process.wait(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        finally:
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            with self._lock:
                self._active.pop(request.request_id, None)
                explicitly_cancelled = request.request_id in self._cancelled
                self._cancelled.discard(request.request_id)

        ended_at = datetime.now(timezone.utc)
        if ended_at < now:
            ended_at = now
        dirty_after = self._worktree.is_dirty(cwd)
        if explicitly_cancelled:
            termination = WindowsExecutionTermination.CANCELLED
            cancelled = True
            exit_code = None
        elif timed_out:
            termination = WindowsExecutionTermination.TIMED_OUT
            cancelled = False
            exit_code = None
        else:
            termination = WindowsExecutionTermination.EXITED
            cancelled = False
            exit_code = process.returncode

        result = LocalCommandResult(
            request_id=request.request_id,
            run_id=request.run_id,
            device_id=request.device_id,
            root_ref=request.root_ref,
            started_at=now,
            ended_at=ended_at,
            exit_code=exit_code,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
            cancelled=cancelled,
            dirty_worktree_before=dirty_before,
            dirty_worktree_after=dirty_after,
        )
        return WindowsExecutionReceipt(
            result=result,
            termination=termination,
            executable_profile_ref=profile.profile_ref,
            authorization_ref=grant.grant_ref,
        )

    def cancel(self, request_id: str) -> None:
        request_id = _ref(request_id, "request_id")
        with self._lock:
            process = self._active.get(request_id)
            if process is None:
                raise ContractError("command request is not active")
            self._cancelled.add(request_id)
            process.terminate()

    def active_request_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))


REAL_WINDOWS_SUBPROCESS_EXECUTOR_IMPLEMENTED = True
REAL_WINDOWS_AUTHORIZATION_ADAPTER_CONFIGURED = False
SHELL_EXECUTION_SUPPORTED = False
UNBOUNDED_ENVIRONMENT_INHERITANCE_SUPPORTED = False
ADMIN_ELEVATION_SUPPORTED = False
AUTOMATIC_GIT_NETWORK_SUPPORTED = False
PRODUCTION_REMOTE_CONTROL_CLAIMED = False
