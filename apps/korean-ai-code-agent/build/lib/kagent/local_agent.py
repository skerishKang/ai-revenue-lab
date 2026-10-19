from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PureWindowsPath
import re
from typing import Any, Protocol

from .contracts import ContractError


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_MAX_ARG_COUNT = 64
_MAX_ARG_LENGTH = 2048
_MAX_OUTPUT_CHARS = 8192
_MAX_TIMEOUT_SECONDS = 900


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _windows_root(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ContractError("windows_path must be a bounded absolute Windows path")
    raw = value.strip().replace("/", "\\")
    path = PureWindowsPath(raw)
    if not path.is_absolute() or not path.drive:
        raise ContractError("windows_path must be an absolute Windows path")
    if path.drive.startswith("\\"):
        raise ContractError("UNC roots are not supported in Local Agent M1")
    if any(part in {".", ".."} for part in path.parts):
        raise ContractError("windows_path traversal is not allowed")
    return str(path)


def _relative_windows_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ContractError("cwd_relative must be a bounded relative Windows path")
    raw = value.strip().replace("/", "\\")
    path = PureWindowsPath(raw)
    if path.is_absolute() or path.drive:
        raise ContractError("cwd_relative must remain inside the selected root")
    if any(part in {".."} for part in path.parts):
        raise ContractError("cwd_relative traversal is not allowed")
    return str(path)


def _argv(value: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value or len(value) > _MAX_ARG_COUNT:
        raise ContractError("argv must contain 1-64 direct-process arguments")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > _MAX_ARG_LENGTH or "\x00" in item:
            raise ContractError("argv contains an invalid or oversized argument")
        normalized.append(item)
    return tuple(normalized)


def _bounded_output(value: str) -> tuple[str, bool]:
    if not isinstance(value, str):
        raise ContractError("command output must be text")
    if len(value) <= _MAX_OUTPUT_CHARS:
        return value, False
    return value[:_MAX_OUTPUT_CHARS], True


class LocalAgentPlatform(str, Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


@dataclass(frozen=True, slots=True)
class LocalRoot:
    root_ref: str
    windows_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_ref", _ref(self.root_ref, "root_ref"))
        object.__setattr__(self, "windows_path", _windows_root(self.windows_path))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "root_ref": self.root_ref,
            "windows_path": self.windows_path,
            "user_selected": True,
            "whole_pc": False,
        }


@dataclass(frozen=True, slots=True)
class LocalAgentDeviceProfile:
    device_id: str
    workspace_ref: str
    platform: LocalAgentPlatform
    roots: tuple[LocalRoot, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _ref(self.device_id, "device_id"))
        object.__setattr__(self, "workspace_ref", _ref(self.workspace_ref, "workspace_ref"))
        if not isinstance(self.platform, LocalAgentPlatform):
            try:
                object.__setattr__(self, "platform", LocalAgentPlatform(self.platform))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Local Agent platform") from exc
        if not isinstance(self.roots, tuple) or not self.roots:
            raise ContractError("Local Agent requires at least one user-selected root")
        if not all(isinstance(root, LocalRoot) for root in self.roots):
            raise ContractError("roots must contain LocalRoot values")
        refs = [root.root_ref for root in self.roots]
        paths = [root.windows_path.casefold() for root in self.roots]
        if len(set(refs)) != len(refs) or len(set(paths)) != len(paths):
            raise ContractError("Local Agent roots must be unique")

    def root(self, root_ref: str) -> LocalRoot:
        root_ref = _ref(root_ref, "root_ref")
        for root in self.roots:
            if root.root_ref == root_ref:
                return root
        raise ContractError("selected root is not authorized for this device")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "workspace_ref": self.workspace_ref,
            "platform": self.platform.value,
            "roots": [root.safe_dict() for root in self.roots],
            "outbound_connection_only": True,
            "public_inbound_port": False,
            "admin_default": False,
            "credential_discovery": False,
        }


@dataclass(frozen=True, slots=True)
class LocalCommandRequest:
    request_id: str
    run_id: str
    device_id: str
    root_ref: str
    argv: tuple[str, ...]
    cwd_relative: str
    requested_at: datetime
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "device_id", "root_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "argv", _argv(self.argv))
        object.__setattr__(self, "cwd_relative", _relative_windows_path(self.cwd_relative))
        object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or not 1 <= self.timeout_seconds <= _MAX_TIMEOUT_SECONDS
        ):
            raise ContractError("timeout_seconds must be between 1 and 900")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "root_ref": self.root_ref,
            "argv_count": len(self.argv),
            "cwd_relative": self.cwd_relative,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "timeout_seconds": self.timeout_seconds,
            "direct_process": True,
            "shell_authority": False,
            "admin_elevation": False,
            "automatic_git_network": False,
        }


@dataclass(frozen=True, slots=True)
class LocalCommandResult:
    request_id: str
    run_id: str
    device_id: str
    root_ref: str
    started_at: datetime
    ended_at: datetime
    exit_code: int | None
    stdout: str
    stderr: str
    cancelled: bool
    dirty_worktree_before: bool
    dirty_worktree_after: bool
    stdout_truncated: bool = field(default=False, init=False)
    stderr_truncated: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "device_id", "root_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        started = _aware(self.started_at, "started_at")
        ended = _aware(self.ended_at, "ended_at")
        if ended < started:
            raise ContractError("ended_at cannot precede started_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "ended_at", ended)
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)):
            raise ContractError("exit_code must be an integer or None")
        if not isinstance(self.cancelled, bool):
            raise ContractError("cancelled must be boolean")
        if self.cancelled and self.exit_code is not None:
            raise ContractError("cancelled command must not claim an exit code")
        if not isinstance(self.dirty_worktree_before, bool) or not isinstance(self.dirty_worktree_after, bool):
            raise ContractError("dirty worktree flags must be boolean")
        stdout, stdout_truncated = _bounded_output(self.stdout)
        stderr, stderr_truncated = _bounded_output(self.stderr)
        object.__setattr__(self, "stdout", stdout)
        object.__setattr__(self, "stderr", stderr)
        object.__setattr__(self, "stdout_truncated", stdout_truncated)
        object.__setattr__(self, "stderr_truncated", stderr_truncated)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "device_id": self.device_id,
            "root_ref": self.root_ref,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "ended_at": self.ended_at.isoformat().replace("+00:00", "Z"),
            "exit_code": self.exit_code,
            "cancelled": self.cancelled,
            "stdout_chars": len(self.stdout),
            "stderr_chars": len(self.stderr),
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "dirty_worktree_before": self.dirty_worktree_before,
            "dirty_worktree_after": self.dirty_worktree_after,
            "automatic_git_clean_reset": False,
            "raw_host_credentials": False,
        }


class LocalAgentRuntimePort(Protocol):
    def execute(self, request: LocalCommandRequest, *, now: datetime) -> LocalCommandResult:
        ...

    def cancel(self, request_id: str) -> None:
        ...


class UnconfiguredLocalAgentRuntime:
    def execute(self, request: LocalCommandRequest, *, now: datetime) -> LocalCommandResult:
        raise ContractError("Local Agent runtime is not configured")

    def cancel(self, request_id: str) -> None:
        raise ContractError("Local Agent runtime is not configured")


class DeterministicFakeLocalAgentRuntime:
    def __init__(
        self,
        profile: LocalAgentDeviceProfile,
        *,
        dirty_roots: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(profile, LocalAgentDeviceProfile):
            raise ContractError("profile must be LocalAgentDeviceProfile")
        if profile.platform is not LocalAgentPlatform.WINDOWS:
            raise ContractError("Local Agent M1 deterministic runtime is Windows-first")
        self._profile = profile
        self._cancelled: set[str] = set()
        self._dirty_roots = {_ref(root_ref, "root_ref") for root_ref in dirty_roots}
        for root_ref in self._dirty_roots:
            profile.root(root_ref)

    def resolve_working_directory(self, request: LocalCommandRequest) -> str:
        self._validate_request(request)
        root = self._profile.root(request.root_ref)
        relative = PureWindowsPath(request.cwd_relative)
        return str(PureWindowsPath(root.windows_path).joinpath(relative))

    def execute(self, request: LocalCommandRequest, *, now: datetime) -> LocalCommandResult:
        self._validate_request(request)
        now = _aware(now, "now")
        if now < request.requested_at:
            raise ContractError("execution cannot start before requested_at")
        dirty_before = request.root_ref in self._dirty_roots
        cancelled = request.request_id in self._cancelled
        if cancelled:
            return LocalCommandResult(
                request_id=request.request_id,
                run_id=request.run_id,
                device_id=request.device_id,
                root_ref=request.root_ref,
                started_at=now,
                ended_at=now,
                exit_code=None,
                stdout="",
                stderr="cancelled",
                cancelled=True,
                dirty_worktree_before=dirty_before,
                dirty_worktree_after=dirty_before,
            )
        executable = PureWindowsPath(request.argv[0]).name
        stdout = f"fake-local-agent:{executable}"
        return LocalCommandResult(
            request_id=request.request_id,
            run_id=request.run_id,
            device_id=request.device_id,
            root_ref=request.root_ref,
            started_at=now,
            ended_at=now,
            exit_code=0,
            stdout=stdout,
            stderr="",
            cancelled=False,
            dirty_worktree_before=dirty_before,
            dirty_worktree_after=dirty_before,
        )

    def cancel(self, request_id: str) -> None:
        self._cancelled.add(_ref(request_id, "request_id"))

    def _validate_request(self, request: LocalCommandRequest) -> None:
        if not isinstance(request, LocalCommandRequest):
            raise ContractError("request must be LocalCommandRequest")
        if request.device_id != self._profile.device_id:
            raise ContractError("command request does not match Local Agent device")
        self._profile.root(request.root_ref)


WINDOWS_FIRST_LOCAL_AGENT = True
OUTBOUND_CONNECTION_ONLY = True
PUBLIC_INBOUND_PORT_REQUIRED = False
REAL_LOCAL_HOST_EXECUTION_CONFIGURED = False
ADMIN_ELEVATION_DEFAULT = False
RAW_HOST_CREDENTIAL_DISCOVERY = False
AUTOMATIC_GIT_PUSH_MERGE_DEPLOY = False
