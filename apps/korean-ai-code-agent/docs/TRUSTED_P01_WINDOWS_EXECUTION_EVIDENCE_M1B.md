# B54 Trusted P01 Windows Execution Evidence M1b

Issue: #1760  
Parent: #1633  
Related: #1634 #1635 #1755 #1757 #1569

Status: repository-side trusted-evidence adapter. No real P01 remote client, broker or Production remote-control session is configured.

## Purpose

The Windows Local Agent authorization path already had the canonical final validator:

```text
P01LocalPermissionWindowsExecutionAuthorizationPort
```

but its evidence source defaulted to an unconfigured port. M1b fills only that repository-side adapter boundary.

It does **not** create a second approval service or database.

```text
trusted product/control-plane caller
        ↓ already-authenticated evidence
TrustedP01WindowsExecutionEvidenceClient
        ↓ exact command fingerprint lookup
TrustedP01WindowsExecutionAuthorityEvidencePort
        ↓ authority/correlation checks
WindowsExecutionAuthorityEvidence
        ↓
P01LocalPermissionWindowsExecutionAuthorizationPort
        ↓ canonical P01 + recomputed local policy
TrustedWindowsExecutionGrant
```

## Canonical authority remains P01/Core

`padiem_ai_core.agent_approval.VerifiedApprovalDecision` explicitly defines itself as evidence that has already been authenticated by a trusted product/control-plane caller before construction.

Therefore B54 must not infer approval from a client boolean, a Local Agent message, a browser payload, or a local permission ALLOW rule.

M1b only accepts canonical Core objects:

- `ApprovalPause`
- `VerifiedApprovalDecision`

and does not introduce alternate approval types.

## Trusted envelope

`TrustedP01WindowsExecutionEvidenceEnvelope` contains:

```text
evidence_ref
request_fingerprint
ApprovalPause
VerifiedApprovalDecision
LocalPermissionRequest[]
local_policy_ref
expires_at
```

It intentionally does not contain:

```text
raw argv
raw device credential
bearer/access/refresh token
actor browser session payload
approval UI payload
```

## Correlation rules

The envelope fails closed unless:

1. request fingerprint is a lowercase SHA-256 digest;
2. pause tool is exactly `local.process.execute`;
3. decision belongs to the exact pause;
4. decision `evidence_ref` equals the envelope `evidence_ref`;
5. each local permission request has the same run as the pause;
6. each local permission request targets the exact command fingerprint;
7. each capability appears at most once;
8. evidence expiry is after the decision;
9. evidence expiry does not outlive the canonical P01 pause.

The authority adapter additionally requires:

```text
returned fingerprint == requested fingerprint
VerifiedApprovalDecision.authority_ref == pinned expected P01 authority ref
```

The caller cannot override the expected authority per request.

## What M1b does not validate twice

M1b does not duplicate the final P01 approval lifecycle or local execution policy.

The existing `P01LocalPermissionWindowsExecutionAuthorizationPort` remains responsible for:

- exact LocalCommandRequest fingerprint validation;
- exact request/run/device/root correlation;
- recomputing current `DevicePermissionProfile` policy;
- rejecting local `DENY`;
- binding the pause to the exact canonical ToolInvocation digest;
- checking approval scope against executable capabilities;
- requiring `ApprovalOutcome.APPROVED`;
- resolving canonical pause/decision lifecycle and expiry;
- rejecting replayed command fingerprints and approval decisions;
- issuing a short-lived exact Windows execution grant.

A denied P01 decision is never promoted by M1b.

## Client boundary

`TrustedP01WindowsExecutionEvidenceClient` is a dependency-injected protocol only.

The default implementation is deliberately unconfigured and fails closed:

```text
REAL_P01_REMOTE_EVIDENCE_CLIENT_CONFIGURED = NO
```

No HTTP URL, authentication token, database table, RPC method or Production endpoint is guessed in this slice.

A future real implementation must live behind a trusted Padiem service/control-plane boundary and authenticate its own service/session before constructing the canonical evidence envelope.

## Deterministic CI

`DeterministicTrustedP01WindowsExecutionEvidenceClient` is test-only and network-free.

Tests cover:

- exact fingerprint lookup;
- pinned P01 authority;
- unknown fingerprint fail-closed;
- wrong returned fingerprint fail-closed;
- wrong P01 authority fail-closed;
- invalid client return type fail-closed;
- wrong tool/pause/evidence correlation rejection;
- mixed run/fingerprint local permission evidence rejection;
- evidence TTL cannot exceed the P01 pause;
- full integration with existing P01/local Windows authorization;
- approval decision replay remains blocked by the existing authorization adapter;
- denied P01 decision remains denied;
- safe projection excludes raw execution/credential/session payloads.

## Live gate

Before a real Local Agent execution path can use this adapter remotely:

1. canonical P01/Product approval persistence/read authority must be identified;
2. a trusted service-to-service evidence read contract must be defined;
3. caller authentication and authorization must be implemented outside the Local Agent client;
4. exact run/request/tool/actor/workspace evidence ownership must be enforced by that trusted service;
5. transport must return canonical `ApprovalPause` and `VerifiedApprovalDecision` semantics without client-minted authority;
6. a disposable Windows acceptance run must prove approved execution succeeds and denied/revoked/expired/replayed evidence fails;
7. result evidence must remain bounded;
8. explicit live/Production approval is still required.

## Non-claims

```text
TRUSTED_P01_EVIDENCE_ADAPTER = YES
P01_AUTHORITY_PINNED = YES
EXACT_FINGERPRINT_LOOKUP = YES
PAUSE_DECISION_EVIDENCE_CORRELATION = YES
LOCAL_PROCESS_TOOL_PINNED = YES
RAW_ARGV_IN_EVIDENCE_ENVELOPE = NO
RAW_CREDENTIAL_IN_EVIDENCE_ENVELOPE = NO
CLIENT_APPROVAL_AUTHORITY = NO
P01_POLICY_DUPLICATED = NO
REAL_P01_REMOTE_CLIENT = NO
REAL_REMOTE_BROKER = NO
REAL_USER_PC_EXECUTION_OVER_NETWORK = NO
PRODUCTION_MUTATION = NO
PRODUCTION_READY = NO
```
