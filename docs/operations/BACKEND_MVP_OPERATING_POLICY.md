# Backend MVP Operating Policy

- Status: canonical portfolio operating policy
- Owner: Web CTO under owner authority
- Applies to: MVP vertical slices, service-led pilots, local/runtime pilots, and commercial hardening
- Evidence policy: `UI_UX_BACKEND_PHASE_GATES.md`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Decision

Backend work is not frozen by default.

> Build the smallest observable, reversible, secure-enough runtime slice that is necessary to prove the product's primary evidence journey.

Do not build backend infrastructure that does not contribute to the current evidence question. Do not hide a required runtime behind a static demo when that runtime is the main uncertainty.

## 2. Backend modes

Choose one explicitly:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

- **NO_BACKEND** — visual/product-story uncertainty can be answered without runtime.
- **DETERMINISTIC_SIMULATION** — realistic bounded behavior without persistence/external calls.
- **SERVICE_LED** — an operator manually performs bounded delivery behind a truthful product surface.
- **LOCAL_RUNTIME** — controlled local model/indexing/file/privacy/runtime evidence.
- **LIVE_VERTICAL_SLICE** — one primary journey needs a real API, DB, authentication, provider, or external integration.
- **PILOT_RUNTIME** — bounded external use with observability, recovery, data handling, and cost controls.
- **COMMERCIAL_HARDENING** — demand/operating evidence justifies reliability, multi-user isolation, billing, support, migrations, or redundancy.

## 3. Vertical-slice contract

Before implementation define:

- primary user and success event;
- frontend/entry point;
- live versus simulated/manual boundaries;
- required backend actions;
- data entities/source of truth/ownership;
- persistence and retention;
- authentication/authorization requirement;
- provider/local-runtime dependency;
- latency and cost boundary;
- failure/retry/cancellation behavior;
- observability/audit evidence;
- deployment/recovery path.

## 4. Data and authorization

Use product-local data contracts. Record private/sensitive fields, ownership, lifecycle/deletion, schema/migration, and export/backup where relevant.

Authentication is not mandatory for every MVP. Authorization is mandatory whenever users can read or mutate private records.

Prefer synthetic or bounded pilot data until real data is required to answer the product question.

## 5. Provider/model boundary

For live AI define:

- task/output contract;
- provider/model identity;
- timeout/retry/fallback rules;
- cost ceiling;
- data/privacy boundary;
- prompt/version identity when material;
- evaluation fixtures;
- human review requirement;
- provider replacement path.

Mocked/deterministic evidence and live provider evidence must be labelled separately.

## 6. Service-led MVP

A service-led MVP is a valid operating mode, not a fake backend.

Record:

- customer-facing promise;
- operator steps;
- AI/manual assistance;
- response-time promise;
- workload ceiling;
- quality-control step;
- customer-data handling;
- price/margin hypothesis;
- automation candidates after validation.

## 7. Runtime/API quality

When applicable require:

- explicit request/response schema;
- input validation at trust boundaries;
- bounded payloads;
- authorization checks;
- stable error shape;
- idempotency for retried mutations;
- sanitized logs;
- bounded timeout/retry;
- observable request/journey identity.

## 8. Failure and recovery

Implement the failure paths that can make the primary evidence journey unusable, such as validation failure, unauthorized access, provider timeout/quota, malformed response, persistence failure, stale/conflicting data, partial completion, cancellation, or bounded retry.

Do not build exhaustive enterprise recovery for an early slice. Do not omit the one failure that invalidates the pilot.

## 9. Security and privacy

Always:

- keep secrets out of source/browser/logs/evidence;
- validate trust-boundary inputs;
- enforce product-local authorization for private records;
- minimize collected data;
- sanitize evidence;
- document retention/deletion when real personal data is persisted.

Escalate concrete material risks, not generic warnings detached from the product decision.

## 10. Cost and observability

Record the relevant subset of:

- infrastructure cost;
- model/API cost per primary journey;
- storage/bandwidth;
- service-led human time;
- fallback cost;
- latency;
- provider/model/route outcome;
- user-visible success/failure event.

Use cost ceilings before scaling automation.

## 11. Testing

Choose the smallest useful set that proves the claim changed by the current slice:

- schema/contract tests;
- domain unit tests;
- storage/provider integration tests;
- primary browser/journey tests;
- failure-path tests;
- authorization/leakage tests;
- migration tests when schema changes;
- Production smoke after deployment.

Implementation self-test is not independent validation.

### 11A. MVP closeout test discipline

For a narrow MVP defect, default to:

```text
focused regression
→ relevant configured CI
→ bounded Production smoke
→ handoff
```

Do not automatically rerun the whole backend, whole browser matrix, every previously accepted journey, or unrelated product surfaces.

Broader testing is required only when at least one applies:

- the fix changes shared authority or a broadly reused contract;
- the fix changes auth/authz, persistence, migration, billing, destructive behavior, secrets/bindings, or another high-blast-radius boundary;
- relevant dependency/configuration/runtime drift occurred since the prior evidence;
- a focused test reveals evidence of a wider defect class;
- the work contract explicitly names the broader suite as a handoff gate.

A previously passed journey is not invalidated merely by elapsed time. A newer `main` invalidates it only to the extent that intervening changes can affect that journey.

For customer-bound MVPs, classify every remaining finding:

```text
HANDOFF_BLOCKER
POST_HANDOFF_FIX
HARDENING
BACKLOG
```

Only `HANDOFF_BLOCKER` may delay delivery. The classification must be supported by concrete evidence, not the possibility that another defect might exist.

If the accepted primary journey and required safety boundaries pass after the final fix, stop expanding pre-handoff validation and deliver. Continue non-blocking reliability and hardening work after the customer has the MVP.

## 11B. Finish-first vertical completion

When multiple backend/platform capabilities are partially built, prefer finishing one customer-visible vertical slice over opening more independent implementation lanes.

```text
one primary vertical slice
+ at most two blocker-support lanes
+ parallel validation
!= many unrelated feature lanes
```

Start implementation at the lowest missing dependency of the selected slice, then move upward through shared platform/runtime and into the reference product.

A source-complete backend capability may remain deferred if it is not required by the active slice. Free worker capacity is not itself a reason to activate another backend capability.

## 12. Commercial hardening trigger

Hardening begins only when evidence justifies one or more of:

- multiple real users/organizations;
- paid pilot/contract;
- sensitive persistent data;
- recurring operational dependence;
- billing/payment;
- meaningful provider spend;
- reliability/support obligation;
- external integration commitment.

Then address tenant isolation, migration/backup, audit/support tooling, provider redundancy, abuse/rate limits, billing correctness, security review, incident response, and service objectives.

## 13. Deployment

Follow `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

Before deployment record exact revision, environment/bindings, migration state, known-good recovery state, smoke journey, and fix/revert path. After deployment verify the primary journey, not merely root HTTP status.
