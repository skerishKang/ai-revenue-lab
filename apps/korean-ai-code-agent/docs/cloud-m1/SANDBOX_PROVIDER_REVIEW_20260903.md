# Padiem Claw Cloud M1 — Sandbox Provider Research Review

Date: 2026-09-03
Status: RESEARCH REVIEW ONLY
Provider selected: NO
Live provider probe completed: NO
Production ready claim: NO

## Purpose

This review records official-documentation evidence for potential Cloud M1 sandbox providers. It does not convert documentation claims into accepted `SandboxProviderCapabilities`, does not choose a vendor, and does not authorize a provider account, credential, external write, deployment, or Production release.

The authoritative Cloud M1 control set remains the provider-neutral `SandboxProviderCapabilities` / `SandboxProviderConformanceGate` contract. Final promotion requires current acceptance-grade evidence through the v2 provider evidence review gate and then the existing v1 evidence pack.

## Evidence rule

```text
official documentation
    ↓
research evidence only
    ↓
provider adapter prototype + deterministic harness
    ↓
trusted live provider probe / trusted provider attestation
    ↓
complete current v1 evidence pack
    ↓
provider-neutral Cloud M1 conformance gate
```

Documentation-only evidence is never sufficient for provider selection.

## Candidate summary

| Candidate | Isolation evidence | Network control evidence | Lifecycle/resource evidence | Current research disposition |
| --- | --- | --- | --- | --- |
| Modal | gVisor sandbox runtime | full outbound block, CIDR allowlist, domain allowlist | hard CPU/memory limits, maximum lifetime timeout, terminate APIs | Strong live-probe candidate; disk/process/metadata and complete teardown evidence still need acceptance-grade proof |
| Daytona | isolated sandbox with dedicated kernel/filesystem/network stack; container and VM classes documented | strict block-all / CIDR / domain policy on applicable tiers | wall-clock TTL, allocated CPU/RAM/disk, explicit delete/ephemeral options | Strong live-probe candidate; selected sandbox class/tier and no-reuse/teardown semantics must be proven exactly |
| Runloop | dedicated MicroVM / VM-based Devbox isolation | deny-all and hostname allowlists through Network Policies | configurable CPU/memory/storage; shutdown/suspend lifecycle | Strong live-probe candidate; M1 must force an explicit deny-all policy and prove hard wall-clock lifetime/process/teardown controls |
| E2B | Firecracker microVM | current SDK documents `allow_internet_access=False`, equivalent to deny-out for all IPv4 | timeout with kill default, explicit kill, CPU/memory/disk metrics | Strong live-probe candidate after current SDK update; resource hard-limit, metadata, process, artifact and exact teardown controls still need proof |

## Modal

Official sources reviewed:

- https://modal.com/docs/guide/sandbox-networking
- https://modal.com/docs/sdk/py/latest/Sandbox
- https://modal.com/docs/guide/custom-container
- https://modal.com/docs/guide/restricted-access

Current official evidence supports:

- Sandboxes use gVisor-based isolation.
- A Sandbox does not have inbound access or access to other Modal workspace resources by default.
- `block_network=True` drops all outbound traffic.
- CIDR allowlists and domain allowlists are available.
- CPU and memory can have hard limits.
- Sandbox maximum lifetime timeout and idle timeout are available.

Cloud M1 constraints if prototyped:

- use the stable Sandbox path rather than depending on V2 Beta features unless separately accepted;
- `block_network=True` for M1 network-off phase;
- no Modal Secret injection, Volume, NetworkFileSystem, CloudBucketMount, tunnel, proxy, OIDC token, or snapshot reuse unless a later policy explicitly permits it;
- exact CPU/memory limits and <= Cloud M1 TTL;
- fresh per-run Sandbox and explicit termination/teardown evidence.

Unproven at this research stage include complete provider-side disk/process limits, provider metadata blocking, and end-to-end B54 artifact/output controls. Those may be implemented partly by the B54 adapter, but they still require acceptance-grade evidence.

## Daytona

Official sources reviewed:

- https://www.daytona.io/docs/en/sandboxes/
- https://www.daytona.io/docs/en/network-limits/
- https://www.daytona.io/docs/en/persistence/
- https://www.daytona.io/docs/en/tools/cli/

Current official evidence supports:

- isolated sandboxes with dedicated kernel, filesystem, network stack, and allocated CPU/RAM/disk; multiple sandbox classes exist, including container and VM classes;
- outbound `networkBlockAll`, CIDR allowlists, and domain allowlists;
- strict sandbox-level block/allow behavior depends on the relevant organization tier, so the accepted commercial/tier configuration must be explicit;
- wall-clock TTL destroys the Sandbox even while stopped, paused, or archived;
- CPU, memory, and disk sizing are explicit;
- sandboxes are persistent by default, with explicit ephemeral/delete lifecycle options.

Cloud M1 constraints if prototyped:

- choose and record an exact sandbox class and qualifying tier;
- force block-all at creation;
- set wall-clock TTL <= Cloud M1 policy;
- use no volume/shared persistence and no cross-run reuse;
- explicitly delete/teardown the sandbox and verify terminal state;
- keep secrets out of the sandbox for M1 even though Daytona supports managed secret facilities.

The default persistence model is not acceptable for Cloud M1 without the adapter explicitly forcing ephemeral/no-reuse behavior.

## Runloop

Official sources reviewed:

- https://docs.runloop.ai/docs/devboxes/overview
- https://docs.runloop.ai/docs/devboxes/blueprints/network-policies
- https://docs.runloop.ai/docs/devboxes/start-stop
- https://docs.runloop.ai/docs/devboxes/configuration/sizes
- https://runloop.ai/security-compliance

Current official evidence supports:

- VM/microVM-based isolated Devboxes; Runloop describes dedicated MicroVM isolation on its security material;
- deny-all and hostname-allowlist Network Policies;
- network access is allow-all when no policy is specified, so Cloud M1 must never rely on the provider default;
- configurable CPU, memory, and storage sizes;
- shutdown/suspend lifecycle and ephemeral Devbox workflows.

Cloud M1 constraints if prototyped:

- create an explicit deny-all Network Policy before Devbox execution and bind it at creation;
- never accept missing/default network policy;
- no suspend/resume or snapshot reuse in M1;
- explicit shutdown/teardown evidence;
- prove a hard maximum lifetime bound rather than relying only on idle lifecycle;
- prove remaining process/resource/artifact/output controls through the adapter and live evidence.

## E2B

Official sources reviewed:

- https://e2b.dev/
- https://e2b.dev/docs/sdk-reference/python-sdk/v2.15.2/sandbox_async

Current official evidence supports:

- each Sandbox is backed by a Firecracker microVM;
- the current Python SDK exposes `allow_internet_access=False`; documentation states this is equivalent to an outbound deny rule covering all IPv4;
- timeout is available and the default timeout lifecycle kills the Sandbox;
- explicit Sandbox kill exists;
- Sandbox metrics expose CPU, memory, and disk usage;
- snapshots can persist beyond sandbox deletion, so snapshot creation/reuse must remain disabled in Cloud M1.

This supersedes an earlier research note that E2B outbound deny controls were unproven. The current SDK documentation now supplies explicit network-deny evidence. It remains research evidence, not a live conformance result.

Cloud M1 constraints if prototyped:

- `allow_internet_access=False` and no automatic resume;
- timeout lifecycle must remain `kill`, not pause;
- no snapshots/persistent reuse;
- prove exact hard CPU/memory/disk/process constraints if used for M1;
- prove provider metadata blocking and the full teardown/artifact/output control set through current live evidence.

## What this review does not prove

The review does not prove any candidate satisfies all of these existing Cloud M1 controls:

- exact revision materialization and checkout hook suppression;
- privileged-runtime, host-mount and runtime-socket restrictions;
- provider metadata blocking;
- no inherited host secrets;
- per-run dedicated workspace and no reuse;
- CPU, memory, disk and process hard limits as required by the exact adapter configuration;
- cancellation kills workload and teardown is guaranteed;
- artifact allowlist/size limits;
- terminal output bound/sanitization;
- image/snapshot provenance;
- run/lease/audit correlation;
- private preview ports.

Some controls are provider-native and some are B54-adapter responsibilities. Final acceptance requires evidence for the composed provider + adapter behavior, not product marketing or documentation in isolation.

## Next gate

No provider is selected yet. The next safe step is to build one provider-specific, network-free/dry adapter contract prototype for the leading candidates, starting with request-shape validation only. A real provider call requires separate account authorization and current trusted live probes.

Refs: #1405 #1456 #1562 #1569 #1611.
