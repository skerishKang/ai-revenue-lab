# Padiem Claw Cloud M1 — Sandbox Live Probe Runbook

Date: 2026-09-03  
Status: REPOSITORY-SIDE PREPARATION COMPLETE / REAL PROVIDER PROBE NOT AUTHORIZED  
Provider selected: NO  
Production ready claim: NO

## Purpose

This runbook defines the final repository-side boundary before Padiem Claw Cloud M1 makes a real sandbox-provider API call.

The implementation intentionally separates four different claims:

1. **research evidence** — official provider documentation;
2. **request-shape readiness** — a provider-specific launch profile can express the Cloud M1 safety constraints;
3. **live evidence** — a trusted provider probe actually observes every required control;
4. **provider acceptance** — the existing provider-neutral evidence and conformance gates accept the complete current evidence set.

A provider-specific request shape is never provider selection, security certification, deployment approval, or a Production-ready claim.

## Authority chain

```text
official documentation
        ↓
CloudM1ProviderLaunchProfile
(request shape only)
        ↓
SandboxProviderLiveProbePlan
(complete control coverage)
        ↓
AUTHORIZED real provider probe
        ↓
SandboxProviderLiveProbeResult
(trusted observations only)
        ↓
SandboxProviderEvidenceReview v2
(current + acceptance-grade evidence)
        ↓
SandboxProviderEvidencePack v1
        ↓
SandboxProviderConformanceGate
        ↓
separate provider selection / release authority
```

The repository does not currently implement the final provider-selection or Production-release authority.

## Global Cloud M1 launch invariants

Every candidate profile is fail-closed around the same provider-neutral requirements:

- execution mode must be `cloud`;
- an exact immutable `requested_revision` is mandatory;
- network policy must be `off`;
- TTL must be within both Cloud M1 policy and the candidate profile;
- a fresh ephemeral workspace is required for every run;
- persistent/shared storage is disabled for M1;
- secret injection is disabled for M1;
- snapshot/resume/cross-run reuse is disabled;
- public preview ports/tunnels are disabled;
- explicit teardown is mandatory.

The profile accepts no credential or provider endpoint field.

## Candidate request-shape profiles

### Modal

Required request shape:

- `block_network = true`;
- timeout bound to the Cloud M1 lease TTL;
- no Secret injection;
- no Volume/shared persistence;
- no snapshot reuse;
- no public tunnel.

Still requires live proof of the exact account/workspace configuration, disk/process hard limits, provider metadata blocking, and terminal teardown state.

### Daytona

Required request shape:

- `networkBlockAll = true`;
- explicit ephemeral lifecycle;
- wall-clock TTL bound to the Cloud M1 lease;
- no shared persistence;
- no secret injection;
- no snapshot reuse.

Still requires an exact sandbox class, a qualifying network-policy tier, process-limit proof, and provider metadata blocking proof.

### Runloop

Required request shape:

- an explicit deny-all Network Policy;
- a fresh Devbox for every run;
- no suspend/resume;
- no snapshot reuse;
- explicit teardown;
- no secret injection.

Still requires an exact Devbox size, a hard wall-clock TTL, process-limit proof, and provider metadata blocking proof.

### E2B

Required request shape:

- `allow_internet_access = false`;
- timeout terminal action is `kill`;
- no automatic resume;
- no snapshot reuse;
- no secret injection;
- no public ports.

Still requires the exact resource hard-limit contract, process-limit proof, provider metadata blocking proof, and terminal teardown proof.

## Live probe coverage

The live plan contains exactly one probe for every current `SandboxProviderCapabilities` control. Missing or duplicate controls are rejected before a result can be constructed.

Probe methods are intentionally separated:

- **in-sandbox negative tests** — network deny, egress enforcement, privileged runtime, mounts, runtime socket, provider metadata, inherited secrets, checkout hooks, private ports;
- **lifecycle observations** — server-owned lifecycle, dedicated workspace, no reuse, TTL, cancellation, teardown, audit correlation;
- **provider API observations** — CPU, memory, disk, and process hard-limit behavior;
- **artifact verification** — artifact allowlist/size and terminal-output bounds/sanitization;
- **adapter assertions** — exact revision materialization, image/snapshot provenance, and other composed adapter controls.

A provider marketing statement or documentation page is not substituted for a live observation.

## Result ingestion

A live probe operator records only:

- candidate identity;
- launch-profile reference;
- probe-plan reference;
- result reference;
- observed isolation primitive;
- one status/evidence reference/time window for every control.

Do not place any of the following in the result contract:

- API keys or tokens;
- raw provider responses;
- sandbox hostnames or provider endpoints;
- secret values;
- raw terminal output;
- raw repository content.

Each observation is converted to the existing `ProviderEvidenceBasis.LIVE_PROVIDER_PROBE` evidence row. `UNPROVEN`, `NOT_SUPPORTED`, stale, future, incomplete, or unknown-isolation evidence remains fail-closed.

## Exact external inputs required before the first real call

Repository-side preparation stops here. A real probe requires all of the following outside the repository:

1. explicit authorization to use one candidate provider account;
2. the exact provider account/workspace/project identity;
3. the exact commercial tier and sandbox class/size relevant to the candidate;
4. a credential delivered through the approved secret channel, never committed or pasted into evidence;
5. a designated non-Production probe environment;
6. operator approval for the one-time network/provider API call;
7. a current evidence timestamp and evidence-retention location.

Until those inputs exist:

```text
PROVIDER_ACCOUNT_AUTHORIZATION_CONFIGURED = false
PROVIDER_LIVE_PROBE_EXECUTION_CONFIGURED = false
provider_selected = false
deployment_approval = false
production_ready_claim = false
```

## First authorized probe sequence

When authorization exists, execute one candidate at a time:

1. instantiate the canonical candidate launch profile;
2. validate a Cloud M1 lease request with exact revision, network off, and bounded TTL;
3. resolve the exact external account/tier/class without copying credentials into repository artifacts;
4. instantiate the complete live-probe plan;
5. create one fresh disposable sandbox using the locked request shape;
6. execute every planned control probe and record trusted evidence references;
7. cancel/terminate the workload and prove terminal teardown;
8. construct `SandboxProviderLiveProbeResult`;
9. correlate result ↔ plan ↔ launch profile;
10. convert to `SandboxProviderEvidenceReview`;
11. reject if any acceptance blocker exists;
12. only then promote to the existing v1 evidence pack and run the provider-neutral conformance gate;
13. destroy remaining provider resources;
14. separately seek provider-selection and release approval.

A successful conformance result by itself still does not deploy Padiem Claw to Production.

## Repository implementation

Canonical module:

`apps/korean-ai-code-agent/src/kagent/sandbox_provider_probe.py`

Deterministic tests:

`apps/korean-ai-code-agent/tests/test_sandbox_provider_probe.py`

Research source:

`apps/korean-ai-code-agent/docs/cloud-m1/SANDBOX_PROVIDER_REVIEW_20260903.md`

Related authority gates:

- `sandbox_provider_review.py`
- `sandbox_provider_evidence.py`
- `sandbox_conformance.py`

Refs: #1405 #1456 #1562 #1569 #1611 #1624.
