# UI / UX / Backend Evidence Gates

- Status: canonical portfolio operating policy
- Owner: Web CTO
- Authority: Issue #148 + current portfolio governance
- Portfolio mode: `MVP_AND_VISUAL_UPGRADE`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Decision

UI, UX, backend/runtime, deployment, and business evidence remain **separate verdicts**, but they are not a mandatory sequential ceremony.

The old repository-wide rule:

```text
UI only
→ UI approval
→ UX only
→ UX approval
→ backend decision
→ backend implementation
```

is historical policy for the revisions that used it. It is not the default contract for new work.

Current rule:

> Select the smallest evidence slice that proves the current product question, while keeping each evidence dimension independently truthful.

## 2. Product-evidence stages

A work item may target one or more stages:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

These stages are not mandatory sequential gates.

## 3. Evidence dimensions

Record each independently when relevant:

### UI / visual

Answers whether the visual system is coherent, readable, responsive, distinctive, and technically sound.

Possible verdicts:

```text
UI_NOT_READY
UI_CONDITIONALLY_READY
UI_APPROVED
```

Historical `UI_APPROVED` evidence remains valid for its exact revision. It does not imply UX, backend, merge, Production, commercial, or current-owner approval unless those were separately recorded.

### UX / interaction

Answers whether the intended journey, navigation, feedback, errors/recovery, accessibility, and mobile/keyboard behavior are understandable and usable.

```text
UX_NOT_READY
UX_CONDITIONALLY_READY
UX_APPROVED
```

UX may be designed in the same vertical slice as UI when that is the smallest useful product evidence. The verdicts still remain separate.

### Backend / runtime

Answers whether the required runtime behavior, data contracts, provider/local-model integration, persistence, authorization, failure handling, observability, and cost boundaries work.

Select a backend mode:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

Backend is not frozen by default. It may begin early when it is the key product uncertainty and is explicitly included in the work contract.

### Deployment

Deployment proves only that an authorized revision is operating at the intended target. It does not manufacture UI, UX, backend, owner, or commercial approval.

### Business evidence

Record user behavior, willingness to pay, operating cost, revenue, retention, service-led workload, or other evidence appropriate to the experiment.

## 4. Scope selection examples

### Visual-first

Use when the product is understood but desirability/identity is not.

```text
product framing
→ competitive visual reference
→ representative desktop/mobile screens
→ technical + visual review
```

No backend is required unless the visual/product question depends on live behavior.

### UX-first or combined UI/UX vertical slice

Use when the product journey is the main uncertainty.

```text
bounded product surface
→ primary journey
→ loading/error/recovery
→ browser/usability validation
```

### Service-led MVP

Use when demand can be tested faster with a human-operated backend boundary.

```text
customer-facing surface
→ explicit operator step
→ AI-assisted/manual delivery
→ quality control
→ response-time + workload + price evidence
```

### Runtime-first

Use when the product value depends on local processing, model execution, ingestion, API behavior, or persistence.

```text
minimal interface/fixture
→ bounded runtime
→ deterministic failure/security tests
→ real-environment validation
```

### Commercial hardening

Use only after demand/usage/operating evidence justifies reliability, tenant isolation, billing, migrations, support, or provider redundancy.

## 5. Owner and CTO authority

The Web CTO may reject objective visual/UX defects and assign technical readiness statuses.

If a work contract explicitly requires owner aesthetic approval, only an explicit owner decision creates `OWNER_UI_APPROVED`.

If the owner explicitly delegates design selection to the CTO, the CTO may select the direction and record `CTO_DELEGATED_DECISION`; this does not rewrite historical owner-approval records.

## 6. Evidence and independence

Follow:

- `AI_DEVELOPMENT_OPERATING_POLICY.md`
- `EVIDENCE_REQUIREMENTS.md`
- `WORKFLOW_STATUS_MODEL.md`

Implementation self-check and independent validation are different evidence types. The same actor must not claim implementation and independent Local Validation for the same revision.

## 7. Merge and Production

A passed evidence dimension does not itself authorize merge or Production.

For Git-connected Production targets, follow the expected-head review and automatic deployment contract in `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

Preview/staging/manual deployment remains disabled unless separately authorized.

## 8. Historical records

Do not rewrite old Issues/PRs simply because the repository-wide policy changed. Historical UI-only, phase-gate, backend-frozen, or Preview records remain evidence of the rules and decisions that applied to those revisions.

New work follows this current policy unless a Business-specific authority is stricter.
