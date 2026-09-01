# P01 Engine Idempotency Activation Blockers v1

## Authority

Issue: #1235 — `[P01][Engine Runtime] Wire trusted idempotency adapter for orchestration execution`

This document records the repository-side closeout boundary after the source-only #1235 slices that added the Engine durable idempotency adapter boundary, D1 schema contract, stale reservation expiry recovery, and idempotency-bound resume regression coverage.

## Current disposition

```text
IDEMPOTENCY_ADAPTER_BOUNDARY = SOURCE_PRESENT
D1_SCHEMA_CONTRACT = SOURCE_PRESENT
STALE_RESERVATION_EXPIRY_RECOVERY = SOURCE_PRESENT
IDEMPOTENT_RESUME_GATE = SOURCE_PRESENT
MANIFEST_IDEMPOTENCY_REPLAY = DEFERRED
PRODUCTION_ACTIVATION = NOT_DONE
ISSUE1235_CLOSE = NO
```

## Completed repository-side slices

```text
PR1335 = ENGINE_IDEMPOTENCY_DURABLE_BINDING_ADAPTER
PR1338 = ENGINE_IDEMPOTENCY_D1_SCHEMA_CONTRACT
PR1341 = ENGINE_IDEMPOTENCY_EXPIRY_RECOVERY
PR1353 = ENGINE_IDEMPOTENT_RESUME_GATE_TEST
```

These slices are allowed to exist before production activation because they do not provision D1, mutate Cloudflare bindings, deploy, or mark the public Engine manifest as available.

## Required activation blockers

The Engine manifest must keep idempotency replay deferred until all blockers below are satisfied by a separately authorized activation change.

```text
BLOCKER_1_PRODUCTION_D1_BINDING_PROVISIONED = REQUIRED
BLOCKER_2_D1_SCHEMA_APPLIED_TO_TARGET_ENVIRONMENT = REQUIRED
BLOCKER_3_WORKER_BINDING_NAME_ENGINE_IDEMPOTENCY_CONFIRMED = REQUIRED
BLOCKER_4_ADAPTER_READ_WRITE_SMOKE_AGAINST_BOUND_DURABLE_STORE = REQUIRED
BLOCKER_5_CROSS_APP_REPLAY_ISOLATION_SMOKE = REQUIRED
BLOCKER_6_CONFLICTING_FINGERPRINT_FAIL_CLOSED_SMOKE = REQUIRED
BLOCKER_7_FAILURE_ABORT_RELEASE_SMOKE = REQUIRED
BLOCKER_8_STALE_RESERVATION_EXPIRY_RECOVERY_SMOKE = REQUIRED
BLOCKER_9_PAUSE_RESUME_NO_SECOND_LOGICAL_RUN_SMOKE = REQUIRED
BLOCKER_10_MANIFEST_AVAILABLE_CHANGE_SEPARATE_PR = REQUIRED
```

## Forbidden before activation

```text
MANIFEST_IDEMPOTENCY_REPLAY_AVAILABLE = FORBIDDEN
EXECUTION_IDEMPOTENCY_REPLAY_COMPLETED_AVAILABLE = FORBIDDEN
EXECUTION_IDEMPOTENCY_REPLAY_STREAMING_AVAILABLE = FORBIDDEN
PROCESS_LOCAL_FAKE_PRODUCTION_STORE = FORBIDDEN
B62_IDEMPOTENCY_AUTHORITY = FORBIDDEN
B14_IDEMPOTENCY_AUTHORITY = FORBIDDEN
PRODUCTION_D1_PROVISIONING_IN_SOURCE_ONLY_SLICE = FORBIDDEN
WRANGLER_BINDING_MUTATION_IN_SOURCE_ONLY_SLICE = FORBIDDEN
```

## Closeout rule

#1235 remains open until a future production-activation PR proves the blockers above and then updates the Engine manifest from `deferred` to `available` only for the capabilities that are actually wired at the real Worker boundary.

```text
REPLAY != RERUN
RESUME != NEW_RUN
IDEMPOTENCY_KEY != AUTHORIZATION
SOURCE_PRESENT != AVAILABLE
```
