# Padiem Claw Cloud M1 — Sandbox Threat Model and Provider Acceptance Gate

Status: **PRE-PRODUCTION / PROVIDER-NEUTRAL**  
Business: **B54 Padiem Claw**  
Issue: **#1405**  
Authority: this document describes B54 physical sandbox requirements. P01 remains Agent/Tool/Approval/Evidence/Orchestration authority; B14 remains Provider/model credential and routing authority.

## 1. Cloud M1 claim boundary

Cloud M1 may not claim real cloud execution merely because an API can create a container, VM, workspace, or browser.

The first accepted provider must prove this exact boundary:

```text
accepted repository + exact immutable revision
→ one server-owned isolated sandbox lease
→ dedicated writable workspace
→ canonical P01 RUN_STARTED
→ one bounded task
→ allowlisted/bounded verification
→ bounded artifact + verified-diff evidence
→ workload kill + sandbox teardown
```

Critical invariant:

```text
SANDBOX_LEASE_ALLOCATED != P01_AGENT_EXECUTION_STARTED
```

No implementation in this PR selects a provider, calls a real sandbox, stores provider credentials, or authorizes Production.

## 2. Trust zones

### Untrusted

- repository content and history;
- build/test scripts;
- project-local configuration;
- task text;
- generated code;
- model-produced shell/tool arguments;
- browser/page content;
- external documents and inbound messages.

### Trusted product control boundary

B54 may own:
- exact repository/revision request;
- sandbox lease correlation;
- server-owned resource/network policy;
- physical workspace lifecycle adapter;
- changed-file/test/diff artifact collection;
- bounded user-visible sandbox projection.

### Trusted shared authorities

- **P01:** Agent, Tool, Skill, approval, recovery, evidence and orchestration semantics.
- **B14:** model/provider registry, credentials, routing/fallback and model execution.
- **Control Plane:** identity, entitlement, usage, credits/billing and authoritative account audit.

The sandbox provider must not become any of those authorities.

## 3. Threat inventory

### 3.1 Untrusted repository/code

Assume repository code may intentionally attempt:
- fork bombs and uncontrolled child processes;
- CPU, RAM and disk exhaustion;
- symlink/path traversal and workspace escape;
- reading host home/tmp/cache state;
- accessing runtime/container sockets;
- privileged syscalls/capabilities;
- persistence after task termination;
- DNS/network exfiltration;
- cloud metadata access;
- environment/host secret discovery;
- malicious checkout/build hooks;
- oversized or deceptive artifacts;
- terminal/control-sequence injection;
- background processes surviving the foreground command.

Required controls are therefore deny-by-default and must not rely on cooperative guest code.

### 3.2 Cross-run / multi-tenant

Assume an attacker attempts:
- workspace/volume/cache reuse;
- `/tmp` or home leakage;
- process namespace observation;
- cross-run network reachability;
- lease/run ID substitution;
- stale lease resurrection;
- artifact/result mix-up;
- browser profile/session leakage.

Cloud M1 requires dedicated per-run workspace state, no cross-run reuse, exact run/lease audit correlation, terminal teardown, and no host-secret inheritance.

### 3.3 Repository acquisition / supply chain

Assume:
- a branch moves after task acceptance;
- submodules or LFS introduce unexpected content;
- a repository is oversized or maliciously packed;
- checkout configuration/hooks try to execute;
- history contains credential-like material;
- image/snapshot provenance is unclear.

Cloud M1 therefore requires exact immutable revision materialization, checkout hooks disabled, bounded acquisition, and image/snapshot provenance.

### 3.4 Output / evidence

Assume generated output may contain:
- secrets accidentally printed by code;
- control sequences;
- oversized logs;
- deceptive file names;
- unbounded diffs;
- artifacts belonging to a different run.

Only allowlisted, bounded, hash-addressed artifact metadata may cross the sandbox boundary. Terminal output must be bounded and sanitized. General product projections must not carry raw diff or raw terminal output by default.

## 4. Mandatory Cloud M1 policy

The server-owned policy is equivalent to:

```text
network default                  = OFF
privileged runtime               = DISABLED
host mounts                      = DISABLED
runtime/container socket         = HIDDEN
provider metadata access         = BLOCKED
host secret inheritance          = DISABLED
workspace reuse                  = DISABLED
mutable source revision          = DISABLED
exact revision materialization   = REQUIRED
checkout hooks                   = DISABLED
CPU/RAM/disk/process limits      = REQUIRED
TTL                              = HARD ENFORCED
cancellation                     = KILLS WORKLOAD
terminal teardown                = REQUIRED
artifact allowlist               = REQUIRED
artifact size/count limits       = REQUIRED
terminal output bound/sanitize   = REQUIRED
image/snapshot provenance        = REQUIRED
run/lease audit correlation      = REQUIRED
preview ports                    = PRIVATE BY DEFAULT
```

A client, task, repository, model output, or provider adapter cannot relax these defaults.

### 4.1 Where each control is enforced

A control that only appears in this list is a request, not a guarantee. Each row names the
code that actually refuses a violation, so a reviewer can check the claim instead of
accepting it.

| Control | Enforcement point | How it is proven |
| --- | --- | --- |
| network default OFF | `contracts.SandboxLeaseRequest`, `SandboxSecurityPolicy.__post_init__`, `SandboxProviderConformanceGate.validate_lease_request`, `preparation.CloudWorkspacePreparer.prepare` | refused at construction, at the policy, and at the allocation seam |
| exact immutable revision | `contracts.exact_commit_revision` applied inside `SandboxLeaseRequest` for CLOUD, re-checked by the gate | a mutable ref never reaches `allocate()` |
| TTL bound | `contracts` 60..3600 and `policy.max_ttl_seconds` at the seam | a longer TTL is refused before allocation |
| privileged / host mounts / runtime socket / provider metadata / host secrets / workspace reuse / mutable revision | `SandboxSecurityPolicy.__post_init__` refuses a policy that enables any of them | constructing such a policy raises |
| CPU / RAM / disk / process ceiling | `SandboxSecurityPolicy.max_cpu_cores` … `max_process_count`, `require_within_bounds(SandboxAppliedLimits)`, harness case `resource_limits_within_policy` | a provider's *reported* numbers are checked, not its four `*_limit_enforced` booleans |
| artifact export allowlist | `SandboxSecurityPolicy.allowed_artifact_kinds`, enforced in `SandboxArtifactManifest.validate_against` | an unlisted kind is refused even at in-policy size and count |
| artifact size / count | `SandboxArtifactManifest.validate_against` | per-artifact, total, and count bounds |
| terminal output bound | `sanitize_terminal_output` against `policy.max_terminal_output_bytes` | oversize output is refused, never truncated |
| terminal output sanitized | `sanitize_terminal_output` + `SandboxArtifactManifest.require_sanitized_output` | the boolean claim is re-derived from the raw bytes and must match |
| one active lease per run, cancellation, TTL reclamation, no terminal resurrection | `SandboxProviderConformanceHarness.evaluate_lease_lifecycle` / `evaluate_cancellation` / `evaluate_reclamation` | each is exercised against a provider through the port, not read off a declared flag |
| run ↔ lease correlation | `VerifiedDiffEvidence`, `SandboxArtifactManifest` carry `run_id` + `lease_id` | projection cannot be built without both |

### 4.2 Not yet enforced by any code path

Stated so that a green conformance report is not read as a production claim:

- nothing schedules `reap_expired_leases`; reclamation exists as an operation and a
  conformance exercise, not as a running driver (`sandbox_reclamation.py`).
- `TeardownVerification.process_tree_killed` has no producer, so "child processes are
  killed at teardown" is a required provider property that B54 cannot yet observe.
- `CloudWorkspacePathPolicy` decides per-path authority only inside artifact collection;
  it is not applied to a lease allocation.
- No real provider has ever been evaluated by this harness, and the probe and teardown
  configuration constants remain false. Selecting a provider is #1405 phase C, gated on a
  separate decision record.

## 5. Provider capability manifest

A candidate provider is represented only by provider-neutral capability facts in `kagent.sandbox_conformance.SandboxProviderCapabilities`.

The manifest intentionally does **not** contain:
- provider credential values;
- provider account IDs;
- arbitrary runtime hostnames/endpoints;
- user-supplied host mounts;
- model/provider routing settings.

`SandboxProviderConformanceGate` returns every missing required control. A candidate with an unknown isolation primitive fails closed even when all boolean claims are true.

Passing the static capability gate is necessary but not sufficient for final provider selection. A later provider-specific implementation must independently prove the claims through provider documentation, configuration inspection, integration tests and destructive isolation tests where appropriate.

## 6. Verified-diff evidence

Cloud M1 output must preserve attributable evidence without dumping unbounded raw content into product state.

`VerifiedDiffEvidence` binds:
- B54 run ID;
- sandbox lease ID;
- repository reference;
- exact input revision;
- bounded changed-file set;
- unified diff SHA-256;
- allowlisted verification command identity;
- verification exit code;
- verification output SHA-256;
- terminal reason;
- optional final workspace revision reference.

Raw diff and raw terminal output are intentionally outside the default projection and belong in separately bounded artifacts.

## 7. Artifact export

`SandboxArtifactManifest` requires:
- unique artifact IDs;
- bounded count;
- bounded individual sizes;
- bounded total export;
- SHA-256 identity;
- bounded terminal output;
- terminal output sanitization before export.

Artifact export does not authorize GitHub commit/push/merge/deploy.

## 8. Lifecycle invariants

```text
QUEUED
→ PREPARING
→ lease allocated
→ still PREPARING
→ canonical P01 RUN_STARTED
→ RUNNING
→ WAITING_APPROVAL | COMPLETED | FAILED | CANCELLED
→ workload killed
→ lease released / sandbox torn down
```

Required rules:
- cancellation must kill the workload;
- expired lease cannot start or resume execution;
- terminal run cannot reuse its old sandbox;
- provider retry cannot leave two active sandboxes for one run;
- teardown failure is an auditable failure/incident condition, never silent success;
- sandbox state cannot create P01 approval authority;
- sandbox state cannot create B14 provider/model authority.

## 9. OpenBot benchmark boundary

Issue #1437 permits OpenBot as an architecture/reference candidate only.

Useful patterns to benchmark:
- per-agent computer/workspace;
- privileged supervisor separated from workload;
- policy/audit gateway;
- human takeover/release lifecycle;
- optional AG-UI interoperability.

Not adopted as Padiem authority:
- memory/thread authority;
- provider/model authority;
- credential ownership;
- identity/entitlement/billing;
- product identity.

No OpenBot source is copied by this PR.

## 10. Provider selection evidence still required

Before a concrete provider adapter is accepted, record:
1. provider/product/version and upstream documentation references;
2. isolation primitive and kernel-sharing facts;
3. exact configuration proving every capability flag;
4. network and metadata blocking test evidence;
5. CPU/RAM/disk/process exhaustion tests;
6. cancellation and teardown tests;
7. cross-run leakage tests;
8. artifact/output bound tests;
9. image/snapshot provenance;
10. region/data-residency choices;
11. startup latency and price measurements;
12. API reliability/rate limits;
13. license/Terms/commercial constraints.

A provider-specific credential or endpoint must remain in trusted deployment configuration, never in B54 task/run contracts or this evidence document.

## 11. Current disposition

```text
THREAT_MODEL = DEFINED
SERVER_POLICY = EXPLICIT
RESOURCE_CEILING_EXPRESSED_IN_POLICY = YES        (#1405 A; was declared only on an unconsumed model)
ARTIFACT_EXPORT_ALLOWLIST_ENFORCED = YES         (#1405 A)
TERMINAL_OUTPUT_SANITIZER_EXISTS = YES           (#1405 A; replaces a bare boolean claim)
POLICY_CEILING_CHECKED_AT_ALLOCATION_SEAM = YES  (#1405 A; refusals never reach a provider)
PROVIDER_CONFORMANCE_HARNESS = IMPLEMENTED
VERIFIED_DIFF_CONTRACT = IMPLEMENTED
CONTROLS_NOT_YET_ENFORCED = SEE_SECTION_4_2
REAL_PROVIDER_SELECTED = NO
REAL_PROVIDER_CALLS = 0
PRODUCTION_SANDBOX_CLAIM = NO
PRODUCTION_MUTATION = 0
CLOUD_M1_ACCEPTED = NO   # acceptance is a review verdict, not a test outcome
```
