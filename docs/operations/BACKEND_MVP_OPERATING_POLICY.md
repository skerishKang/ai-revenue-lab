# Backend MVP Operating Policy

- Status: portfolio operating policy
- Owner: Web CTO under owner authority
- Applies to: MVP vertical slices, service-led pilots, runtime pilots, and commercial hardening
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`
- Stage policy: `UI_UX_BACKEND_PHASE_GATES.md`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Purpose

This policy lets AI Revenue Lab build real backend capability early when it is necessary to prove product value, without forcing every experiment to carry full enterprise architecture.

The backend goal is:

> Build the smallest observable, reversible, secure-enough runtime slice that completes the product's primary evidence journey and can evolve if the Business earns demand.

Backend work must increase product credibility and learning speed. It must not become an infrastructure exercise detached from the customer result.

## 2. Backend modes

Choose one mode explicitly:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

### NO_BACKEND

Use when visual desirability or product storytelling is the current uncertainty.

### DETERMINISTIC_SIMULATION

Use when realistic behavior can be demonstrated without persistence or external systems.

### SERVICE_LED

Use when an operator can manually perform bounded work behind a convincing product surface to validate customer demand.

### LOCAL_RUNTIME

Use when model execution, indexing, processing, or privacy should remain on a controlled local machine for the evidence stage.

### LIVE_VERTICAL_SLICE

Use when one end-to-end journey requires a real API, database, authentication, AI provider, or external integration.

### PILOT_RUNTIME

Use for bounded external use with observability, recovery, data handling, and cost controls.

### COMMERCIAL_HARDENING

Use only after demand or operating evidence justifies multi-user reliability, security, billing, and scale work.

## 3. Vertical-slice contract

Before implementation, define:

- primary user;
- primary success event;
- frontend entry point;
- required backend actions;
- live versus simulated boundaries;
- data entities and ownership;
- persistence and retention;
- authentication and authorization;
- provider or external-system dependency;
- service-led manual steps;
- expected latency and cost;
- failure and recovery behavior;
- observability and audit evidence;
- deployment and rollback path.

Avoid architecture that does not contribute to this journey.

## 4. Data design

Use a product-local data contract.

Required decisions:

- entity names and relationships;
- source of truth;
- user, organization, and tenant ownership;
- public, private, and sensitive fields;
- lifecycle and deletion;
- seed and synthetic demo data;
- schema version and migration path;
- export or portability when relevant.

For an early MVP, a compact schema is preferred. Do not collapse unrelated Businesses into one generic database merely for reuse.

## 5. Authentication and authorization

Authentication is not mandatory for every MVP.

Use it when required to prove:

- private user data;
- organization boundaries;
- role-specific actions;
- ownership and history;
- paid or limited access.

When authentication is unnecessary, use a truthful demo mode, shared pilot code, local workspace, or service-led operation instead of implementing accounts for ceremony.

Authorization must be explicit whenever users can read or mutate private records.

## 6. AI providers and model routing

When live AI is part of the product promise, define:

- task and expected output schema;
- primary provider and model;
- deterministic or local fallback;
- timeout and retry policy;
- cost ceiling;
- rate-limit behavior;
- content and data boundary;
- prompt and version identity;
- human review requirement;
- evaluation fixtures;
- provider replacement path.

Do not hide a required live-AI capability behind static copy when it is the main technical uncertainty. Do not add a live provider when a deterministic fixture can answer the current product question more quickly.

## 7. Service-led MVPs

A service-led MVP is an intentional operating model, not a fake backend.

Document:

- what the customer sees;
- what the operator performs;
- which AI tools assist the operator;
- response-time promise;
- maximum operator workload;
- quality-control step;
- customer-data handling;
- price and margin hypothesis;
- automation candidates after validation.

The goal is to test demand and delivery before automating low-value complexity.

## 8. API contract

APIs should have:

- explicit methods and routes;
- request and response schemas;
- stable error shape;
- validation at the trust boundary;
- idempotency for retried mutations where relevant;
- authorization checks;
- bounded payload size;
- version or compatibility strategy;
- sanitized logs.

Use typed contracts when practical. Avoid speculative API layers that serve no current client.

## 9. Observability

Every live vertical slice should expose enough evidence to answer:

- did the request start and finish;
- where did it fail;
- how long did it take;
- which provider or fallback ran;
- what did it cost;
- what user-visible result occurred;
- was data persisted;
- can the operation be safely retried.

Minimum evidence may include:

- structured event names;
- request or journey IDs;
- stage and outcome taxonomy;
- latency buckets;
- sanitized error codes;
- provider usage and estimated cost;
- deployment and version identity.

Do not log secrets, raw private data, or unnecessary model prompts.

## 10. Failure and recovery

Implement the failure states that matter to the primary journey:

- validation failure;
- unauthorized access;
- provider timeout or quota;
- invalid provider response;
- persistence failure;
- stale or conflicting data;
- partial completion;
- retry and cancellation.

Use reversible operations, idempotency, feature flags, and bounded retries where they materially reduce pilot risk.

Do not build exhaustive enterprise recovery for an early demo. Do not omit the one failure that would make the pilot unusable.

## 11. Testing layers

Choose the smallest useful set:

- schema and contract tests;
- unit tests for domain rules;
- integration tests for storage and providers;
- browser or journey tests for the primary path;
- failure-path tests;
- authorization and leakage tests;
- migration tests when schema changes;
- production smoke tests after deployment.

A worker's self-test is implementation evidence, not independent approval.

## 12. Security and privacy

Security work should match the stage and concrete data risk.

Always:

- keep secrets out of source, browser bundles, logs, and evidence;
- validate inputs at trust boundaries;
- enforce product-local authorization for private records;
- minimize collected data;
- document retention and deletion when real personal data is stored;
- sanitize evidence packages.

For demos and early pilots, prefer synthetic data, limited pilot records, access controls, and reversible storage over deleting the product's core capability.

Escalate concrete high-impact risks. Avoid generic warnings that do not change the implementation decision.

## 13. Cost discipline

Record:

- infrastructure cost;
- model and API cost per primary journey;
- storage and bandwidth assumptions;
- service-led human time;
- fallback cost;
- expected price or attributable value.

Use cost ceilings and sample-volume estimates before expanding automation.

## 14. Commercial hardening trigger

Do not harden merely because the architecture could be more complete.

Hardening begins when evidence justifies one or more of:

- multiple real users or organizations;
- paid pilot or contract;
- sensitive persistent data;
- recurring operational dependence;
- billing or payment;
- meaningful provider spend;
- reliability or support obligation;
- external integration commitment.

Then address:

- tenant isolation;
- migration and backup;
- audit and support tooling;
- provider redundancy;
- rate and abuse controls;
- billing correctness;
- security review;
- incident response;
- service-level objectives.

## 15. Deployment

Backend and runtime deployment follows `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` and the Business-specific contract.

Before deployment, record:

- exact head;
- environment and bindings;
- migration state;
- known-good source and configuration;
- feature flags;
- smoke journey;
- fix or revert path.

After deployment, verify the actual primary journey, not only root HTTP status.

## 16. Completion report

Report:

- backend mode;
- primary journey;
- live versus simulated boundary;
- data schema and retention;
- auth and authorization;
- provider and fallback;
- observability;
- tests and failure paths;
- cost estimate;
- exact head and deployment evidence;
- known limitations;
- next commercialization decision.

## 17. Default instruction

```text
Do not freeze backend work by default.
Build it when it is required to prove the product, and keep it bounded to the evidence goal.
```