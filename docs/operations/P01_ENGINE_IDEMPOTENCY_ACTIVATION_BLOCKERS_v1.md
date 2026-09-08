# P01 Engine Idempotency Activation Blockers v1

## Authority

Issue: #1235 — `[P01][Engine Runtime] Wire trusted idempotency adapter for orchestration execution`

This document records the repository-side closeout boundary after the source-only #1235 slices that added the Engine durable idempotency adapter boundary, D1 schema contract, stale reservation expiry recovery, and idempotency-bound resume regression coverage, and after the WO-8 production activation (PR-B #2021, PR-B.1 #2022, PR-B.2 #2023, PR-C manifest flip).

## Current disposition

```text
IDEMPOTENCY_ADAPTER_BOUNDARY = ACTIVATED
MANIFEST_IDEMPOTENCY_REPLAY = AVAILABLE
EXECUTION_IDEMPOTENCY_REPLAY_COMPLETED = AVAILABLE
EXECUTION_IDEMPOTENCY_REPLAY_STREAMING = DEFERRED
PRODUCTION_D1 = padiem-engine 6b77ad02-bc27-488f-bb97-6325f6750cba
ACTIVATION_MAIN = bd02bde0
SMOKE_RUN = 34070150768
```

## Completed repository-side slices

```text
PR1335 = ENGINE_IDEMPOTENCY_DURABLE_BINDING_ADAPTER
PR1338 = ENGINE_IDEMPOTENCY_D1_SCHEMA_CONTRACT
PR1341 = ENGINE_IDEMPOTENCY_EXPIRY_RECOVERY
PR1353 = ENGINE_IDEMPOTENT_RESUME_GATE_TEST
```

These slices were allowed to exist before production activation because they do not provision D1, mutate Cloudflare bindings, deploy, or mark the public Engine manifest as available.

## Required activation blockers

All blockers below are proven against the real bound durable store; the WO-8 PR-C change is the separately authorized manifest-activation change (BLOCKER_10). Final gate line: `A9_SMOKE=PASS REAL_PROVIDER_CALLS=1 ROWS_WRITTEN=1 BLOCKER_4=PASS BLOCKER_5=PASS BLOCKER_6=PASS BLOCKER_7=PASS` (main bd02bde0, run 34070150768).

```text
BLOCKER_1_PRODUCTION_D1_BINDING_PROVISIONED = PROVEN
  D1 provision run 34042827563: padiem-engine 6b77ad02-bc27-488f-bb97-6325f6750cba created (recorded in #1621).
BLOCKER_2_D1_SCHEMA_APPLIED_TO_TARGET_ENVIRONMENT = PROVEN
  D1 provision run 34042827563: migrations 0001+0002 applied, table assert PASS (recorded in #1621).
BLOCKER_3_WORKER_BINDING_NAME_ENGINE_IDEMPOTENCY_CONFIRMED = PROVEN
  #2021 squash b3c18c06: wrangler.toml [[d1_databases]] ENGINE_IDEMPOTENCY + ENGINE_CONTINUATION bound.
BLOCKER_4_ADAPTER_READ_WRITE_SMOKE_AGAINST_BOUND_DURABLE_STORE = PROVEN
  run 34070150768 S6: production D1 row state {'completed': 1} for this run's smoke key.
BLOCKER_5_CROSS_APP_REPLAY_ISOLATION_SMOKE = PROVEN
  run 34070150768 S5: app_id b62 replay probe -> 403 service_app_not_authorized.
BLOCKER_6_CONFLICTING_FINGERPRINT_FAIL_CLOSED_SMOKE = PROVEN
  run 34070150768 S3: 409 idempotency_conflict before the provider is reached (pre-execution).
BLOCKER_7_FAILURE_ABORT_RELEASE_SMOKE = PROVEN
  run 34070150768 S2: durable replay — run_completed metadata.replay=true, request_id identical across S1/S2, 0 extra provider calls.
BLOCKER_8_STALE_RESERVATION_EXPIRY_RECOVERY_SMOKE = PROVEN_BY_SOURCE_TEST
  tests/test_idempotency_binding.py::test_expired_reserved_idempotency_key_is_recovered_without_replay_or_conflict (accepted deviation, see below).
BLOCKER_9_PAUSE_RESUME_NO_SECOND_LOGICAL_RUN_SMOKE = PROVEN_BY_SOURCE_TEST
  tests/test_identity_continuation_runtime.py::test_d1_identity_bound_store_issue_claim_release_commit_and_cancel
  + tests/test_idempotency_replay_service.py::test_reserved_or_aborted_records_are_never_replayed (accepted deviation, see below).
BLOCKER_10_MANIFEST_AVAILABLE_CHANGE_SEPARATE_PR = PROVEN
  This PR (WO-8 PR-C) is the separate manifest-activation change.
```

## Accepted deviations (CTO 2026-09-07)

BLOCKER_8 and BLOCKER_9 cannot be synthesized against production without injecting a stale reservation or a paused run into the live durable store, which the deploy-gate smoke contract forbids. Per CTO decision, source-level tests are adopted as the evidence for these two blockers:

- `apps/padiem-ai-engine/tests/test_idempotency_binding.py::test_expired_reserved_idempotency_key_is_recovered_without_replay_or_conflict`
- `apps/padiem-ai-engine/tests/test_identity_continuation_runtime.py::test_d1_identity_bound_store_issue_claim_release_commit_and_cancel`
- `apps/padiem-ai-engine/tests/test_idempotency_replay_service.py::test_reserved_or_aborted_records_are_never_replayed`

Follow-up: wiring streaming idempotency replay to the adapter (flipping `execution_idempotency_replay_streaming` to AVAILABLE) is tracked separately, not in this closeout.

## Forbidden (post-activation)

```text
EXECUTION_IDEMPOTENCY_REPLAY_STREAMING_AVAILABLE = FORBIDDEN
PROCESS_LOCAL_FAKE_PRODUCTION_STORE = FORBIDDEN
B62_IDEMPOTENCY_AUTHORITY = FORBIDDEN
B14_IDEMPOTENCY_AUTHORITY = FORBIDDEN
```

## Closeout rule

#1235 close condition is met by this PR's merge and the subsequent authorized production deploy: after that deploy, `GET /internal/v1/health` must report `capabilities.idempotency_replay = "available"` on the exact activated main, with `A9_SMOKE=PASS` on the same run. Until then the issue stays open.

```text
REPLAY != RERUN
RESUME != NEW_RUN
IDEMPOTENCY_KEY != AUTHORIZATION
SOURCE_PRESENT != AVAILABLE
```
