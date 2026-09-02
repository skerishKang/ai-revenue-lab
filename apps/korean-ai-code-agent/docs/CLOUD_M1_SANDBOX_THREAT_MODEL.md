# Padiem Claw Cloud M1 Sandbox Threat Model

Status: **pre-provider security gate**  
Owner: **B54 Padiem Claw**  
Issue: **#1405**  
Dependencies: **#1383 / PR #1392**, **#1396 / PR #1404**

This document defines the minimum security properties required before Padiem Claw may claim real cloud sandbox execution. It is intentionally provider-neutral. It does not authorize a cloud vendor, credentials, Production deployment, GitHub write automation, or unrestricted network access.

## 1. Security objective

Cloud M1 has one deliberately narrow execution promise:

```text
1 accepted repository
→ 1 exact revision
→ 1 isolated sandbox
→ 1 canonical P01 run
→ bounded verification
→ 1 verified diff result
→ sandbox teardown
```

The security goal is not “run arbitrary code safely in every possible environment.” The goal is to make this specific product path fail closed unless the provider can enforce the controls below.

## 2. Authority model

```text
B54 Padiem Claw
  task/run/repository/sandbox/product artifact state

P01 Padiem AI Core
  Agent/Tool/Skill/approval/recovery/evidence/orchestration authority

B14 Korean AI Platform
  provider/model credential, routing, fallback and model execution authority

Control Plane
  identity/entitlement/usage/credits/audit authority when integrated
```

A sandbox allocation never authorizes P01 execution. A P01 run never grants sandbox network, host, GitHub, or Provider credentials. These are separate authorities.

Critical invariant:

```text
SANDBOX_LEASE_ALLOCATED != P01_AGENT_EXECUTION_STARTED
```

## 3. Protected assets

Cloud M1 must protect:

- host and provider control-plane credentials;
- other users' repositories, workspaces, caches and artifacts;
- B14 Provider/model credentials;
- P01 trusted policy and approval state;
- GitHub tokens and repository write authority;
- Claw run/lease correlation state;
- exact input revision provenance;
- verified diff/test evidence;
- platform availability and resource capacity.

## 4. Trust boundaries

Everything from the selected repository is untrusted, including source, build files, scripts, package manifests, Git metadata, submodules, hooks, binaries, generated files and test commands.

User task text is untrusted product input. It can request work but cannot widen sandbox policy, model routing, provider credentials, host access or approval authority.

Provider APIs and returned metadata are external dependencies. Provider claims become trusted only through explicit adapter validation and conformance evidence.

## 5. Threat actors and failure modes

### 5.1 Malicious or compromised repository

Potential actions:

- fork bomb or runaway child process;
- CPU/RAM/disk exhaustion;
- read environment variables or metadata credentials;
- access host or runtime sockets;
- mount/path/symlink escape;
- persist processes after task termination;
- attempt network/DNS exfiltration;
- emit terminal control sequences or enormous logs;
- poison diff/test artifacts;
- exploit package-manager or build hooks;
- alter Git configuration to execute hooks or credential helpers.

Required mitigation: hard resource bounds, no host mounts/runtime socket, no inherited secrets, metadata-service blocking, network deny-by-default, dedicated per-run workspace, bounded output/artifacts and process-tree teardown.

### 5.2 Cross-run / cross-tenant leakage

Potential actions:

- reuse another run's volume, cache, `/tmp`, home directory or process namespace;
- substitute run/lease identifiers;
- retrieve another run's artifacts;
- reconnect to an expired or terminal lease;
- reach another sandbox through provider-private networking.

Required mitigation: dedicated filesystem/workspace, no cross-run lease reuse, strict run/lease correlation, network isolation, terminal lease invalidation, bounded artifact references and explicit teardown.

### 5.3 Mutable or deceptive repository acquisition

Potential actions:

- branch moves after task acceptance;
- checkout of a different commit than requested;
- submodule/LFS expansion into unexpected content;
- oversized repository or decompression bomb;
- symlink checkout escape;
- implicit hook execution during clone/materialization.

Required mitigation: Cloud M1 accepts an exact hexadecimal revision, provider materialization must attest that exact revision, checkout/materialization must not execute repository-controlled hooks, and repository/artifact size must be bounded by the selected provider adapter.

### 5.4 Provider/control-plane failure

Potential failures:

- duplicate allocation after retry;
- lease reports terminated while workload is still alive;
- timeout is advisory rather than enforced;
- API returns logs/artifacts for the wrong sandbox;
- provider silently enables network or privileged mode;
- metadata credentials become reachable;
- stale sandbox is reused.

Required mitigation: one-active-lease invariant, provider capability gate, explicit teardown, terminal-state verification, correlation checks, network policy assertion and provider-specific conformance tests before selection.

## 6. Mandatory Cloud M1 policy

A provider adapter must be able to enforce all of the following:

```text
network = off
privileged = false
host mounts = none
runtime socket = none
provider metadata access = blocked
host secret inheritance = none
dedicated per-run writable workspace = true
exact revision materialization = required
hard CPU limit = required
hard memory limit = required
hard disk limit = required
hard TTL = required
process-tree kill on teardown = required
explicit teardown API/guarantee = required
bounded logs = required
bounded artifact export = required
cross-run workspace reuse = disabled
terminal sandbox reuse = disabled
```

If any mandatory capability cannot be proven, the provider is rejected for Cloud M1.

## 7. Network model

Cloud M1 starts with `network=off`.

This means task text cannot request internet access, arbitrary egress, webhook callbacks, SSH, package installation from the public internet or arbitrary preview exposure. A later network-enabled milestone requires a separate policy with destination/protocol controls and cannot be smuggled into the first provider adapter.

Model execution remains outside the sandbox through canonical P01 → B14 boundaries. Disabling sandbox egress does not mean disabling the trusted platform's model call path.

## 8. Secret model

The sandbox receives no inherited host secrets, GitHub write token, B14 Provider credentials, cloud control-plane key or unrelated application secrets.

A future task-specific secret injection capability requires a separate design covering scope, lifetime, redaction, audit and revocation. It is not part of Cloud M1.

Repository content may itself contain secrets. Claw must not claim that sandbox isolation removes repository-secret risk. Output and artifact projections continue to use bounded secret redaction, but source owners remain responsible for secrets committed to repository history.

## 9. Lifecycle and teardown

Expected product lifecycle:

```text
QUEUED
→ PREPARING
→ lease allocated
→ PREPARING
→ canonical P01 RUN_STARTED
→ RUNNING
→ WAITING_APPROVAL | COMPLETED | FAILED | CANCELLED
→ sandbox terminated/released
```

Rules:

- allocation alone never sets `RUNNING`;
- cancellation must terminate the workload and preserve B54 `CANCELLED`;
- expiry blocks new execution;
- terminal run cannot reacquire its old lease;
- retry cannot leave two active sandboxes for one run;
- teardown failure is an observable incident condition, not silent success;
- provider termination and P01 cancellation remain separately auditable events.

## 10. Verified diff evidence

A successful sandbox command is not enough. Cloud M1 result acceptance requires bounded product evidence containing:

- B54 run ID;
- sandbox lease ID;
- exact input revision;
- changed-file list;
- bounded unified diff;
- verification command identity;
- verification exit status;
- bounded/redacted verification output;
- terminal reason;
- final workspace revision when available;
- optional bounded artifact reference.

This envelope does not replace P01 Evidence/Verification semantics. It is B54 product evidence used to present and correlate the repository result.

## 11. Provider acceptance process

A provider-specific implementation is not allowed in the A/B slice. Before selection, candidates must be compared on one matrix:

1. isolation primitive;
2. startup latency;
3. hard CPU/RAM/disk limits;
4. network egress controls;
5. per-run filesystem isolation;
6. secret injection/inheritance behavior;
7. metadata and host escape protection;
8. hard timeout and kill guarantee;
9. image/snapshot provenance;
10. logs and artifact API;
11. preview-port exposure model;
12. region/data-residency options;
13. price per useful run/minute;
14. API reliability/rate limits;
15. operational burden;
16. commercial/terms constraints.

Selection must record rejected alternatives and reasons without recording credentials, account IDs or secret endpoints.

## 12. Out of scope

Cloud M1 A/B explicitly excludes:

- real provider credentials or calls;
- Production sandbox deployment;
- persistent warm sandboxes;
- parallel/fan-out agents;
- arbitrary internet/network access;
- arbitrary user images or privileged containers;
- GitHub commit/push/merge/deploy automation;
- background scheduler at Production scale;
- shared `packages/padiem-sandbox-*` extraction;
- B62 execution authority.

## 13. Acceptance checklist

```text
THREAT_MODEL_REVIEWED = YES
SANDBOX_POLICY_EXPLICIT = YES
NETWORK_DEFAULT_OFF = YES
HOST_SECRET_INHERITANCE = NO
HOST_MOUNT = NO
PRIVILEGED_RUNTIME = NO
RUNTIME_SOCKET = NO
METADATA_SERVICE_ACCESS = NO
EXACT_REVISION_BINDING = YES
ONE_ACTIVE_LEASE_PER_RUN = YES
CROSS_RUN_REUSE = NO
TTL_TIMEOUT_ENFORCED = YES
PROCESS_TREE_KILL = YES
EXPLICIT_TEARDOWN = YES
TERMINAL_RESURRECTION = NO
ARTIFACT_OUTPUT_BOUNDED = YES
VERIFIED_DIFF_CONTRACT = PASS
PROVIDER_CONFORMANCE_HARNESS = PASS
REAL_PROVIDER_SELECTED = NO
REAL_PROVIDER_CALLS = 0
PRODUCTION_MUTATION = 0
```

No provider is Cloud M1-eligible until every mandatory capability is demonstrated by provider-specific conformance evidence in a later dedicated decision/implementation slice.
