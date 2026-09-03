# B54 Local Agent Command Admission → Request Integrity Binding M2b

Issue: #1763  
Parent: #1634  
Related: #1633 #1757 #1760 #1569

Status: repository-side integrity/correlation bridge only. No real broker transport or Production remote-control path is configured.

## Purpose

The canonical Local Agent pairing layer already defines `DeviceCommandEnvelope` and owns command admission semantics such as expiry, replay rejection and monotonically increasing sequence. The Local Agent runtime assembly already owns the bounded physical execution path.

M2b closes the gap between those two layers:

```text
#1634 DeviceCommandEnvelope
        ↓ trusted broker/control-plane admission
TrustedDeviceCommandAdmissionEvidence
        ↓ exact command_id + recomputed request fingerprint
AdmittedLocalAgentExecutionBridge
        ↓ exact session/binding/run/tool_request/sequence/time correlation
BoundLocalAgentRuntimeAssembly
        ↓ existing P01/local authorization
existing Windows executor
```

The bridge proves that the `LocalCommandRequest` physically delegated to the Local Agent assembly is the same materialization that trusted command-admission evidence was issued for.

## Authority ownership is unchanged

```text
pairing/session identity       = #1634
command replay rejection       = #1634
monotonic command sequence      = #1634
command envelope expiry         = #1634
request materialization binding = M2b
P01 execution approval          = canonical P01/Core
local narrowing permissions     = #1635
physical Windows execution      = existing Windows executor
```

M2b deliberately does not maintain a replay set and does not consume sequence numbers.

```text
REPLAY_MODEL_DUPLICATED = NO
```

## Request fingerprint

Immediately before trusted admission evidence is read, M2b recomputes the existing canonical Windows request fingerprint from the actual `LocalCommandRequest`.

That fingerprint already binds:

```text
request_id
run_id
device_id
root_ref
argv
cwd_relative
requested_at
timeout_seconds
shell = false
admin_elevation = false
```

The fingerprint rather than raw argv is carried in trusted admission evidence.

Changing argv, cwd, root, timeout, request id, run, device or materialization time changes the fingerprint and causes exact evidence lookup to fail.

## Trusted admission evidence

`TrustedDeviceCommandAdmissionEvidence` contains only bounded correlation state:

```text
admission_ref
authority_ref
command_id
session_id
binding_ref
run_id
tool_request_ref
sequence
request_fingerprint
accepted_at
expires_at
```

It does not contain:

```text
raw argv
raw file contents
raw device credential
broker bearer/token payload
P01 approval payload
```

The injected `TrustedDeviceCommandAdmissionClient` is responsible only for reading already-authenticated broker/control-plane evidence. The default implementation is unconfigured and fails closed.

## Exact correlation gate

Before delegating to the runtime assembly, M2b requires:

1. `DeviceSession` is current;
2. `DeviceCommandEnvelope` is currently valid;
3. command binding equals session binding;
4. command run equals materialized request run;
5. request device equals session device;
6. request materialization cannot predate the command envelope;
7. request materialization cannot be in the future or at/after command expiry;
8. actual `LocalCommandRequest` fingerprint is recomputed;
9. trusted admission evidence is resolved by exact `command_id + request_fingerprint`;
10. evidence authority equals the pinned expected admission authority;
11. evidence command/session/binding/run/tool_request_ref/sequence all exactly match;
12. evidence fingerprint equals the recomputed request fingerprint;
13. evidence acceptance cannot predate the command envelope;
14. evidence acceptance cannot predate request materialization;
15. evidence acceptance cannot be from the future;
16. evidence expiry cannot exceed command expiry;
17. evidence itself must still be current.

Only then does the bridge call the already-merged Local Agent runtime assembly.

## Result correlation

After assembly execution, M2b validates that the returned `LocalAgentRuntimeAssemblyReceipt` still contains the exact:

```text
session_id
binding_ref
request_id
run_id
request_fingerprint
```

The final `AdmittedLocalCommandExecutionReceipt` contains bounded correlation only and does not reproduce argv/stdout/stderr/credentials/broker payload.

## Why there is no second replay model

`local_agent_pairing.py` already performs canonical admission:

- the session must exist and be current;
- the device binding must be `ONLINE`;
- binding correlation is required;
- command issue/expiry is validated;
- command IDs are replay-protected;
- sequence must increase monotonically.

A real broker/control-plane adapter must call or faithfully preserve that canonical admission authority before issuing `TrustedDeviceCommandAdmissionEvidence`.

M2b only verifies evidence from that authority against the local request materialization. Repeating replay state locally here would create two competing authorities, so it is intentionally absent.

## No broker wire protocol

This slice does not define JSON, protobuf, HTTP paths, WebSocket message frames, queue schemas or how raw argv is serialized over a network.

```text
BROKER_WIRE_PROTOCOL_INVENTED = NO
```

A future real transport must map its authenticated command payload to the canonical `DeviceCommandEnvelope` and `LocalCommandRequest` while preserving the exact correlation rules above.

## Deterministic CI

Tests use only deterministic evidence clients and fake runtime assemblies. They cover:

- valid exact command/request admission and delegation;
- changed argv changes the fingerprint and fails before execution;
- wrong admission authority;
- wrong session/binding/run;
- wrong tool request ref;
- wrong sequence;
- command/evidence expiry narrowing;
- request cannot predate command;
- request cannot be future or at command expiry;
- admission cannot predate local request materialization;
- invalid/unconfigured evidence client;
- assembly receipt fingerprint mismatch;
- bounded safe projections;
- explicit non-live/non-authority constants.

No real Windows process or remote network broker is used in CI.

## Live gate

Before #1634 can be considered live transport-ready:

1. real trusted Padiem broker/control endpoint must exist;
2. service/device authentication must be implemented;
3. canonical #1634 pairing/session/command admission must back the service;
4. real admission evidence client/transport must be implemented without client-minted authority;
5. network command payload → `DeviceCommandEnvelope` + `LocalCommandRequest` materialization must preserve this exact integrity binding;
6. reconnect/replay/rotation/revocation must be acceptance-tested on a disposable Windows device;
7. P01 trusted evidence path from #1760 must be live-wired;
8. approved non-destructive command, denied command, modified payload, expired command and replay cases must be demonstrated;
9. bounded result/evidence readback must be captured;
10. explicit live/Production approval is still required.

## Non-claims

```text
COMMAND_REQUEST_INTEGRITY_BINDING = YES
REQUEST_FINGERPRINT_RECOMPUTED = YES
SESSION_BINDING_RUN_EXACT = YES
TOOL_REQUEST_REF_EXACT = YES
SEQUENCE_EXACT = YES
COMMAND_EXPIRY_NOT_WIDENED = YES
REPLAY_MODEL_DUPLICATED = NO
BROKER_WIRE_PROTOCOL_INVENTED = NO
RAW_ARGV_IN_ADMISSION_EVIDENCE = NO
CLIENT_ADMISSION_AUTHORITY = NO
REAL_REMOTE_BROKER = NO
REAL_USER_PC_EXECUTION_OVER_NETWORK = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
