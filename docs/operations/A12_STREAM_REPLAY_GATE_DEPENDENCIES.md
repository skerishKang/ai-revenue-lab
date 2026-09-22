# A12 Streaming Replay Gate — Responsibility and Provider Dependencies

```
Issue      #2786 (E9 A5-Agent activation) — M4-4 closing item
Scope      A12 stream-replay gate interpretation only
Applies to
  .github/workflows/b54-engine-production-deploy-gate.yml      (step: Run A12 …)
  .github/workflows/b54-engine-production-smoke-only-gate.yml  (step: Run A12 …)
  apps/padiem-ai-engine/scripts/a12_stream_replay_production_smoke.py
```

## 1. What A12 is for

A12 proves the **Engine's streaming idempotency contract** on the served Production worker: a streamed run
completes exactly once, a replay of the same idempotency key returns exactly one event marked
`replayed: true`, a conflicting payload with the same key is rejected with `409 idempotency_conflict`
before execution, and the durable row state ends consistent.

It is **not** a provider SLA check. Its subject is the Engine; the model provider is the medium one
execution happens through.

## 2. Stage map

| Stage | What it asserts | Provider dependency |
|---|---|---|
| S0 | health 200, `/internal/v1/stream` advertised, `capabilities.provider_streaming_run == available` | none |
| S1 | first streamed run: 200, NDJSON, terminal `done: true`, answer present, `replayed` not true | **needs a provider response** |
| S2 | replay: exactly one event line, `ok: true`, `replayed: true` | needs the same provider path |
| S3 | conflicting payload with the same key → `409 idempotency_conflict`, pre-execution | none |
| S4 | D1 `padiem_engine_idempotency` row state for this run's keys: exactly 1 `completed`, 0 `reserved` | none (reads only) |

```text
MANDATORY (provider-independent)   S0, S3        always evaluated, must pass
MANDATORY (when an execution ran)  S4            skipped runs record NOT_APPLICABLE, never "passed"
PROVIDER LEG                       S1, S2        outcome is PASS or SKIPPED_UPSTREAM, never silently dropped
```

## 3. Verdict vocabulary

```text
A12_STREAM_REPLAY_SMOKE=PASS                every stage ran and every invariant held
A12_STREAM_REPLAY_SMOKE=SKIPPED_UPSTREAM    the provider leg hit an external 5xx; the mandatory stages
                                            still ran and still had to pass
A12_STREAM_REPLAY_SMOKE=FAIL                anything else
```

Both gate workflows accept `PASS` and `SKIPPED_UPSTREAM`, and both fail the step on `FAIL`. Each run
records the outcome it actually reached:

```text
A12_REPLAY_EVIDENCE=PASS
A12_REPLAY_EVIDENCE=SKIPPED_UPSTREAM MANDATORY_STAGES=S0,S3 A12_SKIP_REASON=S1: upstream provider returned 502 (HTTP 502)
```

`SKIPPED_UPSTREAM` is a **recorded external condition**, not a pass. A gate that answers
`A12_REPLAY_EVIDENCE=SKIPPED_UPSTREAM` says: the Engine-side invariants held, and the provider could not be
exercised.

## 4. Classification rule (what may be skipped, and what may not)

A response is treated as an external provider outage only when **both** hold:

1. the HTTP status is 5xx, **and**
2. the Engine preserved the provider's own status as `error.metadata.upstream_status_code` (a 5xx integer).

Everything else is a hard `FAIL`:

```text
Engine 5xx without an upstream status   -> FAIL (an Engine defect is never a skip)
4xx (auth, credential, contract)        -> FAIL
idempotency invariant violation         -> FAIL
S3 conflict contract violation          -> FAIL
S4 D1 row-state mismatch                -> FAIL
```

## 5. Provider dependency and outage disposition

The pinned provider for the stream leg is `sensenova/sensenova-6.8-flash-lite` (a module constant, not an
environment value). It is intentionally **pinned**: a silent fallback would change what the smoke proves.

```text
Provider unavailable  -> A12 records SKIPPED_UPSTREAM
                      -> Engine activation readiness is NOT retroactively invalidated
                      -> the provider condition is tracked separately (provider compatibility health)
Provider available    -> A12 must reach PASS
```

An activation decision therefore rests on the Engine truth (S0, S3, S4 plus whatever provider leg evidence
exists), never on one external model's availability.

## 6. What a `SKIPPED_UPSTREAM` gate run does and does not prove

```text
PROVES      the served Engine advertises the streaming capability, rejects a conflicting replay with 409
            before execution, and did not violate a provider-independent invariant
DOES NOT    prove that a streamed execution and its replay behave correctly while a provider is reachable
PROVE
```

Closing the A12 item requires either a `PASS` run once the provider is healthy, or an explicitly recorded
`SKIPPED_UPSTREAM` run where the mandatory stages are green and the provider condition is tracked.

## 7. Change boundaries

```text
Allowed in this interpretation     the A12 verdict classification and the two A12 gate steps
Never part of it                   deploy, rollback, secret, credential, environment, binding, D1 mutation
```

The deploy and rollback logic in `b54-engine-production-deploy-gate.yml` is out of scope for any A12
interpretation change; `rollback_version_id` stays mandatory for the rollback branch, and the deploy step
stays exactly as it is.
