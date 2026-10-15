from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any, Protocol

from .contracts import ContractError
from .sandbox_conformance import SandboxSecurityPolicy
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SHELL_EXECUTABLES = frozenset({"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"})
_NETWORK_EXECUTABLES = frozenset({"curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "netcat", "telnet", "ftp"})
_DEPLOY_EXECUTABLES = frozenset({"wrangler", "vercel", "netlify", "kubectl", "helm", "terraform", "pulumi", "flyctl"})
_GIT_MUTATING_SUBCOMMANDS = frozenset({
    "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "commit", "fetch", "merge", "mv", "pull", "push", "rebase", "reset", "restore", "revert", "rm", "switch", "tag",
})
_SHELL_METACHARACTERS = re.compile(r"(?:&&|\|\||[;`]|\$\(|>|<)")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _argv_token(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("argv tokens must be strings")
    value = value.strip()
    if not value or len(value) > 512 or _CONTROL_RE.search(value):
        raise ContractError("argv token is empty, unbounded, or contains control characters")
    if _SHELL_METACHARACTERS.search(value):
        raise ContractError("argv token contains shell metacharacters")
    if redact_secrets(value) != value:
        raise ContractError("argv token must not contain raw credential material")
    return value


def _cwd(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("cwd must be a string")
    value = value.strip()
    if not value or len(value) > 256 or "\\" in value or _CONTROL_RE.search(value):
        raise ContractError("cwd must be a bounded POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".."} for part in path.parts):
        raise ContractError("cwd must remain inside the sandbox workspace")
    return "." if value == "." else str(path)


def _validate_program(argv: tuple[str, ...]) -> None:
    executable = PurePosixPath(argv[0]).name.lower()
    if executable in _SHELL_EXECUTABLES:
        raise ContractError("shell interpreters are not allowed in Cloud M1 verification catalog")
    if executable in _NETWORK_EXECUTABLES:
        raise ContractError("network client commands are not allowed in Cloud M1 verification catalog")
    if executable in _DEPLOY_EXECUTABLES:
        raise ContractError("deployment commands are not allowed in Cloud M1 verification catalog")
    if executable == "git" and len(argv) > 1 and argv[1].lower() in _GIT_MUTATING_SUBCOMMANDS:
        raise ContractError("Git mutation commands are not allowed in Cloud M1 verification catalog")


@dataclass(frozen=True, slots=True)
class VerificationCommandSpec:
    command_id: str
    argv: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: int = 60
    max_output_bytes: int = 256_000
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", _id(self.command_id, "command_id"))
        if not isinstance(self.argv, tuple) or not self.argv or len(self.argv) > 32:
            raise ContractError("argv must be a non-empty tuple with at most 32 tokens")
        normalized = tuple(_argv_token(item) for item in self.argv)
        _validate_program(normalized)
        object.__setattr__(self, "argv", normalized)
        object.__setattr__(self, "cwd", _cwd(self.cwd))
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 3600:
            raise ContractError("timeout_seconds must be between 1 and 3600")
        if isinstance(self.max_output_bytes, bool) or not isinstance(self.max_output_bytes, int) or not 1024 <= self.max_output_bytes <= 20 * 1024 * 1024:
            raise ContractError("max_output_bytes must be between 1024 and 20 MiB")
        if self.environment != ():
            raise ContractError("Cloud M1 verification commands must not inherit or inject environment values in v1")

    def validate_against(self, policy: SandboxSecurityPolicy) -> None:
        if not isinstance(policy, SandboxSecurityPolicy):
            raise ContractError("policy must be SandboxSecurityPolicy")
        if self.timeout_seconds > policy.max_ttl_seconds:
            raise ContractError("verification command timeout exceeds Cloud M1 TTL policy")
        if self.max_output_bytes > policy.max_terminal_output_bytes:
            raise ContractError("verification output bound exceeds Cloud M1 terminal-output policy")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "environment": [],
            "shell": False,
            "inherit_host_environment": False,
        }


@dataclass(frozen=True, slots=True)
class VerificationCommandRequest:
    request_id: str
    run_id: str
    lease_id: str
    command_id: str

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "lease_id", "command_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "command_id": self.command_id,
            "client_supplied_argv": False,
            "client_supplied_shell": False,
            "client_supplied_environment": False,
        }


class VerificationCommandCatalog:
    def __init__(
        self,
        specs: tuple[VerificationCommandSpec, ...],
        *,
        policy: SandboxSecurityPolicy | None = None,
    ) -> None:
        if not isinstance(specs, tuple) or not specs:
            raise ContractError("verification command catalog requires at least one spec")
        if not all(isinstance(spec, VerificationCommandSpec) for spec in specs):
            raise ContractError("catalog entries must be VerificationCommandSpec")
        ids = [spec.command_id for spec in specs]
        if len(ids) != len(set(ids)):
            raise ContractError("verification command IDs must be unique")
        self.policy = policy or SandboxSecurityPolicy()
        for spec in specs:
            spec.validate_against(self.policy)
        self._specs = {spec.command_id: spec for spec in specs}

    def resolve(self, request: VerificationCommandRequest) -> VerificationCommandSpec:
        if not isinstance(request, VerificationCommandRequest):
            raise ContractError("request must be VerificationCommandRequest")
        try:
            return self._specs[request.command_id]
        except KeyError as exc:
            raise ContractError("verification command_id is not registered") from exc

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-verification-command-catalog.v1",
            "commands": [self._specs[key].safe_dict() for key in sorted(self._specs)],
            "server_owned": True,
        }


@dataclass(frozen=True, slots=True)
class VerificationExecutionReceipt:
    request_id: str
    run_id: str
    lease_id: str
    command_id: str
    exit_code: int
    output_bytes: int
    output_sha256: str
    duration_ms: int
    output_sanitized: bool = True

    def __post_init__(self) -> None:
        for field_name in ("request_id", "run_id", "lease_id", "command_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int) or not -255 <= self.exit_code <= 255:
            raise ContractError("exit_code must be bounded")
        if isinstance(self.output_bytes, bool) or not isinstance(self.output_bytes, int) or not 0 <= self.output_bytes <= 20 * 1024 * 1024:
            raise ContractError("output_bytes must be bounded")
        digest = self.output_sha256.strip().lower() if isinstance(self.output_sha256, str) else ""
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ContractError("output_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "output_sha256", digest)
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or not 0 <= self.duration_ms <= 3_600_000:
            raise ContractError("duration_ms must be bounded")
        if self.output_sanitized is not True:
            raise ContractError("verification output must be sanitized before receipt projection")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "lease_id": self.lease_id,
            "command_id": self.command_id,
            "exit_code": self.exit_code,
            "output_bytes": self.output_bytes,
            "output_sha256": self.output_sha256,
            "duration_ms": self.duration_ms,
            "output_sanitized": True,
            "raw_output_in_receipt": False,
        }


class VerificationExecutorPort(Protocol):
    def execute(
        self,
        request: VerificationCommandRequest,
        spec: VerificationCommandSpec,
    ) -> VerificationExecutionReceipt:
        ...


class UnconfiguredVerificationExecutor:
    def execute(
        self,
        request: VerificationCommandRequest,
        spec: VerificationCommandSpec,
    ) -> VerificationExecutionReceipt:
        raise ContractError("verification execution adapter is not configured")


class DeterministicFakeVerificationExecutor:
    def __init__(self, *, exit_code: int = 0, output: str = "ok", duration_ms: int = 1) -> None:
        if not isinstance(output, str):
            raise ContractError("fake output must be a string")
        self.exit_code = exit_code
        self.output = output
        self.duration_ms = duration_ms
        self.executed: list[tuple[VerificationCommandRequest, VerificationCommandSpec]] = []

    def execute(
        self,
        request: VerificationCommandRequest,
        spec: VerificationCommandSpec,
    ) -> VerificationExecutionReceipt:
        if not isinstance(request, VerificationCommandRequest) or not isinstance(spec, VerificationCommandSpec):
            raise ContractError("fake executor received invalid request/spec")
        payload = redact_secrets(self.output).encode("utf-8")
        if len(payload) > spec.max_output_bytes:
            raise ContractError("verification output exceeds command bound")
        self.executed.append((request, spec))
        return VerificationExecutionReceipt(
            request_id=request.request_id,
            run_id=request.run_id,
            lease_id=request.lease_id,
            command_id=spec.command_id,
            exit_code=self.exit_code,
            output_bytes=len(payload),
            output_sha256=hashlib.sha256(payload).hexdigest(),
            duration_ms=self.duration_ms,
        )


class VerificationCommandRunner:
    def __init__(
        self,
        catalog: VerificationCommandCatalog,
        executor: VerificationExecutorPort | None = None,
    ) -> None:
        if not isinstance(catalog, VerificationCommandCatalog):
            raise ContractError("catalog must be VerificationCommandCatalog")
        self.catalog = catalog
        self.executor = executor or UnconfiguredVerificationExecutor()

    def run(self, request: VerificationCommandRequest) -> VerificationExecutionReceipt:
        spec = self.catalog.resolve(request)
        receipt = self.executor.execute(request, spec)
        if receipt.request_id != request.request_id or receipt.run_id != request.run_id or receipt.lease_id != request.lease_id:
            raise ContractError("verification receipt correlation mismatch")
        if receipt.command_id != spec.command_id:
            raise ContractError("verification receipt command mismatch")
        if receipt.output_bytes > spec.max_output_bytes:
            raise ContractError("verification receipt exceeds command output bound")
        return receipt


REAL_SUBPROCESS_EXECUTION_CONFIGURED = False
ARBITRARY_SHELL_SUPPORTED = False
HOST_ENVIRONMENT_INHERITANCE_SUPPORTED = False
