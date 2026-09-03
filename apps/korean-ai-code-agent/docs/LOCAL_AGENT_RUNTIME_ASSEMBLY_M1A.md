# B54 Local Agent Runtime Assembly M1a

Issue: #1757  
Parent: #1633  
Related: #1634 #1635 #1636 #1755 #1569

Status: repository-side trust-boundary composition. No real broker or remote-control session is configured.

## Purpose

M1a composes the Local Agent trust pieces already present on main instead of creating another executor, approval engine, permission model or replay model.

```text
DeviceBinding + DeviceSession
        ↓ exact identity + ONLINE lifecycle
PinnedOutboundBrokerBinding
        ↓ exact credential generation/ref fingerprint
LocalAgentDeviceProfile + DevicePermissionProfile
        ↓ exact selected root set
BoundLocalAgentRuntimeAssembly
        ↓
WindowsSubprocessLocalAgentRuntime
        ↓
P01LocalPermissionWindowsExecutionAuthorizationPort
        ↓ canonical P01 approval + recomputed local narrowing policy
WindowsExecutionReceipt
        ↓
LocalAgentRuntimeAssemblyReceipt
```

## Authority ownership

```text
Device identity/session/replay admission = #1634
Local allow/ask/deny policy             = #1635
P01 Tool/Approval/Evidence              = canonical P01/Core authority
Physical Windows execution             = existing Windows executor
Credential-at-rest + broker pinning     = #1755
M1a                                     = correlation + fail-closed composition
```

## Construction gate

The assembly requires:

- one `LocalAgentDeviceProfile`;
- one `DeviceBinding`;
- one `DevicePermissionProfile`;
- one `PinnedOutboundBrokerBinding`;
- one receipt-capable Windows runtime.

Construction rejects device/workspace mismatch, a permission root set different from the selected device root set, and pinned broker binding/account/workspace/device/credential-generation mismatch.

The root set is exact. After a trusted root revoke/add change, callers must rebuild the assembly from the new management snapshot instead of continuing with stale hidden authority.

## ONLINE is mandatory for execution

The canonical #1634 pairing implementation changes the binding to `ONLINE` when a device successfully connects. Its `accept_command()` path also requires `DeviceLifecycle.ONLINE`.

M1a therefore applies the same lifecycle rule:

```text
ONLINE         -> eligible for further session/request validation
PAIRED_OFFLINE -> execution refused
UNPAIRED       -> execution refused
REVOKED        -> execution refused
CREDENTIAL_EXPIRED -> execution refused
UPDATE_REQUIRED    -> execution refused
```

A structurally unexpired `DeviceSession` by itself cannot override an offline or otherwise blocked binding state.

## Execution gate

Before delegating to the Windows runtime:

1. binding state must be exactly `ONLINE`;
2. pinned broker authority must still match the exact current binding credential generation/ref fingerprint;
3. credential must be current;
4. `DeviceSession` must be current;
5. session binding/device/account/workspace must exactly match;
6. request device must match;
7. request root must exist in the selected device roots;
8. the same root must exist in the current permission profile;
9. request timestamp cannot be in the future.

Only after those checks does the assembly call the configured runtime.

## P01/local permission authority is reused

The assembly does **not** approve a command.

The existing real repository authorization adapter, `P01LocalPermissionWindowsExecutionAuthorizationPort`, already:

- resolves trusted evidence for the exact command fingerprint;
- recomputes the current local permission decision;
- refuses local `DENY`;
- verifies canonical P01 approval pause/decision;
- binds approval to the exact canonical ToolInvocation digest;
- consumes approval/command authority once;
- issues a short-lived exact Windows execution grant.

M1a preserves that path unchanged.

## Windows executor is reused

`WindowsSubprocessLocalAgentRuntime` remains the physical executor. Its existing protections include explicit executable profiles, selected-root real-path containment, blocked shell/script hosts, `shell=False`, bounded environment inheritance, bounded output capture, timeout/cancellation, dirty-worktree observation, no admin elevation and no automatic Git network authority.

## Bounded assembly receipt

`LocalAgentRuntimeAssemblyReceipt` contains only bounded correlation/result metadata:

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

It does not contain:

```text
raw argv
stdout body
stderr body
raw device credential
broker payload
client-authoritative approval state
```

The assembly also verifies that the executor receipt's request/run/device/root identity exactly equals the original request before constructing this receipt.

## Cancellation ownership

While a request is active, the assembly tracks only:

```text
request_id -> exact session_id
```

Cancellation revalidates the current ONLINE binding/session and refuses any request that is not owned by that exact session, then delegates process termination to the existing runtime.

This is cancellation ownership only; it is not a second command replay/admission model.

## Broker protocol remains out of scope

M1a intentionally does not define how a future Padiem broker maps a `DeviceCommandEnvelope` into `LocalCommandRequest` argv/cwd material.

```text
BROKER_WIRE_PROTOCOL_INVENTED = NO
REPLAY_MODEL_DUPLICATED = NO
```

The #1634 command/session replay contract remains canonical. A future physical HTTPS/WSS broker adapter must integrity-bind the admitted command envelope to the materialized local request before this assembly is used remotely.

## Deterministic CI gate

Tests verify:

- valid ONLINE execution delegates to the configured receipt runtime;
- bounded receipt correlation;
- wrong account/session or request device fails before runtime;
- `PAIRED_OFFLINE` fails even with a structurally current session;
- unpaired/revoked/credential-expired/update-required fail;
- stale pinned credential generation fails;
- selected-root and permission-root sets must exactly match;
- future request fails;
- cancellation only by the exact owning session;
- no raw argv/stdout/stderr/device credential in the assembly receipt;
- no real broker/Production claim.

CI uses fake receipt runtimes only. It does not execute a real Windows process.

## Live gate

Before #1633/#1634 can be called live-ready:

1. deploy the canonical trusted Padiem Local Agent broker/control endpoint;
2. implement the physical HTTPS/WSS adapter;
3. obtain broker-issued current `DeviceSession` and canonical command admission evidence;
4. define and integrity-bind the admitted `DeviceCommandEnvelope` to the resulting `LocalCommandRequest`;
5. validate Windows DPAPI restart/rotation/revoke on a disposable device;
6. wire the real trusted P01 authority evidence source;
7. execute one non-destructive approved command under a disposable selected root;
8. test cancel/timeout/offline/reconnect/replay behavior;
9. capture bounded evidence/readback;
10. obtain explicit live/Production approval before any Production remote-control claim.

## Non-claims

```text
ONE_LOCAL_AGENT_RUNTIME_ASSEMBLY = YES
ONLINE_BINDING_REQUIRED = YES
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
