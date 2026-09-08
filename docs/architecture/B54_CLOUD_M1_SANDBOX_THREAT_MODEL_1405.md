# B54 Cloud M1 Sandbox Threat Model & Provider Acceptance Gate (#1405)

- Status: REVIEWED / ACT-A
- Target Milestone: Cloud M1 (1 repo / 1 task / 1 sandbox / canonical P01 execution / bounded tests / verified diff)
- Scope: Provider-neutral security policy, boundary definition, and threat mitigation contracts
- Provider Execution: NONE (ACT-A is contract/threat-model only; real cloud provider execution = 0)

---

## 1. Executive Summary & Boundary Invariants

Padiem Claw (B54) provides autonomous agent execution for software engineering tasks. To execute untrusted repository code safely in cloud environments, Cloud M1 establishes a strict sandbox boundary:
- **1 Repository**
- **1 Task**
- **1 Isolated Sandbox**
- **Canonical P01 Execution**
- **Bounded Verification Tests**
- **Verified Diff Evidence Output**

### Non-Negotiable Invariants
```text
NETWORK_DEFAULT = OFF (deny-by-default egress/ingress)
PRIVILEGED_RUNTIME = FALSE (no container root/host capability)
HOST_MOUNTS = FALSE (zero host directory/device access)
RUNTIME_SOCKET_EXPOSED = FALSE (no /var/run/docker.sock or containerd/crio socket)
HOST_SECRET_INHERITANCE = NONE (no ambient cloud metadata or env credentials)
CROSS_RUN_REUSE = FORBIDDEN (ephemeral, disposable sandbox per task run)
EXACT_REVISION_BINDING = REQUIRED (immutable git commit SHA)
TERMINAL_RESURRECTION = FORBIDDEN (completed/failed/cancelled leases are permanently terminated)
REAL_PROVIDER_SELECTED = NO (ACT-A does not configure or call real cloud vendors)
REAL_PROVIDER_CALLS = 0
PROVIDER_CREDENTIALS = 0
PRODUCTION_MUTATION = 0
```

---

## 2. Threat Vector Enumeration & Mitigations

### 2.1 Untrusted Repository & Malicious Code Execution
- **Threat**: Malicious code executed within the repository (e.g. via setup.py, post-install hooks, pytest fixtures, or malicious build scripts) attempts to exploit the host kernel, install rootkits, or scan internal infrastructure.
- **Mitigations**:
  - MicroVM or strictly isolated hardware virtualization (IsolationPrimitive.MICROVM or VM).
  - Container breakout defense: rootless container runtime inside isolated VM, zero Linux host capabilities, seccomp/apparmor enforcement.
  - Checkout hooks disabled during initial repository cloning (core.hooksPath=/dev/null).

### 2.2 Cross-Run / Multi-Tenant Contamination
- **Threat**: Residual files, background daemons, cached secrets, or modified binaries from Run A persist into Run B.
- **Mitigations**:
  - Ephemeral disposable sandbox: 1 sandbox instance allocated per run, destroyed immediately upon task termination.
  - Dedicated workspace per run; zero shared volumes or persistent root filesystems across tasks.
  - Cross-run reuse explicitly rejected in SandboxSecurityPolicy and DeterministicFakeSandboxProvider.

### 2.3 Supply-Chain & Network Exfiltration
- **Threat**: Executed code attempts to contact C2 servers, download malware, or exfiltrate source code or credentials over the internet.
- **Mitigations**:
  - Network policy is strictly OFF by default. Egress and ingress are closed.
  - No ambient internet access during agent modification or test execution.
  - When dependencies are required, they must be pre-baked into the environment image or fetched through an authoritative authenticated proxy (future milestone).

### 2.4 Artifact Poisoning & Resource Exhaustion (Oversized Output)
- **Threat**: Malicious workloads generate gigabytes of log output or disk-filling files to exhaust host/control plane memory and storage.
- **Mitigations**:
  - Disk limits strictly enforced (e.g. max disk quota).
  - Maximum artifact bytes bounded (default 25 MB per artifact, max 100 MB).
  - Maximum artifact count bounded (max 100 artifacts).
  - Maximum terminal output bounded (max 2 MB) and ANSI control sequence sanitized.

### 2.5 Terminal Escape & Control Sequence Poisoning
- **Threat**: Workloads emit raw terminal escape sequences (ESC codes, cursor movement, window title changes, bracketed paste exploits) to compromise agent terminals or operator displays.
- **Mitigations**:
  - Raw terminal output is scrubbed of dangerous control characters before export.
  - Run projections and verified diff evidence store only cryptographic digests (unified_diff_sha256, verification_output_sha256) and redacted summaries, never raw unchecked terminal streams.

### 2.6 Metadata & Cloud Credential Harvesting
- **Threat**: Workload attempts to contact Cloud Instance Metadata Services (IMDSv1/v2 at 169.254.169.254) or inspect environment variables to steal cloud IAM tokens.
- **Mitigations**:
  - Provider metadata blocked (provider_metadata_blocked = True).
  - Zero host secret inheritance (host_secret_inheritance_disabled = True).
  - Sandbox execution environment is completely unprivileged and has no access to control plane or infrastructure keys.

### 2.7 Bounded Resource Limits & Teardown Guarantees
- **Threat**: Runaway processes (fork bombs, infinite loops, crypto miners) consume infinite compute or outlive the task.
- **Mitigations**:
  - Hard CPU, memory, process count, and disk limits enforced by provider.
  - Hard TTL timeout enforced (max 3600s).
  - Cancellation barrier: cancellation kills the workload process tree and immediately triggers full sandbox teardown.
  - Expired or released leases cannot be reacquired or reused.

---

## 3. Provider Acceptance Gate Matrix

A cloud sandbox provider candidate (e.g. MicroVM/Cloud provider) must pass the following provider-neutral acceptance gate before being admitted:

| Security Control | Required Value | Rationale |
| :--- | :--- | :--- |
| `isolation_primitive` | `microvm` or `vm` | Strong hypervisor boundary; untrusted code cannot share kernel |
| `server_owned_lifecycle` | `true` | Client cannot prolong sandbox life or bypass teardown |
| `exact_revision_materialization` | `true` | Source checkout is pinned to exact immutable git SHA |
| `checkout_hooks_disabled` | `true` | Prevents arbitrary code execution during checkout |
| `network_deny_by_default` | `true` | Disallows network egress/ingress during run |
| `egress_policy_enforced` | `true` | Zero unauthorized network calls |
| `privileged_runtime_disabled` | `true` | No root privileges, no CAP_SYS_ADMIN |
| `host_mounts_disabled` | `true` | Host filesystem is invisible and unmounted |
| `runtime_socket_hidden` | `true` | No access to Docker/containerd/microvm management socket |
| `provider_metadata_blocked` | `true` | Blocks 169.254.169.254 and cloud provider metadata APIs |
| `host_secret_inheritance_disabled` | `true` | Prevents ambient host secrets from leaking into container |
| `dedicated_workspace_per_run` | `true` | Guarantees clean isolation between runs |
| `cross_run_reuse_disabled` | `true` | Forbids re-attaching or recycling past sandbox containers |
| `cpu_limit_enforced` | `true` | Prevents CPU starvation |
| `memory_limit_enforced` | `true` | Prevents OOM kills of host services |
| `disk_limit_enforced` | `true` | Prevents disk exhaustion |
| `process_limit_enforced` | `true` | Prevents fork bomb Denial of Service |
| `ttl_enforced` | `true` | Bounded maximum lifetime (max 3600 seconds) |
| `cancellation_kills_workload` | `true` | Immediate process termination upon cancellation |
| `teardown_guaranteed` | `true` | Resources destroyed deterministically on exit/abort |
| `artifact_allowlist_enforced` | `true` | Only recognized artifact kinds are exported |
| `artifact_size_limit_enforced` | `true` | Limits artifact payload sizes to policy boundaries |
| `terminal_output_bounded` | `true` | Caps maximum log/terminal size |
| `terminal_output_sanitized` | `true` | Strips terminal escape codes |
| `image_or_snapshot_provenance` | `true` | Base rootfs/image is cryptographically signed and audited |
| `run_lease_audit_correlation` | `true` | Every lease maps 1:1 to a verified run ID |
| `preview_ports_private_by_default` | `true` | Ephemeral preview ports are never publicly bound |

---

## 4. Verified Diff Evidence Contract

Cloud M1 does **NOT** project raw diffs or raw terminal streams to the client or control plane. Instead, evidence is delivered via VerifiedDiffEvidence:
- run_id: Verified run identifier.
- lease_id: Cryptographically verified sandbox lease identifier.
- repository_ref: Authorized target repository.
- input_revision: Exact immutable input git commit SHA.
- changed_files: Bounded tuple of unique relative file paths (max 100).
- unified_diff_sha256: SHA-256 digest of the unified diff.
- verification_command_id: Allowlisted verification command (e.g. pytest_allowlisted).
- verification_exit_code: Numeric exit code (-255 to 255).
- verification_output_sha256: SHA-256 digest of the verification output.
- terminal_reason: Terminal reason string (e.g. completed, failed, cancelled).
- final_revision_ref: Optional final commit SHA if committed.

---

## 5. Authority Boundaries

- B54 Padiem Claw Owns:
  - Sandbox lease request lifecycle and state transitions.
  - Repository reference and revision materialization request.
  - Workspace mount and write policies.
  - Test command invocation within sandbox boundaries.
  - Diff and artifact collection and hashing.
  - Safe user-visible run projections.

- B54 Padiem Claw Must NOT Own:
  - P01 execution semantics and kernel enforcement.
  - B14 model/provider routing or token allocation.
  - Control Plane identity, authentication, billing, or tenant entitlement.
  - Production sandbox hosting infrastructure.
  - GitHub write/commit/push/PR mutation behavior in ACT-A.

---

## 6. Non-Goals & Forbidden Operations (ACT-A)

1. No Real Cloud Provider Implementation: ACT-A defines threats, boundaries, contracts, and tests only.
2. No Provider Selection: No vendor is selected or wired as default.
3. Zero Provider Calls: External HTTP/gRPC requests to cloud providers are 0.
4. Zero Provider Secrets: No API keys, tokens, or account credentials stored in repository.
5. Zero Production Mutation: No DNS, Cloudflare, R2, D1, or database mutation.
6. Zero GitHub Write Automation: No automated PR creation, push, or merge behavior in ACT-A.
