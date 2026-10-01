"""One-shot non-Production Vercel parser runtime probe executor (#3283).

This is a probe transport, not a Production parser binding.

Authority boundaries:
* padiem_ai_core.isolated_parser_client owns the bounded parser request/response contract.
* #1405 sandbox_conformance / sandbox_provider_probe own the resource/security policy.
* #2824 document_parser_boundary remains the only product parser authority.
* This module owns only the bounded non-Production measurement transport needed by #3283.

Importing this module performs no provider I/O and does not import the Vercel SDK. The SDK is
loaded lazily only after a validated owner authorization reaches the execution path. No credential
value is accepted by any public function here; the official Vercel SDK resolves host-side bindings.

The workload is deliberately parser-shaped, not a second product parser: it consumes the canonical
IsolatedParserClient request envelope and returns a canonical bounded document envelope while also
measuring sandbox controls. Binary semantic extraction remains solely in Core.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .contracts import ContractError
from .sandbox_conformance import SandboxAppliedLimits, SandboxSecurityPolicy
from .vercel_parser_live_gate import (
    PARSER_HARD_DEADLINE_SECONDS,
    VERCEL_PARSER_CENTRAL_CONFIRMATION,
    build_vercel_parser_live_probe_gate,
)

VERCEL_PARSER_PROBE_RUNTIME_VERSION = "claw-vercel-parser-runtime-probe.v1"
VERCEL_SANDBOX_SDK_REQUIREMENT = "vercel-sandbox==0.7.0"
VERCEL_PROBE_IMAGE = "vercel/sandbox/python:3.14"

VERCEL_PROBE_VCPUS = 1
VERCEL_PROBE_MEMORY_MB = 2048
VERCEL_PROBE_PUBLIC_PORTS = 0
VERCEL_PROBE_GUEST_ENV_VARS = 0
VERCEL_PROBE_PERSISTENT = False
VERCEL_PROBE_NETWORK_POLICY = "deny-all"

VERCEL_PARSER_EXPECTED_SANDBOX_ALLOCATIONS = 1
# Logical SDK operations, not undocumented SDK-internal HTTP request count:
# create, control/parse, timeout-start, timeout-wait, timeout-check,
# cancel-start, cancel-kill, cancel-wait, cancel-check, stop, destroy, absent-check.
VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS = 12

VERCEL_PARSER_OWNER_APPROVAL_MARKER = "OWNER_VERCEL_PARSER_LIVE_PROBE_APPROVED=YES"
VERCEL_PARSER_TARGET_ENVIRONMENT = "non_production"

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")

_CONTROL_AND_PARSE_SCRIPT = r"""
import base64
import json
import os
import resource
import shutil
import socket
import subprocess
import sys

request_raw = base64.b64decode(sys.argv[1].encode("ascii"), validate=True)
request = json.loads(request_raw.decode("utf-8"))
if set(request) != {"type", "name", "media_type", "payload_b64"}:
    raise SystemExit(21)
if request.get("type") != "isolated_parser_request":
    raise SystemExit(22)
payload = base64.b64decode(request["payload_b64"].encode("ascii"), validate=True)

def denied(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        sock.connect((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()

def mem_mb():
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemTotal:"):
                return max(1, int(line.split()[1]) // 1024)
    return 1048576

soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
unlimited = getattr(resource, "RLIM_INFINITY", -1)
process_limit = hard
if hard in (-1, unlimited) or hard > 1048576:
    process_limit = 1048576

sudo_allowed = False
try:
    sudo_allowed = subprocess.run(
        ["sudo", "-n", "true"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2,
        check=False,
    ).returncode == 0
except (OSError, subprocess.SubprocessError):
    sudo_allowed = False

evidence = {
    "network_external_denied": denied("1.1.1.1", 443),
    "metadata_link_local_denied": denied("169.254.169.254", 80),
    "host_credential_names_absent": not any(name in os.environ for name in (
        "VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID", "VERCEL_OIDC_TOKEN"
    )),
    "runtime_socket_hidden": not any(os.path.exists(path) for path in (
        "/var/run/docker.sock", "/run/docker.sock",
        "/run/containerd/containerd.sock", "/var/run/containerd/containerd.sock"
    )),
    "privileged_runtime_disabled": os.geteuid() != 0 and not sudo_allowed,
    "cpu_cores": max(1, int(os.cpu_count() or 1)),
    "memory_mb": mem_mb(),
    "disk_mb": max(1, int(shutil.disk_usage("/").total // (1024 * 1024))),
    "process_count": max(1, int(process_limit)),
}
response = {
    "type": "document",
    "name": request["name"],
    "media_type": request["media_type"],
    "text": "vercel-parser-runtime-probe",
    "byte_size": len(payload),
    "source_kind": "binary",
    "status": "complete",
    "warnings": [],
}
sys.stdout.write(json.dumps(
    {"response": response, "evidence": evidence},
    separators=(",", ":"), sort_keys=True
))
"""

_TREE_SCRIPT = r"""
import subprocess
import sys
import time
token = sys.argv[1]
grandchild = "import sys,time; token=sys.argv[1]; time.sleep(300)"
child = (
    "import subprocess,sys,time; token=sys.argv[1]; "
    "subprocess.Popen([sys.executable,'-c',sys.argv[2],token]); time.sleep(300)"
)
subprocess.Popen([sys.executable, "-c", child, token, grandchild])
time.sleep(300)
"""

_PROCESS_ABSENCE_SCRIPT = r"""
import os
import sys
token = sys.argv[1].encode("utf-8")
me = os.getpid()
found = False
for entry in os.listdir("/proc"):
    if not entry.isdigit() or int(entry) == me:
        continue
    try:
        data = open(f"/proc/{entry}/cmdline", "rb").read(8192)
    except OSError:
        continue
    if token in data:
        found = True
        break
sys.stdout.write("1" if found else "0")
"""


class VercelParserProbeError(RuntimeError):
    """Bounded probe failure. Messages must not contain provider payloads."""


class ProbeProcessPort(Protocol):
    def wait(self) -> int: ...
    def kill(self) -> Any: ...


class ProbeSandboxPort(Protocol):
    name: str

    def run_process(self, command: str, args: list[str], **kwargs: Any) -> Any: ...
    def create_process(
        self, command: str, args: list[str], **kwargs: Any
    ) -> ProbeProcessPort: ...
    def stop(self) -> Any: ...
    def destroy(self) -> Any: ...


class VercelProbeProviderPort(Protocol):
    def create(self, *, ttl_seconds: int) -> ProbeSandboxPort: ...
    def get(self, *, name: str) -> Any: ...


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


@dataclass(frozen=True, slots=True)
class VercelParserProbeAuthorization:
    exact_main_sha: str
    central_confirmation: str
    owner_approval_ref: str
    owner_authorized: bool
    target_environment: str
    parser_deadline_seconds: int
    sandbox_ttl_seconds: int
    max_sandbox_allocations: int = 1
    max_logical_provider_operations: int = VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS

    def __post_init__(self) -> None:
        # Reuse the already-reviewed #3283 source gate for exact SHA, CENTRAL
        # marker, deadline, TTL, launch profile and probe-plan policy. This
        # authorization layer adds only the owner decision and one-shot budget.
        gate = build_vercel_parser_live_probe_gate(
            exact_main_sha=self.exact_main_sha,
            central_confirmation=self.central_confirmation,
            parser_deadline_seconds=self.parser_deadline_seconds,
            sandbox_ttl_seconds=self.sandbox_ttl_seconds,
        )
        object.__setattr__(self, "exact_main_sha", gate.exact_main_sha)
        if self.owner_authorized is not True:
            raise ContractError("owner authorization is required for a live Vercel parser probe")
        if self.target_environment != gate.target_environment:
            raise ContractError("Vercel parser probe is restricted to canonical non_production")
        if self.max_sandbox_allocations != 1:
            raise ContractError("probe authorization permits exactly one sandbox allocation")
        if self.max_logical_provider_operations != VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS:
            raise ContractError("probe authorization operation ceiling is fixed by source")
        object.__setattr__(
            self, "owner_approval_ref", _safe_ref(self.owner_approval_ref, "owner_approval_ref")
        )
    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": VERCEL_PARSER_PROBE_RUNTIME_VERSION,
            "exact_main_sha": self.exact_main_sha,
            "owner_approval_ref": self.owner_approval_ref,
            "owner_authorized": True,
            "target_environment": self.target_environment,
            "parser_deadline_seconds": self.parser_deadline_seconds,
            "sandbox_ttl_seconds": self.sandbox_ttl_seconds,
            "max_sandbox_allocations": self.max_sandbox_allocations,
            "max_logical_provider_operations": self.max_logical_provider_operations,
            "credential_value": None,
            "production_binding": False,
        }


@dataclass(frozen=True, slots=True)
class VercelParserRuntimeEvidence:
    fresh_sandbox: bool
    persistence_disabled: bool
    network_deny_default: bool
    metadata_link_local_negative_test: bool
    host_guest_secret_inheritance_disabled: bool
    runtime_socket_hidden: bool
    privileged_runtime_disabled: bool
    parser_request_bounds: bool
    parser_response_bounds: bool
    timeout_kills_parser_process_tree: bool
    cancellation_kills_parser_process_tree: bool
    terminal_sandbox_non_resurrectable: bool
    cpu_memory_disk_process_limit_evidence: bool
    cpu_cores: int
    memory_mb: int
    disk_mb: int
    process_count: int
    parser_hard_deadline_seconds: int
    sandbox_allocations: int
    logical_provider_operations: int
    raw_provider_payload_output: int = 0
    raw_document_output: int = 0
    provider_credential_output: int = 0

    @property
    def accepted(self) -> bool:
        return all(
            (
                self.fresh_sandbox,
                self.persistence_disabled,
                self.network_deny_default,
                self.metadata_link_local_negative_test,
                self.host_guest_secret_inheritance_disabled,
                self.runtime_socket_hidden,
                self.privileged_runtime_disabled,
                self.parser_request_bounds,
                self.parser_response_bounds,
                self.timeout_kills_parser_process_tree,
                self.cancellation_kills_parser_process_tree,
                self.terminal_sandbox_non_resurrectable,
                self.cpu_memory_disk_process_limit_evidence,
            )
        )

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": VERCEL_PARSER_PROBE_RUNTIME_VERSION,
            "FRESH_SANDBOX": self.fresh_sandbox,
            "PERSISTENCE_DISABLED": self.persistence_disabled,
            "NETWORK_DENY_DEFAULT": self.network_deny_default,
            "METADATA_LINK_LOCAL_NEGATIVE_TEST": self.metadata_link_local_negative_test,
            "HOST_GUEST_SECRET_INHERITANCE": (
                "NO" if self.host_guest_secret_inheritance_disabled else "UNPROVEN"
            ),
            "RUNTIME_SOCKET_HIDDEN": self.runtime_socket_hidden,
            "PRIVILEGED_RUNTIME_DISABLED": self.privileged_runtime_disabled,
            "PARSER_REQUEST_BOUNDS": self.parser_request_bounds,
            "PARSER_RESPONSE_BOUNDS": self.parser_response_bounds,
            "PARSER_HARD_DEADLINE_SECONDS": self.parser_hard_deadline_seconds,
            "TIMEOUT_KILLS_PARSER_PROCESS_TREE": self.timeout_kills_parser_process_tree,
            "CANCELLATION_KILLS_PARSER_PROCESS_TREE": self.cancellation_kills_parser_process_tree,
            "TERMINAL_SANDBOX_NON_RESURRECTABLE": self.terminal_sandbox_non_resurrectable,
            "CPU_MEMORY_DISK_PROCESS_LIMIT_EVIDENCE": self.cpu_memory_disk_process_limit_evidence,
            "applied_cpu_cores": self.cpu_cores,
            "applied_memory_mb": self.memory_mb,
            "applied_disk_mb": self.disk_mb,
            "applied_process_count": self.process_count,
            "SANDBOX_ALLOCATIONS": self.sandbox_allocations,
            "LOGICAL_PROVIDER_OPERATIONS": self.logical_provider_operations,
            "RAW_PROVIDER_PAYLOAD_OUTPUT": self.raw_provider_payload_output,
            "RAW_DOCUMENT_OUTPUT": self.raw_document_output,
            "PROVIDER_CREDENTIAL_OUTPUT": self.provider_credential_output,
            "VERCEL_PARSER_RUNTIME_CANDIDATE_ACCEPTED": (
                "YES" if self.accepted else "NO"
            ),
            "FALLBACK_CANDIDATE": None if self.accepted else "E2B",
            "production_binding": False,
            "production_ready_claim": False,
        }


class VercelPythonSdkProbeProvider:
    """Lazy official Python SDK adapter with explicit client ownership.

    SyncSandboxClient construction is documented as synchronous and I/O-free.
    The client is created only on the first authorized provider operation and is
    explicitly closed after the one-shot probe. No ambient SDK session is used.
    """

    def __init__(self) -> None:
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from vercel.sandbox.sync import SandboxServiceOptions, SyncSandboxClient
        except ImportError as exc:
            raise VercelParserProbeError(
                f"Vercel Sandbox SDK unavailable; install {VERCEL_SANDBOX_SDK_REQUIREMENT}"
            ) from exc
        self._client = SyncSandboxClient.create(
            options=SandboxServiceOptions(region="iad1")
        )
        return self._client

    def create(self, *, ttl_seconds: int) -> ProbeSandboxPort:
        try:
            from vercel.sandbox import NetworkPolicy, SandboxResources
        except ImportError as exc:
            raise VercelParserProbeError(
                f"Vercel Sandbox SDK unavailable; install {VERCEL_SANDBOX_SDK_REQUIREMENT}"
            ) from exc
        client = self._ensure_client()
        return client.create_sandbox(
            image=VERCEL_PROBE_IMAGE,
            execution_time_limit=ttl_seconds,
            resources=SandboxResources(
                vcpus=VERCEL_PROBE_VCPUS, memory=VERCEL_PROBE_MEMORY_MB
            ),
            ports=[],
            env=None,
            network_policy=NetworkPolicy.deny_all(),
            persistent=False,
        )

    def get(self, *, name: str) -> Any:
        return self._ensure_client().get_sandbox(name=name)

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            client.close()

class VercelIsolatedParserProbeTransport:
    """Canonical IsolatedParserClient transport over one probe sandbox."""

    def __init__(self, *, sandbox: ProbeSandboxPort, counter: list[int]) -> None:
        self._sandbox = sandbox
        self._counter = counter
        self._safe_runtime_evidence: Mapping[str, Any] | None = None
        self.last_request_bytes = 0
        self.last_response_bytes = 0

    @property
    def safe_runtime_evidence(self) -> Mapping[str, Any]:
        if self._safe_runtime_evidence is None:
            raise VercelParserProbeError("runtime evidence is unavailable")
        return self._safe_runtime_evidence

    def exchange(self, request: bytes) -> bytes:
        if not isinstance(request, bytes) or not request:
            raise VercelParserProbeError("canonical parser request must be non-empty bytes")
        encoded = base64.b64encode(request).decode("ascii")
        self._counter[0] += 1
        completed = self._sandbox.run_process(
            "python3",
            ["-c", _CONTROL_AND_PARSE_SCRIPT, encoded],
            capture_output=True,
            kill_after=PARSER_HARD_DEADLINE_SECONDS,
        )
        if int(getattr(completed, "returncode", getattr(completed, "exit_code", 1))) != 0:
            raise VercelParserProbeError("parser-shaped sandbox workload failed")
        stdout = getattr(completed, "stdout", "")
        if not isinstance(stdout, str) or len(stdout.encode("utf-8")) > 512 * 1024:
            raise VercelParserProbeError("sandbox probe response is missing or unbounded")
        try:
            packet = json.loads(stdout)
        except (TypeError, ValueError):
            raise VercelParserProbeError("sandbox probe response is not bounded JSON") from None
        if not isinstance(packet, dict) or set(packet) != {"response", "evidence"}:
            raise VercelParserProbeError("sandbox probe response shape is invalid")
        if not isinstance(packet["response"], dict) or not isinstance(packet["evidence"], dict):
            raise VercelParserProbeError("sandbox probe response objects are invalid")
        response = json.dumps(
            packet["response"], separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        self.last_request_bytes = len(request)
        self.last_response_bytes = len(response)
        self._safe_runtime_evidence = dict(packet["evidence"])
        return response


def _process_absent(sandbox: ProbeSandboxPort, token: str, counter: list[int]) -> bool:
    counter[0] += 1
    result = sandbox.run_process(
        "python3",
        ["-c", _PROCESS_ABSENCE_SCRIPT, token],
        capture_output=True,
        kill_after=5,
    )
    return (
        int(getattr(result, "returncode", getattr(result, "exit_code", 1))) == 0
        and str(getattr(result, "stdout", "")).strip() == "0"
    )


def _start_tree(
    sandbox: ProbeSandboxPort,
    *,
    token: str,
    kill_after: int,
    counter: list[int],
) -> ProbeProcessPort:
    counter[0] += 1
    return sandbox.create_process(
        "python3",
        ["-c", _TREE_SCRIPT, token],
        kill_after=kill_after,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_bounded(process: ProbeProcessPort, counter: list[int]) -> None:
    counter[0] += 1
    try:
        process.wait()
    except Exception:
        return


def _kill_bounded(process: ProbeProcessPort, counter: list[int]) -> None:
    counter[0] += 1
    try:
        process.kill()
    except Exception:
        return


def _resource_evidence_pass(
    evidence: Mapping[str, Any],
) -> tuple[bool, SandboxAppliedLimits]:
    try:
        applied = SandboxAppliedLimits(
            cpu_cores=int(evidence["cpu_cores"]),
            memory_mb=int(evidence["memory_mb"]),
            disk_mb=int(evidence["disk_mb"]),
            process_count=int(evidence["process_count"]),
        )
        SandboxSecurityPolicy().require_within_bounds(applied)
        return True, applied
    except (KeyError, TypeError, ValueError, ContractError):
        fallback = SandboxAppliedLimits(
            cpu_cores=1024,
            memory_mb=1_048_576,
            disk_mb=10_485_760,
            process_count=1_048_576,
        )
        return False, fallback


def _bool(evidence: Mapping[str, Any], name: str) -> bool:
    return evidence.get(name) is True


def _provider_absent_after_destroy(
    provider: VercelProbeProviderPort,
    *,
    name: str,
    counter: list[int],
) -> bool:
    counter[0] += 1
    try:
        provider.get(name=name)
    except Exception as exc:
        status = getattr(exc, "status_code", getattr(exc, "status", None))
        code = str(getattr(exc, "code", "")).lower()
        return status == 404 or code in {"404", "not_found", "sandbox_not_found"}
    return False


def execute_authorized_vercel_parser_probe(
    authorization: VercelParserProbeAuthorization,
    *,
    provider: VercelProbeProviderPort | None = None,
) -> VercelParserRuntimeEvidence:
    """Execute one bounded sandbox lineage after explicit owner authorization."""

    if not isinstance(authorization, VercelParserProbeAuthorization):
        raise ContractError("authorization must be VercelParserProbeAuthorization")

    chosen = provider if provider is not None else VercelPythonSdkProbeProvider()
    operations = [0]
    sandbox: ProbeSandboxPort | None = None
    sandbox_name = ""
    stopped = False
    destroyed = False

    try:
        operations[0] += 1
        sandbox = chosen.create(ttl_seconds=authorization.sandbox_ttl_seconds)
        sandbox_name = _safe_ref(str(getattr(sandbox, "name", "")), "sandbox_name")

        transport = VercelIsolatedParserProbeTransport(
            sandbox=sandbox, counter=operations
        )

        try:
            from padiem_ai_core.isolated_parser_client import (
                ISOLATED_PARSER_MAX_REQUEST_BYTES,
                ISOLATED_PARSER_MAX_RESPONSE_BYTES,
                IsolatedParserClient,
            )
        except ImportError as exc:
            raise VercelParserProbeError(
                "canonical padiem_ai_core isolated parser client is unavailable"
            ) from exc

        client = IsolatedParserClient(transport=transport)
        normalized = client.parse_binary_document(
            name="runtime-probe.pdf",
            media_type="application/pdf",
            payload=b"%PDF-1.4\n% bounded synthetic parser runtime probe\n",
        )
        if normalized.text != "vercel-parser-runtime-probe":
            raise VercelParserProbeError("canonical parser client rejected probe response")

        runtime = transport.safe_runtime_evidence
        request_bounds = (
            0 < transport.last_request_bytes <= ISOLATED_PARSER_MAX_REQUEST_BYTES
        )
        response_bounds = (
            0 < transport.last_response_bytes <= ISOLATED_PARSER_MAX_RESPONSE_BYTES
        )

        timeout_token = f"padiem-timeout-{authorization.exact_main_sha[:12]}"
        timeout_process = _start_tree(
            sandbox,
            token=timeout_token,
            kill_after=authorization.parser_deadline_seconds,
            counter=operations,
        )
        _wait_bounded(timeout_process, operations)
        timeout_tree_dead = _process_absent(sandbox, timeout_token, operations)

        cancellation_token = f"padiem-cancel-{authorization.exact_main_sha[:12]}"
        cancellation_process = _start_tree(
            sandbox,
            token=cancellation_token,
            kill_after=authorization.sandbox_ttl_seconds,
            counter=operations,
        )
        time.sleep(1.0)
        _kill_bounded(cancellation_process, operations)
        _wait_bounded(cancellation_process, operations)
        cancellation_tree_dead = _process_absent(
            sandbox, cancellation_token, operations
        )

        resource_pass, applied = _resource_evidence_pass(runtime)

        operations[0] += 1
        sandbox.stop()
        stopped = True
        operations[0] += 1
        sandbox.destroy()
        destroyed = True
        non_resurrectable = _provider_absent_after_destroy(
            chosen, name=sandbox_name, counter=operations
        )

        if operations[0] > authorization.max_logical_provider_operations:
            raise VercelParserProbeError("logical provider operation ceiling exceeded")

        return VercelParserRuntimeEvidence(
            fresh_sandbox=True,
            persistence_disabled=VERCEL_PROBE_PERSISTENT is False,
            network_deny_default=_bool(runtime, "network_external_denied"),
            metadata_link_local_negative_test=_bool(
                runtime, "metadata_link_local_denied"
            ),
            host_guest_secret_inheritance_disabled=_bool(
                runtime, "host_credential_names_absent"
            ),
            runtime_socket_hidden=_bool(runtime, "runtime_socket_hidden"),
            privileged_runtime_disabled=_bool(runtime, "privileged_runtime_disabled"),
            parser_request_bounds=request_bounds,
            parser_response_bounds=response_bounds,
            timeout_kills_parser_process_tree=timeout_tree_dead,
            cancellation_kills_parser_process_tree=cancellation_tree_dead,
            terminal_sandbox_non_resurrectable=non_resurrectable,
            cpu_memory_disk_process_limit_evidence=resource_pass,
            cpu_cores=applied.cpu_cores,
            memory_mb=applied.memory_mb,
            disk_mb=applied.disk_mb,
            process_count=applied.process_count,
            parser_hard_deadline_seconds=authorization.parser_deadline_seconds,
            sandbox_allocations=1,
            logical_provider_operations=operations[0],
        )
    finally:
        if sandbox is not None and not stopped:
            try:
                operations[0] += 1
                sandbox.stop()
            except Exception:
                pass
        if sandbox is not None and not destroyed:
            try:
                operations[0] += 1
                sandbox.destroy()
            except Exception:
                pass
        close = getattr(chosen, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def live_probe_source_readiness() -> dict[str, object]:
    """Safe source-only readiness projection. Calling this performs no I/O."""

    return {
        "contract_version": VERCEL_PARSER_PROBE_RUNTIME_VERSION,
        "sdk_requirement": VERCEL_SANDBOX_SDK_REQUIREMENT,
        "canonical_parser_client": (
            "padiem_ai_core.isolated_parser_client.IsolatedParserClient"
        ),
        "canonical_security_policy": (
            "kagent.sandbox_conformance.SandboxSecurityPolicy"
        ),
        "candidate": "vercel_sandbox",
        "target_environment": VERCEL_PARSER_TARGET_ENVIRONMENT,
        "parser_hard_deadline_seconds": PARSER_HARD_DEADLINE_SECONDS,
        "expected_sandbox_allocations": VERCEL_PARSER_EXPECTED_SANDBOX_ALLOCATIONS,
        "max_logical_provider_operations": (
            VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS
        ),
        "network_policy": VERCEL_PROBE_NETWORK_POLICY,
        "persistent": VERCEL_PROBE_PERSISTENT,
        "public_ports": VERCEL_PROBE_PUBLIC_PORTS,
        "guest_env_vars": VERCEL_PROBE_GUEST_ENV_VARS,
        "owner_approval_marker": VERCEL_PARSER_OWNER_APPROVAL_MARKER,
        "credential_values_in_source": False,
        "provider_calls_at_import": 0,
        "sandbox_allocations_at_import": 0,
        "production_binding": False,
        "production_ready_claim": False,
    }


def _print_safe_evidence(evidence: VercelParserRuntimeEvidence) -> None:
    for key, value in evidence.safe_dict().items():
        if isinstance(value, bool):
            rendered = "PASS" if value else "FAIL"
        elif value is None:
            rendered = "NONE"
        else:
            rendered = str(value)
        print(f"{key}={rendered}")


def main(argv: list[str] | None = None) -> int:
    """Owner-gated CLI used only by the manual workflow_dispatch live job."""

    import argparse

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--exact-main-sha", required=True)
    parser.add_argument("--owner-approval-ref", required=True)
    parser.add_argument(
        "--parser-deadline-seconds",
        type=int,
        default=PARSER_HARD_DEADLINE_SECONDS,
    )
    parser.add_argument("--sandbox-ttl-seconds", type=int, default=120)
    args = parser.parse_args(argv)

    try:
        authorization = VercelParserProbeAuthorization(
            exact_main_sha=args.exact_main_sha,
            central_confirmation=VERCEL_PARSER_CENTRAL_CONFIRMATION,
            owner_approval_ref=args.owner_approval_ref,
            owner_authorized=True,
            target_environment=VERCEL_PARSER_TARGET_ENVIRONMENT,
            parser_deadline_seconds=args.parser_deadline_seconds,
            sandbox_ttl_seconds=args.sandbox_ttl_seconds,
        )
        evidence = execute_authorized_vercel_parser_probe(authorization)
    except Exception as exc:
        print("VERCEL_PARSER_RUNTIME_PROBE=FAIL_CLOSED")
        print(f"FAILURE_CLASS={type(exc).__name__}")
        print("RAW_PROVIDER_PAYLOAD_OUTPUT=0")
        print("RAW_DOCUMENT_OUTPUT=0")
        print("PROVIDER_CREDENTIAL_OUTPUT=0")
        return 2

    print("VERCEL_PARSER_RUNTIME_PROBE=MEASURED")
    _print_safe_evidence(evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "VERCEL_PARSER_EXPECTED_SANDBOX_ALLOCATIONS",
    "VERCEL_PARSER_MAX_LOGICAL_PROVIDER_OPERATIONS",
    "VERCEL_PARSER_OWNER_APPROVAL_MARKER",
    "VERCEL_SANDBOX_SDK_REQUIREMENT",
    "VercelIsolatedParserProbeTransport",
    "VercelParserProbeAuthorization",
    "VercelParserProbeError",
    "VercelParserRuntimeEvidence",
    "VercelPythonSdkProbeProvider",
    "execute_authorized_vercel_parser_probe",
    "live_probe_source_readiness",
    "main",
]
