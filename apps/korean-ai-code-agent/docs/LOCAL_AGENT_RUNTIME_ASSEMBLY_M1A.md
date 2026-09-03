# B54 Local Agent Runtime Assembly M1a

Issue: #1757  
Parent: #1633  
Related: #1634 #1635 #1636 #1755 #1569

Status: repository-side trust-boundary composition. No real broker or remote-control session is configured.

## Purpose

The Local Agent already had separate, tested implementations for device/session identity, local permissions, P01 execution approval, Windows subprocess execution and protected credential/pinned broker state. M1a composes those pieces into one execution boundary instead of creating another executor, policy engine or replay model.

```text
DeviceBinding + DeviceSession
        ↓ exact correlation
PinnedOutboundBrokerBinding
        ↓ current credential generation/ref fingerprint
LocalAgentDeviceProfile + DevicePermissionProfile
        ↓ exact selected root set
BoundLocalAgentRuntimeAssembly
        ↓
WindowsSubprocessLocalAgentRuntime
        ↓
P01LocalPermissionWindowsExecutionAuthorizationPort
        ↓ canonical P01 approval + recomputed local narrowing policy
bounded Windows execution receipt
        ↓
LocalAgentRuntimeAssemblyReceipt
```

## Authority ownership

M1a does not move authority boundaries.

```text
Device identity/session/replay admission = #1634
Local allow/ask/deny policy             = #1635
P01 Tool/Approval/Evidence              = canonical P01/Core authority
Physical Windows process execution      = existing Windows executor
Credential-at-rest + broker pinning      = #1755
M1a assembly                             = correlation + fail-closed composition only
```

## Construction gate

`BoundLocalAgentRuntimeAssembly` requires one exact current configuration:

- `LocalAgentDeviceProfile`;
- `DeviceBinding`;
- `DevicePermissionProfile`;
- `PinnedOutboundBrokerBinding`;
- a runtime implementing `execute_with_receipt` + `cancel`.

Construction rejects:

- device mismatch;
- workspace mismatch;
- permission root set different from the selected device root set;
- pinned broker binding/account/workspace/device/generation mismatch.

The permission root set is exact rather than a hidden superset/subset. A revoked root therefore requires rebuilding the assembly from the new trusted management snapshot.

## Execution gate

Before delegation to the Windows runtime:

1. binding lifecycle must permit execution;
2. credential must not be expired;
3. pinned broker credential generation/ref fingerprint must still match;
4. `DeviceSession` must be current;
5. session binding/device/account/workspace must exactly match;
6. request device must match;
7. request root must exist in both selected roots and current permission roots;
8. request timestamp cannot be in the future.

Blocked lifecycle states:

```text
UNPAIRED
REVOKED
CREDENTIAL_EXPIRED
UPDATE_REQUIRED
```

`PAIRED_OFFLINE` is not independently treated as a remote-online claim; a current valid `DeviceSession` is still required by `execute`. The real broker will remain responsible for truthful online/offline session creation.

## P01 and local policy are reused, not duplicated

The assembly does **not** decide whether a command is approved.

The configured `WindowsSubprocessLocalAgentRuntime` already calls `WindowsExecutionAuthorizationPort`. The real repository implementation `P01LocalPermissionWindowsExecutionAuthorizationPort`:

- resolves trusted authority evidence for the exact command fingerprint;
- recomputes the current local permission decision;
- rejects local `DENY`;
- validates the canonical P01 approval pause and verified decision;
- binds approval to the exact ToolInvocation digest;
- consumes the command fingerprint/decision once;
- issues only a short-lived exact Windows execution grant.

M1a simply preserves that path.

## Windows executor is reused

The existing `WindowsSubprocessLocalAgentRuntime` remains the physical executor and already enforces:

- Windows only;
- explicit executable profile allowlist;
- selected-root real-path containment;
- shell/script-host prohibition;
- `shell=False`;
- bounded environment allowlist;
- bounded stdout/stderr capture;
- timeout/cancellation;
- dirty-worktree observation;
- no admin elevation;
- no automatic Git network authority.

M1a does not create a second subprocess implementation.

## Bounded assembly receipt

`LocalAgentRuntimeAssemblyReceipt` records correlation/evidence-safe state only:

```text
assembly_ref
binding_ref
session_id
request_id
run_id
device_id
workspace_ref
root_ref
request_fingerprint
termination
executable_profile_ref
authorization_ref
started_at / ended_at
exit_code
dirty-worktree before/after
stdout/stderr character counts
```

Not included:

```text
raw argv
stdout body
stderr body
raw device credential
broker payload
client-authoritative approval state
```

The receipt verifies that the Windows receipt's request/run/device/root identity exactly matches the input request before it can be constructed.

## Cancellation ownership

While `execute` is active, the assembly records only:

```text
request_id -> exact session_id
```

`cancel` first revalidates the current binding/session and then refuses cancellation unless the exact session owns that active request. It delegates the actual process termination to the existing runtime.

This is request ownership for cancellation, **not a second network replay model**.

## Broker protocol non-scope

M1a intentionally does not define how a future Padiem broker serializes a `DeviceCommandEnvelope` into argv/cwd or transfers command payloads.

```text
BROKER_WIRE_PROTOCOL_INVENTED = NO
REPLAY_MODEL_DUPLICATED = NO
```

The #1634 pairing/session/command admission contract remains canonical. The physical HTTPS/WSS broker adapter is still future work.

## Deterministic CI gate

Tests use fake receipt runtimes and never execute a real process. They verify:

- valid execution delegates to the configured runtime;
- bounded receipt correlation;
- wrong session/account rejected before runtime;
- wrong request device rejected before runtime;
- unpaired/revoked/expired/update-required binding rejected;
- stale pinned credential generation rejected;
- permission/device root sets must exactly match;
- future request rejected;
- cancellation only by the exact owning session;
- no raw argv/stdout/stderr/credential in assembly receipt;
- no live broker/Production claim.

## Live gate

Before #1633/#1634 can be considered live-ready:

1. real trusted Padiem broker/control endpoint exists;
2. physical HTTPS/WSS transport is implemented against that endpoint;
3. trusted broker admission produces current `DeviceSession` and accepted command evidence;
4. broker command payload mapping to `LocalCommandRequest` is specified and cryptographically/integrity bound;
5. disposable Windows device validates DPAPI restart/rotation/revocation;
6. actual `P01LocalPermissionWindowsExecutionAuthorizationPort` evidence source is wired;
7. actual Windows executor runs a non-destructive approved command under a selected disposable root;
8. cancel/timeout/reconnect behavior is acceptance-tested;
9. bounded evidence/readback proves the exact command and result correlation;
10. explicit owner/live approval is obtained before any Production remote-control claim.

## Non-claims

```text
ONE_LOCAL_AGENT_RUNTIME_ASSEMBLY = YES
P01_AUTHORIZATION_REUSED = YES
WINDOWS_EXECUTOR_REUSED = YES
BROKER_WIRE_PROTOCOL_INVENTED = NO
REPLAY_MODEL_DUPLICATED = NO
RAW_CREDENTIAL_IN_ASSEMBLY_RECEIPT = NO
RAW_ARGV_IN_ASSEMBLY_RECEIPT = NO
RAW_STDOUT_STDERR_IN_ASSEMBLY_RECEIPT = NO
REAL_REMOTE_BROKER_CONFIGURED = NO
REAL_REMOTE_CONTROL_CONFIGURED = NO
REAL_USER_PC_EXECUTION_OVER_NETWORK = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
