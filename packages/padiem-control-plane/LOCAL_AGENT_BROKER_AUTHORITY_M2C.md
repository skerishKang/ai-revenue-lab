# Padiem Control Plane — Local Agent Broker Authority M2c

Issue: #1766  
Parent: #1634  
Related: #1633 #1760 #1763 #1569

Status: **repository-side server authority + structured-clone RPC facade only**.

No public Local Agent endpoint, durable broker persistence, Cloudflare deployment, or Production remote-control path is configured by this slice.

## Purpose

The Local Agent client already has:

- outbound-only transport contracts;
- TLS/443 endpoint pinning;
- Windows current-user DPAPI credential storage;
- canonical pairing/session/replay contracts;
- request fingerprinting;
- P01 execution evidence consumption;
- selected-root/local permission enforcement;
- Windows physical execution.

The missing server-side boundary was a trusted authority that can authenticate one device binding, issue a bounded device session, queue bounded command metadata, and produce exact admission evidence for the already-merged B54 request-integrity bridge.

M2c places that authority in `packages/padiem-control-plane`, consistent with Padiem ownership rules:

```text
account / workspace / device trust     = Control Plane
broker device session                  = Control Plane
broker command metadata + admission    = Control Plane
request materialization integrity      = B54 #1763
P01 approval / execution evidence      = P01 / Core #1760
local narrowing permission             = B54 #1635
physical Windows execution             = B54 Local Agent
model/provider routing                  = B14
```

## Core authority

`padiem_control_plane.local_agent_broker.InMemoryLocalAgentBrokerAuthority`
provides a deterministic server-side authority model for repository conformance.

It supports:

```text
register_binding
rotate_credential
revoke_binding
open_session
enqueue_command
poll
admit_command
acknowledge
```

The current implementation is intentionally in-memory. It defines lifecycle and trust semantics but is **not durable Production persistence**.

## Device credential rule

A raw device credential may exist transiently at an authenticated server boundary so possession can be verified, but the broker authority stores only:

```text
HMAC-SHA256(server_pepper, raw_device_credential)
```

Verification uses constant-time digest comparison.

Safe/public projections do not expose the keyed digest or raw credential.

```text
KEYED_DEVICE_CREDENTIAL_DIGEST_ONLY = YES
RAW_DEVICE_CREDENTIAL_PERSISTED = NO
```

A future deployed service must keep the server pepper in trusted secret storage. It must not move the pepper into a Local Agent client, browser bundle, queue payload, or database row.

## Binding and rotation

A broker binding is exact over:

```text
binding_ref
device_id
account_ref
workspace_ref
credential_generation
credential_digest
credential_expires_at
state
```

Credential rotation:

- requires the exact current generation at the trusted server operation;
- increments generation;
- replaces the keyed credential digest;
- invalidates all old sessions for that binding;
- does not reactivate a revoked binding.

Commands are also bound to the credential generation that existed when they were queued.

Therefore a command queued under generation 1 cannot be polled, admitted, or acknowledged through generation 2 after rotation.

```text
COMMAND_CREDENTIAL_GENERATION_BOUND = YES
```

This prevents a credential rotation from silently transferring previously queued execution authority to a new device credential generation.

## Broker session

A broker session is issued only after:

1. binding exists and is active;
2. credential has not expired;
3. transient credential verifies against the keyed digest;
4. account and workspace exactly match the binding.

The session captures the exact current credential generation and expires no later than either:

- the requested bounded session TTL; or
- the underlying device credential expiry.

Rotation/revocation invalidates old sessions.

## Command queue contents

`BrokerCommandRecord` deliberately stores only bounded command correlation:

```text
command_id
run_id
tool_request_ref
binding_ref
credential_generation
sequence
request_fingerprint
issued_at
expires_at
state
admission/evidence correlation after admission
```

It does **not** store:

```text
argv
cwd payload
file contents
raw device credential
P01 approval payload
model prompt/response
```

The broker command queue therefore does not itself define the future Local Agent command wire serializer.

## Sequence and replay

Sequence is monotonically allocated per binding.

A command ID is single-use in the authority state. Once a command transitions from `QUEUED` to `ADMITTED`, it cannot be admitted again. Once acknowledged, it cannot be acknowledged again through the normal transition.

This server-side authority is the future durable counterpart of #1634 command admission semantics. B54 #1763 does not maintain a competing replay set; it only verifies trusted admission evidence against the exact local request materialization.

## Poll

Poll requires:

- exact current binding credential;
- exact current broker session;
- current credential generation;
- non-negative `after_sequence`;
- bounded result count;
- queued and unexpired commands only.

Old-generation, admitted, acknowledged and expired commands are not returned.

## Admission

`admit_command` requires:

- current credential and current session;
- exact binding;
- exact current credential generation;
- `QUEUED` state;
- unexpired command;
- exact `request_fingerprint`;
- unique `admission_ref`;
- unique `evidence_ref`.

It returns `BrokerCommandAdmission`, whose bounded fields map directly to the semantics consumed by B54 #1763:

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
evidence_ref
accepted_at
expires_at
```

No argv is required in this admission evidence.

## Acknowledgement

Acknowledgement is allowed only after exact admission and requires the same:

- binding;
- current session;
- credential generation;
- command;
- admission ref;
- evidence ref.

Thus an arbitrary client boolean such as `done=true` cannot acknowledge a command without the server-side admission correlation.

## RPC facade

`padiem_control_plane.local_agent_broker_rpc.LocalAgentBrokerRpcFacade`
uses the existing Control Plane structured-clone facade pattern.

The facade:

- reconstructs timestamps and transient credential bytes;
- calls the canonical broker core;
- returns bounded dictionaries;
- converts canonical `ControlPlaneContractError` values to safe RPC errors;
- does not implement a second broker algorithm.

Credential material is accepted as base64 only as an RPC transport representation and is never echoed in the response.

## Why there is no public Worker yet

The Control Plane foundation CI explicitly keeps runtime side-effect clients out of `packages/padiem-control-plane`.

M2c therefore does not guess a public HTTP path or deploy a Worker.

A later physical adapter must decide and implement:

- durable state storage;
- authenticated device-facing HTTPS/WSS endpoint;
- server secret storage;
- rate limiting / abuse controls;
- deployment binding;
- observability and rollback;
- actual command-material delivery protocol.

The existing contact-verification architecture remains the reference separation: canonical core/RPC in the package, physical Worker adapter outside the foundation semantics.

## Important remaining command-material gap

The broker queue currently stores `request_fingerprint`, not raw argv or file contents. This is intentional for M2c.

A real remote execution path still needs a trusted command-material resolver or authenticated wire payload that supplies the actual `LocalCommandRequest` material to the device and then proves that the resulting request hashes to the queued fingerprint before execution.

B54 #1763 already supplies the final integrity check once that materialization exists.

Therefore:

```text
REMOTE_COMMAND_METADATA_AUTHORITY = YES
REMOTE_COMMAND_MATERIAL_DELIVERY = NO
REAL_REMOTE_EXECUTION = NO
```

## Deterministic acceptance

Repository tests cover:

- keyed digest only / no raw credential projection;
- wrong credential failure;
- account/workspace mismatch failure;
- session bounded by credential expiry;
- monotonic command sequence and poll cursor;
- exact request fingerprint admission;
- admission replay rejection;
- acknowledgement only after exact admission;
- acknowledgement correlation and replay rejection;
- credential rotation invalidates old sessions/credential;
- old-generation queued command cannot move to new generation;
- revocation blocks sessions/poll;
- expired commands are not delivered/admitted;
- structured-clone RPC round trip;
- malformed credential transport is safely rejected;
- no live/deployment claims.

## Source-of-truth status

```text
SERVER_SIDE_LOCAL_AGENT_BROKER_AUTHORITY = YES
KEYED_DEVICE_CREDENTIAL_DIGEST_ONLY = YES
BOUND_BROKER_SESSION = YES
MONOTONIC_COMMAND_SEQUENCE = YES
COMMAND_CREDENTIAL_GENERATION_BOUND = YES
EXACT_REQUEST_FINGERPRINT = YES
ADMISSION_BEFORE_ACK = YES
STRUCTURED_CLONE_SAFE_LOCAL_AGENT_BROKER_RPC = YES
RAW_ARGV_IN_BROKER_COMMAND = NO
RAW_DEVICE_CREDENTIAL_PERSISTED = NO
RAW_DEVICE_CREDENTIAL_RETURNED = NO
P01_AUTHORITY_DUPLICATED = NO
PUBLIC_HTTP_ENDPOINT = NO
PUBLIC_HTTP_AUTHENTICATION_IMPLEMENTED = NO
DURABLE_BROKER_PERSISTENCE_CONFIGURED = NO
PRODUCTION_DEPLOYMENT = NO
REAL_REMOTE_EXECUTION = NO
PRODUCTION_READY = NO
```
